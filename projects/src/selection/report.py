from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from .config import DELTA, budget_for
from .search.exhaustive import optimality_gap


BASELINES = tuple(f"A{i}_" for i in range(1, 7))


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_jsonl(path):
    rows = []
    if not Path(path).exists():
        return rows
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _recommended_evaluation(result, evaluations):
    direct_mean = result.get("recommended_cv_c_mean")
    direct_folds = result.get("recommended_cv_folds")
    if direct_mean is not None and len(direct_folds or ()) == 5:
        return {"cv_c_mean": direct_mean, "cv_folds": direct_folds,
                "k": int(result.get("recommended_k", len(result.get("recommended_subset") or ())))}
    recommended = frozenset(result.get("recommended_subset") or ())
    if not recommended:
        return {"cv_c_mean": 0.5, "cv_folds": [0.5] * 5, "k": 0}
    matches = [row for row in evaluations if row.get("status") == "ok" and frozenset(row.get("subset") or ()) == recommended]
    return matches[-1] if matches else None


def seed_record(seed_dir) -> dict:
    seed_dir = Path(seed_dir)
    result = _read_json(seed_dir / "result.json")
    config = _read_json(seed_dir / "run_config.json")
    evaluations = _read_jsonl(seed_dir / "evaluations.jsonl")
    recommended = _recommended_evaluation(result, evaluations)
    if recommended is None:
        raise ValueError(f"recommended subset has no successful evaluation: {seed_dir}")
    ok = sum(row.get("status") == "ok" for row in evaluations)
    failures = sum(row.get("status") == "error" for row in evaluations)
    cache_hits = int(result.get("cache_hits", sum(bool(row.get("physical_cache_hit")) for row in evaluations)))
    logical = int(result.get("logical_evals", len(evaluations)))
    return {
        "dataset": config["dataset"],
        "landmark_tag": config["landmark_tag"],
        "algorithm": result["algorithm"],
        "seed": int(result["seed"]),
        "recommended_subset": list(result.get("recommended_subset") or ()),
        "recommended_k": int(recommended["k"]),
        "cv_c_mean": float(recommended["cv_c_mean"]),
        "cv_folds": list(recommended["cv_folds"]),
        "best_subset": list(result.get("best_subset") or ()),
        "best_cv_c_mean": float(result["best_cv_c_mean"]),
        "logical_evals": logical,
        "physical_trains": int(result.get("physical_trains", logical - cache_hits)),
        "cache_hits": cache_hits,
        "cache_rate": cache_hits / logical if logical else math.nan,
        "proposal_count": int(result.get("proposal_count", logical)),
        "failure_count": failures,
        "failure_rate": failures / (ok + failures) if ok + failures else math.nan,
        "wall_ms": int(result.get("wall_ms", sum(int(row.get("wall_ms", 0)) for row in evaluations))),
        "stop_reason": result.get("stop_reason", ""),
        "metadata": dict(result.get("metadata") or {}),
        "budget": budget_for(len(config.get("fields") or ())),
        "fields": list(config.get("fields") or ()),
        "restricted_anchor": bool(config.get("restricted_anchor", False)),
        "seed_dir": str(seed_dir),
    }


def _sample_std(values):
    return float(np.std(values, ddof=1)) if len(values) > 1 else math.nan


def aggregate_seed_records(records) -> dict:
    rows = list(records)
    if not rows:
        raise ValueError("cannot aggregate zero seed records")
    means = [float(row["cv_c_mean"]) for row in rows]
    return {
        "dataset": rows[0]["dataset"],
        "landmark_tag": rows[0]["landmark_tag"],
        "algorithm": rows[0]["algorithm"],
        "n_seeds": len(rows),
        "seeds": [int(row["seed"]) for row in rows],
        "cv_c_mean": float(np.mean(means)),
        "cv_c_std": _sample_std(means),
        "recommended_k_mean": float(np.mean([row["recommended_k"] for row in rows])),
        "logical_evals_mean": float(np.mean([row["logical_evals"] for row in rows])),
        "physical_trains_mean": float(np.mean([row["physical_trains"] for row in rows])),
        "cache_rate": float(np.nanmean([row["cache_rate"] for row in rows])),
        "failure_rate": float(np.nanmean([row["failure_rate"] for row in rows])),
        "wall_ms_mean": float(np.mean([row["wall_ms"] for row in rows])),
        "seed_results": rows,
    }


