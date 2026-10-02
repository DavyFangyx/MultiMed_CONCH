#!/usr/bin/env python3
"""Test_1a 单字段泄露对照（时间轴链动机 + Test_2b 机制解释）。

规格：z_notes/Test_series_spec.md §5bis；范围：执行日志 R13（仅 n_event >= 100 的 15 个主集）。
本步纯分析，**不新增训练**。

两臂（同患者集，唯一差异 = 取值 mask 状态）：
  - t0 臂：results/univariate/prompt/landmark_0/{dataset}/mlp_clinic_flatten/field_cindex.csv
  - off 臂：results/univariate_raw/univariate/prompt/landmark_none/{dataset}/mlp_clinic_flatten/field_cindex.csv
  - Δc_field = c(off) − c(t0)

数据集名单不硬编码：从 results/Test_0_dataset_availability/manifest.csv 的 n_event 派生
（R13：n_event >= 100），veriyfier 与 scripts/s5b_univariate_enqueue.py 同口径。

leak_rate 列（Test_2a 审计）：
  - 来源 results/leak_audit/{dataset}/{scheme}.json（scheme = G1_{md5(field_idx)}，逐字段条目）；
    该逐字段审计（用户新 Test_2a）尚未运行时，leak_rate 列留空并标 pending_test_2a，
    脚本可在审计出数后直接重跑填列（无需改代码）。
  - 「理论上能动组合 Δc 的字段清单」= leak_rate > --leak_threshold 且 |Δc_field| >= --delta_threshold。

输出（默认 results_display/Test_1a_field_level/；gitignore 产物，不入库）：
  Test_1a_field_delta.csv       逐 (dataset, field)：c_t0/c_off/Δc/leak_rate（待填）
  Test_1a_dataset_summary.csv   逐 dataset：字段数、Δc 均值/中位/极值、非平凡占比、Top ± 字段
  Test_1a_field_summary.csv     逐 field 跨数据集：Δc 均值/中位/极值、符号计数
  Test_1a_delta_matrix.csv      dataset × field Δc 对齐矩阵
  Test_1a_influential_fields.csv「能动字段清单」（leak 未出数时为空表，列齐全）
  Test_1a_metrics.json          头条量化数字 + 覆盖度（pending 数据集/字段）
  Test_1a_c_off_vs_t0.png       两臂 c-index 散点（对角线 = 无差异）
  Test_1a_delta_distribution.png  Δc 分布（全体 + 逐数据集条带）
  Test_1a_delta_boxplot.png      逐数据集 Δc 箱线（按 n_event 排序）
  Test_1a_delta_by_mask_group.png Δc 分组（取值未改动 = 噪声本底 vs 被 mask 改动）
  Test_1a_audit.json             --audit 的抽查记录
  Test_1a_leak_vs_delta.png      x=leak_rate, y=Δc_field（leak 未出数时跳过并记 pending）

可复跑：同输入重跑 diff=0（无时间戳、固定排序、固定数值格式、固定随机种子）。

用法：
  python3 results_display/scripts/Test_1a_field_level.py              # 生成全部产物
  python3 results_display/scripts/Test_1a_field_level.py --audit      # 生成 + 3 组抽查
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "mplconfig"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CSV_NAME = "field_cindex.csv"
DEFAULT_ANALYZER = "mlp_clinic_flatten"
DEFAULT_T0_ROOT = REPO_ROOT / "results" / "univariate" / "prompt" / "landmark_0"
DEFAULT_OFF_ROOT = (
    REPO_ROOT / "results" / "univariate_raw" / "univariate" / "prompt" / "landmark_none"
)
DEFAULT_MANIFEST = REPO_ROOT / "results" / "Test_0_dataset_availability" / "manifest.csv"
DEFAULT_EVENT_SUMMARY = REPO_ROOT / "rawdata_stats" / "_shared" / "event_summary.csv"
DEFAULT_LEAK_ROOT = REPO_ROOT / "results" / "leak_audit"
DEFAULT_OUT_DIR = REPO_ROOT / "results_display" / "Test_1a_field_level"
MIN_EVENT = 100  # R13

# ---- 视觉常量（与 Test_1b_dataset_cindex.py / Test_2b_delta_report.py 同一套）----
INK = "#0b0b0b"
MUTED = "#898781"
BASELINE = "#c3c2b7"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"
COL_POS = "#e34948"  # Δc > 0：off 臂更高（泄露可能高估）
COL_NEG = "#2a78d6"  # Δc < 0
COL_NEUTRAL = "#898781"

LEAK_STATUS_PENDING = "pending_test_2a"
LEAK_STATUS_OK = "ok"
LEAK_STATUS_UNDEFINED = "undefined"


# --------------------------------------------------------------------------- 输入
def load_manifest(path: Path) -> dict[str, dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {row["dataset"]: row for row in csv.DictReader(handle)}


def load_event_summary(path: Path) -> dict[str, dict]:
    if not Path(path).exists():
        return {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {row["dataset"]: row for row in csv.DictReader(handle)}


def load_value_diff(dataset: str, off_root: Path) -> dict[str, dict]:
    """raw 变体取值差异（构建期落盘在 raw bank 目录）：{field: {changed_cells, timed_family}}。

    用途：标出"取值确实被 mask 改动"的字段（mask_affected）——未改动的字段构成
    编码/训练抖动对照组（噪声本底），Δc 的可解释性以它为准。
    """
    # raw bank 目录与 off 臂结果目录同源于 outputs/_raw（见 scripts/s5b_build_raw_field_bank.py）
    path = (
        REPO_ROOT / "outputs" / "_raw" / dataset / "field_bank" / "prompt" / "landmark_none"
        / "raw_value_diff.json"
    )
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for item in payload.get("fields") or []:
        name = str(item.get("field") or "").strip()
        if name:
            out[name] = {
                "changed_cells": int(float(item.get("changed_cells") or 0)),
                "timed_family": bool(item.get("timed_family")),
            }
    return out


def main_datasets(manifest: dict[str, dict], events: dict[str, dict]) -> list[str]:
    """R13 主集：n_event >= 100 的 TCGA 数据集（来源 manifest，回退 event_summary）。"""
    table = {}
    for name, row in manifest.items():
        if str(name).startswith(("TCGA-", "TCGA_")) and str(row.get("n_event") or "").strip():
            table[name] = int(float(row["n_event"]))
    if not table:
        for name, row in events.items():
            if str(name).startswith(("TCGA-", "TCGA_")) and str(row.get("n_event") or "").strip():
                table[name] = int(float(row["n_event"]))
    if not table:
        raise FileNotFoundError("no n_event source (manifest / event_summary)")
    return sorted(name for name, n in table.items() if int(n) >= MIN_EVENT)


def read_field_rows(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def index_field_rows(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for row in rows:
        name = str(row.get("field") or "").strip()
        if not name:
            continue
        out[name] = row
    return out


# --------------------------------------------------------------------------- leak_rate
def scheme_for_field_idx(field_idx: int) -> str:
    from greedy.embeddings import subset_scheme_name

    return subset_scheme_name([int(field_idx)])


def load_leak_rates(leak_root: Path, dataset: str, schemes: list[str]) -> dict[str, dict]:
    """{scheme: {field: {leak_rate, leak_rate_undefined, family, ...}}}；文件缺失返回空。"""
    out: dict[str, dict] = {}
    for scheme in schemes:
        path = Path(leak_root) / dataset / f"{scheme}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        per_field = {}
        for item in payload.get("fields") or []:
            name = str(item.get("field") or "").strip()
            if name:
                per_field[name] = item
        out[scheme] = per_field
    return out


def timed_family_for(field: str) -> str:
    try:
        from discovery.landmark import timed_family_for_field

        family, _ = timed_family_for_field(field)
        if family:
            return family
    except Exception:
        pass
    head = str(field).split(".")[0].split("[")[0]
    return head or str(field)


# --------------------------------------------------------------------------- 取值
def assemble(
    datasets: list[str],
    *,
    t0_root: Path,
    off_root: Path,
    analyzer: str,
    manifest: dict[str, dict],
    events: dict[str, dict],
    leak_root: Path,
) -> tuple[list[dict], list[dict], dict]:
    """返回 (field_rows, pending, coverage)。pending 记 (dataset, 原因)。"""
    rows: list[dict] = []
    pending: list[dict] = []
    n_field_rows_t0 = 0
    n_field_rows_off = 0
    n_leak_available = 0
    n_field_pairs = 0
    for dataset in datasets:
        t0_path = Path(t0_root) / dataset / analyzer / CSV_NAME
        off_path = Path(off_root) / dataset / analyzer / CSV_NAME
        if not t0_path.exists():
            pending.append({"dataset": dataset, "reason": "missing_t0_csv", "path": str(t0_path)})
            continue
        if not off_path.exists():
            pending.append({"dataset": dataset, "reason": "missing_off_csv", "path": str(off_path)})
            continue
        t0_rows = index_field_rows(read_field_rows(t0_path))
        off_rows = index_field_rows(read_field_rows(off_path))
        n_field_rows_t0 += len(t0_rows)
        n_field_rows_off += len(off_rows)
        idx_to_field = {}
        for name, row in t0_rows.items():
            try:
                idx_to_field[int(row["field_idx"])] = name
            except (KeyError, TypeError, ValueError):
                pass
        schemes = [scheme_for_field_idx(i) for i in sorted(idx_to_field)]
        leak = load_leak_rates(leak_root, dataset, schemes)
        value_diff = load_value_diff(dataset, off_root)
        ev = events.get(dataset, {})
        man = manifest.get(dataset, {})
        n_event = int(float(ev.get("n_event") or man.get("n_event") or 0))
        n_patients = int(float(ev.get("n_patients") or man.get("n_patients") or 0))
        event_rate = ev.get("event_rate") or man.get("event_rate") or ""
        for idx in sorted(idx_to_field):
            field = idx_to_field[idx]
            t0 = t0_rows.get(field)
            off = off_rows.get(field)
            if t0 is None or str(t0.get("status") or "").strip() not in ("", "ok"):
                pending.append({"dataset": dataset, "field": field, "reason": "t0_not_ok"})
                continue
            if off is None:
                pending.append({"dataset": dataset, "field": field, "reason": "off_missing_field"})
                continue
            if str(off.get("status") or "").strip() not in ("", "ok"):
                pending.append(
                    {"dataset": dataset, "field": field, "reason": f"off_status={off.get('status')}"}
                )
                continue
            n_field_pairs += 1
            c_t0 = float(t0["c_index_mean"])
            c_off = float(off["c_index_mean"])
            scheme = scheme_for_field_idx(idx)
            leak_item = (leak.get(scheme) or {}).get(field)
            if leak_item is None:
                leak_rate = ""
                leak_status = LEAK_STATUS_PENDING
            elif leak_item.get("leak_rate_undefined"):
                leak_rate = ""
                leak_status = LEAK_STATUS_UNDEFINED
            else:
                leak_rate = float(leak_item["leak_rate"])
                leak_status = LEAK_STATUS_OK
                n_leak_available += 1
            rows.append(
                {
                    "dataset": dataset,
                    "field": field,
                    "field_idx": int(idx),
                    "scheme": scheme,
                    "family": (leak_item or {}).get("family") or timed_family_for(field),
                    "timed_family": (value_diff.get(field) or {}).get("timed_family"),
                    "mask_affected": (
                        None if not value_diff
                        else bool((value_diff.get(field) or {}).get("changed_cells", 0) > 0)
                    ),
                    "value_cells_changed": (
                        None if not value_diff
                        else int((value_diff.get(field) or {}).get("changed_cells", 0))
                    ),
                    "n_event": n_event,
                    "n_patients": n_patients,
                    "event_rate": event_rate,
                    "c_t0": c_t0,
                    "c_t0_std": float(t0.get("c_index_std") or 0.0),
                    "c_off": c_off,
                    "c_off_std": float(off.get("c_index_std") or 0.0),
                    "delta_c": c_off - c_t0,
                    "leak_rate": leak_rate,
                    "leak_rate_status": leak_status,
                }
            )
    coverage = {
        "n_datasets": len(datasets),
        "n_field_pairs": n_field_pairs,
        "n_t0_field_rows": n_field_rows_t0,
        "n_off_field_rows": n_field_rows_off,
        "n_leak_available": n_leak_available,
        "n_pending": len(pending),
        "leak_rate_status": LEAK_STATUS_OK if n_leak_available else LEAK_STATUS_PENDING,
    }
    return rows, pending, coverage


# --------------------------------------------------------------------------- 汇总
def fmt(x) -> str:
    if x == "" or x is None:
        return ""
    return f"{float(x):.6f}"


def noise_floor_stats(rows: list[dict], delta_threshold: float) -> dict:
    """按取值是否被 mask 改动分组：未改动组 = 编码/训练抖动对照组（Δc 噪声本底）。

    两臂的嵌入由两次独立构建产生（raw bank vs lm0 bank），CONCH 文本编码对全局 padding 长度
    不敏感度有限，故"取值未改动"的字段也可能有非零 Δc。该组的 Δc 分布给出本底，
    只有显著超过本底的 Δc 才能归因于 mask（取值口径）。
    """
    groups = {}
    for label, subset in (
        ("mask_unaffected", [r for r in rows if r.get("mask_affected") is False]),
        ("mask_affected", [r for r in rows if r.get("mask_affected") is True]),
        ("unknown", [r for r in rows if r.get("mask_affected") is None]),
    ):
        if not subset:
            continue
        arr = np.asarray([r["delta_c"] for r in subset], dtype=float)
        groups[label] = {
            "n_fields": len(subset),
            "delta_mean": float(arr.mean()),
            "delta_median": float(np.median(arr)),
            "delta_std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
            "delta_min": float(arr.min()),
            "delta_max": float(arr.max()),
            "abs_delta_p90": float(np.quantile(np.abs(arr), 0.9)),
            "abs_delta_max": float(np.abs(arr).max()),
            "share_abs_ge_threshold": float(np.mean(np.abs(arr) >= delta_threshold)),
        }
    return groups


def summarize_datasets(rows: list[dict], delta_threshold: float) -> list[dict]:
    out = []
    by_ds: dict[str, list[dict]] = {}
    for row in rows:
        by_ds.setdefault(row["dataset"], []).append(row)
    for dataset in sorted(by_ds, key=lambda d: (-max(r["n_event"] for r in by_ds[d]), d)):
        items = sorted(by_ds[dataset], key=lambda r: r["field"])
        deltas = [r["delta_c"] for r in items]
        arr = np.asarray(deltas, dtype=float)
        n_nontrivial = int(np.sum(np.abs(arr) >= delta_threshold))
        top_pos = max(items, key=lambda r: (r["delta_c"], r["field"]))
        top_neg = min(items, key=lambda r: (r["delta_c"], r["field"]))
        out.append(
            {
                "dataset": dataset,
                "n_event": items[0]["n_event"],
                "n_patients": items[0]["n_patients"],
                "event_rate": items[0]["event_rate"],
                "n_fields": len(items),
                "delta_mean": float(arr.mean()),
                "delta_median": float(np.median(arr)),
                "delta_min": float(arr.min()),
                "delta_max": float(arr.max()),
                "n_abs_ge_threshold": n_nontrivial,
                "share_abs_ge_threshold": n_nontrivial / len(items),
                "n_delta_positive": int(np.sum(arr > 0)),
                "top_positive_field": top_pos["field"],
                "top_positive_delta": top_pos["delta_c"],
                "top_negative_field": top_neg["field"],
                "top_negative_delta": top_neg["delta_c"],
            }
        )
    return out


def summarize_fields(rows: list[dict], delta_threshold: float) -> list[dict]:
    by_field: dict[str, list[dict]] = {}
    for row in rows:
        by_field.setdefault(row["field"], []).append(row)
    out = []
    for field in sorted(by_field):
        items = by_field[field]
        arr = np.asarray([r["delta_c"] for r in items], dtype=float)
        out.append(
            {
                "field": field,
                "family": items[0]["family"],
                "n_datasets": len(items),
                "delta_mean": float(arr.mean()),
                "delta_median": float(np.median(arr)),
                "delta_min": float(arr.min()),
                "delta_max": float(arr.max()),
                "n_positive": int(np.sum(arr > 0)),
                "n_negative": int(np.sum(arr < 0)),
                "n_abs_ge_threshold": int(np.sum(np.abs(arr) >= delta_threshold)),
                "leak_rate_max": (
                    fmt(max(float(r["leak_rate"]) for r in items))
                    if all(str(r["leak_rate"]) not in ("", "None") for r in items)
                    else ""
                ),
            }
        )
    out.sort(key=lambda r: (-abs(r["delta_mean"]), r["field"]))
    return out


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: (fmt(row.get(col)) if isinstance(row.get(col), float) else row.get(col, "")) for col in columns})


FIELD_COLUMNS = [
    "dataset", "field", "field_idx", "scheme", "family", "timed_family", "mask_affected",
    "value_cells_changed", "n_event", "n_patients", "event_rate",
    "c_t0", "c_t0_std", "c_off", "c_off_std", "delta_c", "leak_rate", "leak_rate_status",
]
DATASET_COLUMNS = [
    "dataset", "n_event", "n_patients", "event_rate", "n_fields", "delta_mean", "delta_median",
    "delta_min", "delta_max", "n_abs_ge_threshold", "share_abs_ge_threshold", "n_delta_positive",
    "top_positive_field", "top_positive_delta", "top_negative_field", "top_negative_delta",
]
FIELD_SUMMARY_COLUMNS = [
    "field", "family", "n_datasets", "delta_mean", "delta_median", "delta_min", "delta_max",
    "n_positive", "n_negative", "n_abs_ge_threshold", "leak_rate_max",
]
INFLUENTIAL_COLUMNS = [
    "dataset", "field", "field_idx", "scheme", "family", "n_event", "leak_rate", "delta_c",
    "abs_delta_c", "leak_threshold", "delta_threshold",
]


# --------------------------------------------------------------------------- 图
def _style_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(BASELINE)
    ax.grid(True, color=GRIDLINE, linewidth=0.6, alpha=0.9)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=8)


def plot_c_off_vs_t0(rows: list[dict], out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 6.0), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style_axes(ax)
    xs = np.asarray([r["c_t0"] for r in rows], dtype=float)
    ys = np.asarray([r["c_off"] for r in rows], dtype=float)
    ds = np.asarray([r["delta_c"] for r in rows], dtype=float)
    lo = float(min(xs.min(), ys.min())) - 0.01
    hi = float(max(xs.max(), ys.max())) + 0.01
    ax.plot([lo, hi], [lo, hi], color=BASELINE, linewidth=1.0, zorder=1)
    colors = [COL_POS if d > 0 else (COL_NEG if d < 0 else COL_NEUTRAL) for d in ds]
    ax.scatter(xs, ys, s=16, c=colors, alpha=0.75, linewidths=0, zorder=3)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("c(t0)  mask on", color=INK, fontsize=9)
    ax.set_ylabel("c(off)  mask off", color=INK, fontsize=9)
    n_up = int(np.sum(ds > 0))
    n_dn = int(np.sum(ds < 0))
    ax.set_title(
        f"Test_1a single-field c-index: mask off vs t0  (n={len(rows)} pairs)\n"
        f"red: Δc>0 x{n_up}   blue: Δc<0 x{n_dn}   grey line: no change",
        color=INK, fontsize=10, loc="left",
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)


def plot_delta_distribution(rows: list[dict], out_path: Path, delta_threshold: float) -> None:
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(9.0, 7.2), dpi=160, gridspec_kw={"height_ratios": [2, 3]}
    )
    fig.patch.set_facecolor(SURFACE)
    ds = np.asarray([r["delta_c"] for r in rows], dtype=float)
    _style_axes(ax1)
    bins = np.linspace(ds.min() - 0.005, ds.max() + 0.005, 41)
    ax1.hist(ds, bins=bins, color=COL_NEG, alpha=0.85, edgecolor=SURFACE, linewidth=0.4)
    for x in (-delta_threshold, delta_threshold):
        ax1.axvline(x, color=BASELINE, linewidth=1.0, linestyle="--")
    ax1.axvline(0.0, color=INK, linewidth=1.0)
    ax1.set_ylabel("fields", color=INK, fontsize=9)
    ax1.set_title(
        f"Δc_field = c(off) − c(t0) distribution  (n={len(rows)})\n"
        f"median={np.median(ds):+.4f}  mean={ds.mean():+.4f}  "
        f"share |Δc|>={delta_threshold:.3f}: {float(np.mean(np.abs(ds) >= delta_threshold)):.1%}",
        color=INK, fontsize=10, loc="left",
    )
    # 逐数据集条带
    _style_axes(ax2)
    datasets = sorted({r["dataset"] for r in rows}, key=lambda d: (-max(r["n_event"] for r in rows if r["dataset"] == d), d))
    for i, dataset in enumerate(datasets):
        vals = np.asarray([r["delta_c"] for r in rows if r["dataset"] == dataset], dtype=float)
        ax2.scatter(vals, np.full_like(vals, i, dtype=float), s=9, color=COL_NEG, alpha=0.6, linewidths=0)
        ax2.plot([np.median(vals)] * 2, [i - 0.32, i + 0.32], color=INK, linewidth=1.4)
    ax2.axvline(0.0, color=INK, linewidth=1.0)
    for x in (-delta_threshold, delta_threshold):
        ax2.axvline(x, color=BASELINE, linewidth=1.0, linestyle="--")
    ax2.set_yticks(range(len(datasets)))
    ax2.set_yticklabels(datasets)
    ax2.invert_yaxis()
    ax2.set_xlabel("Δc_field", color=INK, fontsize=9)
    ax2.set_title("per dataset (sorted by n_event desc; black bar = median)", color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)


def plot_delta_boxplot(rows: list[dict], out_path: Path) -> None:
    datasets = sorted(
        {r["dataset"] for r in rows},
        key=lambda d: (-max(r["n_event"] for r in rows if r["dataset"] == d), d),
    )
    fig, ax = plt.subplots(figsize=(9.0, 5.2), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style_axes(ax)
    data = [[r["delta_c"] for r in rows if r["dataset"] == d] for d in datasets]
    bp = ax.boxplot(
        data, vert=False, widths=0.6, patch_artist=True,
        medianprops={"color": INK, "linewidth": 1.4},
        boxprops={"facecolor": "#cde2fb", "edgecolor": BASELINE, "linewidth": 0.8},
        whiskerprops={"color": BASELINE}, capprops={"color": BASELINE},
        flierprops={"marker": "o", "markersize": 3, "markerfacecolor": COL_POS, "markeredgecolor": "none", "alpha": 0.7},
    )
    del bp
    ax.axvline(0.0, color=INK, linewidth=1.0)
    ax.set_yticks(range(1, len(datasets) + 1))
    ax.set_yticklabels(datasets)
    ax.invert_yaxis()
    ax.set_xlabel("Δc_field = c(off) − c(t0)", color=INK, fontsize=9)
    ax.set_title("Test_1a Δc_field by dataset (R13 main set, n_event >= 100)", color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)


def plot_delta_by_mask_group(rows: list[dict], out_path: Path, delta_threshold: float) -> None:
    """Δc 按"取值是否被 mask 改动"分组：未改动组 = 编码/训练抖动本底。"""
    groups = [
        ("mask unaffected\n(value unchanged, noise floor)", [r["delta_c"] for r in rows if r.get("mask_affected") is False], COL_NEUTRAL),
        ("mask affected\n(value changed)", [r["delta_c"] for r in rows if r.get("mask_affected") is True], COL_NEG),
    ]
    groups = [(label, vals, color) for label, vals, color in groups if vals]
    if not groups:
        return
    fig, ax = plt.subplots(figsize=(7.6, 4.6), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style_axes(ax)
    for i, (label, vals, color) in enumerate(groups):
        arr = np.asarray(vals, dtype=float)
        x = np.full_like(arr, i, dtype=float) + np.linspace(-0.12, 0.12, len(arr))
        ax.scatter(x, arr, s=14, color=color, alpha=0.7, linewidths=0)
        ax.plot([i - 0.25, i + 0.25], [np.median(arr)] * 2, color=INK, linewidth=1.6)
    ax.axhline(0.0, color=INK, linewidth=1.0)
    for y in (-delta_threshold, delta_threshold):
        ax.axhline(y, color=BASELINE, linewidth=1.0, linestyle="--")
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([f"{label}\nn={len(vals)}" for label, vals, _ in groups])
    ax.set_ylabel("Δc_field", color=INK, fontsize=9)
    ax.set_title("Test_1a Δc by mask effect (dashed: ±threshold; black bar: median)", color=INK, fontsize=10, loc="left")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)


def plot_leak_vs_delta(rows: list[dict], out_path: Path, delta_threshold: float, leak_threshold: float) -> bool:
    usable = [r for r in rows if str(r["leak_rate"]) not in ("", "None")]
    if not usable:
        return False
    fig, ax = plt.subplots(figsize=(7.2, 5.6), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    _style_axes(ax)
    xs = np.asarray([float(r["leak_rate"]) for r in usable], dtype=float)
    ys = np.asarray([r["delta_c"] for r in usable], dtype=float)
    colors = [COL_POS if d > 0 else (COL_NEG if d < 0 else COL_NEUTRAL) for d in ys]
    ax.scatter(xs, ys, s=16, c=colors, alpha=0.75, linewidths=0)
    ax.axhline(0.0, color=INK, linewidth=1.0)
    for y in (-delta_threshold, delta_threshold):
        ax.axhline(y, color=BASELINE, linewidth=1.0, linestyle="--")
    ax.axvline(leak_threshold, color=BASELINE, linewidth=1.0, linestyle="--")
    n_inf = sum(1 for r in usable if float(r["leak_rate"]) > leak_threshold and abs(r["delta_c"]) >= delta_threshold)
    ax.set_xlabel("leak_rate (Test_2a)", color=INK, fontsize=9)
    ax.set_ylabel("Δc_field", color=INK, fontsize=9)
    ax.set_title(
        f"Test_1a leak_rate × Δc_field  (n={len(usable)}; influential >{leak_threshold:.2f} & |Δc|>={delta_threshold:.3f}: {n_inf})",
        color=INK, fontsize=10, loc="left",
    )
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)
    return True


# --------------------------------------------------------------------------- 抽查
def run_audit(rows: list[dict], *, t0_root: Path, off_root: Path, analyzer: str, seed: int, n: int) -> list[dict]:
    rng = random.Random(seed)
    eligible = [r for r in rows if r["n_event"] >= MIN_EVENT]
    picks = rng.sample(eligible, min(n, len(eligible)))
    checks = []
    for pick in sorted(picks, key=lambda r: (r["dataset"], r["field_idx"])):
        ds, field = pick["dataset"], pick["field"]
        t0_rows = index_field_rows(read_field_rows(Path(t0_root) / ds / analyzer / CSV_NAME))
        off_rows = index_field_rows(read_field_rows(Path(off_root) / ds / analyzer / CSV_NAME))
        t0_val = float(t0_rows[field]["c_index_mean"])
        off_val = float(off_rows[field]["c_index_mean"])
        manual = off_val - t0_val
        record = {
            "dataset": ds,
            "field": field,
            "field_idx": pick["field_idx"],
            "c_t0": t0_val,
            "c_off": off_val,
            "delta_c_from_row": pick["delta_c"],
            "delta_c_manual": manual,
            "match": abs(pick["delta_c"] - manual) <= 1e-12,
        }
        checks.append(record)
        print(
            f"[audit] {ds} idx={pick['field_idx']} {field}: "
            f"c_t0={t0_val:.4f} c_off={off_val:.4f} Δc={manual:+.4f} "
            f"{'OK' if record['match'] else 'MISMATCH'}"
        )
    return checks


# --------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--t0_root", default=str(DEFAULT_T0_ROOT))
    parser.add_argument("--off_root", default=str(DEFAULT_OFF_ROOT))
    parser.add_argument("--analyzer", default=DEFAULT_ANALYZER)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--event_summary", default=str(DEFAULT_EVENT_SUMMARY))
    parser.add_argument("--leak_root", default=str(DEFAULT_LEAK_ROOT))
    parser.add_argument("--out_dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--delta_threshold", type=float, default=0.01, help="|Δc| 视为非平凡的阈值")
    parser.add_argument("--leak_threshold", type=float, default=0.05, help="leak_rate 视为高的阈值")
    parser.add_argument("--audit", action="store_true", help="生成后做 3 组抽查（规格 §5bis 验收）")
    parser.add_argument("--audit_seed", type=int, default=20261002)
    parser.add_argument("--audit_n", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(Path(args.manifest))
    events = load_event_summary(Path(args.event_summary))
    datasets = main_datasets(manifest, events)
    rows, pending, coverage = assemble(
        datasets,
        t0_root=Path(args.t0_root),
        off_root=Path(args.off_root),
        analyzer=args.analyzer,
        manifest=manifest,
        events=events,
        leak_root=Path(args.leak_root),
    )
    if not rows:
        print("[Test_1a] no comparable (dataset, field) pairs yet — off arm still running?")
        print(f"[Test_1a] pending: {len(pending)}")
        return 1

    ds_summary = summarize_datasets(rows, args.delta_threshold)
    field_summary = summarize_fields(rows, args.delta_threshold)

    # 能动字段清单（leak_rate 未出数时为空表，列齐）
    influential = []
    for row in rows:
        if str(row["leak_rate"]) in ("", "None"):
            continue
        if float(row["leak_rate"]) > args.leak_threshold and abs(row["delta_c"]) >= args.delta_threshold:
            item = dict(row)
            item["abs_delta_c"] = abs(row["delta_c"])
            item["leak_threshold"] = args.leak_threshold
            item["delta_threshold"] = args.delta_threshold
            influential.append(item)
    influential.sort(key=lambda r: (-float(r["leak_rate"]), -r["abs_delta_c"], r["dataset"], r["field"]))

    write_csv(out_dir / "Test_1a_field_delta.csv", rows, FIELD_COLUMNS)
    write_csv(out_dir / "Test_1a_dataset_summary.csv", ds_summary, DATASET_COLUMNS)
    write_csv(out_dir / "Test_1a_field_summary.csv", field_summary, FIELD_SUMMARY_COLUMNS)
    write_csv(out_dir / "Test_1a_influential_fields.csv", influential, INFLUENTIAL_COLUMNS)

    # dataset × field 矩阵
    datasets_present = sorted({r["dataset"] for r in rows})
    field_order = [r["field"] for r in field_summary]
    with (out_dir / "Test_1a_delta_matrix.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dataset"] + field_order)
        lookup = {(r["dataset"], r["field"]): r["delta_c"] for r in rows}
        for dataset in datasets_present:
            writer.writerow([dataset] + [fmt(lookup.get((dataset, f), "")) for f in field_order])

    plot_c_off_vs_t0(rows, out_dir / "Test_1a_c_off_vs_t0.png")
    plot_delta_distribution(rows, out_dir / "Test_1a_delta_distribution.png", args.delta_threshold)
    plot_delta_boxplot(rows, out_dir / "Test_1a_delta_boxplot.png")
    plot_delta_by_mask_group(rows, out_dir / "Test_1a_delta_by_mask_group.png", args.delta_threshold)
    leak_plotted = plot_leak_vs_delta(
        rows, out_dir / "Test_1a_leak_vs_delta.png", args.delta_threshold, args.leak_threshold
    )

    deltas = np.asarray([r["delta_c"] for r in rows], dtype=float)
    metrics = {
        "scope": f"R13 main set (n_event >= {MIN_EVENT})",
        "n_datasets_expected": len(datasets),
        "n_datasets_covered": len({r["dataset"] for r in rows}),
        "n_field_pairs": coverage["n_field_pairs"],
        "n_pending": coverage["n_pending"],
        "pending_reasons": sorted({p["reason"] for p in pending}),
        "delta_mean": float(deltas.mean()),
        "delta_median": float(np.median(deltas)),
        "delta_min": float(deltas.min()),
        "delta_max": float(deltas.max()),
        "n_delta_positive": int(np.sum(deltas > 0)),
        "n_delta_negative": int(np.sum(deltas < 0)),
        "n_delta_zero": int(np.sum(deltas == 0)),
        "delta_threshold": args.delta_threshold,
        "n_abs_delta_ge_threshold": int(np.sum(np.abs(deltas) >= args.delta_threshold)),
        "share_abs_delta_ge_threshold": float(np.mean(np.abs(deltas) >= args.delta_threshold)),
        "leak_threshold": args.leak_threshold,
        "n_leak_available": coverage["n_leak_available"],
        "leak_rate_status": coverage["leak_rate_status"],
        "leak_rate_todo": (
            "TODO: 用户新版 Test_2a 逐字段审计（results/leak_audit/{dataset}/G1_*.json）出数后重跑本脚本，"
            "leak_rate 列与 leak × Δc 散点自动补齐"
            if coverage["leak_rate_status"] != LEAK_STATUS_OK
            else ""
        ),
        "n_influential_fields": len(influential),
        "leak_scatter_plotted": leak_plotted,
        "delta_c_by_mask_group": noise_floor_stats(rows, args.delta_threshold),
        "noise_floor_note": (
            "两臂嵌入来自两次独立构建（raw bank vs lm0 bank）；CONCH 文本编码对全局 padding 长度不"
            "完全不变，故取值未改动（mask_affected=False）的字段仍有非零 Δc —— 该组即本底（噪声本底），"
            "Δc 归因于 mask 需显著超过它。"
        ),
    }
    (out_dir / "Test_1a_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"[Test_1a] datasets covered: {metrics['n_datasets_covered']}/{len(datasets)}  pairs={len(rows)}  pending={len(pending)}")
    print(f"[Test_1a] Δc: mean={deltas.mean():+.4f} median={np.median(deltas):+.4f} "
          f"[{deltas.min():+.4f}, {deltas.max():+.4f}]  |Δc|>={args.delta_threshold}: "
          f"{metrics['n_abs_delta_ge_threshold']}/{len(rows)}")
    print(f"[Test_1a] leak_rate: {coverage['leak_rate_status']} ({coverage['n_leak_available']}/{len(rows)} filled)  "
          f"influential={len(influential)}")
    for label, stats in metrics["delta_c_by_mask_group"].items():
        print(f"[Test_1a]   Δc[{label}]: n={stats['n_fields']} mean={stats['delta_mean']:+.4f} "
              f"median={stats['delta_median']:+.4f} p90|Δc|={stats['abs_delta_p90']:.4f}")
    print(f"[Test_1a] out: {out_dir}")

    if args.audit:
        checks = run_audit(
            rows,
            t0_root=Path(args.t0_root),
            off_root=Path(args.off_root),
            analyzer=args.analyzer,
            seed=args.audit_seed,
            n=args.audit_n,
        )
        (out_dir / "Test_1a_audit.json").write_text(
            json.dumps(checks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if not all(c["match"] for c in checks):
            print("[Test_1a] AUDIT MISMATCH")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
