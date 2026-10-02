"""Test_2 对照报表: 贪婪最优组合 vs 各工作去泄露后的组合。

三臂(见 z_notes/Test_series_spec.md §7.2, 全部 landmark_0):
  臂 B  = 工作完整组合 × scheme 模板 (results/A_manual_landmark/{dataset}[gdc]/cindex.csv 行 {work}__landmark_0)
  臂 B' = 工作完整组合 × bank 模板 (自定义方案 Test_3_{work}_{dataset})
  臂 C  = 贪婪最优组合 × bank 模板 (自定义方案 Test_3_greedy_{dataset})

输出: Δc = C − B'(模板控制头条) 与 C − B(交叉验证), 遗漏字段清单(C \\ 工作组合)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "A_pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

A_TEMPLATES = ROOT / "A_pipeline" / "templates"
RESULTS = ROOT / "results"
OUT_ROOT = ROOT / "results_display" / "Test_3_greedy_vs_works"


def load_fields(scheme: str) -> list[str]:
    path = A_TEMPLATES / scheme / "fields.json"
    if not path.exists():
        raise SystemExit(f"[test_2] 方案不存在: {scheme}")
    return [str(f).strip() for f in json.loads(path.read_text(encoding="utf-8")).get("fields", [])]


def rows_for(dataset: str, scheme: str) -> pd.DataFrame:
    path = RESULTS / "A_manual_landmark" / f"{dataset}[gdc]" / "cindex.csv"
    if not path.exists():
        raise SystemExit(f"[test_2] 缺 cindex 表: {path}")
    df = pd.read_csv(path)
    mask = df["scheme"] == f"{scheme}__landmark_0"
    if not mask.any():
        raise SystemExit(f"[test_2] 表内无 {scheme}__landmark_0 行: {path}")
    return df[mask]


def cindex_by_modality(rows: pd.DataFrame) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for _, row in rows.iterrows():
        modality = str(row.get("modality", ""))
        out[modality] = {
            "c": float(row["val_c_index_mean"]),
            "std": float(row["val_c_index_std"]),
        }
    return out


def compare(dataset: str, work: str, name_bp: str, name_c: str) -> dict:
    b = cindex_by_modality(rows_for(dataset, work))
    bp = cindex_by_modality(rows_for(dataset, name_bp))
    c = cindex_by_modality(rows_for(dataset, name_c))
    work_fields = set(load_fields(work))
    c_fields = set(load_fields(name_c))
    missed = sorted(c_fields - work_fields)
    report = {"dataset": dataset, "work": work,
              "n_fields_work": len(work_fields), "n_fields_greedy": len(c_fields),
              "missed_fields": missed,
              "per_modality": {}}
    for modality in sorted(set(c) & set(bp) & set(b)):
        report["per_modality"][modality] = {
            "B": b[modality], "Bp": bp[modality], "C": c[modality],
            "delta_C_minus_Bp": round(c[modality]["c"] - bp[modality]["c"], 6),
            "delta_C_minus_B": round(c[modality]["c"] - b[modality]["c"], 6),
        }
    return report


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Test_2 贪婪 vs 工作 对照")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--work", required=True, help="工作方案名(如 MULTISURV)")
    parser.add_argument("--name-bp", default=None, help="臂 B' 自定义方案名(默认 Test_3_{work}_{dataset})")
    parser.add_argument("--name-c", default=None, help="臂 C 自定义方案名(默认 Test_3_greedy_{dataset})")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    name_bp = args.name_bp or f"Test_3_{args.work}_{args.dataset}"
    name_c = args.name_c or f"Test_3_greedy_{args.dataset}"
    report = compare(args.dataset, args.work, name_bp, name_c)

    out = Path(args.out) if args.out else OUT_ROOT / f"{args.dataset}__{args.work}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[test_2] 写 {out}")


if __name__ == "__main__":
    main()
