#!/usr/bin/env python3
"""Test_4 三档汇总表（报告值 / 去泄露值 / 可达值）——纯汇总，无训练。

口径（z_notes/Test_series_spec.md §12 U1 协议 A；分层与列风格对齐 Test_2b_delta_report.py）：
  - 档 1 报告值   = results/Test_2b/arm_A/{dataset}[gdc]/cindex.csv 的 {work} 行（论文报告原值）
  - 档 2 去泄露值 = results/Test_2b/arm_B/{dataset}[gdc]/cindex.csv 的 {work}__landmark_0 行
                    （S6 已修复的汇总口径；与报告值同字段集、同编码、同模型、同划分）
  - 档 3 可达值   = results/Test_3_greedy_vs_works/three_arm.csv 的 C_c
                    （Test_3 臂 C：贪婪最优字段 × bank 模板，landmark_0 同协议）
  - 档间 Δ：Δ1 = 报告 − 去泄露（泄露高估幅度）；Δ2 = 去泄露 − 可达（字段选择差距）
  - 主口径 analyzer = mlp_clinic_flatten；clinic_cox 作交叉列（与 three_arm.csv 的 cox 列同源口径）
  - 缺臂哲学（与 Test_3_compare.py 一致）：缺可达值（无搜索 result.json / 未 drain）的行
    **整行保留**，C 相关列记 "pending"，不中断；arm_A 无该 (dataset, work) 行时报告列记 "n/a"
    （该工作在论文中未报告该数据集，如 SURVPGC / MMSURV 的非原文数据集）。
  - 数据集分层 = 协议 A 四档（n_event 从 Test_0 manifest / event_summary 读，不硬编码）：
    main ≥100 / main_ci 70–100（须带 CI，不排名）/ supp 30–70 / low <30。

输入（全部只读）：
  - results/Test_2b/arm_A/{dataset}[gdc]/cindex.csv、results/Test_2b/arm_B/{dataset}[gdc]/cindex.csv
  - results/Test_3_greedy_vs_works/three_arm.csv（Test_3_compare.py 产物）
  - scripts/Test_3_common.py（主集名单 / 方案绑定 / n_event；硬编码禁令 R13）
  - A_pipeline/templates/{work}/fields.json（工作组合字段数）

输出（默认 results_display/Test_4_three_tiers/；Main_ 前缀 = 头条）：
  - Main_three_tiers.csv   每 (dataset, work) 一行三档 + 档间 Δ（协议 A 档位 → 数据集 → 方案排序）
  - Main_tier_summary.csv  按协议 A 四档聚合（行数 / pending 数 / Δ 均值中位）
  - README.md              口径与状态说明（手写，results_display/** 被 .gitignore 忽略，不入库）

说明（预览版）：可达值产自 Test_3 **旧 sig 停点**（δ=0.005 + Wilcoxon 门控）；D4 修订
（2026-10-04，stop_mode=gain_only）后如需重出，对应数据集 C 值会变。15 集齐后重出完整版。

用法：
  python3 results_display/scripts/Test_4_three_tiers.py            # 生成
  python3 results_display/scripts/Test_4_three_tiers.py --audit    # 生成 + 前 2 行三档抽查
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT, REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common.paths import remap_legacy_result_path, test_results_dir  # noqa: E402
import Test_3_common as C3  # noqa: E402

ARM_A_ROOT = test_results_dir("Test_2b/arm_A")
ARM_B_ROOT = test_results_dir("Test_2b/arm_B")
THREE_ARM_CSV = C3.OUT_ROOT / "three_arm.csv"
TEMPLATES = REPO_ROOT / "A_pipeline" / "templates"

MLP = "mlp_clinic_flatten"  # 主口径（E2 唯一搜索目标模型）
COX = "clinic_cox"          # 交叉列
PENDING = "pending"         # 缺可达值（与 Test_3_compare 同哲学）
NA = "n/a"                  # 源表无该行（工作未报告该数据集）

TIER_ORDER = {"main": 0, "main_ci": 1, "supp": 2, "low": 3}

FIELDS = [
    "dataset", "work", "tier", "n_event", "n_fields_work",
    "report_c", "report_std",
    "deleak_c", "deleak_std",
    "delta_report_minus_deleak",
    "reach_c", "reach_std", "reach_bp_c", "reach_bp_std",
    "delta_deleak_minus_reach", "delta_C_minus_Bp",
    "n_fields_greedy", "n_missed",
    "report_cox_c", "deleak_cox_c", "delta_report_minus_deleak_cox",
    "status",
]


# --------------------------------------------------------------------------- 分层
def tier_for(n_event: int) -> str:
    if n_event >= 100:
        return "main"
    if n_event >= 70:
        return "main_ci"
    if n_event >= 30:
        return "supp"
    return "low"


def tier_label(tier: str) -> str:
    return {
        "main": "main (n_event>=100)",
        "main_ci": "main_ci (70-100, CI required, no ranking)",
        "supp": "supp (30-70, qualitative)",
        "low": "low (<30, qualitative only)",
    }[tier]


# --------------------------------------------------------------------------- 读取
def read_metric(csv_path: Path, scheme: str, modality: str) -> dict | None:
    """从 cindex.csv 取一行 (scheme, modality)；表缺失/无该行 -> None。

    返回 {"mean": float, "std": float, "results_dir": str|None, "source": str}。
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    sub = df[(df["scheme"] == scheme) & (df["modality"] == modality)]
    if sub.empty:
        return None
    row = sub.iloc[0]
    std = row.get("val_c_index_std")
    return {
        "mean": float(row["val_c_index_mean"]),
        "std": None if pd.isna(std) else float(std),
        "results_dir": None if pd.isna(row.get("results_dir")) else str(row.get("results_dir")),
        "source": "" if pd.isna(row.get("source")) else str(row.get("source")),
    }


