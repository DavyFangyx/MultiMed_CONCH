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
