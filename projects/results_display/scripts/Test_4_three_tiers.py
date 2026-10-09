#!/usr/bin/env python3
"""Test_4 三档汇总表（报告值 / 去泄露值 / 可达值）——纯汇总，无训练。

口径(bank-only,2026-10-07;臂语义见 z_notes/experiment_list/arm_registry.md):
  - 档 1 报告值   = results/Test_2b/arm_A/{dataset}[gdc]/cindex.csv 的 {work} 行
                    (论文报告原值 = work × raw × apipe;apipe 编码已退役删除,本行为冻结历史口径,
                     待 report 臂 bank 重建(work × raw-bank 切片 + 训练)后替换)
  - 档 2 去泄露值 = deleak 臂(Test_3_{work}_{ds}__landmark_0 行,work × lm0 × bank 切片)
  - 档 3 可达值   = two_arm.csv 的 C_c;缺失回退搜索 result.json 的 best_cv_c_mean
                    (bank-only 口径下与 reach 臂同嵌入同模型同折同 seed,零训练)
  - 档间 Δ:Δ1 = 报告 − 去泄露(泄露高估幅度;现混 apipe→bank 路径差,干净口径 =
    Test_2b_delta 的 A−B 同路径对照);Δ2 = 去泄露 − 可达(字段选择差距,同 bank 路径)
  - 主口径 analyzer = mlp_clinic_flatten;clinic_cox 仅作报告值交叉列(论文历史数字)
  - 缺臂哲学(与 Test_3_compare.py 一致):缺可达值(无搜索 result.json / 未 drain)的行
    **整行保留**,C 相关列记 "pending",不中断;arm_A 无该 (dataset, work) 行时报告列记 "n/a"
    (该工作在论文中未报告该数据集,如 SURVPGC / MMSURV 的非原文数据集)。
  - 数据集分层 = 协议 A 四档(n_event 从 Test_0 manifest / event_summary 读,不硬编码):
    main ≥100 / main_ci 70–100(须带 CI,不排名)/ supp 30–70 / low <30。

输入（全部只读）：
  - results/Test_2b/arm_A/{dataset}[gdc]/cindex.csv、results/Test_2b/arm_B/{dataset}[gdc]/cindex.csv
  - results/Test_3_greedy_vs_works/two_arm.csv（Test_3_compare.py 产物）
  - scripts/Test_3_common.py（主集名单 / 方案绑定 / n_event；硬编码禁令 R13）
  - templates/manual_schemes/{work}/fields.json（工作组合字段数）

输出（默认 results_display/Test_4_three_tiers/；Main_ 前缀 = 头条）：
  - Main_three_tiers.csv   每 (dataset, work) 一行三档 + 档间 Δ（协议 A 档位 → 数据集 → 方案排序）
  - Main_three_tiers.png   头条柱状图：逐数据集三档均值（橙=报告/蓝=去泄露/绿=可达，仅可达值就绪的数据集）
  - Appx_three_tiers_by_work.png 附录柱状图：逐工作三档均值（跨可达值就绪数据集聚合）
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

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

# ---- 视觉常量（与 Test_2b_delta_report.py 同一套 light 表面；三档配色）----
INK = "#0b0b0b"
MUTED = "#898781"
BASELINE = "#c3c2b7"
SURFACE = "#fcfcfb"
COL_REPORT = "#eb6834"  # 报告值（橙）
COL_DELEAKED = "#2a78d6"  # 去泄露值（蓝）
COL_REACH = "#3d8b52"  # 可达值（绿）

OUT_MAIN_FIG = "Main_three_tiers.png"
OUT_APPX_FIG = "Appx_three_tiers_by_work.png"
TWO_ARM_CSV = C3.OUT_ROOT / "two_arm.csv"
TEMPLATES = REPO_ROOT / "templates" / "manual_schemes"

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
    "reach_c", "reach_std", "reach_b_c", "reach_b_std",
    "delta_deleak_minus_reach", "delta_C_minus_B",
    "n_fields_greedy", "n_missed",
    "report_cox_c",
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


def load_two_arm(path: Path) -> dict[tuple[str, str], dict]:
    """two_arm.csv -> {(dataset, work): row dict}；文件缺失 -> 空表（全部 pending）。"""
    path = Path(path)
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    out: dict[tuple[str, str], dict] = {}
    for _, row in df.iterrows():
        out[(str(row["dataset"]), str(row["work"]))] = row.to_dict()
    return out


def search_best_c(dataset: str) -> dict | None:
    """搜索 result.json 的 best_cv_c_mean(bank-only 口径下即臂 C 的 c-index)。"""
    path = C3.search_result_json(dataset)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    mean = data.get("best_cv_c_mean")
    if mean is None:
        return None
    per_fold = data.get("best_cv_folds") or []
    std = None
    if len(per_fold) >= 2:
        import math
        m = sum(per_fold) / len(per_fold)
        std = math.sqrt(sum((x - m) ** 2 for x in per_fold) / (len(per_fold) - 1))
    return {"c": float(mean), "std": std}


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
               two_arm: dict[tuple[str, str], dict] | None = None,
               templates: Path = TEMPLATES) -> list[dict]:
    """(dataset, work) × 三档;缺臂不中断(C -> pending,报告值缺 -> n/a)。

    口径(bank-only,2026-10-07;臂语义 arm_registry.md):去泄露值 = deleak 臂
    (Test_3_{work}_{ds},work × lm0 × bank 切片);可达值 = two_arm.csv 的 C,缺失时回退
    搜索 result.json 的 best_cv_c_mean(与 reach 臂同嵌入同模型同折同 seed)。
    """
    if two_arm is None:
        two_arm = load_two_arm(TWO_ARM_CSV)
    rows: list[dict] = []
    for dataset, work in pairs:
        if dataset not in n_event:
            raise SystemExit(f"[error] n_event 表缺 {dataset}(manifest/event_summary)")
        n_ev = n_event[dataset]
        report = read_metric(Path(arm_a_root) / f"{dataset}[gdc]" / "cindex.csv", work, MLP)
        report_cox = read_metric(Path(arm_a_root) / f"{dataset}[gdc]" / "cindex.csv", work, COX)
        # 去泄露值:deleak 臂(work × lm0 × bank 切片;apipe scheme 分支已删 T31)
        b_key = f"{C3.b_scheme_name(work, dataset)}__landmark_0"
        deleak = read_metric(Path(arm_b_root) / f"{dataset}[gdc]" / "cindex.csv", b_key, MLP)
        arm3 = two_arm.get((dataset, work))

        d1 = None
        if report is not None and deleak is not None:
            d1 = _r6(report["mean"] - deleak["mean"])

        reach = _num(arm3.get("C_c")) if arm3 else None
        reach_std = _num(arm3.get("C_std")) if arm3 else None
        reach_b = _num(arm3.get("B_c")) if arm3 else None
        reach_b_std = _num(arm3.get("B_std")) if arm3 else None
        d_c_b = _num(arm3.get("delta_C_minus_B")) if arm3 else None
        if reach is None:
            # 回退:搜索 result.json 的 best_cv_c_mean(与臂 C 同口径,零训练)
            best = search_best_c(dataset)
            if best is not None:
                reach = best["c"]
                reach_std = best["std"]
        d2 = _r6(deleak["mean"] - reach) if (deleak is not None and reach is not None) else None

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
            "reach_b_c": PENDING if reach_b is None else reach_b,
            "reach_b_std": PENDING if reach_b is None else reach_b_std,
            "delta_deleak_minus_reach": PENDING if d2 is None else d2,
            "delta_C_minus_B": PENDING if d_c_b is None else d_c_b,
            "n_fields_greedy": PENDING if arm3 is None else int(arm3["n_fields_greedy"]),
            "n_missed": PENDING if arm3 is None else int(arm3["n_missed"]),
            "report_cox_c": _cell(report_cox, "mean"),
            
            "status": "ok" if reach is not None else "pending_C",
        })
    rows.sort(key=lambda r: (TIER_ORDER[r["tier"]], r["dataset"], r["work"]))
    return rows


# --------------------------------------------------------------------------- 图
def _tier_means(rows: list[dict], group_key: str) -> dict[str, tuple[list[float], int]]:
    """按 group_key 聚合三档均值；只取 status==ok 且三档齐全的行（报告 n/a 剔除）。"""
    groups: dict[str, list[tuple[float, float, float]]] = {}
    for r in rows:
        if r["status"] != "ok":
            continue
        rep, de, rc = _num(r["report_c"]), _num(r["deleak_c"]), _num(r["reach_c"])
        if rep is None or de is None or rc is None:
            continue
        groups.setdefault(r[group_key], []).append((rep, de, rc))
    return {
        key: ([sum(v[i] for v in vals) / len(vals) for i in range(3)], len(vals))
        for key, vals in groups.items()
    }


def _three_tier_bar_figure(names: list[str], agg: dict, *, n_label: str, title: str,
                           ylabel: str, out_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(9.6, 5.2))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    x = np.arange(len(names))
    w = 0.26
    series = (
        (COL_REPORT, "report (paper fields)"),
        (COL_DELEAKED, "deleaked (landmark_0)"),
        (COL_REACH, "reachable (greedy)"),
    )
    for i, (color, label) in enumerate(series):
        means = [agg[n][0][i] for n in names]
        ax.bar(x + (i - 1) * w, means, w, color=color, zorder=2, label=label)
    for xi, name in enumerate(names):
        means, n = agg[name]
        ax.annotate(
            f"{n_label}={n}", xy=(xi, max(means)), xytext=(0, 4),
            textcoords="offset points", ha="center", fontsize=8.0, color=MUTED,
        )
    all_means = [agg[n][0][i] for n in names for i in range(3)]
    ax.axhline(0.5, color=BASELINE, linewidth=1.2, zorder=1)
    ax.set_ylim(min(0.5, min(all_means)) * 0.97, max(all_means) * 1.09)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=28, ha="right", fontsize=8.5, color=INK)
    ax.set_ylabel(ylabel, color=INK, fontsize=9)
    ax.set_title(title, color=INK, fontsize=10.5, loc="left")
    ax.legend(frameon=False, fontsize=9, loc="upper right", labelcolor=INK)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out_path


def figure_three_tiers_by_dataset(rows: list[dict], out_path: Path) -> Path | None:
    """头条柱状图：逐数据集三档均值（报告/去泄露/可达），仅含可达值就绪的数据集。"""
    agg = _tier_means(rows, "dataset")
    if not agg:
        return None
    names = sorted(agg)
    return _three_tier_bar_figure(
        names, agg, n_label="n works",
        title="Test_4 three tiers per dataset (reachable ready: partial)\n"
              "report (orange) vs deleaked (blue) vs reachable (green)",
        ylabel="mean c-index across works", out_path=out_path,
    )


def figure_three_tiers_by_work(rows: list[dict], out_path: Path) -> Path | None:
    """附录柱状图：逐工作三档均值（跨可达值就绪的数据集聚合）。"""
    agg = _tier_means(rows, "work")
    if not agg:
        return None
    names = sorted(agg)
    return _three_tier_bar_figure(
        names, agg, n_label="n datasets",
        title="Test_4 three tiers per work (reachable ready: partial)\n"
              "report (orange) vs deleaked (blue) vs reachable (green)",
        ylabel="mean c-index across datasets", out_path=out_path,
    )


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
    """run 目录折文件重算（与 manual_pipeline.cindex/read_cindex 同算术：末行 val_cindex）。"""
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
        # 3) 可达值：two_arm.csv 重读
        arm3 = load_two_arm(TWO_ARM_CSV).get((dataset, work))
        checks["可达值=two_arm.csv"] = (
            arm3 is not None and abs(float(r["reach_c"]) - float(arm3["C_c"])) == 0.0
            and abs(float(r["reach_b_c"]) - float(arm3["B_c"])) == 0.0)
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
            checks["cox 报告列 n/a"] = (str(r["report_cox_c"]) == NA)

        else:
            checks["cox 报告列=arm_A表"] = (
                abs(float(r["report_cox_c"]) - rc["mean"]) == 0.0)
        # 6) n_fields_work 与 two_arm 对齐（表格口径自洽）
        checks["n_fields_work=two_arm"] = (
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
    for fn in (figure_three_tiers_by_dataset, figure_three_tiers_by_work):
        path = fn(rows, out_dir / (OUT_MAIN_FIG if fn is figure_three_tiers_by_dataset else OUT_APPX_FIG))
        if path is not None:
            written.append(path)
            print(f"[png] {path.name}")
        else:
            print(f"[png] {OUT_MAIN_FIG if fn is figure_three_tiers_by_dataset else OUT_APPX_FIG}: skipped (no reachable rows)")

    if args.audit:
        audit(rows)
    check_out_dir_inventory(out_dir, written)
    print("[done]")


if __name__ == "__main__":
    main()
