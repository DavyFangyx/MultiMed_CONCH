"""Test_6 bake-off 汇总:比较性 GT 判定表 + 图(只读,无训练)。

用法示例(试点跑完后):
  python scripts/run_bakeoff_report.py \
    --results-root results/Test_6_search/prompt \
    --extra-roots results/Test_3_greedy_vs_works/search \
    --budget_cap 500
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from selection.bakeoff import (COMPETING_ALGOS, comparative_gt, decide, gap_table,
                               mean_rank_table, win_rate_vs_greedy)
from selection.report import plot_anytime, seed_record


def _write_csv(path, rows):
    rows = list(rows)
    if not rows:
        print(f"[skip] {path}: 无行可写")
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                                   if isinstance(value, (list, dict, tuple)) else value)
                             for key, value in row.items()})


def _collect_records(roots):
    seed_dirs = []
    for root in roots:
        seed_dirs.extend(sorted(path.parent for path in Path(root).glob("**/seed_*/result.json")))
    records = [seed_record(path) for path in seed_dirs]
    # 同名 (dataset/landmark/algo/modality/seed) 重复时按出现顺序取第一个(results-root 优先)
    seen, unique = set(), []
    for row in records:
        key = (row["dataset"], row["landmark_tag"], row["algorithm"],
               row["modality"], row["seed"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def main(argv=None):
    parser = argparse.ArgumentParser(description="Test_6 搜索算法选型 bake-off 汇总(比较性 GT)")
    parser.add_argument("--results-root", default=str(ROOT / "results/Test_6_search/prompt"),
                        help="试点结果根目录(**/seed_*/result.json)")
    parser.add_argument("--extra-roots", default="",
                        help="逗号分隔的附加根目录(如贪心既有结果 results/Test_3_greedy_vs_works/search)")
    parser.add_argument("--display-root", default="results_display/Test_6_search")
    parser.add_argument("--budget_cap", type=int, default=500, help="对比预算上限(anytime 截断处)")
    parser.add_argument("--competitors", default=",".join(COMPETING_ALGOS),
                        help="竞争算法列表(逗号分隔);其余算法视为参考行")
    parser.add_argument("--delta", type=float, default=0.005)
    args = parser.parse_args(argv)

    roots = [Path(args.results_root)]
    for raw in str(args.extra_roots).split(","):
        if raw.strip():
            roots.append(Path(raw.strip()))
    competitors = tuple(name.strip() for name in args.competitors.split(",") if name.strip())
    records = _collect_records(roots)
    if not records:
        raise SystemExit(f"没有找到任何 seed_*/result.json: {[str(r) for r in roots]}")

    display = Path(args.display_root)
    if not display.is_absolute():
        display = ROOT / display
    display.mkdir(parents=True, exist_ok=True)

    gt = comparative_gt(records, competitors)
    _write_csv(display / "gap_table.csv", gap_table(records, competitors))
    _write_csv(display / "win_rate.csv", win_rate_vs_greedy(records, competitors))
    ranks, per_instance = mean_rank_table(records, competitors)
    _write_csv(display / "ranks.csv", ranks)
    decision = decide(records, delta=args.delta, competitors=competitors)
    decision["comparative_gt"] = {"/".join(instance): value for instance, value in gt.items()}
    (display / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    plot_anytime(records, display, budget_cap=args.budget_cap)
    print(json.dumps(decision, ensure_ascii=False, indent=2, allow_nan=True))


if __name__ == "__main__":
    main()