def _csv_value(value):
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _write_csv(path, rows):
    rows = list(rows)
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: _csv_value(row.get(key)) for key in columns} for row in rows)


def write_algorithm_aggregate(algorithm_dir) -> dict:
    algorithm_dir = Path(algorithm_dir)
    records = [seed_record(path) for path in sorted(algorithm_dir.glob("seed_*")) if (path / "result.json").exists()]
    aggregate = aggregate_seed_records(records)
    serializable = {key: value for key, value in aggregate.items()}
    (algorithm_dir / "aggregate.json").write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2, allow_nan=True) + "\n", encoding="utf-8"
    )
    flat = {key: value for key, value in aggregate.items() if key != "seed_results"}
    _write_csv(algorithm_dir / "aggregate.csv", [flat])
    return aggregate


def paired_algorithm_comparison(left_records, right_records) -> dict:
    left = {int(row["seed"]): float(row["cv_c_mean"]) for row in left_records}
    right = {int(row["seed"]): float(row["cv_c_mean"]) for row in right_records}
    seeds = sorted(set(left) & set(right))
    differences = [left[seed] - right[seed] for seed in seeds]
    payload = {
        "common_seeds": seeds,
        "n_common_seeds": len(seeds),
        "mean_difference": float(np.mean(differences)) if differences else math.nan,
        "wilcoxon_p": math.nan,
    }
    if len(seeds) >= 2:
        try:
            from scipy.stats import wilcoxon
            if all(value == 0 for value in differences):
                payload["wilcoxon_p"] = 1.0
            else:
                value = float(wilcoxon(differences, alternative="two-sided").pvalue)
                payload["wilcoxon_p"] = value if math.isfinite(value) else 1.0
        except Exception:
            payload["wilcoxon_p"] = 1.0
            payload["wilcoxon_fallback"] = True
    return payload


def anytime_curve(evaluations, budget):
    points = []
    best = float("-inf")
    for row in sorted(evaluations, key=lambda item: int(item.get("logical_eval_idx", 0))):
        value = row.get("cv_c_mean") if row.get("status") == "ok" else None
        if value is not None and math.isfinite(float(value)):
            best = max(best, float(value))
        if math.isfinite(best):
            points.append((int(row["logical_eval_idx"]), best))
    if points and points[-1][0] < int(budget):
        points.append((int(budget), points[-1][1]))
    return points


def evaluate_h1(seed_rows) -> dict:
    grouped = defaultdict(lambda: defaultdict(list))
    for row in seed_rows:
        grouped[(row["dataset"], row["landmark_tag"])][row["algorithm"]].append(row)
    instances = []
    for (dataset, landmark), algorithms in sorted(grouped.items()):
        greedy_name = next((name for name in algorithms if name.startswith("A2_")), None)
        full_name = next((name for name in algorithms if name.startswith("A0_full")), None)
        if not greedy_name or not full_name:
            continue
        comparison = paired_algorithm_comparison(algorithms[greedy_name], algorithms[full_name])
        instances.append({"dataset": dataset, "landmark_tag": landmark, **comparison,
                          "meets_delta": comparison["mean_difference"] >= DELTA})
    successes = sum(row["meets_delta"] for row in instances)
    return {"instances": instances, "n_instances": len(instances), "n_meets_delta": successes,
            "fraction_meets_delta": successes / len(instances) if instances else math.nan,
            "target_fraction": 2 / 3, "supported": bool(instances) and successes / len(instances) >= 2 / 3}


