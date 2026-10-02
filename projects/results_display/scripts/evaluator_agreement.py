#!/usr/bin/env python3
"""Rank-agreement analysis between clinical evaluators on field combinations.

Answers: is the field-combination ranking from the Cox evaluator
(``clinic_cox``) consistent with the prompt-MLP evaluators? If the ranking
were consistent, Cox could replace MLP as the combo-quality evaluator.

Reads ``model_fieldcombo_cindex.csv`` (written by FigA_Other_Paper_Works.py),
computes within-dataset ranks of the shared (dataset, field-combo) pairs and:

  * pooled pairwise Spearman among all five models (within-dataset ranks),
  * per-dataset Spearman rho (Cox vs each MLP, plus the MLP-vs-MLP reference),
  * top-1 / top-2 combo agreement per dataset,
  * where the greedy final subset lands in each model's ranking.

Writes ``evaluator_agreement.png`` and ``evaluator_agreement_per_dataset.csv``
next to the input CSV.

Usage:
conda activate conch
python results_display/scripts/evaluator_agreement.py \
    --encoding prompt --landmark_tag landmark_0
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = (
    PROJECT_ROOT
    / "results_display"
    / "FigA_Other_Paper_Works"
    / "prompt"
    / "landmark_0"
    / "model_fieldcombo_cindex.csv"
)
DEFAULT_EVENT_SUMMARY = PROJECT_ROOT / "rawdata_stats" / "_shared" / "event_summary.csv"
MODELS = [
    "clinic_cox",
    "mlp_clinic_mean",
    "mlp_clinic_flatten",
    "snn_clinic_mean",
    "snn_clinic_flatten",
]
REFERENCE_PAIR = ("mlp_clinic_mean", "mlp_clinic_flatten")
INNER_MODEL = "mlp_clinic_flatten"

# dataviz palette (validated): blue slot 1, orange slot 2, aqua slot 3
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
SURFACE = "#fcfcfb"
GRID = "#d8d6d0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="model_fieldcombo_cindex.csv path")
    parser.add_argument(
        "--event_summary",
        default=str(DEFAULT_EVENT_SUMMARY),
        help="per-dataset event summary CSV (provides the event_rate column)",
    )
    parser.add_argument("--out_dir", default="", help="output dir; default: next to the input CSV")
    return parser


def load_shared_pivot(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df = df[df["c_index_mean"].notna()].copy()
    return df.pivot_table(index=["dataset", "field_combo", "kind"], columns="model", values="c_index_mean")


def pooled_rank_table(pivot: pd.DataFrame, models: list[str]) -> pd.DataFrame:
    """Pivot restricted to rows with a Cox score, plus within-dataset ranks."""
    shared = pivot.dropna(subset=["clinic_cox"]).copy()
    for model in models:
        shared[f"{model}_rank"] = shared.groupby(level="dataset")[model].rank(method="average")
    return shared


def per_dataset_rho(shared: pd.DataFrame, model_a: str, model_b: str, min_combos: int = 2) -> pd.DataFrame:
    rows = []
    for ds, sub in shared.groupby(level="dataset"):
        sub = sub[[model_a, model_b]].dropna()
        if len(sub) < min_combos:
            continue
        rho, _ = spearmanr(sub[model_a], sub[model_b])
        rows.append({"dataset": ds, "n_combos": len(sub), "rho": rho})
    return pd.DataFrame(rows)


def top_agreement(shared: pd.DataFrame, model: str) -> dict:
    agree_top1 = agree_top2 = total = 0
    for _, sub in shared.groupby(level="dataset"):
        sub = sub[["clinic_cox", model]].dropna()
        if len(sub) < 2:
            continue
        total += 1
        if sub["clinic_cox"].idxmax() == sub[model].idxmax():
            agree_top1 += 1
        if set(sub["clinic_cox"].nlargest(2).index) & set(sub[model].nlargest(2).index):
            agree_top2 += 1
    return {"top1": agree_top1, "top2": agree_top2, "n": total}


def plot_figure(
    png_path: Path,
    shared: pd.DataFrame,
    rho_cox_mlp: pd.DataFrame,
    rho_mlp_mlp: pd.DataFrame,
    encoding: str,
    landmark_tag: str,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(12.5, 4.6), facecolor=SURFACE)
    for ax in (ax_a, ax_b):
        ax.set_facecolor(SURFACE)

    # ---- panel A: within-dataset rank scatter, Cox vs inner MLP ----
    rng = np.random.default_rng(7)
    cox_rank = f"clinic_cox_rank"
    mlp_rank = f"{INNER_MODEL}_rank"
    rows = shared[[cox_rank, mlp_rank]].dropna()
    is_paper = rows.index.get_level_values("kind") == "paper"
    for mask, color, label in ((~is_paper, BLUE, "greedy final subset"), (is_paper, ORANGE, "paper scheme")):
        sub = rows[mask]
        ax_a.scatter(
            sub[cox_rank] + rng.uniform(-0.18, 0.18, len(sub)),
            sub[mlp_rank] + rng.uniform(-0.18, 0.18, len(sub)),
            s=26, alpha=0.85, color=color, edgecolors="white", linewidths=2.0, label=label, zorder=3,
        )
    lo, hi = 0.4, rows[[cox_rank, mlp_rank]].max().max() + 0.6
    ax_a.plot([lo, hi], [lo, hi], color="#8a8987", linestyle="--", linewidth=1.5, zorder=1)
    rho_all, p_all = spearmanr(rows[cox_rank], rows[mlp_rank])
    ax_a.text(
        0.03, 0.97,
        f"pooled Spearman ρ = {rho_all:+.2f}   (n = {len(rows)}, p = {p_all:.1e})",
        transform=ax_a.transAxes, ha="left", va="top", fontsize=9, color=INK_PRIMARY,
    )
    ax_a.text(
        0.03, 0.03,
        "rank 1 = best combo within dataset\n(jittered; points on the diagonal agree)",
        transform=ax_a.transAxes, ha="left", va="bottom", fontsize=8, color=INK_SECONDARY,
    )
    ax_a.set_xlim(lo, hi)
    ax_a.set_ylim(lo, hi)
    ax_a.set_xlabel(f"clinic_cox rank", fontsize=9, color=INK_SECONDARY)
    ax_a.set_ylabel(f"{INNER_MODEL} rank", fontsize=9, color=INK_SECONDARY)
    ax_a.set_title("A | Cox vs prompt-MLP combo ranking (shared combos, 33 datasets)", fontsize=10, color=INK_PRIMARY)
    ax_a.tick_params(labelsize=8, colors=INK_SECONDARY)
    ax_a.grid(True, alpha=0.25, color=GRID, zorder=0)
    for spine in ("top", "right"):
        ax_a.spines[spine].set_visible(False)
    ax_a.legend(frameon=False, loc="lower right", fontsize=8)

    # ---- panel B: per-dataset rho distributions, with MLP-vs-MLP reference ----
    bins = np.linspace(-1, 1, 21)
    series = [
        (rho_cox_mlp["rho"], BLUE, f"Cox vs {INNER_MODEL}", "left"),
        (rho_mlp_mlp["rho"], ORANGE, " vs ".join(REFERENCE_PAIR) + " (reference)", "right"),
    ]
    for values, color, label, _align in series:
        ax_b.hist(values, bins=bins, color=color, alpha=0.45, edgecolor="white", linewidth=1.5, label=label)
    ytop = ax_b.get_ylim()[1] * 1.08
    ax_b.set_ylim(0, ytop)
    for values, color, _label, align in series:
        mean = float(values.mean())
        ax_b.axvline(mean, color=color, linewidth=2.0)
        ax_b.text(
            mean, ytop * 0.97, f"ρ̄ = {mean:+.2f}", color=INK_PRIMARY, fontsize=8,
            ha=align, va="top",
        )
    ax_b.set_xlim(-1.05, 1.05)
    ax_b.set_xlabel("per-dataset Spearman ρ of combo ranking", fontsize=9, color=INK_SECONDARY)
    ax_b.set_ylabel("datasets", fontsize=9, color=INK_SECONDARY)
    ax_b.set_title("B | Per-dataset agreement, Cox vs MLP against MLP-vs-MLP reference", fontsize=10, color=INK_PRIMARY)
    ax_b.axvline(0, color="#8a8987", linewidth=1.0)
    ax_b.tick_params(labelsize=8, colors=INK_SECONDARY)
    ax_b.grid(True, alpha=0.25, color=GRID)
    for spine in ("top", "right"):
        ax_b.spines[spine].set_visible(False)
    ax_b.legend(frameon=False, loc="upper left", fontsize=8)

    fig.suptitle(
        f"Evaluator agreement on field-combination ranking  |  {encoding} / {landmark_tag}",
        fontsize=11, color=INK_PRIMARY, y=1.02,
    )
    fig.tight_layout()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(f"missing CSV: {csv_path}")
    out_dir = Path(args.out_dir) if args.out_dir else csv_path.parent
    encoding = csv_path.parent.parent.name
    landmark_tag = csv_path.parent.name

    pivot = load_shared_pivot(csv_path)
    shared = pooled_rank_table(pivot, MODELS)

    print(f"shared (dataset, combo) rows with Cox score: {len(shared)}  ({shared.index.get_level_values('dataset').nunique()} datasets)")
    print()
    print("pooled pairwise Spearman (within-dataset ranks):")
    for i, model_a in enumerate(MODELS):
        for model_b in MODELS[i + 1 :]:
            rows = shared[[f"{model_a}_rank", f"{model_b}_rank"]].dropna()
            rho, p = spearmanr(rows[f"{model_a}_rank"], rows[f"{model_b}_rank"])
            print(f"  {model_a:22s} vs {model_b:22s}: rho={rho:+.3f} (p={p:.2e}, n={len(rows)})")

    print()
    print("top-combo agreement (Cox's best combo vs model's best combo):")
    for model in MODELS[1:]:
        agree = top_agreement(shared, model)
        print(f"  Cox vs {model:22s}: top-1 {agree['top1']}/{agree['n']}, top-2 overlap {agree['top2']}/{agree['n']}")

    print()
    print("rank of the greedy final subset within each dataset's shared combos:")
    for model in MODELS:
        ranks = []
        for _, sub in shared.groupby(level="dataset"):
            sub = sub[[model]].dropna()
            greedy_rows = sub[sub.index.get_level_values("kind") == "greedy"]
            if len(greedy_rows) == 0 or len(sub) < 2:
                continue
            ranks.append(sub[model].rank(ascending=False).loc[greedy_rows.index[0]])
        ranks = pd.Series(ranks)
        print(f"  {model:22s}: #1 in {(ranks == 1).sum():2d}/{len(ranks)} datasets, mean rank {ranks.mean():.2f}")

    rho_cox_mlp = per_dataset_rho(shared, "clinic_cox", INNER_MODEL)
    rho_cox_mean = per_dataset_rho(shared, "clinic_cox", "mlp_clinic_mean")
    rho_mlp_mlp = per_dataset_rho(shared, *REFERENCE_PAIR)
    print()
    print("per-dataset rho summary:")
    for name, table in (
        (f"cox_vs_{INNER_MODEL}", rho_cox_mlp),
        ("cox_vs_mlp_clinic_mean", rho_cox_mean),
        ("_vs_".join(REFERENCE_PAIR), rho_mlp_mlp),
    ):
        print(f"  {name:28s}: mean={table['rho'].mean():+.3f}, median={table['rho'].median():+.3f}, n={len(table)}")

    out_csv = out_dir / "evaluator_agreement_per_dataset.csv"
    merged = rho_cox_mlp[["dataset", "n_combos"]].rename(
        columns={"n_combos": "n_shared_combos"}
    )
    merged = merged.merge(
        rho_cox_mlp[["dataset", "rho"]].rename(columns={"rho": f"rho_cox_vs_{INNER_MODEL}"}),
        on="dataset",
    )
    merged = merged.merge(
        rho_cox_mean[["dataset", "rho"]].rename(columns={"rho": "rho_cox_vs_mlp_clinic_mean"}),
        on="dataset",
    )
    merged = merged.merge(
        rho_mlp_mlp[["dataset", "rho"]].rename(columns={"rho": "rho_mlp_mean_vs_flatten"}),
        on="dataset",
        how="left",
    )
    event_summary_path = Path(args.event_summary)
    if event_summary_path.exists():
        events = pd.read_csv(event_summary_path)
        events = events[events["dataset"].isin(merged["dataset"])]
        merged = merged.merge(
            events[["dataset", "event_rate"]], on="dataset", how="left"
        )
        # second column, right after dataset
        cols = ["dataset", "event_rate"] + [c for c in merged.columns if c not in ("dataset", "event_rate")]
        merged = merged[cols]
    else:
        print(f"event summary not found: {event_summary_path} (no event_rate column)")
    merged.to_csv(out_csv, index=False)
    print(f"wrote {out_csv}")

    png_path = out_dir / "evaluator_agreement.png"
    plot_figure(png_path, shared, rho_cox_mlp, rho_mlp_mlp, encoding, landmark_tag)
    print(f"wrote {png_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
