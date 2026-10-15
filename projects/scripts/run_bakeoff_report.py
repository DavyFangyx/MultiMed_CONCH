"""Test_6 bake-off 汇总:比较性 GT 判定表 + 图(只读,无训练)。

用法示例(试点跑完后):
  python scripts/run_bakeoff_report.py \
    --results-root results/Test_6_search/prompt \
    --extra-roots results/greedy_lm0/search
  # 预算上限从结果目录名 cap_{cap} 自动识别,无需传参;
  # 根下有多个 cap 目录时一次跑完,产物落 results_display/Test_6_search/cap_{cap}/
"""

from __future__ import annotations

import argparse
import csv
import json
import re
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


def _cap_from_dir(path: Path) -> int | None:
    """cap_{cap} 目录名 → 预算上限;非 cap 目录返回 None。"""
    m = re.fullmatch(r"cap_(\d+)", path.name)
    return int(m.group(1)) if m else None


def _discover_caps(results_root: Path) -> list[tuple[int | None, Path]]:
    """结果根 → [(cap, 结果目录)]。

    - 根本身是 cap_{cap} 目录:单 cap(显式指定);
    - 根下任意深度有 cap_{cap} 目录:全部纳入,一次报告跑完所有 cap;
    - 都没有:视为无 cap 旧布局,原根整体作为一个单元(cap=None,口径回落 --budget_cap/500)。
    """
    if _cap_from_dir(results_root) is not None:
        return [(_cap_from_dir(results_root), results_root)]
    found: dict[int, Path] = {}
    for path in results_root.glob("**/cap_*"):
        if path.is_dir() and (cap := _cap_from_dir(path)) is not None:
            found.setdefault(cap, path)
    if found:
        return [(cap, found[cap]) for cap in sorted(found)]
    return [(None, results_root)]


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
    parser.add_argument("--budget_cap", type=int, default=None,
                        help="anytime 截断上限;默认从结果路径 cap_{cap} 自动推断(旧布局回落 500)")
    parser.add_argument("--competitors", default=",".join(COMPETING_ALGOS),
                        help="竞争算法列表(逗号分隔);其余算法视为参考行")
    parser.add_argument("--delta", type=float, default=0.005)
    args = parser.parse_args(argv)

    extra_roots = []
    for raw in str(args.extra_roots).split(","):
        if raw.strip():
            extra_roots.append(Path(raw.strip()))
    competitors = tuple(name.strip() for name in args.competitors.split(",") if name.strip())

    done = 0
    for cap, cap_root in _discover_caps(Path(args.results_root)):
        records = _collect_records([cap_root] + extra_roots)
        if not records:
            print(f"[bakeoff] cap={cap} 无 seed_*/result.json,跳过: {cap_root}")
            continue
        horizon = args.budget_cap if args.budget_cap is not None else (cap if cap is not None else 500)
        display = Path(args.display_root)
        if not display.is_absolute():
            display = ROOT / display
        if cap is not None:
            display = display / f"cap_{cap}"
        display.mkdir(parents=True, exist_ok=True)
        print(f"[bakeoff] cap={cap} horizon={horizon} display={display}", flush=True)

        gt = comparative_gt(records, competitors)
        _write_csv(display / "gap_table.csv", gap_table(records, competitors))
        _write_csv(display / "win_rate.csv", win_rate_vs_greedy(records, competitors))
        ranks, per_instance = mean_rank_table(records, competitors)
        _write_csv(display / "ranks.csv", ranks)
        decision = decide(records, delta=args.delta, competitors=competitors)
        decision["comparative_gt"] = {"/".join(instance): value for instance, value in gt.items()}
        (display / "decision.json").write_text(
            json.dumps(decision, ensure_ascii=False, indent=2, allow_nan=True) + "\n", encoding="utf-8")
        plot_anytime(records, display, budget_cap=horizon)
        print(json.dumps(decision, ensure_ascii=False, indent=2, allow_nan=True))
        done += 1
    if not done:
        raise SystemExit(f"没有找到任何 seed_*/result.json: "
                         f"{[str(r) for r in [Path(args.results_root)] + extra_roots]}")


if __name__ == "__main__":
    main()
