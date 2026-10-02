"""Profile one uncached E2 Evaluator.evaluate call on a fixed field subset.

The script intentionally performs no search and disables the SQLite cache so
that cProfile/py-spy capture one real five-fold Clinic Analyzer evaluation.

`--analyzer` accepts a comma-separated list; each analyzer gets its own
output directory under results/E2_selection/profiling/{dataset}/{tag}/{analyzer}/,
created automatically. A cProfile report (sorted by cumtime) is written there
as profile.txt, so no manual mkdir / shell redirection is needed.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import pstats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from common.paths import dataset_field_bank_dir
from greedy.clinic import DEFAULT_INNER_MODALITY, ensure_modalities_allowed, parse_modalities
from greedy.clinic_evaluator import ClinicSubsetEvaluator
from greedy.data import default_analyzer_split_dir, load_field_bank
from selection.evaluator import Evaluator
from selection.runner import load_univariate_prior


def _profile_text(profiler: cProfile.Profile) -> str:
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumtime")
    stats.print_stats()
    return stream.getvalue()


def profile_one(args, *, modality: str, tag: str, bank_dir: Path, fields, split_dir: Path) -> bool:
    prior_rows, _, _ = load_univariate_prior(
        args.dataset, tag, args.seed, fields, split_dir, expected_modality=modality)
    ranked = sorted(prior_rows, key=lambda row: (-float(row["c_index_mean"]), int(row["field_idx"])))
    selected = tuple(str(row["field"]) for row in ranked[: min(args.top_k, len(fields))])
    selected_indices = tuple(fields.index(name) for name in selected)

    out_dir = Path(args.out_dir) / modality if args.out_dir else ROOT / "results" / "E2_selection" / "profiling" / args.dataset / tag / modality
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "subset.json").write_text(
        json.dumps({"dataset": args.dataset, "landmark_tag": tag, "modality": modality,
                    "seed": args.seed,
                    "fields": list(selected), "field_indices": list(selected_indices)},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    inner = ClinicSubsetEvaluator(
        args.dataset, list(fields), None, field_bank_dir=bank_dir,
        work_dir=out_dir / "clinic", modality=modality, seed=args.seed,
        split_dir=split_dir, landmark_tag=tag,
    )
    evaluator = Evaluator(
        inner, fields, seed=args.seed, budget=1, cache=None,
        field_index_hash=hashlib.sha256((bank_dir / "field_index.json").read_bytes()).hexdigest(),
        dataset=args.dataset, landmark_tag=tag, modality=modality,
        run_id=f"profile-{args.dataset}-{tag}-{modality}-seed{args.seed}", algorithm="PROFILE", field_indices=range(len(fields)),
    )

    profiler = cProfile.Profile()
    profiler.enable()
    result = evaluator.evaluate(frozenset(selected))
    profiler.disable()
    (out_dir / "profile.txt").write_text(_profile_text(profiler), encoding="utf-8")

    payload = {"subset": list(selected), "subset_indices": list(selected_indices),
               "modality": modality,
               "cv_c_mean": result.cv_c_mean, "cv_folds": list(result.cv_folds),
               "wall_ms": result.wall_ms, "status": result.status}
    (out_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return result.status == "ok"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="TCGA-LGG")
    parser.add_argument("--landmark_time", default="0")
    parser.add_argument("--seed", type=int, default=0, help="univariate 先验与 Evaluator 的 seed，默认 0")
    parser.add_argument("--top_k", type=int, default=5)
    parser.add_argument("--analyzer", default=DEFAULT_INNER_MODALITY,
                        help="clinic analyzer，逗号分隔；每个 analyzer 独立建目录并写出 profile.txt/subset.json/result.json")
    parser.add_argument("--out_dir", default=None)
    args = parser.parse_args(argv)
    if args.top_k < 1:
        parser.error("--top_k must be positive")

    modalities = parse_modalities(args.analyzer)
    ensure_modalities_allowed(args.dataset, modalities)

    tag = "landmark_none" if str(args.landmark_time).lower() in {"none", "off"} else f"landmark_{int(args.landmark_time)}"
    bank_dir = dataset_field_bank_dir(args.dataset, "prompt", tag)
    loaded = load_field_bank(bank_dir, encoding="prompt")
    fields = tuple(loaded["fields"])
    split_dir = default_analyzer_split_dir(args.dataset)

    ok = True
    for modality in modalities:
        ok = profile_one(args, modality=modality, tag=tag, bank_dir=bank_dir, fields=fields, split_dir=split_dir) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