def work_n_fields(work: str, templates: Path = TEMPLATES) -> int | None:
    path = Path(templates) / work / "fields.json"
    if not path.exists():
        return None
    return len(json.loads(path.read_text(encoding="utf-8")).get("fields", []))


def load_three_arm(path: Path) -> dict[tuple[str, str], dict]:
    """three_arm.csv -> {(dataset, work): row dict}；文件缺失 -> 空表（全部 pending）。"""
    path = Path(path)
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    out: dict[tuple[str, str], dict] = {}
    for _, row in df.iterrows():
        out[(str(row["dataset"]), str(row["work"]))] = row.to_dict()
    return out


def _num(value) -> float | None:
    """工作表值 -> float；"pending"/"n/a"/None/NaN -> None。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text in ("", PENDING, NA):
        return None
    return float(text)


def _r6(value: float) -> float:
    return round(value, 6)


def _cell(metric: dict | None, key: str):
    return NA if metric is None else metric[key]


# --------------------------------------------------------------------------- 装配
def build_rows(datasets: list[str], pairs: list[tuple[str, str]],
               n_event: dict[str, int], *,
               arm_a_root: Path = ARM_A_ROOT, arm_b_root: Path = ARM_B_ROOT,
               three_arm: dict[tuple[str, str], dict] | None = None,
               templates: Path = TEMPLATES) -> list[dict]:
    """(dataset, work) × 三档；缺臂不中断（C -> pending，报告值缺 -> n/a）。"""
    if three_arm is None:
        three_arm = load_three_arm(THREE_ARM_CSV)
    rows: list[dict] = []
    for dataset, work in pairs:
        if dataset not in n_event:
            raise SystemExit(f"[error] n_event 表缺 {dataset}（manifest/event_summary）")
        n_ev = n_event[dataset]
        report = read_metric(Path(arm_a_root) / f"{dataset}[gdc]" / "cindex.csv", work, MLP)
        report_cox = read_metric(Path(arm_a_root) / f"{dataset}[gdc]" / "cindex.csv", work, COX)
        deleak = read_metric(Path(arm_b_root) / f"{dataset}[gdc]" / "cindex.csv",
                             f"{work}__landmark_0", MLP)
        deleak_cox = read_metric(Path(arm_b_root) / f"{dataset}[gdc]" / "cindex.csv",
                                 f"{work}__landmark_0", COX)
        arm3 = three_arm.get((dataset, work))

        d1 = None
        if report is not None and deleak is not None:
            d1 = _r6(report["mean"] - deleak["mean"])
        d1_cox = None
        if report_cox is not None and deleak_cox is not None:
            d1_cox = _r6(report_cox["mean"] - deleak_cox["mean"])

        reach = _num(arm3.get("C_c")) if arm3 else None
        reach_std = _num(arm3.get("C_std")) if arm3 else None
        reach_bp = _num(arm3.get("Bp_c")) if arm3 else None
        reach_bp_std = _num(arm3.get("Bp_std")) if arm3 else None
        d2 = _r6(deleak["mean"] - reach) if (deleak is not None and reach is not None) else None
        d_c_bp = _num(arm3.get("delta_C_minus_Bp")) if arm3 else None

        rows.append({
            "dataset": dataset,
            "work": work,
            "tier": tier_for(n_ev),
            "n_event": n_ev,
            "n_fields_work": work_n_fields(work, templates),
            "report_c": _cell(report, "mean"),
            "report_std": _cell(report, "std"),
            "deleak_c": _cell(deleak, "mean"),
            "deleak_std": _cell(deleak, "std"),
            "delta_report_minus_deleak": NA if d1 is None else d1,
            "reach_c": PENDING if reach is None else reach,
            "reach_std": PENDING if reach is None else reach_std,
            "reach_bp_c": PENDING if reach_bp is None else reach_bp,
            "reach_bp_std": PENDING if reach_bp is None else reach_bp_std,
            "delta_deleak_minus_reach": PENDING if d2 is None else d2,
            "delta_C_minus_Bp": PENDING if d_c_bp is None else d_c_bp,
            "n_fields_greedy": PENDING if arm3 is None else int(arm3["n_fields_greedy"]),
            "n_missed": PENDING if arm3 is None else int(arm3["n_missed"]),
            "report_cox_c": _cell(report_cox, "mean"),
            "deleak_cox_c": _cell(deleak_cox, "mean"),
            "delta_report_minus_deleak_cox": NA if d1_cox is None else d1_cox,
            "status": "ok" if reach is not None else "pending_C",
        })
    rows.sort(key=lambda r: (TIER_ORDER[r["tier"]], r["dataset"], r["work"]))
    return rows


def tier_summary_rows(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for tier in sorted(TIER_ORDER, key=TIER_ORDER.get):
        sub = [r for r in rows if r["tier"] == tier]
        if not sub:
            continue
        ok = [r for r in sub if r["status"] == "ok"]
        d1 = [v for v in (_num(r["delta_report_minus_deleak"]) for r in sub) if v is not None]
        d2 = [v for v in (_num(r["delta_deleak_minus_reach"]) for r in ok) if v is not None]

        def _mean(values: list[float]):
            return None if not values else _r6(sum(values) / len(values))

        def _median(values: list[float]):
            if not values:
                return None
            ordered = sorted(values)
            mid = len(ordered) // 2
            if len(ordered) % 2:
                return _r6(ordered[mid])
            return _r6((ordered[mid - 1] + ordered[mid]) / 2)

        out.append({
            "tier": tier,
            "tier_label": tier_label(tier),
            "n_pairs": len(sub),
            "n_ok": len(ok),
            "n_pending_C": len(sub) - len(ok),
            "n_report_unavailable": sum(1 for r in sub if _num(r["report_c"]) is None),
            "delta1_mean": "" if not d1 else _mean(d1),
            "delta1_median": "" if not d1 else _median(d1),
            "delta2_mean": "" if not d2 else _mean(d2),
            "delta2_median": "" if not d2 else _median(d2),
        })
    return out


# --------------------------------------------------------------------------- 写出
def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_tables(rows: list[dict], out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    written = [
        _write_csv(out_dir / "Main_three_tiers.csv", rows, FIELDS),
        _write_csv(
            out_dir / "Main_tier_summary.csv",
            tier_summary_rows(rows),
            ["tier", "tier_label", "n_pairs", "n_ok", "n_pending_C",
             "n_report_unavailable", "delta1_mean", "delta1_median",
             "delta2_mean", "delta2_median"],
        ),
    ]
    return written


# --------------------------------------------------------------------------- 审计
def fold_mean_std(results_dir: str | Path) -> tuple[float, float, int]:
    """run 目录折文件重算（与 A_pipeline.read_cindex 同算术：末行 val_cindex）。"""
    path = Path(results_dir)
    vals: list[float] = []
    for f in sorted(path.glob("val_result_fold*.csv")):
        df = pd.read_csv(f)
        vals.append(float(df["val_cindex"].iloc[-1]))
    if not vals:
        raise SystemExit(f"[error] 折文件缺失: {path}")
    mean = sum(vals) / len(vals)
    std = (sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5
    return mean, std, len(vals)


def audit(rows: list[dict], *, arm_a_root: Path = ARM_A_ROOT,
          arm_b_root: Path = ARM_B_ROOT, n_sample: int = 2) -> None:
    """抽前 n_sample 个 status=ok 行：三档数值与各源表/折文件手算对照（逐位）。"""
    ok_rows = [r for r in rows if r["status"] == "ok"]
    sample = [r for r in ok_rows if _num(r["report_c"]) is not None][:n_sample]
    fallback = len(sample) < n_sample
    if fallback:  # 报告值 n/a 的行也保留在表中，但不能做三档全查
        sample = (sample + [r for r in ok_rows if r not in sample])[:n_sample]
    if not sample:
        print("[audit] 无可达值行（全 pending），跳过抽查（这不等于失败）")
        return
    print(f"[audit] 抽查前 {len(sample)} 个可达值行:")
    all_pass = True
    for r in sample:
        dataset, work = r["dataset"], r["work"]
        study = dataset.lower().replace("-", "_")
        print(f"  - {dataset} × {work}")
        checks: dict[str, bool] = {}

        # 1) 报告值：arm_A 表重读 + 折文件重算（legacy 路径 remap）
        ra = read_metric(Path(arm_a_root) / f"{dataset}[gdc]" / "cindex.csv", work, MLP)
        if ra is None:
            # 该工作未在论文中报告该数据集：表内报告列记 n/a，此处跳过报告相关核对
            checks["报告值 n/a（源表确无该行）"] = (_num(r["report_c"]) is None
                                             and _num(r["delta_report_minus_deleak"]) is None)
        else:
            checks["报告值=arm_A表"] = abs(float(r["report_c"]) - ra["mean"]) == 0.0
            if ra["results_dir"]:
                mean, _, n = fold_mean_std(remap_legacy_result_path(ra["results_dir"]))
                checks["报告值=arm_A折文件重算"] = (abs(float(r["report_c"]) - mean) < 1e-12
                                          and n == 5)
        # 2) 去泄露值：arm_B 表重读 + 折文件重算
        rb = read_metric(Path(arm_b_root) / f"{dataset}[gdc]" / "cindex.csv",
                         f"{work}__landmark_0", MLP)
        if rb is None:
            checks["去泄露值存在"] = False
        else:
            checks["去泄露值=arm_B表"] = abs(float(r["deleak_c"]) - rb["mean"]) == 0.0
            if rb["results_dir"]:
                mean, _, n = fold_mean_std(remap_legacy_result_path(rb["results_dir"]))
                checks["去泄露值=arm_B折文件重算"] = (abs(float(r["deleak_c"]) - mean) < 1e-12
                                          and n == 5)
        # 3) 可达值：three_arm.csv 重读
        arm3 = load_three_arm(THREE_ARM_CSV).get((dataset, work))
        checks["可达值=three_arm.csv"] = (
            arm3 is not None and abs(float(r["reach_c"]) - float(arm3["C_c"])) == 0.0
            and abs(float(r["reach_bp_c"]) - float(arm3["Bp_c"])) == 0.0)
        # 4) 档间 Δ 与手算差值一致（同为 6 位舍入）；报告值缺时 Δ1 = n/a
        if _num(r["report_c"]) is None:
            checks["Δ1=n/a（报告值缺）"] = str(r["delta_report_minus_deleak"]) == NA
        else:
            d1_hand = _r6(float(r["report_c"]) - float(r["deleak_c"]))
            checks["Δ1=手算(报告−去泄露)"] = (
                abs(float(r["delta_report_minus_deleak"]) - d1_hand) == 0.0)
        d2_hand = _r6(float(r["deleak_c"]) - float(r["reach_c"]))
        checks["Δ2=手算(去泄露−可达)"] = abs(float(r["delta_deleak_minus_reach"]) - d2_hand) == 0.0
        # 5) cox 交叉列同源
        rc = read_metric(Path(arm_a_root) / f"{dataset}[gdc]" / "cindex.csv", work, COX)
        if rc is None:
            checks["cox 报告列 n/a"] = (str(r["report_cox_c"]) == NA
                                        and str(r["delta_report_minus_deleak_cox"]) == NA)
        else:
            checks["cox 报告列=arm_A表"] = (
                abs(float(r["report_cox_c"]) - rc["mean"]) == 0.0)
        # 6) n_fields_work 与 three_arm 对齐（表格口径自洽）
        checks["n_fields_work=three_arm"] = (
            arm3 is not None and int(r["n_fields_work"]) == int(arm3["n_fields_work"]))
        for name, passed in checks.items():
            print(f"      [{'PASS' if passed else 'FAIL'}] {name}")
            all_pass &= bool(passed)
    pending = [r for r in rows if r["status"] == "pending_C"]
    print(f"[audit] 同行口径核对: pending_C {len(pending)}/{len(rows)} 行 C 列记 pending"
          f"（其 Δ2 同为 pending）")
    print(f"[audit] 总体: {'ALL PASS' if all_pass else 'HAS FAILURES'}")
    if not all_pass:
        sys.exit(1)


def check_out_dir_inventory(out_dir: Path, written: list[Path]) -> None:
    expected = {p.name for p in written}
    missing = sorted(name for name in expected if not (out_dir / name).exists())
    if missing:
        print(f"[warn] 产物缺失: {', '.join(missing)}")
    for name in sorted(p.name for p in Path(out_dir).iterdir() if p.is_file()):
        if name not in expected and name != "README.md":
            print(f"[warn] 清单外文件: {name}")


# --------------------------------------------------------------------------- 主流程
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Test_4 三档汇总表（纯汇总）")
    ap.add_argument("--out", default=str(REPO_ROOT / "results_display" / "Test_4_three_tiers"),
                    help="产物目录（默认 results_display/Test_4_three_tiers）")
    ap.add_argument("--audit", action="store_true", help="生成后抽查前 2 行三档数值")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    datasets = C3.main_datasets()
    pairs = C3.work_pairs(datasets)
    n_event = C3.load_n_event()
    rows = build_rows(datasets, pairs, n_event)
    ok = [r for r in rows if r["status"] == "ok"]
    pending_ds = sorted({r["dataset"] for r in rows if r["status"] == "pending_C"})
    print(f"[build] 主集 {len(datasets)} × 工作组合 = {len(rows)} 行；"
          f"可达值 {len(ok)} 行 / pending_C {len(rows) - len(ok)} 行")
    print(f"[build] tier 分布: "
          f"{ {t: sum(1 for r in rows if r['tier'] == t) for t in TIER_ORDER} }")
    print(f"[build] pending 数据集（{len(pending_ds)}）: {', '.join(pending_ds)}")

    written = write_tables(rows, out_dir)
    for path in written:
        print(f"[csv] {path.name}")

    if args.audit:
        audit(rows)
    check_out_dir_inventory(out_dir, written)
    print("[done]")


if __name__ == "__main__":
    main()
