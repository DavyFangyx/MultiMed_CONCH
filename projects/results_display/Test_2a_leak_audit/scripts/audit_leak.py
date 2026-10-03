#!/usr/bin/env python3
"""H1a leakage-audit figures: where the paper schemes carry t0-future information.

New-definition display (spec §2.1 / §5.2, S2c): a patient leaks for field f iff the value
that actually entered the model came from a source slot with ``t_hi > 0``;
``leak_rate(f, D) = n_leak / n_valid`` with n_valid = patients whose pipeline value is
not the field's missing placeholder.  ``leaky_ratio`` (per scheme × dataset) counts
fields with ``leak_rate > 0``.

Reads the audit products written by ``scripts/run_leak_audit.py``:

  * ``results/Test_2a_leak_audit/leak_audit_summary.csv``  —— (dataset, scheme) aggregates,
  * ``results/Test_2a_leak_audit/{dataset}/{scheme}.json`` —— per-field detail
    (``n_valid`` / ``n_leak`` / ``n_t0_blocked`` / ``audit_mode`` …; 旧口径的
    ``n_valid_none`` / ``n_valid_t0`` / ``mask_applicable`` 列已作废)。

Renders two figures:

  * ``leak_audit_overview.png``  —— 工作 × 癌种 泄露字段占比 (leaky_ratio) 热图 +
    各工作跨队列的 leaky_ratio 分布（条形 = 均值，点 = 单个队列）；
  * ``leak_audit_fields.png``    —— 逐字段 × 工作 平均 leak_rate 热图 +
    各字段跨队列平均 leak_rate（† 标记「多数队列里不在 Field Bank」的字段）。

并把聚合表落盘为 ``leak_audit_scheme_mean.csv`` / ``leak_audit_field_mean.csv``。

用法::

    python results_display/Test_2a_leak_audit/scripts/audit_leak.py
    python results_display/Test_2a_leak_audit/scripts/audit_leak.py --audit_root results/Test_2a_leak_audit
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]

SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from common.paths import test_display_dir, test_results_dir

DEFAULT_AUDIT_ROOT = test_results_dir("Test_2a_leak_audit")
DEFAULT_OUT_DIR = test_display_dir("Test_2a_leak_audit")

# spec §2.4 方案顺序（10 个论文工作）
SCHEME_ORDER = [
    "MULTISURV",
    "SURVPGC",
    "MMSURV",
    "INTEGRATIVE_DNN",
    "HGCN_KIRC",
    "HGCN_LIHC",
    "HGCN_ESCA",
    "HGCN_LUSC",
    "HGCN_LUAD",
    "HGCN_UCEC",
]

# HGCN 系列与 TCGA 癌种的对应队列（spec §2.4；仅当产物缺 binding_datasets 时用作回退）
MATCHED_DATASET = {
    "HGCN_KIRC": "TCGA-KIRC",
    "HGCN_LIHC": "TCGA_LIHC",
    "HGCN_ESCA": "TCGA-ESCA",
    "HGCN_LUSC": "TCGA-LUSC",
    "HGCN_LUAD": "TCGA-LUAD",
    "HGCN_UCEC": "TCGA-UCEC",
}

# dataviz palette (validated): blue slot 1, orange slot 2, aqua slot 3
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
SURFACE = "#fcfcfb"
GRID = "#d8d6d0"
EMPTY = "#e9e7e1"  # 方案不含该字段 / 无数据
RAMP = ["#eef4fc", "#c4daf4", "#7fb2e5", BLUE, "#1d5aa0", "#123f73"]


def setup_matplotlib():
    """Agg backend + 可用的中文字体回退（图内标签为中文）。"""
    os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    cjk = [name for name in ("Noto Sans CJK JP", "Noto Sans CJK SC", "WenQuanYi Zen Hei", "Droid Sans Fallback") if name in available]
    # font.family 用列表才会触发逐字回退（只设 font.sans-serif 时中文会缺字）
    plt.rcParams["font.family"] = ["DejaVu Sans", *cjk]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audit_root", default=str(DEFAULT_AUDIT_ROOT), help="results/Test_2a_leak_audit 目录")
    parser.add_argument("--summary", default="", help="汇总 CSV；默认 <audit_root>/leak_audit_summary.csv")
    parser.add_argument("--out_dir", default=str(DEFAULT_OUT_DIR), help="图片与聚合表输出目录")
    parser.add_argument("--top_fields", type=int, default=12, help="字段图中展示的字段数上限（0=全部）")
    return parser


def load_summary(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    for col in ("n_fields", "n_leaky", "n_not_in_bank", "n_leak_rate_undefined"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("leaky_ratio", "mean_leak_rate"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "n_leak_total" not in df.columns or "n_valid_total" not in df.columns:
        raise ValueError(
            f"{path} 不是新口径（S2c）产物：缺 n_leak_total / n_valid_total 列。"
            "请先跑 python3 scripts/run_leak_audit.py --prune 重出 Test_2a 审计。"
        )
    df["scheme"] = pd.Categorical(df["scheme"], categories=SCHEME_ORDER, ordered=True)
    return df


def load_field_rows(audit_root: Path, summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in summary.iterrows():
        path = audit_root / str(row["dataset"]) / f"{row['scheme']}.json"
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for item in payload.get("fields", []):
            rows.append(
                {
                    "dataset": payload["dataset"],
                    "scheme": payload["scheme"],
                    "field": item["field"],
                    "family": item.get("family"),
                    "leak_rate": item.get("leak_rate"),
                    "leak_rate_undefined": bool(item.get("leak_rate_undefined")),
                    "n_valid": item.get("n_valid"),
                    "n_leak": item.get("n_leak"),
                    "n_t0_blocked": item.get("n_t0_blocked"),
                    "max_source_t_hi": item.get("max_source_t_hi"),
                    "not_in_bank": bool(item.get("not_in_bank")),
                    "audit_mode": item.get("audit_mode"),
                    "a_pipeline": str(item.get("audit_mode")) == "a_pipeline",
                }
            )
    df = pd.DataFrame(rows)
    df["leak_rate"] = pd.to_numeric(df["leak_rate"], errors="coerce")
    return df


def load_bindings(audit_root: Path, summary: pd.DataFrame) -> dict:
    """读每方案「被允许的队列」= spec §2.4 绑定，来自审计产物本身（不重复硬编码范围）。

    ``results/Test_2a_leak_audit/{dataset}/{scheme}.json`` 的 ``scheme_binding`` /
    ``binding_datasets`` 由 ``src/leak/audit.py`` 写入。
    返回 {"allowed": {scheme: [dataset, ...]}, "kind": {scheme: 绑定类型}}。
    """
    allowed: dict[str, list[str]] = {}
    kinds: dict[str, str] = {}
    for _, row in summary.iterrows():
        scheme, dataset = str(row["scheme"]), str(row["dataset"])
        allowed.setdefault(scheme, [])
        if dataset not in allowed[scheme]:
            allowed[scheme].append(dataset)
        path = audit_root / dataset / f"{scheme}.json"
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        kind = str(payload.get("scheme_binding") or "")
        if kind:
            kinds[scheme] = kind
        declared = payload.get("binding_datasets")
        if isinstance(declared, list) and declared:
            allowed[scheme] = [str(item) for item in declared]
    # 产物缺绑定元数据时回退到 spec §2.4 的静态对应表
    for scheme, dataset in MATCHED_DATASET.items():
        if scheme in allowed and len(allowed[scheme]) == 1 and not kinds.get(scheme):
            allowed[scheme] = [dataset]
            kinds[scheme] = "hgcn_cancer"
    return {"allowed": allowed, "kind": kinds}


def scheme_table(summary: pd.DataFrame) -> pd.DataFrame:
    table = (
        summary.groupby("scheme", observed=True)
        .agg(
            n_datasets=("dataset", "nunique"),
            mean_leaky_ratio=("leaky_ratio", "mean"),
            max_leaky_ratio=("leaky_ratio", "max"),
            mean_leak_rate=("mean_leak_rate", "mean"),
        )
        .reset_index()
        .sort_values("mean_leaky_ratio", ascending=False)
    )
    return table


def field_table(rows: pd.DataFrame, top: int = 0) -> pd.DataFrame:
    table = (
        rows.groupby("field")
        .agg(
            n_entries=("field", "size"),
            n_datasets=("dataset", "nunique"),
            mean_leak_rate=("leak_rate", "mean"),
            max_leak_rate=("leak_rate", "max"),
            n_not_in_bank=("not_in_bank", "sum"),
            n_a_pipeline=("a_pipeline", "sum"),
        )
        .reset_index()
        .sort_values("mean_leak_rate", ascending=False)
    )
    if top:
        table = table.head(top)
    return table


def _heatmap(ax, values, row_labels, col_labels, *, cmap, vmin, vmax, annotate=True, fmt="{:.2f}"):
    import matplotlib.pyplot as plt

    masked = np.ma.masked_invalid(values)
    cmap = cmap.copy()
    cmap.set_bad(EMPTY)
    image = ax.imshow(masked, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels, rotation=30, ha="right", fontsize=8, color=INK_SECONDARY)
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=7, color=INK_PRIMARY)
    ax.set_xticks(np.arange(-0.5, len(col_labels), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(row_labels), 1), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=1.0)
    ax.tick_params(which="minor", length=0)
    ax.tick_params(which="major", length=0)
    if annotate:
        for i in range(values.shape[0]):
            for j in range(values.shape[1]):
                value = values[i, j]
                if not np.isfinite(value):
                    continue
                ax.text(
                    j, i, fmt.format(value),
                    ha="center", va="center", fontsize=6.5,
                    color="white" if value > 0.55 * (vmax or 1) else INK_PRIMARY,
                )
    for spine in ax.spines.values():
        spine.set_visible(False)
    return image


def plot_overview(
    summary: pd.DataFrame,
    out_path: Path,
    schemes: pd.DataFrame,
    bindings: dict | None = None,
) -> None:
    plt = setup_matplotlib()
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("leak_blue", RAMP)
    allowed = dict((bindings or {}).get("allowed") or {})
    n_datasets = int(summary["dataset"].nunique())
    n_pairs = int(len(summary))

    dataset_order = (
        summary.groupby("dataset")["leaky_ratio"].mean().sort_values(ascending=False).index.tolist()
    )
    grid = (
        summary.pivot_table(index="dataset", columns="scheme", values="leaky_ratio", observed=True)
        .reindex(index=dataset_order, columns=SCHEME_ORDER)
    )

    fig = plt.figure(figsize=(16.0, 11.0), facecolor=SURFACE)
    ax_a = fig.add_axes([0.13, 0.10, 0.40, 0.79])
    ax_cb = fig.add_axes([0.548, 0.10, 0.011, 0.79])
    ax_b = fig.add_axes([0.70, 0.10, 0.275, 0.79])
    for ax in (ax_a, ax_b):
        ax.set_facecolor(SURFACE)

    image = _heatmap(
        ax_a, grid.to_numpy(dtype=float), list(grid.index), list(grid.columns),
        cmap=cmap, vmin=0.0, vmax=1.0,
    )
    # 勾出被绑定的交叉格 + 给「未绑定」格打 ×（spec §2.4：HGCN_* 只跑其癌种）
    for j, scheme in enumerate(SCHEME_ORDER):
        permit = allowed.get(scheme)
        if not permit or len(permit) >= n_datasets:
            continue  # 泛癌种方案：全部队列都在范围内
        for i, dataset in enumerate(dataset_order):
            if dataset in permit:
                ax_a.add_patch(
                    plt.Rectangle(
                        (j - 0.5, i - 0.5), 1, 1, fill=False,
                        edgecolor=INK_PRIMARY, linewidth=1.8, zorder=5,
                    )
                )
            else:
                ax_a.text(
                    j, i, "×", ha="center", va="center",
                    fontsize=7.5, color=INK_SECONDARY, alpha=0.55, zorder=4,
                )
    ax_a.set_title(
        "A | 工作 × 癌种队列：leaky_ratio（黑框 = 绑定计入；× = §2.4 未绑定，不跑）",
        fontsize=10, color=INK_PRIMARY, pad=10,
    )
    ax_a.set_xlabel("论文方案（工作）", fontsize=9, color=INK_SECONDARY)
    ax_a.set_ylabel("队列（按平均 leaky_ratio 降序）", fontsize=9, color=INK_SECONDARY)
    cbar = fig.colorbar(image, cax=ax_cb)
    cbar.ax.tick_params(labelsize=7, colors=INK_SECONDARY)
    cbar.set_label("leaky_ratio", fontsize=8, color=INK_SECONDARY)

    order_b = schemes.sort_values("mean_leaky_ratio")
    y = np.arange(len(order_b))
    ax_b.barh(y, order_b["mean_leaky_ratio"], color=BLUE, height=0.62, zorder=2)
    dots = (
        summary.dropna(subset=["leaky_ratio"])
        .groupby("scheme", observed=True)["leaky_ratio"]
        .apply(list)
    )
    rng = np.random.default_rng(11)
    for pos, scheme in enumerate(order_b["scheme"]):
        values = dots.get(scheme, [])
        ax_b.scatter(
            values, pos + rng.uniform(-0.20, 0.20, len(values)),
            s=16, color=ORANGE, alpha=0.85, edgecolors="white", linewidths=0.8, zorder=3,
        )
    for pos, (_, row) in enumerate(order_b.iterrows()):
        scheme = str(row["scheme"])
        permit = allowed.get(scheme) or []
        scope = (
            f", 仅 {permit[0]}" if permit and len(permit) == 1 else f", n={int(row['n_datasets'])}"
        )
        ax_b.text(
            row["mean_leaky_ratio"] + 0.012, pos,
            f"{row['mean_leaky_ratio']:.2f}  (max {row['max_leaky_ratio']:.2f}{scope})",
            va="center", fontsize=7.5, color=INK_SECONDARY,
        )
    ax_b.set_yticks(y)
    ax_b.set_yticklabels(order_b["scheme"], fontsize=8.5, color=INK_PRIMARY)
    ax_b.set_xlim(0, max(0.6, float(order_b["max_leaky_ratio"].max()) * 1.45))
    ax_b.set_xlabel("leaky_ratio（泄露字段占比）", fontsize=9, color=INK_SECONDARY)
    ax_b.set_title(
        "B | 各工作泄露占比（条形 = 跨队列均值，橙点 = 单个队列）",
        fontsize=10, color=INK_PRIMARY, pad=10,
    )
    ax_b.grid(True, axis="x", alpha=0.25, color=GRID, zorder=0)
    for spine in ("top", "right", "left"):
        ax_b.spines[spine].set_visible(False)

    restricted = sum(
        1 for scheme in SCHEME_ORDER if 0 < len(allowed.get(scheme) or []) < n_datasets
    )
    fig.suptitle(
        f"H1a 泄露审计 | 10 个论文方案 × {n_datasets} 个 TCGA 队列"
        f"（spec §2.4 绑定，{n_pairs} 个组合）：t0 landmark 门控下不可得的方案字段占比（landmark_0, t0=0d）",
        fontsize=12, color=INK_PRIMARY, x=0.13, ha="left", y=0.965,
    )
    fig.text(
        0.13, 0.935,
        "leaky_ratio = 泄露字段数 / 方案字段数；leak_rate(f,D) = #(实际进入模型的值来自 t_hi > 0 槽位的患者) "
        "/ #(管线产出有效值的患者)（spec §2.1 新口径，A_pipeline 取值 + time_stats 槽位时点；"
        "无人工阈值，泄露字段 = leak_rate > 0）；"
        "灰格 = 该方案不含此字段；× = 该方案按 §2.4 不绑定该队列"
        + (f"（{restricted} 个 HGCN 工作各只跑其对应癌种）" if restricted else "")
        + "；CPTAC/MMRF 不在本阶段范围。",
        fontsize=8.5, color=INK_SECONDARY, ha="left",
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def plot_fields(
    rows: pd.DataFrame,
    table: pd.DataFrame,
    out_path: Path,
    scope_note: str = "",
) -> None:
    plt = setup_matplotlib()
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("leak_blue", RAMP)
    fields = list(dict.fromkeys(table["field"]))
    grid = (
        rows.groupby(["field", "scheme"])["leak_rate"].mean().unstack()
        .reindex(index=fields, columns=SCHEME_ORDER)
    )
    nib = rows.groupby("field")["not_in_bank"].mean()

    fig = plt.figure(figsize=(16.0, max(5.6, 0.42 * len(fields) + 2.8)), facecolor=SURFACE)
    height_frac = 0.78
    ax_a = fig.add_axes([0.235, 0.09, 0.275, height_frac])
    ax_cb = fig.add_axes([0.518, 0.09, 0.011, height_frac])
    ax_b = fig.add_axes([0.675, 0.09, 0.30, height_frac])
    for ax in (ax_a, ax_b):
        ax.set_facecolor(SURFACE)

    labels = [f"{name} †" if nib.get(name, 0) >= 0.5 else name for name in fields]
    image = _heatmap(
        ax_a, grid.to_numpy(dtype=float), labels, list(SCHEME_ORDER),
        cmap=cmap, vmin=0.0, vmax=1.0,
    )
    ax_a.set_title("A | 逐字段平均 leak_rate：字段 × 工作", fontsize=10, color=INK_PRIMARY, pad=10)
    ax_a.set_xlabel("论文方案（工作）", fontsize=9, color=INK_SECONDARY)
    ax_a.set_ylabel("方案字段", fontsize=9, color=INK_SECONDARY)
    cbar = fig.colorbar(image, cax=ax_cb)
    cbar.ax.tick_params(labelsize=7, colors=INK_SECONDARY)
    cbar.set_label("平均 leak_rate", fontsize=8, color=INK_SECONDARY)

    order_b = table.sort_values("mean_leak_rate")
    y = np.arange(len(order_b))
    colors = [ORANGE if value >= 0.5 else BLUE for value in order_b["mean_leak_rate"]]
    ax_b.barh(y, order_b["mean_leak_rate"], color=colors, height=0.6, zorder=2)
    for pos, (_, row) in enumerate(order_b.iterrows()):
        ax_b.text(
            row["mean_leak_rate"] + 0.012, pos,
            f"{row['mean_leak_rate']:.3f}  (max {row['max_leak_rate']:.2f}, {int(row['n_datasets'])} 队列, "
            f"不在 bank {int(row['n_not_in_bank'])}/{int(row['n_entries'])})",
            va="center", fontsize=7, color=INK_SECONDARY,
        )
    ax_b.set_yticks(y)
    ax_b.set_yticklabels(order_b["field"], fontsize=7.5, color=INK_PRIMARY)
    ax_b.set_xlim(0, max(0.5, float(order_b["max_leak_rate"].max()) * 1.55))
    ax_b.set_xlabel("跨队列平均 leak_rate", fontsize=9, color=INK_SECONDARY)
    ax_b.set_title("B | 字段级泄露强度（橙 = 平均 leak_rate ≥ 0.5）", fontsize=10, color=INK_PRIMARY, pad=10)
    ax_b.grid(True, axis="x", alpha=0.25, color=GRID, zorder=0)
    for spine in ("top", "right", "left"):
        ax_b.spines[spine].set_visible(False)

    fig.suptitle(
        f"H1a 泄露审计 | 逐字段泄露率（landmark_0, t0=0d）{scope_note}",
        fontsize=12, color=INK_PRIMARY, x=0.235, ha="left", y=0.965,
    )
    fig.text(
        0.235, 0.935,
        f"† = 多数队列里该字段不在 Field Bank（rawdata_stats/{{dataset}}/landmark_0/kept_fields.json；"
        f"≠ 不进模型——审计字段全部来自方案模板，† 字段同样进入模型）。"
        f"leak_rate = 值来源槽位 t_hi > 0 的患者占比（分母 = 管线产出有效值的患者）。"
        f"仅展示平均 leak_rate 最高的 {len(fields)} 个字段。灰格 = 该方案不含此字段 / 未绑定该队列。",
        fontsize=8, color=INK_SECONDARY, ha="left",
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audit_root = Path(args.audit_root)
    summary_path = Path(args.summary) if args.summary else audit_root / "leak_audit_summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"missing summary CSV: {summary_path}（先跑 scripts/run_leak_audit.py）")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = load_summary(summary_path)
    rows = load_field_rows(audit_root, summary)
    bindings = load_bindings(audit_root, summary)
    scheme_stats = scheme_table(summary)
    field_stats = field_table(rows, top=int(args.top_fields))

    scheme_stats.to_csv(out_dir / "leak_audit_scheme_mean.csv", index=False, float_format="%.6f")
    field_stats.to_csv(out_dir / "leak_audit_field_mean.csv", index=False, float_format="%.6f")

    allowed = bindings["allowed"]
    print(f"summary: {summary_path}  ({len(summary)} 行 = {summary['dataset'].nunique()} 队列 × {summary['scheme'].nunique()} 方案)")
    print(f"字段明细: {len(rows)} 条 (dataset, scheme, field)")
    print("绑定（spec §2.4）:")
    for scheme in SCHEME_ORDER:
        permit = allowed.get(scheme) or []
        print(
            f"  {scheme:16s} {bindings['kind'].get(scheme, '?'):16s} "
            f"{len(permit)} 队列" + (f" → {permit[0]}" if len(permit) == 1 else "")
        )
    print()
    print("各工作泄露占比（按 mean leaky_ratio 降序）:")
    for _, row in scheme_stats.iterrows():
        print(
            f"  {str(row['scheme']):16s} mean={row['mean_leaky_ratio']:.3f} "
            f"max={row['max_leaky_ratio']:.3f} mean_leak_rate={row['mean_leak_rate']:.3f} "
            f"n={int(row['n_datasets'])}"
        )
    print()
    print("泄露最严重的字段（按跨队列 mean leak_rate 降序）:")
    for _, row in field_stats.head(8).iterrows():
        print(
            f"  {str(row['field']):52s} mean={row['mean_leak_rate']:.3f} max={row['max_leak_rate']:.3f} "
            f"not_in_bank={int(row['n_not_in_bank'])}/{int(row['n_entries'])}"
        )

    overview_path = out_dir / "leak_audit_overview.png"
    fields_path = out_dir / "leak_audit_fields.png"
    scope_note = f"（{summary['dataset'].nunique()} 个 TCGA 队列 × §2.4 绑定）"
    plot_overview(summary, overview_path, scheme_stats, bindings)
    plot_fields(rows, field_stats, fields_path, scope_note=scope_note)
    print()
    print(f"✅ {overview_path}")
    print(f"✅ {fields_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