def evaluate_h2(seed_rows) -> dict:
    aggregate = defaultdict(list)
    for row in seed_rows:
        aggregate[(row["dataset"], row["landmark_tag"], row["algorithm"])].append(float(row["cv_c_mean"]))
    by_instance = defaultdict(dict)
    for (dataset, landmark, algorithm), values in aggregate.items():
        by_instance[(dataset, landmark)][algorithm] = float(np.mean(values))
    baseline_sets = [
        {name for name in algorithms if name.startswith(BASELINES)}
        for algorithms in by_instance.values()
        if any(name.startswith(BASELINES) for name in algorithms)
    ]
    common_baselines = set.intersection(*baseline_sets) if baseline_sets else set()
    ranks = defaultdict(list)
    for algorithms in by_instance.values():
        baselines = {name: algorithms[name] for name in common_baselines if name in algorithms}
        if baselines:
            from scipy.stats import rankdata
            names = sorted(baselines)
            instance_ranks = rankdata([-baselines[name] for name in names], method="average")
            for name, rank in zip(names, instance_ranks):
                ranks[name].append(float(rank))
    if not ranks:
        return {"strongest_baseline": None, "mean_ranks": {}, "wins": 0, "comparisons": 0,
                "win_rate": math.nan, "target_win_rate": 0.6, "supported": False}
    mean_ranks = {name: float(np.mean(values)) for name, values in ranks.items()}
    strongest = min(mean_ranks, key=lambda name: (mean_ranks[name], name))
    comparisons = wins = 0
    for algorithms in by_instance.values():
        if strongest in algorithms and "SEAS" in algorithms:
            comparisons += 1
            wins += algorithms["SEAS"] > algorithms[strongest]
    rate = wins / comparisons if comparisons else math.nan
    return {"strongest_baseline": strongest, "mean_ranks": mean_ranks, "wins": wins,
            "comparisons": comparisons, "win_rate": rate, "target_win_rate": 0.6,
            "supported": comparisons > 0 and rate >= 0.6}


def _plot_anytime(seed_rows, display_root):
    import matplotlib.pyplot as plt
    grouped = defaultdict(list)
    for row in seed_rows:
        grouped[(row["dataset"], row["landmark_tag"])].append(row)
    out = Path(display_root) / "anytime"
    out.mkdir(parents=True, exist_ok=True)
    for (dataset, landmark), rows in grouped.items():
        fig, ax = plt.subplots(figsize=(7, 4.5))
        references = {}
        for row in rows:
            evaluations = _read_jsonl(Path(row["seed_dir"]) / "evaluations.jsonl")
            if row["algorithm"].startswith(("A0_", "A0b_", "A0c_")):
                references.setdefault(row["algorithm"], []).append(row["cv_c_mean"])
                continue
            points = anytime_curve(evaluations, row["budget"])
            if points:
                ax.step(*zip(*points), where="post", alpha=0.45, label=f'{row["algorithm"]} seed {row["seed"]}')
                if row["algorithm"].startswith("A2_"):
                    result = _read_json(Path(row["seed_dir"]) / "result.json")
                    k_sig = (result.get("metadata") or {}).get("k_sig")
                    if k_sig is not None:
                        recommended = frozenset(result.get("recommended_subset") or ())
                        marker = ({"logical_eval_idx": 0, "cv_c_mean": 0.5} if not recommended else
                                  next((item for item in evaluations if frozenset(item.get("subset") or ()) == recommended), None))
                        if marker is not None:
                            ax.scatter([marker["logical_eval_idx"]], [marker["cv_c_mean"]], marker="x", s=45,
                                       label=f'k_sig={k_sig}, seed {row["seed"]}')
        for name, values in sorted(references.items()):
            ax.axhline(float(np.mean(values)), linestyle="--", label=name)
        ax.set(xlabel="Logical evaluation", ylabel="Best CV c-index", title=f"{dataset} | {landmark}")
        ax.legend(fontsize=7, ncol=2)
        fig.tight_layout()
        fig.savefig(out / f"{dataset}__{landmark}.png", dpi=180)
        plt.close(fig)


