"""Selection-frequency tables across outer folds (section 4.4)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd


def selection_frequency(fold_paths: list[list[dict]], fields: list[str] | None = None) -> pd.DataFrame:
    if not fold_paths:
        return pd.DataFrame(columns=["field", "mean_rank", "first_selected_rate", "n_folds"])

    if fields is None:
        seen = []
        for path in fold_paths:
            for step in path:
                name = step.get("added")
                if name is not None and name not in seen:
                    seen.append(name)
        fields = seen

    n_folds = len(fold_paths)
    max_steps = max((len(path) for path in fold_paths), default=0)
    counts = {field: [0] * max_steps for field in fields}
    ranks = {field: [] for field in fields}
    first_selected = {field: 0 for field in fields}

    for path in fold_paths:
        for step in path:
            name = step.get("added")
            if name not in counts:
                continue
            k = int(step["step"]) - 1
            if 0 <= k < max_steps:
                counts[name][k] += 1
            ranks[name].append(int(step["step"]))
            if int(step["step"]) == 1:
                first_selected[name] += 1

    rows = []
    for field in fields:
        row = {"field": field}
        for i, count in enumerate(counts[field], start=1):
            row[f"step{i}"] = count / n_folds if n_folds else 0.0
        field_ranks = ranks[field]
        row["mean_rank"] = float(sum(field_ranks) / len(field_ranks)) if field_ranks else float("nan")
        row["first_selected_rate"] = first_selected[field] / n_folds if n_folds else 0.0
        row["n_folds"] = n_folds
        rows.append(row)
    return pd.DataFrame(rows)


def write_selection_frequency(df: pd.DataFrame, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def plot_selection_frequency(df: pd.DataFrame, path: Path | str) -> Path | None:
    step_cols = [c for c in df.columns if str(c).startswith("step")]
    if df.empty or not step_cols:
        return None
    os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    matrix = df[step_cols].astype(float).to_numpy()
    labels = [str(x) for x in df["field"].tolist()]
    max_label = max((len(x) for x in labels), default=8)
    fig_w = max(6.0, 0.55 * len(step_cols) + 1.8 + 0.08 * max_label)
    fig_h = max(3.8, 0.32 * len(df) + 1.6)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    im = ax.imshow(matrix, aspect="auto", vmin=0.0, vmax=1.0, cmap="YlOrRd")
    ax.set_xticks(range(len(step_cols)))
    ax.set_xticklabels([c.replace("step", "k=") for c in step_cols])
    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(labels)
    ax.set_xlabel("greedy step")
    ax.set_title("selection frequency")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout(rect=[0.02, 0.02, 0.98, 0.98])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def cindex_curve_frame(path_steps: list[dict], curve: list[dict] | None = None) -> pd.DataFrame:
    curve_by_k = {int(row["k"]): row for row in (curve or [])}
    rows = []
    for step in path_steps or []:
        subset = list(step.get("subset") or [])
        k = int(step.get("step") or len(rows) + 1)
        stats = curve_by_k.get(k, {})
        rows.append(
            {
                "step": k,
                "n_fields": len(subset),
                "added": step.get("added"),
                "c_index_mean": stats.get("c_index_mean", step.get("c_index")),
                "c_index_std": stats.get("c_index_std", step.get("c_index_std")),
                "c_index_se": stats.get("c_index_se"),
                "subset": " | ".join(str(x) for x in subset),
            }
        )
    return pd.DataFrame(rows)


def write_cindex_curve(df: pd.DataFrame, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def plot_cindex_curve(df: pd.DataFrame, path: Path | str, points: dict | None = None) -> Path | None:
    if df.empty or "n_fields" not in df.columns or "c_index_mean" not in df.columns:
        return None
    os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = df["n_fields"].astype(int)
    y = df["c_index_mean"].astype(float)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.plot(x, y, marker="o", linewidth=1.8, color="#1f4e79")
    if "c_index_std" in df.columns:
        std = df["c_index_std"].astype(float).fillna(0.0)
        ax.fill_between(x, y - std, y + std, color="#1f4e79", alpha=0.12)
    markers = {
        "best": ("peak", "#c0392b"),
        "parsimonious": ("1se", "#d68910"),
        "sig_stop": ("sig_stop", "#1e8449"),
    }
    for key, (label, color) in markers.items():
        point = (points or {}).get(key) or {}
        k = point.get("k")
        if k is None:
            continue
        row = df.loc[df["step"] == int(k)]
        if row.empty:
            continue
        ax.scatter(
            row["n_fields"].astype(int),
            row["c_index_mean"].astype(float),
            color=color,
            zorder=3,
            label=f"{label} k={int(k)}",
        )
    ax.set_xlabel("number of selected fields")
    ax.set_ylabel("5-fold mean c-index")
    ax.set_title("c-index vs selected field count")
    ax.grid(True, alpha=0.3)
    if points:
        ax.legend(frameon=False)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
