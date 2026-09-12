from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from .config import MODALITY, parse_seeds, budget_for
from .evaluator import Evaluator
from .cache import SQLiteCache
from .references import load_univariate_rows
from .search import (AntColonySearcher, AnnealingSearcher, BeamSearcher,
                     ExhaustiveSearcher, GeneticSearcher, GreedySearcher,
                     RandomSearcher, SEASNoEISearcher, SEASNoIntSearcher,
                     SEASNoSemSearcher, SEASSearcher)
from .search.exhaustive import ANCHOR_TIMING_DATASETS, anchor_fields, timing_probe
from .search.seas import load_or_encode_field_semantics


SEARCHERS = {s.name: s for s in (RandomSearcher, GreedySearcher, BeamSearcher,
                                  AnnealingSearcher, GeneticSearcher, AntColonySearcher,
                                  SEASSearcher, SEASNoSemSearcher, SEASNoIntSearcher,
                                  SEASNoEISearcher, ExhaustiveSearcher)}


def _univariate_paths(dataset, landmark_tag, seed, csv_path=None, config_path=None):
    root = Path("results/univariate/prompt") / landmark_tag / dataset
    if int(seed) != 0:
        root = root / f"seed_{seed}"
    return Path(csv_path) if csv_path else root / "field_cindex.csv", Path(config_path) if config_path else root / "run_config.json"


def _parse_folds(value):
    raw = json.loads(value) if isinstance(value, str) else value
    folds = tuple(float(item) for item in raw)
    if len(folds) != 5:
        raise ValueError("univariate result must contain five folds")
    return folds


def load_univariate_prior(dataset, landmark_tag, seed, fields, split_dir, *, csv_path=None, config_path=None):
    table, config = _univariate_paths(dataset, landmark_tag, seed, csv_path, config_path)
    if not table.exists() or not config.exists():
        raise FileNotFoundError(
            f"missing seed {seed} univariate prior ({table}); run the existing univariate evaluator first"
        )
    rows = load_univariate_rows(
        table, expected_fields=fields, run_config_path=config, expected_seed=seed
    )
    run_config = json.loads(config.read_text(encoding="utf-8"))
    configured_split = run_config.get("split_dir")
    if configured_split and Path(configured_split).resolve() != Path(split_dir).resolve():
        raise ValueError("univariate split directory does not match the current E2 instance")
    by_field = {str(row["field"]): row for row in rows}
    scores = tuple(float(by_field[field]["c_index_mean"]) for field in fields)
    folds = tuple(_parse_folds(by_field[field]["per_fold"]) for field in fields)
    return rows, scores, folds