def _plot_anchor_gaps(seed_rows, display_root):
    import matplotlib.pyplot as plt
    by_instance = defaultdict(dict)
    for row in seed_rows:
        if row["seed"] == 0:
            by_instance[(row["dataset"], row["landmark_tag"])][row["algorithm"]] = row
    gap_rows = []
    for (dataset, landmark), algorithms in sorted(by_instance.items()):
        anchor = algorithms.get("ANCHOR")
        if not anchor or not anchor["metadata"].get("restricted_exact", False):
            continue
        for name, row in sorted(algorithms.items()):
            if name != "ANCHOR" and set(row["fields"]) == set(anchor["fields"]):
                gap_rows.append({"instance": f"{dataset}/{landmark}", "algorithm": name,
                                 "optimality_gap": optimality_gap(anchor["best_cv_c_mean"], row["best_cv_c_mean"])})
    _write_csv(Path(display_root) / "anchor_gap" / "optimality_gap.csv", gap_rows)
    if gap_rows:
        fig, ax = plt.subplots(figsize=(max(7, 0.35 * len(gap_rows)), 4.5))
        ax.bar(range(len(gap_rows)), [row["optimality_gap"] for row in gap_rows])
        ax.set_xticks(range(len(gap_rows)), [f'{row["instance"]}\n{row["algorithm"]}' for row in gap_rows], rotation=90, fontsize=7)
        ax.set_ylabel("Restricted-space optimality gap")
        fig.tight_layout()
        out = Path(display_root) / "anchor_gap" / "optimality_gap.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=180)
        plt.close(fig)
    return gap_rows


def _plot_landmarks(aggregates, display_root):
    import matplotlib.pyplot as plt
    grouped = defaultdict(list)
    for row in aggregates:
        grouped[row["algorithm"]].append(row)
    out = Path(display_root) / "landmark"
    out.mkdir(parents=True, exist_ok=True)
    order = ("landmark_0", "landmark_365", "landmark_730", "landmark_none")
    for algorithm, rows in grouped.items():
        values = defaultdict(list)
        for row in rows:
            values[row["landmark_tag"]].append(row["cv_c_mean"])
        if not values:
            continue
        means = [float(np.mean(values[tag])) if values[tag] else math.nan for tag in order]
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(order, means, marker="o")
        ax.set(ylabel="Mean CV c-index", title=algorithm)
        fig.tight_layout()
        fig.savefig(out / f"{algorithm}.png", dpi=180)
        plt.close(fig)


def generate_report(results_root="results/E2_selection/prompt", display_root="results_display/E2_selection/prompt",
                    anchor_root="results/E2_selection/anchor/prompt"):
    results_root = Path(results_root)
    seed_dirs = sorted(path.parent for path in results_root.glob("**/seed_*/result.json"))
    anchor_root = Path(anchor_root)
    if anchor_root.exists() and anchor_root.resolve() != results_root.resolve():
        seed_dirs.extend(sorted(path.parent for path in anchor_root.glob("**/seed_*/result.json")))
    seed_rows = [seed_record(path) for path in seed_dirs]
    primary_rows = [row for row in seed_rows if not row["restricted_anchor"]]
    grouped = defaultdict(list)
    for row in primary_rows:
        grouped[(row["dataset"], row["landmark_tag"], row["algorithm"])].append(row)
    aggregates = [aggregate_seed_records(rows) for _, rows in sorted(grouped.items())]
    main_rows = [{key: value for key, value in row.items() if key != "seed_results"} for row in aggregates]
    display_root = Path(display_root)
    display_root.mkdir(parents=True, exist_ok=True)
    _write_csv(display_root / "main_table.csv", main_rows)
    h1, h2 = evaluate_h1(primary_rows), evaluate_h2(primary_rows)
    gaps = _plot_anchor_gaps(seed_rows, display_root)
    _plot_anytime(primary_rows, display_root)
    _plot_landmarks(aggregates, display_root)
    summary = {"h1": h1, "h2": h2, "anchor_gaps": gaps, "n_seed_runs": len(seed_rows)}
    (display_root / "statistics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=True) + "\n", encoding="utf-8"
    )
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aggregate E2 CV results and draw E2 figures")
    parser.add_argument("--results-root", default="results/E2_selection/prompt")
    parser.add_argument("--display-root", default="results_display/E2_selection/prompt")
    parser.add_argument("--anchor-root", default="results/E2_selection/anchor/prompt")
    args = parser.parse_args(argv)
    print(json.dumps(generate_report(args.results_root, args.display_root, args.anchor_root), ensure_ascii=False, allow_nan=True))


if __name__ == "__main__":
    main()
