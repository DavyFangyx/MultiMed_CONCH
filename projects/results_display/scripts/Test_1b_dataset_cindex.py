#!/usr/bin/env python3
"""Test_1b 各数据集 Cindex 情况（字段轴链动机）。

规格：z_notes/Test_series_spec.md §5ter；速查：z_notes/experiment_list/experiment_list.md。

命题（字段轴链动机）：字段的预测能力随数据集而异，各数据集 top-k 字段几乎不重合
→ 每个数据集理论上存在属于自己的最优字段组合 → 针对数据集做字段选择是应该的
（Test_3 贪婪选字段的存在理由）。本步纯分析，**不新增训练**。

三个量化指标：
  a. 各数据集单字段 c-index 分布（原 E1 Fig2 升级版），按协议 A 四档分层标注；
  b. 同一字段跨数据集 c-index 分布（公共字段 = 出现于 >= --min_datasets 个数据集）；
  c. top-k 字段重叠度（k ∈ --top_k）：两两交集矩阵 + 聚合重叠率。

输入（只读）：
  - results/Test_1a/arm_t0/prompt/landmark_0/{dataset}/mlp_clinic_flatten/field_cindex.csv
    （S5 univariate 补跑，33/33，5 折 × seed 0，与 Test_1a t0 臂同源）
  - datasets.json（数据集清单：TCGA 前缀，**禁止硬编码**）
  - results/Test_0_dataset_availability/manifest.csv（tier 列 + provisional 标注）
  - rawdata_stats/_shared/event_summary.csv（n_event / n_patients / event_rate）

分档口径（协议 A，用户 2026-09-30，spec §12 U1）：n_event >= 100 main（干净集）/
  70–100 main_ci（带 CI、不排名）/ 30–70 supp（补充材料）/ < 30 low（仅定性）。
  manifest 现状 33/33 标 provisional(D1)，故 tier 一律由 event_summary 的 n_event 按协议 A
  重算（写进 tier_source 列），并在图/表标题注明；manifest tier 仅作为对照列保留。

输出（默认 results_display/Test_1b_dataset_cindex/；gitignore 产物，不入库）：
  表：Test_1b_dataset_summary.csv     每数据集分布统计 + tier + top-1 字段
      Test_1b_field_summary.csv       每字段跨数据集统计（n_datasets/median/range/...）
      Test_1b_cindex_matrix.csv       dataset × field 对齐矩阵（原始 c_index_mean）
      Test_1b_topk_members.csv        各数据集 top-k 成员（长表）
      Test_1b_topk_pairwise_k{k}.csv  两两重叠率矩阵（交叠数 / k）
      Test_1b_topk_overlap_summary.csv 各 k 的聚合重叠率（Jaccard / 交叠率 / 零重叠对数）
      Test_1b_metrics.json            报告用头条量化数字
  图：Test_1b_per_dataset_profile.png              E1 Fig2 升级（逐数据集字段画像）
      Test_1b_per_dataset_distribution.png       指标 a：分布 + 四挡分层
      Test_1b_cross_dataset_field_distribution.png 指标 b
      Test_1b_topk_overlap_matrix.png            指标 c：两两重叠矩阵
      Test_1b_topk_overlap_summary.png           指标 c：聚合重叠率

可复跑：同输入重跑 diff=0（无时间戳、固定排序、固定数值格式、固定随机种子）。

用法：
  python3 results_display/scripts/Test_1b_dataset_cindex.py            # 生成全部产物
  python3 results_display/scripts/Test_1b_dataset_cindex.py --audit    # 生成 + 3 组抽查
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import textwrap
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "mplconfig"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.paths import test_results_dir

# --------------------------------------------------------------------------- 常量
CSV_NAME = "field_cindex.csv"
DEFAULT_ANALYZER = "mlp_clinic_flatten"
DEFAULT_UNIV_ROOT = (
    test_results_dir("Test_1a/arm_t0") / "prompt" / "landmark_0"
)
DEFAULT_MANIFEST = (
    REPO_ROOT / "results" / "Test_0_dataset_availability" / "manifest.csv"
)
DEFAULT_EVENT_SUMMARY = REPO_ROOT / "rawdata_stats" / "_shared" / "event_summary.csv"
DEFAULT_DATASETS_CONFIG = REPO_ROOT / "datasets.json"
DEFAULT_OUT_DIR = REPO_ROOT / "results_display" / "Test_1b_dataset_cindex"
DEFAULT_TOP_K = (5, 10, 20)
DEFAULT_MIN_DATASETS = 10
AUDIT_SEED = 20261002
AUDIT_N = 3

# ---- 视觉常量（与 Test_2b_delta_report.py 同一套：dataviz 参考调色板 light 表面）----
INK = "#0b0b0b"
MUTED = "#898781"
BASELINE = "#c3c2b7"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"
COL_POS = "#e34948"  # 发散对正极：c-index >= 0.5（高于随机）
COL_NEG = "#2a78d6"  # 发散对负极：c-index < 0.5；亦作单序列标记色
CHANCE = 0.5
# 顺序色阶（palette 参考蓝 100 -> 650；仅用于重叠率热图这一个量级编码）
SEQ_BLUE = [
    "#cde2fb",
    "#b7d3f6",
    "#9ec5f4",
    "#86b6ef",
    "#6da7ec",
    "#5598e7",
    "#3987e5",
    "#2a78d6",
    "#256abf",
    "#1c5cab",
    "#184f95",
    "#104281",
    "#0d366b",
]
BLUE_CMAP = LinearSegmentedColormap.from_list("seq_blue", SEQ_BLUE, N=256)

TIER_ORDER = {"main": 0, "main_ci": 1, "supp": 2, "low": 3}
TIER_LABEL = {
    "main": "main  (n_event >= 100, clean set)",
    "main_ci": "main_ci  (70-100, CI required, no ranking)",
    "supp": "supp  (30-70, supplementary)",
    "low": "low  (< 30, qualitative only)",
}
TIER_SOURCE_MANIFEST = "manifest"
TIER_SOURCE_PROTOCOL_A = "protocolA_provisional_manifest"


# --------------------------------------------------------------------------- 分层
def tier_for(n_event: int) -> str:
    """协议 A 四档（spec §12 U1）。"""
    if n_event >= 100:
        return "main"
    if n_event >= 70:
        return "main_ci"
    if n_event >= 30:
        return "supp"
    return "low"


def resolve_tier(manifest_row: dict | None, n_event: int) -> tuple[str, str]:
    """返回 (tier, tier_source)。manifest 标 provisional → 按协议 A 由 n_event 重算。"""
    note = str((manifest_row or {}).get("note", "") or "")
    provisional = "provisional" in note.lower()
    if manifest_row and not provisional:
        return str(manifest_row["tier"]), TIER_SOURCE_MANIFEST
    return tier_for(int(n_event)), TIER_SOURCE_PROTOCOL_A


# --------------------------------------------------------------------------- 输入
def tcga_dataset_names(config_path: Path) -> list[str]:
    """datasets.json 中 TCGA 前缀的数据集（33 个；含下划线写法 TCGA_LIHC）。"""
    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    names = sorted(k for k in payload if str(k).upper().startswith("TCGA"))
    if not names:
        raise ValueError(f"no TCGA datasets in {config_path}")
    return names


def load_manifest(path: Path) -> dict[str, dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {row["dataset"]: row for row in csv.DictReader(handle)}


def load_event_summary(path: Path) -> dict[str, dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {row["dataset"]: row for row in csv.DictReader(handle)}


def read_field_cindex(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def assemble_dataset(
    dataset: str,
    univ_root: Path,
    analyzer: str,
    manifest: dict[str, dict],
    events: dict[str, dict],
) -> dict:
    csv_path = Path(univ_root) / dataset / analyzer / CSV_NAME
    if not csv_path.exists():
        raise FileNotFoundError(f"missing S5 univariate table: {csv_path}")
    rows = read_field_cindex(csv_path)
    if not rows:
        raise ValueError(f"empty table: {csv_path}")

    fields: dict[str, float] = {}
    stds: dict[str, float] = {}
    for row in rows:
        name = str(row.get("field") or "").strip()
        if not name:
            continue
        status = str(row.get("status") or "").strip()
        if status and status != "ok":
            raise ValueError(f"{dataset}: field {name} status={status} (expected ok)")
        fields[name] = float(row["c_index_mean"])
        stds[name] = float(row["c_index_std"])

    ev = events.get(dataset, {})
    n_event = int(ev.get("n_event", (manifest.get(dataset) or {}).get("n_event", 0)))
    n_patients = int(
        ev.get("n_patients", (manifest.get(dataset) or {}).get("n_patients", 0))
    )
    event_rate = float(
        ev.get("event_rate", (manifest.get(dataset) or {}).get("event_rate", 0.0))
    )
    tier, tier_source = resolve_tier(manifest.get(dataset), n_event)
    values = sorted(fields.values())
    top1_field = max(sorted(fields), key=lambda f: (fields[f], f))
    return {
        "dataset": dataset,
        "src": csv_path,
        "tier": tier,
        "tier_source": tier_source,
        "manifest_tier": str((manifest.get(dataset) or {}).get("tier", "")),
        "n_patients": n_patients,
        "n_event": n_event,
        "event_rate": event_rate,
        "n_fields": len(fields),
        "fields": fields,
        "stds": stds,
        "values_sorted": values,
        "c_min": values[0],
        "c_max": values[-1],
        "c_median": float(np.median(values)),
        "c_q1": float(np.percentile(values, 25)),
        "c_q3": float(np.percentile(values, 75)),
        "c_mean": float(np.mean(values)),
        "c_std_across_fields": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        "fold_std_median": float(np.median(sorted(stds.values()))),
        "top1_field": top1_field,
        "top1_value": fields[top1_field],
        "n_fields_ge_chance": sum(1 for v in values if v >= CHANCE),
        "frac_ge_chance": sum(1 for v in values if v >= CHANCE) / len(values),
        "field_spread": values[-1] - values[0],
    }


# --------------------------------------------------------------------------- 排版
def order_datasets(records: list[dict]) -> list[dict]:
    return sorted(
        records,
        key=lambda r: (TIER_ORDER[r["tier"]], -r["n_event"], r["dataset"]),
    )


def field_leaf(field: str) -> str:
    return str(field).replace("[]", "").split(".")[-1]


def field_parent(field: str) -> str:
    parts = [p for p in str(field).replace("[]", "").split(".") if p]
    return parts[-2] if len(parts) >= 2 else ""


def short_field_labels(fields: list[str]) -> list[str]:
    leaves = [field_leaf(f) for f in fields]
    counts = Counter(leaves)
    out = []
    for field, leaf in zip(fields, leaves):
        if counts[leaf] == 1:
            out.append(leaf)
        else:
            parent = field_parent(field)
            out.append(f"{parent}.{leaf}" if parent else leaf)
    return out


def field_stats(records: list[dict]) -> dict[str, dict]:
    per_field: dict[str, dict[str, float]] = {}
    for record in records:
        for field, value in record["fields"].items():
            per_field.setdefault(field, {})[record["dataset"]] = value
    out: dict[str, dict] = {}
    for field in sorted(per_field):
        by_ds = per_field[field]
        values = sorted(by_ds.values())
        out[field] = {
            "field": field,
            "n_datasets": len(values),
            "datasets": sorted(by_ds),
            "values": by_ds,
            "c_median": float(np.median(values)),
            "c_mean": float(np.mean(values)),
            "c_min": values[0],
            "c_max": values[-1],
            "c_range": values[-1] - values[0],
            "c_std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        }
    return out


def matrix_axes(records: list[dict]) -> tuple[list[str], list[str]]:
    datasets = [r["dataset"] for r in records]
    fields = sorted({f for r in records for f in r["fields"]})
    return datasets, fields


def build_matrix(records: list[dict], fields: list[str]) -> np.ndarray:
    index = {f: i for i, f in enumerate(fields)}
    matrix = np.full((len(records), len(fields)), np.nan, dtype=float)
    for row_idx, record in enumerate(records):
        for field, value in record["fields"].items():
            matrix[row_idx, index[field]] = value
    return matrix


def topk_sets(record: dict, k: int) -> list[str]:
    ranked = sorted(record["fields"], key=lambda f: (-record["fields"][f], f))
    return ranked[: min(k, len(ranked))]


# --------------------------------------------------------------------------- 输出
def write_rows(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_matrix(
    path: Path, names: list[str], values: np.ndarray, fmt: str = "%.6f"
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dataset", *names])
        for name, row in zip(names, values):
            payload = [name]
            for value in row:
                payload.append("" if np.isnan(value) else (fmt % value))
            writer.writerow(payload)


# --------------------------------------------------------------------------- 图
def setup_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASELINE)
    ax.tick_params(colors=MUTED, labelsize=8.0)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)


def row_positions(n: int) -> list[float]:
    """行 y 坐标：records[0]（main 组、事件数最多）在最上方。"""
    return [float(n - 1 - idx) for idx in range(n)]


def row_positions_gapped(records: list[dict], gap: float = 0.9) -> list[float]:
    """同 row_positions，但在档与档之间多留 gap（剖面图里给档位文字留白）。"""
    ys: list[float] = []
    y = 0.0
    prev = None
    for record in records:
        if prev is not None and record["tier"] != prev:
            y -= gap
        ys.append(y)
        y -= 1.0
        prev = record["tier"]
    return ys


def tier_group_bounds(records: list[dict]) -> list[tuple[str, int]]:
    """返回 [(tier, 该 tier 组首行的下标)]，行序 = order_datasets 的输出序。"""
    bounds: list[tuple[str, int]] = []
    prev = None
    for idx, record in enumerate(records):
        if record["tier"] != prev:
            bounds.append((record["tier"], idx))
            prev = record["tier"]
    return bounds


def annotate_tiers(
    ax,
    records: list[dict],
    ys: list[float],
    *,
    gap: float = 0.0,
    fontsize: float = 7.5,
):
    """在每档首行上方画分隔线 + 档位文字（x 为轴比例、y 为数据坐标）。

    gap>0 时档间比档内多留 gap 的行距（剖面图用，避免档位文字压到上一行的高柱）。
    """
    transform = ax.get_yaxis_transform()
    sep_offset = (1.0 + gap) / 2.0 if gap else 0.5
    text_offset = 0.45 if gap else 0.42
    for i, (tier, idx) in enumerate(tier_group_bounds(records)):
        if i > 0:
            ax.axhline(ys[idx] + sep_offset, color=BASELINE, linewidth=1.1, zorder=1)
        ax.text(
            0.004,
            ys[idx] + text_offset,
            TIER_LABEL[tier],
            transform=transform,
            ha="left",
            va="bottom",
            fontsize=fontsize,
            color=MUTED,
        )


def figure_per_dataset_profile(
    records: list[dict],
    all_fields: list[str],
    shared_fields: list[str],
    stats: dict[str, dict],
    out_path: Path,
    *,
    analyzer: str,
    tier_note: str,
) -> Path:
    """E1 Fig2 升级版：逐数据集一行，共用字段轴（>= min_datasets），
    字段按 (覆盖数据集数, 跨数据集中位 c-index) 降序；缺字段 = 该数据集 bank 里没有。"""
    ordered = sorted(
        shared_fields,
        key=lambda f: (-stats[f]["n_datasets"], -stats[f]["c_median"], f),
    )
    index = {f: i for i, f in enumerate(ordered)}
    labels = short_field_labels(ordered)
    n_rows, n_cols = len(records), len(ordered)
    tier_gap = 0.9
    ys = row_positions_gapped(records, tier_gap)
    bar_span = 0.72
    fig_w = max(16.0, n_cols * 0.45)
    fig_h = max(7.0, n_rows * 0.34 + 4.2)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(SURFACE)
    for yi, record in zip(ys, records):
        xs, hs = [], []
        for field, value in record["fields"].items():
            if field not in index:
                continue
            xs.append(index[field])
            hs.append(value * bar_span)
        order = np.argsort(xs)
        ax.bar(
            np.array(xs)[order],
            np.array(hs)[order],
            bottom=yi - bar_span / 2.0,
            width=0.86,
            color=COL_NEG,
            edgecolor="none",
            zorder=3,
        )
        ax.axhline(yi - bar_span / 2.0, color=BASELINE, lw=0.5, zorder=1)
        ax.axhline(yi - bar_span / 2.0 + CHANCE * bar_span,
                   color=GRIDLINE, lw=0.5, ls="--", zorder=2)
    annotate_tiers(ax, records, ys, gap=tier_gap, fontsize=8.0)
    ax.set_xlim(-0.5, n_cols - 0.5)
    ax.set_ylim(min(ys) - 0.55, max(ys) + 0.62)
    ax.set_yticks(ys)
    ax.set_yticklabels(
        [f'{r["dataset"]}  (n={r["n_fields"]})' for r in records],
        fontsize=7.2,
        color=INK,
    )
    ax.set_xticks(np.arange(n_cols))
    ax.set_xticklabels(labels, rotation=90, fontsize=6.8, ha="center", va="top",
                       color=INK)
    ax.tick_params(axis="both", length=0)
    ax.set_xlabel(
        f"shared fields (n={n_cols} of {len(all_fields)} distinct fields; "
        f"present in >= {min(stats[f]['n_datasets'] for f in ordered)} datasets), "
        "sorted by coverage then cross-dataset median c-index"
    )
    ax.set_title(
        "Test_1b — single-field c-index profile per dataset on the shared field axis  |  "
        f"{analyzer} / landmark_0\n"
        "bar height proportional to c-index within each row (row baseline = 0, "
        "dashed line = 0.5, full row = 1.0); a gap = field not in that bank\n"
        f"{tier_note}",
        fontsize=10,
        color=INK,
        pad=10,
    )
    setup_axes(ax)
    fig.subplots_adjust(left=0.13, right=0.995, top=0.895, bottom=0.185)
    fig.savefig(out_path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out_path


def figure_per_dataset_distribution(
    records: list[dict], out_path: Path, *, analyzer: str, tier_note: str
) -> Path:
    """指标 a：各数据集单字段 c-index 分布（四档分层 + top-1 标记）。"""
    n = len(records)
    fig, ax = plt.subplots(figsize=(10.4, max(5.0, 0.31 * n + 3.4)))
    fig.patch.set_facecolor(SURFACE)
    rng = np.random.default_rng(AUDIT_SEED)
    y = np.array(row_positions(n))
    for yi, record in zip(y, records):
        values = np.array(record["values_sorted"])
        q1, med, q3 = record["c_q1"], record["c_median"], record["c_q3"]
        jitter = rng.uniform(-0.28, 0.28, size=values.shape[0])
        colors = [COL_POS if v >= CHANCE else COL_NEG for v in values]
        ax.scatter(values, yi + jitter, s=9, c=colors, linewidths=0, alpha=0.85, zorder=3)
        ax.plot([values[0], values[-1]], [yi, yi], color=BASELINE, lw=1.2, zorder=2)
        ax.plot([q1, q3], [yi, yi], color=MUTED, lw=3.4, solid_capstyle="butt", zorder=4)
        ax.plot([med, med], [yi - 0.22, yi + 0.22], color=INK, lw=1.6, zorder=5)
        ax.scatter(
            [record["top1_value"]], [yi], s=28, marker="D",
            c=COL_POS, edgecolors=SURFACE, linewidths=0.5, zorder=6,
        )
        ax.annotate(
            f'{record["top1_value"]:.3f}',
            xy=(record["top1_value"], yi),
            xytext=(7, 0),
            textcoords="offset points",
            va="center",
            fontsize=6.8,
            color=MUTED,
        )
    ax.axvline(CHANCE, color=BASELINE, lw=1.2, ls="--", zorder=1)
    ax.set_yticks(y)
    ax.set_yticklabels(
        [f'{r["dataset"]}  (n_event={r["n_event"]}, n_fields={r["n_fields"]})' for r in records],
        fontsize=7.2,
        color=INK,
    )
    annotate_tiers(ax, records, list(y))
    ax.set_ylim(-0.7, n - 0.3)
    ax.set_xlim(0.05, 1.14)
    ax.set_xlabel("single-field c-index (5-fold mean, per field); right label = dataset top-1")
    setup_axes(ax)
    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color=COL_POS,
                   label="field c-index >= 0.5"),
        plt.Line2D([], [], marker="o", linestyle="", color=COL_NEG,
                   label="field c-index < 0.5"),
        plt.Line2D([], [], marker="D", linestyle="", color=COL_POS,
                   markeredgecolor=SURFACE, label="dataset top-1 field"),
        plt.Line2D([], [], marker="|", linestyle="", color=INK, markersize=12,
                   label="median"),
        plt.Line2D([], [], marker="_", linestyle="", color=MUTED, markersize=12,
                   label="IQR"),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=8.0,
              loc="upper center", bbox_to_anchor=(0.5, -0.045), ncol=5,
              labelcolor=INK)
    fig.subplots_adjust(left=0.245, right=0.995, top=0.90, bottom=0.105)
    # 标题按整幅居中（轴区偏右，set_title 会越界）
    fig.text(
        0.5, 0.985,
        f"Test_1b — per-dataset single-field c-index distribution  |  "
        f"{analyzer} / landmark_0  (n={n} datasets)",
        ha="center", va="top", fontsize=10.5, color=INK,
    )
    fig.text(0.5, 0.958, tier_note, ha="center", va="top", fontsize=8.0,
             color=MUTED)
    fig.savefig(out_path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out_path


def figure_cross_dataset_fields(
    records: list[dict],
    stats: dict[str, dict],
    shared_fields: list[str],
    out_path: Path,
    *,
    analyzer: str,
    tier_note: str,
    min_datasets: int,
) -> Path:
    """指标 b：同一字段跨数据集 c-index 分布（公共字段）。"""
    ordered = sorted(shared_fields, key=lambda f: (-stats[f]["c_median"], f))
    labels = short_field_labels(ordered)
    n = len(ordered)
    fig, ax = plt.subplots(figsize=(max(12.0, 0.42 * n + 2.0), 6.6))
    fig.patch.set_facecolor(SURFACE)
    rng = np.random.default_rng(AUDIT_SEED)
    for xi, field in enumerate(ordered):
        stat = stats[field]
        values = np.array(sorted(stat["values"].values()))
        jitter = rng.uniform(-0.24, 0.24, size=values.shape[0])
        colors = [
            COL_POS if v >= CHANCE else COL_NEG
            for v in sorted(stat["values"].values())
        ]
        ax.scatter(
            np.full(values.shape[0], xi) + jitter, values, s=11, c=colors,
            linewidths=0, alpha=0.85, zorder=3,
        )
        q1 = float(np.percentile(values, 25))
        q3 = float(np.percentile(values, 75))
        ax.plot([xi - 0.30, xi + 0.30], [stat["c_median"]] * 2, color=INK, lw=1.6, zorder=5)
        ax.plot([xi - 0.22, xi + 0.22], [q1, q1], color=MUTED, lw=1.2, zorder=4)
        ax.plot([xi - 0.22, xi + 0.22], [q3, q3], color=MUTED, lw=1.2, zorder=4)
        ax.plot([xi, xi], [values[0], values[-1]], color=BASELINE, lw=1.0, zorder=2)
        ax.annotate(
            f'{stat["c_range"]:.2f}',
            xy=(xi + 0.34, values[-1]),
            xytext=(2, 0),
            textcoords="offset points",
            va="center",
            fontsize=6.0,
            color=MUTED,
            rotation=90,
        )
        ax.annotate(
            f'n={stat["n_datasets"]}',
            xy=(xi, 1.005),
            xycoords=("data", "axes fraction"),
            ha="center",
            va="bottom",
            fontsize=6.0,
            color=MUTED,
        )
    ax.axhline(CHANCE, color=BASELINE, lw=1.2, ls="--", zorder=1)
    ax.set_xticks(np.arange(n))
    ax.set_xticklabels(labels, rotation=90, fontsize=7.0, ha="center", color=INK)
    ax.set_xlim(-0.7, n - 0.3)
    ax.set_ylim(0.05, 1.02)
    ax.set_ylabel("single-field c-index (5-fold mean)")
    ax.set_title(
        "Test_1b — same field across datasets: single-field c-index distribution  |  "
        f"{analyzer} / landmark_0\nfields present in >= {min_datasets} datasets "
        f"(n={n}); sorted by cross-dataset median; right label = range (max-min)\n"
        f"{tier_note}",
        fontsize=10,
        color=INK,
        pad=12,
    )
    setup_axes(ax)
    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color=COL_POS, label="c-index >= 0.5"),
        plt.Line2D([], [], marker="o", linestyle="", color=COL_NEG, label="c-index < 0.5"),
        plt.Line2D([], [], marker="|", linestyle="", color=INK, markersize=12, label="median"),
        plt.Line2D([], [], marker="_", linestyle="", color=MUTED, markersize=12, label="Q1/Q3"),
        plt.Line2D([], [], color=BASELINE, lw=1.0, label="min-max"),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=7.5, loc="upper right",
              labelcolor=INK, ncol=2)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.99))
    fig.savefig(out_path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out_path


def figure_topk_matrices(
    datasets: list[str],
    overlap_by_k: dict[int, np.ndarray],
    summary: dict[int, dict],
    out_path: Path,
    *,
    tier_note: str,
) -> Path:
    ks = sorted(overlap_by_k)
    short = [d.replace("TCGA-", "").replace("TCGA_", "") for d in datasets]
    n = len(datasets)
    n_panels = len(ks)
    fig_w = 4.5 * n_panels + 1.6
    fig_h = 6.6
    fig = plt.figure(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(SURFACE)
    left, right, top, bottom = 0.075, 0.925, 0.845, 0.155
    slot = (right - left) / n_panels
    panel_w = slot * 0.80
    image = None
    for panel_idx, k in enumerate(ks):
        ax = fig.add_axes([left + panel_idx * slot, bottom, panel_w, top - bottom])
        matrix = overlap_by_k[k].copy()
        np.fill_diagonal(matrix, np.nan)
        image = ax.imshow(
            matrix, cmap=BLUE_CMAP, vmin=0.0, vmax=1.0, interpolation="nearest"
        )
        image.cmap.set_bad(SURFACE)
        ax.set_xticks(np.arange(n))
        ax.set_yticks(np.arange(n))
        ax.set_xticklabels(short, rotation=90, fontsize=5.6, color=INK)
        ax.set_yticklabels(short, fontsize=5.6, color=INK)
        ax.tick_params(colors=MUTED, length=1)
        for spine in ax.spines.values():
            spine.set_color(BASELINE)
        info = summary[k]
        ax.set_title(
            f"k = {k}   mean pairwise overlap {info['mean_overlap']:.3f}\n"
            f"zero-shared-field pairs {info['n_empty_pairs']}/{info['n_pairs']} "
            f"({100.0 * info['n_empty_pairs'] / info['n_pairs']:.1f}%)",
            fontsize=9.5,
            color=INK,
        )
    cax = fig.add_axes([right + 0.018, bottom, 0.013, top - bottom])
    bar = fig.colorbar(image, cax=cax)
    bar.set_label("overlap rate  |A ∩ B| / k", color=MUTED, fontsize=8.5)
    bar.ax.tick_params(colors=MUTED, labelsize=8)
    bar.outline.set_edgecolor(BASELINE)
    fig.text(
        0.5,
        0.975,
        "Test_1b — top-k field overlap between datasets (row / column = dataset)",
        ha="center",
        va="top",
        fontsize=11,
        color=INK,
    )
    fig.text(0.5, 0.955, tier_note, ha="center", va="top", fontsize=8.0, color=MUTED)
    fig.savefig(out_path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out_path


def figure_topk_summary(
    summary: dict[int, dict],
    pairwise_values: dict[int, list[float]],
    out_path: Path,
) -> Path:
    ks = sorted(summary)
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(12.6, 5.4))
    fig.patch.set_facecolor(SURFACE)

    x = np.arange(len(ks))
    means = [summary[k]["mean_overlap"] for k in ks]
    medians = [summary[k]["median_overlap"] for k in ks]
    top = max(means + medians) * 1.55
    ax_a.bar(x, means, width=0.56, color=COL_NEG, edgecolor="none", zorder=2)
    ax_a.plot(x, medians, linestyle="", marker="D", markersize=6, color=INK, zorder=4)
    for xi, (k, mean) in enumerate(zip(ks, means)):
        info = summary[k]
        ax_a.annotate(
            f"{mean:.3f}", xy=(xi, mean), xytext=(0, 5), textcoords="offset points",
            ha="center", va="bottom", fontsize=9.0, color=INK,
        )
        if info["n_empty_pairs"]:
            share = 100.0 * info["fraction_empty_pairs"]
            ax_a.annotate(
                f"{info['n_empty_pairs']}/{info['n_pairs']} pairs\nshare 0 fields "
                f"({share:.1f}%)",
                xy=(xi, top), ha="center", va="top", fontsize=7.5, color=COL_POS,
            )
    ax_a.set_xticks(x)
    ax_a.set_xticklabels([f"k = {k}" for k in ks], color=INK, fontsize=9.5)
    ax_a.set_ylim(0.0, top)
    ax_a.set_ylabel("pairwise overlap rate  |A ∩ B| / k")
    ax_a.set_title(
        "Top-k overlap between dataset field rankings (528 dataset pairs)",
        fontsize=10, color=INK,
    )
    setup_axes(ax_a)
    handles = [
        plt.Line2D([], [], marker="s", linestyle="", color=COL_NEG, markersize=8,
                   label="mean overlap rate"),
        plt.Line2D([], [], marker="D", linestyle="", color=INK, markersize=6,
                   label="median overlap rate"),
    ]
    ax_a.legend(handles=handles, frameon=False, fontsize=8, loc="upper center",
                bbox_to_anchor=(0.5, -0.075), ncol=2, labelcolor=INK)

    for xi, k in enumerate(ks):
        values = np.array(pairwise_values[k])
        jitter = np.random.default_rng(AUDIT_SEED + k).uniform(-0.22, 0.22, size=values.shape[0])
        colors = [COL_POS if v == 0.0 else COL_NEG for v in values]
        ax_b.scatter(np.full(values.shape[0], xi) + jitter, values, s=6, c=colors,
                     linewidths=0, alpha=0.55, zorder=3)
        q1 = float(np.percentile(values, 25))
        q3 = float(np.percentile(values, 75))
        ax_b.plot([xi - 0.26, xi + 0.26], [q1, q1], color=MUTED, lw=1.2, zorder=4)
        ax_b.plot([xi - 0.26, xi + 0.26], [q3, q3], color=MUTED, lw=1.2, zorder=4)
        ax_b.plot([xi - 0.30, xi + 0.30],
                  [summary[k]["median_overlap"]] * 2, color=INK, lw=1.8, zorder=5)
        n_zero = int((values == 0.0).sum())
        if n_zero:
            ax_b.annotate(
                f'{n_zero} pairs = 0',
                xy=(xi + 0.07, 0.035), ha="left", va="bottom", fontsize=7.5,
                color=COL_POS,
            )
    ax_b.set_xticks(np.arange(len(ks)))
    ax_b.set_xticklabels([f"k = {k}" for k in ks], color=INK, fontsize=9)
    ax_b.set_ylim(-0.02, 1.0)
    ax_b.set_ylabel("overlap rate per dataset pair")
    ax_b.set_title(
        "Distribution of pairwise overlap (each dot = one dataset pair)",
        fontsize=10, color=INK,
    )
    setup_axes(ax_b)
    handles_b = [
        plt.Line2D([], [], marker="o", linestyle="", color=COL_POS, markersize=6,
                   label="zero shared fields"),
        plt.Line2D([], [], marker="o", linestyle="", color=COL_NEG, markersize=6,
                   label="at least one shared field"),
        plt.Line2D([], [], marker="|", linestyle="", color=INK, markersize=12,
                   label="median"),
        plt.Line2D([], [], marker="_", linestyle="", color=MUTED, markersize=12,
                   label="Q1/Q3"),
    ]
    ax_b.legend(handles=handles_b, frameon=False, fontsize=8.0,
                loc="upper center", bbox_to_anchor=(0.5, -0.075), ncol=4,
                labelcolor=INK)
    fig.suptitle(
        "Test_1b — top-k field overlap summary  |  "
        "low overlap = the best fields are dataset-specific\n"
        "fields ranked per dataset by single-field c-index (S5 univariate, "
        "mlp_clinic_flatten, landmark_0); top-k over that dataset's own bank",
        fontsize=10,
        color=INK,
        y=0.985,
    )
    fig.subplots_adjust(left=0.065, right=0.99, top=0.82, bottom=0.19, wspace=0.22)
    fig.savefig(out_path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return out_path


# --------------------------------------------------------------------------- 主流程
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Test_1b: per-dataset single-field c-index distributions, "
            "cross-dataset field distributions and top-k field overlap."
        )
    )
    parser.add_argument("--univariate_root", default=str(DEFAULT_UNIV_ROOT),
                        help="S5 univariate root: .../{dataset}/{analyzer}/field_cindex.csv")
    parser.add_argument("--analyzer", default=DEFAULT_ANALYZER)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--event_summary", default=str(DEFAULT_EVENT_SUMMARY))
    parser.add_argument("--datasets_config", default=str(DEFAULT_DATASETS_CONFIG))
    parser.add_argument("--out_dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--top_k", default=",".join(str(k) for k in DEFAULT_TOP_K),
                        help="comma separated k list for the top-k overlap analysis")
    parser.add_argument("--min_datasets", type=int, default=DEFAULT_MIN_DATASETS,
                        help="a field counts as common when present in >= this many datasets")
    parser.add_argument("--audit", action="store_true",
                        help="spot-check 3 (dataset, field) against the raw field_cindex.csv")
    return parser


def parse_top_k(raw: str) -> list[int]:
    ks = sorted({int(tok) for tok in str(raw).split(",") if tok.strip()})
    if not ks or any(k <= 0 for k in ks):
        raise ValueError(f"invalid --top_k: {raw!r}")
    return ks


def audit(records: list[dict], stats: dict[str, dict]) -> bool:
    """固定种子抽 3 个 (dataset, field)，从原始 CSV 独立重算并与产物对照。"""
    all_pairs = sorted(
        (r["dataset"], field) for r in records for field in r["fields"]
    )
    rng = random.Random(AUDIT_SEED)
    sample = rng.sample(all_pairs, AUDIT_N)
    print(f"[audit] seed={AUDIT_SEED} 抽取 {AUDIT_N} 组 (dataset, field)（共 {len(all_pairs)} 组）:")
    ok_all = True
    for dataset, field in sample:
        record = next(r for r in records if r["dataset"] == dataset)
        csv_path = record["src"]
        raw = None
        for row in read_field_cindex(csv_path):
            if str(row["field"]).strip() == field:
                raw = row
                break
        if raw is None:
            print(f"  - {dataset} × {field}: NOT FOUND in {csv_path}")
            ok_all = False
            continue
        folds = json.loads(raw["per_fold"])
        manual_mean = sum(folds) / len(folds)
        stored = float(raw["c_index_mean"])
        in_record = record["fields"][field]
        in_stats = stats[field]["values"][dataset]
        ok = (
            abs(manual_mean - stored) < 1e-12
            and stored == in_record
            and in_record == in_stats
        )
        ok_all &= ok
        print(
            f"  - {dataset} × {field}: mean(per_fold)={manual_mean:.10f} "
            f"csv={stored:.10f} record={in_record:.10f} field_summary={in_stats:.10f} "
            f"→ {'OK' if ok else 'FAIL'}"
        )
    print(f"[audit] {'ALL PASS' if ok_all else 'FAILED'}")
    return ok_all


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    univ_root = Path(args.univariate_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ks = parse_top_k(args.top_k)

    names = tcga_dataset_names(Path(args.datasets_config))
    manifest = load_manifest(Path(args.manifest))
    events = load_event_summary(Path(args.event_summary))

    records = [
        assemble_dataset(name, univ_root, args.analyzer, manifest, events)
        for name in names
    ]
    records = order_datasets(records)
    stats = field_stats(records)
    datasets, fields = matrix_axes(records)
    matrix = build_matrix(records, fields)

    tier_sources = {r["tier_source"] for r in records}
    tier_counts = Counter(r["tier"] for r in records)
    counts_txt = ", ".join(
        f"{t}={tier_counts[t]}" for t in sorted(tier_counts, key=TIER_ORDER.get)
    )
    if tier_sources == {TIER_SOURCE_PROTOCOL_A}:
        tier_note = (
            "Tiers: protocol A on n_event (main >=100 / main_ci 70-100 / supp 30-70 / "
            f"low <30) — {counts_txt}; Test_0 manifest is provisional(D1) for all 33 "
            "TCGA rows, so tiers come from n_event (tier_source column in the CSV)."
        )
    elif tier_sources == {TIER_SOURCE_MANIFEST}:
        tier_note = (
            "Tiers: Test_0 manifest (confirmed, not provisional) — " + counts_txt
        )
    else:
        tier_note = (
            "Tiers: mixed source (per-dataset tier_source in the CSV) — " + counts_txt
        )
    # 图题里的 tier 注记统一切行（避免标题超宽被裁切）
    tier_note = "\n".join(textwrap.wrap(tier_note, 110))

    wrote: list[Path] = []

    # --- 表：数据集级 ---
    ds_rows = []
    for r in records:
        ds_rows.append({
            "dataset": r["dataset"],
            "tier": r["tier"],
            "tier_source": r["tier_source"],
            "manifest_tier": r["manifest_tier"],
            "n_patients": r["n_patients"],
            "n_event": r["n_event"],
            "event_rate": "%.4f" % r["event_rate"],
            "n_fields": r["n_fields"],
            "c_min": "%.6f" % r["c_min"],
            "c_q1": "%.6f" % r["c_q1"],
            "c_median": "%.6f" % r["c_median"],
            "c_q3": "%.6f" % r["c_q3"],
            "c_max": "%.6f" % r["c_max"],
            "c_mean": "%.6f" % r["c_mean"],
            "field_spread_max_minus_min": "%.6f" % r["field_spread"],
            "std_across_fields": "%.6f" % r["c_std_across_fields"],
            "median_fold_std": "%.6f" % r["fold_std_median"],
            "n_fields_ge_0.5": r["n_fields_ge_chance"],
            "frac_fields_ge_0.5": "%.6f" % r["frac_ge_chance"],
            "top1_field": r["top1_field"],
            "top1_c_index": "%.6f" % r["top1_value"],
        })
    p = out_dir / "Test_1b_dataset_summary.csv"
    write_rows(p, ds_rows, list(ds_rows[0]))
    wrote.append(p)

    # --- 表：字段级 ---
    field_rows = []
    for field in sorted(stats):
        st = stats[field]
        field_rows.append({
            "field": field,
            "n_datasets": st["n_datasets"],
            "c_median": "%.6f" % st["c_median"],
            "c_mean": "%.6f" % st["c_mean"],
            "c_min": "%.6f" % st["c_min"],
            "c_max": "%.6f" % st["c_max"],
            "c_range": "%.6f" % st["c_range"],
            "c_std": "%.6f" % st["c_std"],
            "datasets": ";".join(st["datasets"]),
        })
    p = out_dir / "Test_1b_field_summary.csv"
    write_rows(p, field_rows, list(field_rows[0]))
    wrote.append(p)

    # --- 表：对齐矩阵 ---
    p = out_dir / "Test_1b_cindex_matrix.csv"
    write_matrix(p, datasets, matrix)
    wrote.append(p)

    # --- 指标 c：top-k 重叠 ---
    overlap_by_k: dict[int, np.ndarray] = {}
    pairwise_values: dict[int, list[float]] = {}
    summary: dict[int, dict] = {}
    member_rows = []
    n_ds = len(records)
    for k in ks:
        sets = {r["dataset"]: set(topk_sets(r, k)) for r in records}
        for r in records:
            for rank, field in enumerate(topk_sets(r, k), start=1):
                member_rows.append({
                    "k": k,
                    "dataset": r["dataset"],
                    "rank": rank,
                    "field": field,
                    "c_index_mean": "%.6f" % r["fields"][field],
                })
        ov = np.full((n_ds, n_ds), np.nan, dtype=float)
        pairs: list[float] = []
        jac: list[float] = []
        for i, a in enumerate(datasets):
            ov[i, i] = 1.0
            for j, b in enumerate(datasets):
                if j <= i:
                    continue
                inter = len(sets[a] & sets[b])
                rate = inter / k
                ov[i, j] = ov[j, i] = rate
                pairs.append(rate)
                union = len(sets[a] | sets[b])
                jac.append(inter / union if union else 0.0)
        overlap_by_k[k] = ov
        pairwise_values[k] = pairs
        hits = Counter(f for ds in datasets for f in sets[ds])
        summary[k] = {
            "k": k,
            "n_pairs": len(pairs),
            "mean_overlap": float(np.mean(pairs)),
            "median_overlap": float(np.median(pairs)),
            "min_overlap": float(np.min(pairs)),
            "max_overlap": float(np.max(pairs)),
            "mean_jaccard": float(np.mean(jac)),
            "median_jaccard": float(np.median(jac)),
            "n_empty_pairs": sum(1 for v in pairs if v == 0.0),
            "fraction_empty_pairs": sum(1 for v in pairs if v == 0.0) / len(pairs),
            "n_union_fields": len(set().union(*sets.values())),
            "n_fields_in_all_datasets": sum(1 for f, c in hits.items() if c == n_ds),
            "n_fields_in_at_least_half": sum(
                1 for c in hits.values() if c >= n_ds / 2.0
            ),
            "n_fields_unique_to_one_dataset": sum(1 for c in hits.values() if c == 1),
            "n_fields_ge_0.5_of_datasets": int(sum(1 for c in hits.values() if c >= 0.5 * n_ds)),
        }
        p = out_dir / f"Test_1b_topk_pairwise_k{k}.csv"
        write_matrix(p, datasets, ov)
        wrote.append(p)

    p = out_dir / "Test_1b_topk_members.csv"
    write_rows(p, member_rows, ["k", "dataset", "rank", "field", "c_index_mean"])
    wrote.append(p)

    overlap_rows = []
    for k in ks:
        info = summary[k]
        overlap_rows.append({
            "k": k,
            "n_dataset_pairs": info["n_pairs"],
            "mean_overlap_rate": "%.6f" % info["mean_overlap"],
            "median_overlap_rate": "%.6f" % info["median_overlap"],
            "min_overlap_rate": "%.6f" % info["min_overlap"],
            "max_overlap_rate": "%.6f" % info["max_overlap"],
            "mean_jaccard": "%.6f" % info["mean_jaccard"],
            "median_jaccard": "%.6f" % info["median_jaccard"],
            "n_pairs_with_zero_shared_field": info["n_empty_pairs"],
            "fraction_pairs_with_zero_shared_field": "%.6f" % info["fraction_empty_pairs"],
            "n_distinct_fields_in_any_topk": info["n_union_fields"],
            "n_fields_in_all_datasets_topk": info["n_fields_in_all_datasets"],
            "n_fields_in_at_least_half_of_datasets": info["n_fields_in_at_least_half"],
            "n_fields_unique_to_one_dataset": info["n_fields_unique_to_one_dataset"],
        })
    p = out_dir / "Test_1b_topk_overlap_summary.csv"
    write_rows(p, overlap_rows, list(overlap_rows[0]))
    wrote.append(p)

    # --- 指标 b：公共字段 ---
    shared_fields = [f for f in stats if stats[f]["n_datasets"] >= args.min_datasets]
    if not shared_fields:
        raise ValueError("no shared fields at --min_datasets")

    # --- 图 ---
    wrote.append(figure_per_dataset_profile(
        records, fields, shared_fields, stats,
        out_dir / "Test_1b_per_dataset_profile.png",
        analyzer=args.analyzer, tier_note=tier_note,
    ))
    wrote.append(figure_per_dataset_distribution(
        records, out_dir / "Test_1b_per_dataset_distribution.png",
        analyzer=args.analyzer, tier_note=tier_note,
    ))
    wrote.append(figure_cross_dataset_fields(
        records, stats, shared_fields,
        out_dir / "Test_1b_cross_dataset_field_distribution.png",
        analyzer=args.analyzer, tier_note=tier_note, min_datasets=args.min_datasets,
    ))
    wrote.append(figure_topk_matrices(
        datasets, overlap_by_k, summary,
        out_dir / "Test_1b_topk_overlap_matrix.png", tier_note=tier_note,
    ))
    wrote.append(figure_topk_summary(
        summary, pairwise_values, out_dir / "Test_1b_topk_overlap_summary.png",
    ))

    # --- 头条量化数字 ---
    per_ds_top1 = [r["top1_value"] for r in records]
    per_ds_median = [r["c_median"] for r in records]
    top1_counter = Counter(r["top1_field"] for r in records)
    top1_identity = [
        {"field": f, "n_datasets": c} for f, c in
        sorted(top1_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    shared_ranges = [stats[f]["c_range"] for f in shared_fields]
    shared_sorted = sorted(
        shared_fields, key=lambda f: (-stats[f]["c_range"], f)
    )
    metrics = {
        "provenance": {
            "univariate_root": str(univ_root),
            "analyzer": args.analyzer,
            "n_datasets": len(records),
            "n_dataset_field_values": int(sum(r["n_fields"] for r in records)),
            "n_distinct_fields": len(fields),
            "tier_source": sorted(tier_sources),
            "tier_counts": {t: tier_counts[t] for t in sorted(tier_counts, key=TIER_ORDER.get)},
            "min_datasets_for_common_field": args.min_datasets,
            "top_k": ks,
        },
        "a_per_dataset": {
            "top1_min": min(per_ds_top1),
            "top1_median": float(np.median(per_ds_top1)),
            "top1_max": max(per_ds_top1),
            "top1_spread": max(per_ds_top1) - min(per_ds_top1),
            "top1_min_dataset": min(records, key=lambda r: (r["top1_value"], r["dataset"]))["dataset"],
            "top1_max_dataset": max(records, key=lambda r: (r["top1_value"], r["dataset"]))["dataset"],
            "median_across_fields_min": min(per_ds_median),
            "median_across_fields_max": max(per_ds_median),
            "median_across_fields_spread": max(per_ds_median) - min(per_ds_median),
            "median_across_fields_min_dataset": min(
                records, key=lambda r: (r["c_median"], r["dataset"]))["dataset"],
            "median_across_fields_max_dataset": max(
                records, key=lambda r: (r["c_median"], r["dataset"]))["dataset"],
            "n_distinct_top1_fields": len(top1_counter),
            "top1_field_histogram": top1_identity,
            "n_fields_ge_0.5_total": int(sum(r["n_fields_ge_chance"] for r in records)),
            "frac_fields_ge_0.5_total": float(
                sum(r["n_fields_ge_chance"] for r in records) / sum(r["n_fields"] for r in records)
            ),
        },
        "b_cross_dataset": {
            "n_common_fields": len(shared_fields),
            "range_min": min(shared_ranges),
            "range_median": float(np.median(shared_ranges)),
            "range_max": max(shared_ranges),
            "largest_range_field": shared_sorted[0],
            "largest_range_value": stats[shared_sorted[0]]["c_range"],
            "largest_range_n_datasets": stats[shared_sorted[0]]["n_datasets"],
            "smallest_range_field": shared_sorted[-1],
            "smallest_range_value": stats[shared_sorted[-1]]["c_range"],
            "n_fields_range_ge_0.25": int(sum(1 for v in shared_ranges if v >= 0.25)),
            "n_fields_range_le_0.10": int(sum(1 for v in shared_ranges if v <= 0.10)),
        },
        "c_topk_overlap": {
            f"k{k}": {
                "pair_count": summary[k]["n_pairs"],
                "mean_overlap_rate": summary[k]["mean_overlap"],
                "median_overlap_rate": summary[k]["median_overlap"],
                "mean_jaccard": summary[k]["mean_jaccard"],
                "n_pairs_zero_shared": summary[k]["n_empty_pairs"],
                "fraction_pairs_zero_shared": summary[k]["fraction_empty_pairs"],
                "n_distinct_fields_in_any_topk": summary[k]["n_union_fields"],
                "n_fields_unique_to_one_dataset": summary[k]["n_fields_unique_to_one_dataset"],
                "n_fields_in_all_datasets": summary[k]["n_fields_in_all_datasets"],
            }
            for k in ks
        },
    }
    p = out_dir / "Test_1b_metrics.json"
    p.write_text(
        json.dumps(metrics, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    wrote.append(p)

    # --- 控制台摘要 ---
    print(f"Test_1b — {len(records)} datasets, {len(fields)} distinct fields, "
          f"{metrics['provenance']['n_dataset_field_values']} (dataset, field) values")
    print("  tiers (protocol A on n_event): "
          + ", ".join(f"{t}={tier_counts[t]}" for t in sorted(tier_counts, key=TIER_ORDER.get)))
    print(f"  (a) top-1 c-index across datasets: "
          f"{metrics['a_per_dataset']['top1_min']:.3f} .. "
          f"{metrics['a_per_dataset']['top1_max']:.3f} "
          f"(spread {metrics['a_per_dataset']['top1_spread']:.3f}); "
          f"distinct top-1 fields = {metrics['a_per_dataset']['n_distinct_top1_fields']}")
    print(f"  (b) common fields (>= {args.min_datasets} datasets): {len(shared_fields)}; "
          f"cross-dataset range median {metrics['b_cross_dataset']['range_median']:.3f}, "
          f"max {metrics['b_cross_dataset']['range_max']:.3f} "
          f"({metrics['b_cross_dataset']['largest_range_field']})")
    for k in ks:
        info = summary[k]
        print(f"  (c) k={k:2d}: mean overlap {info['mean_overlap']:.3f}, "
              f"median {info['median_overlap']:.3f}, "
              f"zero-shared pairs {info['n_empty_pairs']}/{info['n_pairs']} "
              f"({100.0 * info['fraction_empty_pairs']:.1f}%)")
    print(f"  out_dir: {out_dir}")

    rc = 0
    if args.audit:
        rc = 0 if audit(records, stats) else 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
