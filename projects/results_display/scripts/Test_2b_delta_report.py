#!/usr/bin/env python3
"""Test_2b Δc 对照报表生成器（纯汇总，无训练）。

口径（z_notes/Test_series_spec.md §6.4 / §12 U1 协议 A）：
  - 臂 A（报告值对照）= scheme__landmark_none（S4 新链路，同字段集、同编码、同模型、同划分）
  - 臂 B（去泄露值）  = scheme__landmark_0（经典 landmark 三要件全开）
  - Δc = c(A) − c(B)；Δc > 0 表示去掉未来信息后 c-index 下降 = 文献报告值被高估的证据
  - 数据集分层按 n_event 四档（协议 A）：≥100 main / 70–100 main_ci（必须带 CI，不排名）
    / 30–70 supp / <30 low（仅定性讨论）

输入：
  - results/Test_2b/arm_B/{dataset}[gdc]/cindex.csv + run_config.json（S4 两臂产物；S4 summarize
    把报告臂 {scheme}__landmark_none 行与去泄露臂 {scheme}__landmark_0 行写进同一张表，
    故两臂都从这张表读——同字段集、同编码、同模型、同划分，唯一差异 = mask 状态）
  - results/Test_2b/arm_B/runs/{study}__{scheme}__landmark_{T}/{modality}/val_result_fold*.csv
    （run 折文件 = c 值的最终口径；S4 汇总表首次写入后不再更新，100/552 行为中途快照，
    本脚本按同算术（纯 python sum，python 3.13）从折文件重算，表冻结值保留在 *_table 列）
  - results/Test_2b/arm_A/{dataset}[gdc]/cindex.csv（论文报告值原表，4 方案 × 5 modality；
    仅作 Test_4 三档参考，不参与本文 Δc 配对——配对用同链路的 landmark_none 行）
  - rawdata_stats/_shared/event_summary.csv（n_event 分层）
  - results/Test_2b/arm_B/labels/{study}__landmark_0.json（审计用：排除病例清单）

输出（默认 results_display/Test_2b_delta/，全部为 gitignore 产物，不入库）：
  文件角色前缀（z_notes/experiment_list/naming_convention.md）：Main_ = 头条（回答命题）、
  Appx_ = 附录（明细/主表补充）、Raw_ = 原始矩阵、Meta_ = 元数据；本目录平铺，无子目录。
  - Main_overview_{analyzer}.png（跨方案总览，共 2 张）
  - Main_delta_summary.csv（按 scheme × analyzer × tier_group 汇总）
  - Appx_forest_{scheme}_{analyzer}.png（每方案 × 分析器森林图，共 20 张）
  - Appx_delta_main.csv / Appx_delta_supp.csv / Appx_delta_low.csv

可复跑：同输入重跑 diff=0（固定随机种子、固定行列序、无时间戳）。
产物清单核对：main() 末尾遍历 out_dir，逐个核对上面这组文件名（清单外文件按旧名遗留告警）。
用法：
  python3 results_display/scripts/Test_2b_delta_report.py            # 生成全部产物
  python3 results_display/scripts/Test_2b_delta_report.py --audit    # 生成 + 3 组抽查
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parents[2]

SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.paths import remap_legacy_result_path, test_results_dir

RESULTS_LM = test_results_dir("Test_2b/arm_B")
EVENT_SUMMARY = REPO_ROOT / "rawdata_stats" / "_shared" / "event_summary.csv"

ANALYZERS = ("clinic_cox", "mlp_clinic_flatten")
ARM_A = "landmark_none"  # 报告值对照臂（取值 mask 关）
ARM_B = "landmark_0"     # 去泄露臂（t0 mask + 风险集 + 时间平移）
HGCN_PREFIX = "HGCN_"
EXCLUDED_STUDIES = {"MMRF", "CPTAC"}  # 非 TCGA，协议 A 不纳入

# ---- 视觉常量（dataviz 参考调色板，light 表面，已通过 validate_palette.js）----
INK = "#0b0b0b"
MUTED = "#898781"
BASELINE = "#c3c2b7"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"
COL_POS = "#e34948"  # Δc > 0（高估证据）
COL_NEG = "#2a78d6"  # Δc < 0
COL_HGCN = "#eb6834"  # overview 图中 HGCN 单点标记
COL_REPORT = "#eb6834"  # 论文字段报告值（橙）
COL_DELEAKED = "#2a78d6"  # landmark 处理后去泄露值（蓝）

BOOTSTRAP_SEED = 0
BOOTSTRAP_N = 10_000
AUDIT_SEED = 20260930
AUDIT_N = 3

# ---- 产物文件名（Main_/Appx_/Raw_/Meta_ 角色前缀；本约定平铺，无子目录）----
OUT_MAIN_DELTA_SUMMARY = "Main_delta_summary.csv"
OUT_APPX_DELTA_MAIN = "Appx_delta_main.csv"
OUT_APPX_DELTA_SUPP = "Appx_delta_supp.csv"
OUT_APPX_DELTA_LOW = "Appx_delta_low.csv"


def out_forest_name(scheme: str, analyzer: str) -> str:
    return f"Appx_forest_{scheme}_{analyzer}.png"


def out_overview_name(analyzer: str) -> str:
    return f"Main_overview_{analyzer}.png"


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


TIER_ORDER = {"main": 0, "main_ci": 1, "supp": 2, "low": 3}


def load_event_summary() -> dict[str, dict]:
    df = pd.read_csv(EVENT_SUMMARY)
    out = {}
    for _, r in df.iterrows():
        name = str(r["dataset"])
        if name in EXCLUDED_STUDIES:
            continue
        out[name] = {
            "n_patients": int(r["n_patients"]),
            "n_event": int(r["n_event"]),
            "event_rate": float(r["event_rate"]),
        }
    return out


def dataset_key(dataset: str) -> str:
    """'TCGA-BRCA[gdc]' -> 'TCGA-BRCA'（与 event_summary 命名对齐，TCGA_LIHC 下划线保留）。"""
    return dataset[:-5] if dataset.endswith("[gdc]") else dataset


# --------------------------------------------------------------------------- 数据装配
def read_table(dataset_dir: Path) -> tuple[pd.DataFrame, dict]:
    csv_path = dataset_dir / "cindex.csv"
    cfg_path = dataset_dir / "run_config.json"
    df = pd.read_csv(csv_path)
    cfg = json.loads(cfg_path.read_text())
    rows = cfg.get("rows", [])
    return df, {frozenset((r["scheme"], r["modality"])): r for r in rows}


def fold_values(results_dir: str) -> tuple[float, float, list[float], bool]:
    """从 run 目录的 val_result_fold*.csv 重算 5 折均值/标准差（run 最终状态）。

    返回 (mean, std, folds, table_stale)。table_stale=True 表示 S4 汇总表冻结值
    与折文件不符（summarize 首次写入后不再更新，属 S4 汇总时序伪影）。
    mean 用纯 python sum（与 A_pipeline read_cindex 同算术，同 python 3.13 下逐位一致）。
    """
    vals: list[float] = []
    for f in sorted(Path(results_dir).glob("val_result_fold*.csv")):
        df = pd.read_csv(f)
        if "val_cindex" not in df.columns or len(df) == 0:
            raise SystemExit(f"[error] 折文件缺失/为空: {f}")
        vals.append(float(df["val_cindex"].iloc[-1]))
    if len(vals) != 5:
        raise SystemExit(f"[error] 折数 != 5: {results_dir}")
    mean = sum(vals) / len(vals)
    std = (sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5
    return mean, std, vals, False


def build_rows() -> list[dict]:
    """(dataset, scheme, analyzer) × 两臂配对；Δc = c(A) − c(B)，含折内配对 CI。

    c 值以 run 目录折文件为准（与 S4 汇总表同算术重算）；S4 汇总表冻结值
    保留在 *_table 列供对照（A_pipeline 的 _merge_cindex_rows 首次写入后不再
    更新，100/552 行为跑动中途快照，折文件才是 run 最终状态）。
    """
    events = load_event_summary()
    out = []
    n_skipped_test3 = 0
    for d in sorted(os.listdir(RESULTS_LM)):
        dataset_dir = RESULTS_LM / d
        if not d.endswith("[gdc]") or not dataset_dir.is_dir():
            continue
        dataset = d
        key = dataset_key(dataset)
        if key not in events:
            raise SystemExit(f"[error] event_summary 缺 {key}")
        meta = events[key]
        tier = tier_for(meta["n_event"])
        df, cfg_rows = read_table(dataset_dir)

        schemes = sorted({s.split("__")[0] for s in df["scheme"]})
        for scheme in schemes:
            if scheme.startswith("Test_3_"):
                # Test_3 臂 B'/C 行只有单臂(S6 summarize 合并进 arm_B 表),无臂 A 配对;
                # 其 Δc 由 Test_3_compare.py 负责,本脚本只管 Test_2b 双臂。
                n_skipped_test3 += 1
                continue
            for analyzer in ANALYZERS:
                a = df[
                    (df["scheme"] == f"{scheme}__{ARM_A}") & (df["modality"] == analyzer)
                ]
                b = df[
                    (df["scheme"] == f"{scheme}__{ARM_B}") & (df["modality"] == analyzer)
                ]
                if len(a) != 1 or len(b) != 1:
                    raise SystemExit(
                        f"[error] 两臂行缺失: {dataset} {scheme} {analyzer} "
                        f"(A={len(a)}, B={len(b)})"
                    )
                a_row, b_row = a.iloc[0], b.iloc[0]
                cfg_a = cfg_rows.get(frozenset((a_row["scheme"], analyzer)))
                cfg_b = cfg_rows.get(frozenset((b_row["scheme"], analyzer)))
                if cfg_a is None or cfg_b is None:
                    raise SystemExit(
                        f"[error] run_config 缺行: {dataset} {scheme} {analyzer}"
                    )
                ca_f, ca_std, fa, _ = fold_values(remap_legacy_result_path(cfg_a["results_dir"]))
                cb_f, cb_std, fb, _ = fold_values(remap_legacy_result_path(cfg_b["results_dir"]))
                ca_t = float(cfg_a["val_c_index_mean"])
                cb_t = float(cfg_b["val_c_index_mean"])
                stale = abs(ca_f - ca_t) > 1e-12 or abs(cb_f - cb_t) > 1e-12
                delta = ca_f - cb_f
                d_fold = np.asarray(fa) - np.asarray(fb)
                n_folds = len(d_fold)
                se = d_fold.std(ddof=1) / np.sqrt(n_folds)
                tcrit = stats.t.ppf(0.975, df=n_folds - 1)
                ci_lo, ci_hi = delta - tcrit * se, delta + tcrit * se
                out.append(
                    {
                        "dataset": dataset,
                        "scheme": scheme,
                        "analyzer": analyzer,
                        "tier": tier,
                        "n_patients": meta["n_patients"],
                        "n_event": meta["n_event"],
                        "event_rate": meta["event_rate"],
                        "c_report": ca_f,
                        "c_report_std": ca_std,
                        "c_deleaked": cb_f,
                        "c_deleaked_std": cb_std,
                        "delta": delta,
                        "delta_fold_std": float(d_fold.std(ddof=1)),
                        "delta_ci_lo": float(ci_lo),
                        "delta_ci_hi": float(ci_hi),
                        "c_report_table": ca_t,
                        "c_deleaked_table": cb_t,
                        "delta_table": ca_t - cb_t,
                        "table_stale": stale,
                        "n_folds": n_folds,
                    }
                )
    if n_skipped_test3:
        print(f"[Test_2b_delta] 跳过 Test_3 单臂行 {n_skipped_test3} 条（无臂 A 配对，Δc 由 Test_3_compare 负责）")
    return out


COLUMNS = [
    "dataset",
    "scheme",
    "analyzer",
    "tier",
    "n_patients",
    "n_event",
    "event_rate",
    "c_report",
    "c_report_std",
    "c_deleaked",
    "c_deleaked_std",
    "delta",
    "delta_fold_std",
    "delta_ci_lo",
    "delta_ci_hi",
    "c_report_table",
    "c_deleaked_table",
    "delta_table",
    "table_stale",
    "n_folds",
]


def write_tier_tables(rows: list[dict], out_dir: Path) -> dict[str, Path]:
    df = pd.DataFrame(rows)[COLUMNS]
    files = {}
    for tier, fname in (
        ("main", OUT_APPX_DELTA_MAIN),
        ("supp", OUT_APPX_DELTA_SUPP),
        ("low", OUT_APPX_DELTA_LOW),
    ):
        sub = df[df["tier"] == tier]
        path = out_dir / fname
        sub.to_csv(path, index=False)
        files[tier] = path
    # main_ci（70–100）并入主表文件，用 tier 列标注 CI 要求（不排名）
    main = df[df["tier"].isin(("main", "main_ci"))]
    path = out_dir / OUT_APPX_DELTA_MAIN
    main.to_csv(path, index=False)
    files["main_ci"] = path
    return files


# --------------------------------------------------------------------------- 汇总统计
def bootstrap_mean_ci(vals: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    if len(vals) < 2:
        return float("nan"), float("nan")
    means = np.empty(BOOTSTRAP_N)
    for i in range(BOOTSTRAP_N):
        means[i] = rng.choice(vals, size=len(vals), replace=True).mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarize(rows: list[dict], out_dir: Path) -> Path:
    df = pd.DataFrame(rows)
    recs = []
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    for (scheme, analyzer), g in df.groupby(["scheme", "analyzer"], sort=True):
        for tier in ("main", "main_ci", "supp", "low"):
            sub = g[g["tier"] == tier]
            if len(sub) == 0:
                continue
            delta = sub["delta"].to_numpy(dtype=float)
            ca = sub["c_report"].to_numpy(dtype=float)
            cb = sub["c_deleaked"].to_numpy(dtype=float)
            w_stat = w_p = float("nan")
            if len(delta) >= 2:
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        res = stats.wilcoxon(ca, cb, alternative="two-sided")
                    w_stat, w_p = float(res.statistic), float(res.pvalue)
                except (ValueError, ZeroDivisionError):
                    pass
            lo, hi = bootstrap_mean_ci(delta, rng)
            recs.append(
                {
                    "scheme": scheme,
                    "analyzer": analyzer,
                    "tier_group": tier,
                    "n_datasets": len(sub),
                    "datasets": "|".join(sorted(sub["dataset"])),
                    "mean_delta": float(delta.mean()),
                    "median_delta": float(np.median(delta)),
                    "sd_delta": float(delta.std(ddof=1)) if len(delta) > 1 else float("nan"),
                    "direction_consistency": float((delta > 0).mean()),
                    "wilcoxon_stat": w_stat,
                    "wilcoxon_p": w_p,
                    "bootstrap_ci_lo": lo,
                    "bootstrap_ci_hi": hi,
                }
            )
    out = pd.DataFrame(recs).sort_values(
        ["analyzer", "scheme", "tier_group"], kind="mergesort"
    )
    path = out_dir / OUT_MAIN_DELTA_SUMMARY
    out.to_csv(path, index=False)
    return path


# --------------------------------------------------------------------------- 图
def _setup_axes(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
    ax.tick_params(colors=MUTED, labelsize=8.5)
    ax.xaxis.label.set_color(MUTED)


def forest_figure(rows: list[dict], scheme: str, analyzer: str, out_dir: Path) -> Path:
    sub = [r for r in rows if r["scheme"] == scheme and r["analyzer"] == analyzer]
    sub.sort(
        key=lambda r: (
            TIER_ORDER[r["tier"]],
            -r["n_event"],
            r["dataset"],
        )
    )
    n = len(sub)
    fig, ax = plt.subplots(figsize=(8.5, max(2.6, 0.30 * n + 1.6)))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    y = np.arange(n)
    deltas = np.array([r["delta"] for r in sub])
    err = np.array(
        [
            [r["delta"] - r["delta_ci_lo"], r["delta_ci_hi"] - r["delta"]]
            for r in sub
        ]
    ).T
    colors = [COL_POS if d > 0 else COL_NEG for d in deltas]

    ax.axvline(0.0, color=BASELINE, linewidth=1.2, zorder=1)
    for yi, r, col in zip(y, sub, colors):
        ax.errorbar(
            [r["delta"]],
            [yi],
            xerr=[[r["delta"] - r["delta_ci_lo"]], [r["delta_ci_hi"] - r["delta"]]],
            fmt="none",
            ecolor=col,
            elinewidth=1.5,
            capsize=2.5,
            zorder=2,
        )
    ax.scatter(deltas, y, s=40, c=colors, zorder=3, linewidths=0)

    # 行标签 + 数值（数值标注是森林图的信息本体）
    ax.set_yticks(y)
    ax.set_yticklabels(
        [f'{r["dataset"][:-5]}  (n_event={r["n_event"]})' for r in sub],
        fontsize=8.0,
        color=INK,
    )
    for yi, r in zip(y, sub):
        ax.annotate(
            f'{r["delta"]:+.3f}',
            xy=(r["delta_ci_hi"], yi),
            xytext=(3, 0),
            textcoords="offset points",
            va="center",
            fontsize=7.5,
            color=MUTED,
        )

    # 协议 A 分层分隔线 + 分层标注（文本承载，不用颜色）
    bounds = []
    prev_tier = None
    for yi, r in zip(y, sub):
        if r["tier"] != prev_tier:
            bounds.append((r["tier"], yi))
            prev_tier = r["tier"]
    for i, (tier, yi) in enumerate(bounds):
        if i > 0:
            ax.axhline(yi - 0.5, color=GRIDLINE, linewidth=1.0, zorder=1)
        ax.text(
            0.003,
            min((yi + 0.30) / n, 0.985),
            tier_label(tier),
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=7.0,
            color=MUTED,
        )
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_xlabel("Δc = c(report, none) − c(deleaked, landmark_0)")
    ax.set_title(
        f"{scheme} × {analyzer} — Δc per dataset (n={n})", fontsize=10, color=INK
    )
    _setup_axes(ax)
    handles = [
        plt.Line2D(
            [], [], marker="o", linestyle="", color=COL_POS,
            label="Δc > 0 (overestimation evidence)",
        ),
        plt.Line2D([], [], marker="o", linestyle="", color=COL_NEG, label="Δc < 0"),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=8, loc="lower right", labelcolor=INK)
    path = out_dir / out_forest_name(scheme, analyzer)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


def overview_figure(rows: list[dict], analyzer: str, out_dir: Path) -> Path:
    """头条总览：不用 Δc，直接画两档值——橙 = 论文字段报告值，蓝 = landmark 处理后去泄露值。"""
    df = pd.DataFrame(rows)
    g = df[df["analyzer"] == analyzer]
    schemes = sorted(g["scheme"].unique())
    fig, ax = plt.subplots(figsize=(10.5, 5.0))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    x = np.arange(len(schemes))
    width = 0.30
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    shown_labels: set[str] = set()
    for xi, scheme in zip(x, schemes):
        sub = g[g["scheme"] == scheme]
        main15 = sub[sub["tier"] == "main"]
        if len(main15) == 0:  # HGCN 方案只绑定单一癌种，且其癌种不在 main 档时用单点
            main15 = sub
        crep = main15["c_report"].to_numpy(dtype=float)
        cdel = main15["c_deleaked"].to_numpy(dtype=float)
        m_rep, m_del = float(crep.mean()), float(cdel.mean())
        lo_r, hi_r = bootstrap_mean_ci(crep, rng)
        lo_d, hi_d = bootstrap_mean_ci(cdel, rng)
        if scheme.startswith(HGCN_PREFIX):
            # n=1 单点：两枚钻石分别标两档值，避免与多数据集均值误比
            label = None
            if "hgcn" not in shown_labels:
                label = "HGCN (n=1, bound cancer)"
                shown_labels.add("hgcn")
            ax.scatter(
                [xi - width / 2], [m_rep], marker="D", s=56, color=COL_REPORT, zorder=3, label=label
            )
            ax.scatter([xi + width / 2], [m_del], marker="D", s=56, color=COL_DELEAKED, zorder=3)
            ax.annotate(
                f"n={len(main15)}\n{m_rep:.3f} / {m_del:.3f}",
                xy=(xi, max(m_rep, m_del)),
                xytext=(0, 6),
                textcoords="offset points",
                ha="center",
                fontsize=7.0,
                color=MUTED,
            )
        else:
            label_r = None
            if "rep" not in shown_labels:
                label_r = "Report (paper fields)"
                shown_labels.add("rep")
            label_d = None
            if "del" not in shown_labels:
                label_d = "Deleaked (landmark_0)"
                shown_labels.add("del")
            ax.bar(
                xi - width / 2, m_rep, width, color=COL_REPORT, zorder=2,
                yerr=[[m_rep - lo_r], [hi_r - m_rep]], capsize=3,
                error_kw={"ecolor": MUTED, "elinewidth": 1.5},
                label=label_r,
            )
            ax.bar(
                xi + width / 2, m_del, width, color=COL_DELEAKED, zorder=2,
                yerr=[[m_del - lo_d], [hi_d - m_del]], capsize=3,
                error_kw={"ecolor": MUTED, "elinewidth": 1.5},
                label=label_d,
            )

    ax.axhline(0.5, color=BASELINE, linewidth=1.2, zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels(schemes, rotation=28, ha="right", fontsize=8, color=INK)
    ax.set_ylabel("mean c-index across datasets (main, n_event≥100)")
    ax.set_title(
        f"{analyzer}: per-scheme c-index, report (orange) vs deleaked (blue), bootstrap CI",
        fontsize=10.5,
        color=INK,
    )
    _setup_axes(ax)
    ax.legend(frameon=False, fontsize=8, loc="upper right", labelcolor=INK)
    path = out_dir / out_overview_name(analyzer)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- 审计
def _study_of(dataset: str) -> str:
    """'TCGA-BRCA[gdc]' -> 'tcga_brca'（run/labels 目录的 study 命名）。"""
    return dataset_key(dataset).lower().replace("-", "_")


def audit(rows: list[dict]) -> None:
    """固定种子随机抽 3 个 (dataset, scheme, analyzer)，独立重算 + 两臂对应关系核对。"""
    rng = random.Random(AUDIT_SEED)
    sample = rng.sample(rows, AUDIT_N)
    print(f"[audit] 固定种子 {AUDIT_SEED} 抽取 {AUDIT_N} 组 (dataset, scheme, analyzer):")
    all_pass = True
    for r in sample:
        dataset, scheme, analyzer = r["dataset"], r["scheme"], r["analyzer"]
        print(f"  - {dataset} × {scheme} × {analyzer}")
        # 1) 独立重算 Δc：从 run 目录折文件裸读（不经报表装配逻辑）
        df = pd.read_csv(RESULTS_LM / dataset / "cindex.csv")
        _, cfg = read_table(RESULTS_LM / dataset)
        a = df[(df["scheme"] == f"{scheme}__{ARM_A}") & (df["modality"] == analyzer)]
        b = df[(df["scheme"] == f"{scheme}__{ARM_B}") & (df["modality"] == analyzer)]
        ca_f, _, _, _ = fold_values(remap_legacy_result_path(cfg[frozenset((a.iloc[0]["scheme"], analyzer))]["results_dir"]))
        cb_f, _, _, _ = fold_values(remap_legacy_result_path(cfg[frozenset((b.iloc[0]["scheme"], analyzer))]["results_dir"]))
        manual = ca_f - cb_f
        ok1 = abs(manual - r["delta"]) < 1e-12
        # 2) stale 标记自洽：|折文件均值 − S4 表冻结值| > 1e-12 的行必须被标记
        ca_t = float(a.iloc[0]["val_c_index_mean"])
        cb_t = float(b.iloc[0]["val_c_index_mean"])
        stale_here = abs(ca_f - ca_t) > 1e-12 or abs(cb_f - cb_t) > 1e-12
        ok2 = stale_here == bool(r["table_stale"])
        # 3) SEED 一致：两臂 run 的 config.snapshot SEED 行相同
        seeds = set()
        for row in (a.iloc[0], b.iloc[0]):
            snap = Path(remap_legacy_result_path(row["results_dir"])) / "config.snapshot"
            for line in snap.read_text().splitlines():
                if line.strip().startswith("SEED="):
                    seeds.add(line.strip())
        ok3 = len(seeds) == 1
        # 4) 折对应关系：臂 B 有效患者集 = 臂 A − landmark 排除患者（5 折全核对）
        study = _study_of(dataset)
        sidecar = RESULTS_LM / "labels" / f"{study}__landmark_0.json"
        excl = set(json.loads(sidecar.read_text()).get("excluded_cases", []))
        ok4 = True
        for fold in range(5):
            fa = pd.read_csv(
                Path(remap_legacy_result_path(a.iloc[0]["results_dir"])) / f"splits_{fold}.csv"
            )
            fb = pd.read_csv(
                Path(remap_legacy_result_path(b.iloc[0]["results_dir"])) / f"splits_{fold}.csv"
            )
            ids_a = set(fa["train"].dropna()) | set(fa["val"].dropna()) | set(fa["test"].dropna())
            ids_b = set(fb["train"].dropna()) | set(fb["val"].dropna()) | set(fb["test"].dropna())
            removed = {s[:-4] if s.endswith(".svs") else s for s in ids_a - ids_b}
            ok4 &= removed == (excl & {s[:-4] if s.endswith(".svs") else s for s in ids_a})
        checks = {
            "Δc 独立重算一致(折文件)": ok1,
            "stale 标记自洽": ok2,
            "SEED 两臂一致": ok3,
            "臂B=臂A−排除患者(5折)": ok4,
        }
        for name, passed in checks.items():
            print(f"      [{'PASS' if passed else 'FAIL'}] {name}")
            all_pass &= passed
    print(f"[audit] 总体: {'ALL PASS' if all_pass else 'HAS FAILURES'}")
    if not all_pass:
        sys.exit(1)


# --------------------------------------------------------------------------- 主流程
def check_out_dir_inventory(out_dir: Path, written: list[Path]) -> None:
    """遍历 out_dir 核对本次写出的产物清单（新前缀名），并提示清单外的遗留文件。

    "同输入重跑 diff=0" 的核对即以这份文件名集合为准（本约定平铺、无子目录）；
    清单外文件通常是旧名（Test_2b_delta_*）遗留，删除即可（本脚本只写新名）。
    """
    expected = {p.name for p in written}
    missing = sorted(name for name in expected if not (out_dir / name).exists())
    if missing:
        print(f"[warn] 产物缺失: {', '.join(missing)}")
    for name in sorted(p.name for p in out_dir.iterdir() if p.is_file()):
        if name not in expected and name != "README.md":  # README = 目录说明，非脚本产物
            print(f"[warn] 清单外文件（旧名遗留？）: {name}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Test_2b Δc 对照报表（纯汇总）")
    ap.add_argument(
        "--out", default=str(REPO_ROOT / "results_display" / "Test_2b_delta"),
        help="产物目录（默认 results_display/Test_2b_delta）",
    )
    ap.add_argument("--audit", action="store_true", help="生成后执行 3 组固定种子抽查")
    ap.add_argument("--no-figs", action="store_true", help="跳过出图")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = build_rows()
    print(f"[build] 两臂配对行数: {len(rows)}")
    tier_counts = pd.Series([r["tier"] for r in rows]).value_counts().to_dict()
    print(f"[build] tier 分布: {tier_counts}")

    written: list[Path] = []
    files = write_tier_tables(rows, out_dir)
    written.extend(files.values())
    for tier, path in files.items():
        print(f"[csv] {path.name} ({tier})")
    summary_path = summarize(rows, out_dir)
    written.append(summary_path)
    print(f"[csv] {summary_path.name}")

    if not args.no_figs:
        pairs = sorted({(r["scheme"], r["analyzer"]) for r in rows})
        for scheme, analyzer in pairs:
            p = forest_figure(rows, scheme, analyzer, out_dir)
            written.append(p)
            print(f"[png] {p.name}")
        for analyzer in ANALYZERS:
            p = overview_figure(rows, analyzer, out_dir)
            written.append(p)
            print(f"[png] {p.name}")

    if args.audit:
        audit(rows)
    check_out_dir_inventory(out_dir, written)
    print("[done]")


if __name__ == "__main__":
    main()