def run_one(*, algo, seed, fields, inner, output=None, budget=None, cache=None,
            field_index_hash="", split_hashes=(), train_args_hash="", dataset="",
            landmark_tag="", encoding="prompt", modality=MODALITY,
            univariate_scores=None, univariate_folds=None, semantic_embeddings=None,
            field_indices=None):
    started = time.perf_counter()
    ev = Evaluator(inner, fields, seed=seed, budget=budget,
                   cache=cache, field_index_hash=field_index_hash, split_hashes=split_hashes,
                   train_args_hash=train_args_hash,
                   dataset=dataset, landmark_tag=landmark_tag, encoding=encoding,
                   modality=modality,
                   run_id=f"{getattr(inner, 'dataset', '')}-{seed}", algorithm=algo,
                   jsonl_path=Path(output) / "evaluations.jsonl" if output else None,
                   field_indices=field_indices)
    if univariate_scores is not None:
        ev.univariate_scores = tuple(univariate_scores)
    if univariate_folds is not None:
        ev.univariate_folds = tuple(tuple(row) for row in univariate_folds)
    if semantic_embeddings is not None:
        ev.semantic_embeddings = np.asarray(semantic_embeddings)
    searcher = SEARCHERS[algo]()
    result = searcher.run(ev, tuple(fields), np.random.default_rng(seed))
    if output:
        out = Path(output); out.mkdir(parents=True, exist_ok=True)
        recommended = ev._seen.get(frozenset(result.recommended_subset))
        payload = dict(result.__dict__)
        payload.update({
            "recommended_cv_c_mean": recommended.cv_c_mean if recommended else (0.5 if not result.recommended_subset else None),
            "recommended_cv_folds": list(recommended.cv_folds) if recommended else ([0.5] * 5 if not result.recommended_subset else []),
            "recommended_k": len(result.recommended_subset),
            "cache_hits": ev.cache_hits,
            "failure_count": ev.failures,
            "wall_ms": int((time.perf_counter() - started) * 1000),
        })
        (out / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=list) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="E2 subset selection")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--landmark_time", required=True, help="none or non-negative integer days")
    parser.add_argument("--algo", required=True, choices=sorted((*SEARCHERS, "ANCHOR_TIMING")))
    parser.add_argument("--seed", default="0")
    parser.add_argument("--field_bank_dir", default=None)
    parser.add_argument("--splits", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--max_epochs", type=int, default=None)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--univariate_csv", default=None)
    parser.add_argument("--univariate_config", default=None)
    parser.add_argument("--semantic_embeddings", default=None, help="Optional precomputed field semantic .npy")
    parser.add_argument("--conch_ckpt", default=None)
    parser.add_argument("--conch_python", default=None)
    parser.add_argument("--semantic_batch_size", type=int, default=64)
    parser.add_argument("--anchor_p", type=int, default=None, help="Run seed 0 in the ANCHOR top-univariate field space (8-15)")
    args = parser.parse_args(argv)
    from common.paths import (DEFAULT_CKPT, DEFAULT_GDC_CLINICAL_DICTIONARY,
                              dataset_field_bank_dir, dataset_field_bank_template_dir)
    from greedy.clinic_evaluator import DEFAULT_CONCH_PYTHON, ClinicSubsetEvaluator
    from greedy.data import load_field_bank, default_analyzer_split_dir
    from common.paths import require_landmark_tag

    tag = require_landmark_tag("landmark_none" if str(args.landmark_time).lower() in {"none", "off"} else f"landmark_{int(args.landmark_time)}")
    bank_dir = Path(args.field_bank_dir) if args.field_bank_dir else dataset_field_bank_dir(args.dataset, "prompt", tag)
    loaded = load_field_bank(bank_dir, encoding="prompt")
    fields = tuple(loaded["fields"])
    full_fields = fields
    split_dir = Path(args.splits) if args.splits else default_analyzer_split_dir(args.dataset)
    seeds = parse_seeds(args.seed)
    if args.algo == "ANCHOR_TIMING" and (seeds != [0] or args.dataset not in ANCHOR_TIMING_DATASETS):
        parser.error("ANCHOR_TIMING requires --seed 0 and one of TCGA-BRCA, TCGA-LGG, TCGA-CHOL")
    if args.algo == "ANCHOR" and seeds != [0]:
        parser.error("ANCHOR only supports --seed 0")
    if args.anchor_p is not None and seeds != [0]:
        parser.error("restricted ANCHOR-space comparisons only support --seed 0")
    needs_prior = ((args.algo in SEARCHERS and bool(getattr(SEARCHERS[args.algo], "uses_univariate_prior", False)))
                   or args.algo == "ANCHOR" or args.anchor_p is not None)
    prior_by_seed = {}
    if needs_prior:
        for seed in seeds:
            prior_by_seed[seed] = load_univariate_prior(
                args.dataset, tag, seed, fields, split_dir,
                csv_path=args.univariate_csv, config_path=args.univariate_config,
            )
    if args.algo == "ANCHOR" and args.anchor_p is None:
        parser.error("ANCHOR requires --anchor_p in [8, 15], chosen by the timing plan")
    if args.anchor_p is not None:
        if not 8 <= args.anchor_p <= 15:
            parser.error("ANCHOR requires --anchor_p in [8, 15], chosen by the timing plan")
        fields = anchor_fields(fields, prior_by_seed[0][0], args.anchor_p)
    field_indices = tuple(full_fields.index(field) for field in fields)
    if args.out:
        base = Path(args.out)
    elif args.algo == "ANCHOR_TIMING":
        base = Path("results/E2_selection/timing") / args.dataset / tag
    elif args.anchor_p is not None and args.algo != "ANCHOR":
        base = Path("results/E2_selection/anchor/prompt") / tag / args.dataset / args.algo
    else:
        base = Path("results/E2_selection/prompt") / tag / args.dataset / args.algo
    index_path = bank_dir / "field_index.json"
    index_hash = hashlib.sha256(index_path.read_bytes()).hexdigest() if index_path.exists() else ""
    split_hashes = tuple(hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(split_dir.glob("splits_*.csv")))
    cache = SQLiteCache(Path("results/E2_selection") / "cache.sqlite")
    semantic = None
    if args.algo in {"SEAS", "SEAS-no-ei"}:
        if args.semantic_embeddings:
            semantic = np.load(args.semantic_embeddings)
        else:
            semantic_root = (Path("results/E2_selection/anchor/prompt") if args.anchor_p is not None
                             else Path("results/E2_selection/prompt"))
            semantic = load_or_encode_field_semantics(
                fields,
                template_csv=dataset_field_bank_template_dir(args.dataset, tag) / "FIELD_BANK.csv",
                dictionary_csv=DEFAULT_GDC_CLINICAL_DICTIONARY,
                checkpoint=args.conch_ckpt or DEFAULT_CKPT,
                cache_path=semantic_root / tag / args.dataset / "field_semantics.npy",
                batch_size=args.semantic_batch_size,
                python_executable=args.conch_python or DEFAULT_CONCH_PYTHON,
            )
    elif args.algo in {"SEAS-no-sem", "SEAS-no-int"}:
        semantic = np.zeros((len(fields), 1), dtype=float)
    for seed in seeds:
        out = base / f"seed_{seed}"
        inner = ClinicSubsetEvaluator(args.dataset, list(full_fields), None, field_bank_dir=bank_dir,
                                      work_dir=out / "clinic", modality=MODALITY, seed=seed,
                                      max_epochs=args.max_epochs, split_dir=split_dir,
                                      landmark_tag=tag, conch_python=args.conch_python)
        if args.algo == "ANCHOR_TIMING":
            timing_evaluator = Evaluator(
                inner, fields, seed=0, budget=budget_for(len(fields)), cache=cache,
                field_index_hash=index_hash, split_hashes=split_hashes,
                train_args_hash=hashlib.sha256(json.dumps({"max_epochs": args.max_epochs}, sort_keys=True).encode()).hexdigest(),
                dataset=args.dataset, landmark_tag=tag, modality=MODALITY,
                run_id=f"timing-{args.dataset}-{tag}", algorithm=args.algo,
                jsonl_path=out / "evaluations.jsonl", field_indices=field_indices,
            )
            payload = timing_probe(timing_evaluator, fields, np.random.default_rng(0), n_uncached=20)
            payload.update({"dataset": args.dataset, "landmark_tag": tag})
            out.mkdir(parents=True, exist_ok=True)
            (out / "timing.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(payload))
            if not payload["complete"]:
                raise RuntimeError(
                    f"ANCHOR_TIMING collected {payload['measured_uncached']}/"
                    f"{payload['requested_uncached']} successful uncached evaluations; "
                    f"see {out / 'evaluations.jsonl'}"
                )
            continue
        prior = prior_by_seed.get(seed)
        if prior and args.anchor_p is not None:
            by_field = {str(row["field"]): row for row in prior[0]}
            scores = tuple(float(by_field[field]["c_index_mean"]) for field in fields)
            folds = tuple(_parse_folds(by_field[field]["per_fold"]) for field in fields)
        else:
            scores, folds = (prior[1], prior[2]) if prior else (None, None)
        run_budget = 2 ** len(fields) - 1 if args.algo == "ANCHOR" else budget_for(len(fields))
        result = run_one(algo=args.algo, seed=seed, fields=fields, inner=inner,
                         output=out, budget=run_budget, cache=cache,
                         field_index_hash=index_hash, split_hashes=split_hashes,
                         train_args_hash=hashlib.sha256(json.dumps({"max_epochs": args.max_epochs}, sort_keys=True).encode()).hexdigest(),
                         dataset=args.dataset, landmark_tag=tag, encoding="prompt", modality=MODALITY,
                         univariate_scores=scores, univariate_folds=folds,
                         semantic_embeddings=semantic, field_indices=field_indices)
        (out / "run_config.json").write_text(json.dumps({"dataset": args.dataset, "landmark_tag": tag,
            "encoding": "prompt", "modality": MODALITY, "seed": seed, "val_equals_test": True,
            "fields": list(fields), "split_dir": str(split_dir.resolve()),
            "restricted_anchor": args.anchor_p is not None,
            "p_anchor": args.anchor_p}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result.__dict__, ensure_ascii=False, default=list))
    if args.algo == "ANCHOR_TIMING":
        return
    from .report import write_algorithm_aggregate
    write_algorithm_aggregate(base)


if __name__ == "__main__":
    main()
