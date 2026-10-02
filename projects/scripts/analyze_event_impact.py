#!/usr/bin/env python3
"""Join event_summary with all result tables and analyze few-event effects."""
import json
import re
from pathlib import Path

import pandas as pd

PROJ = Path("/data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects")
EVENT = PROJ / "rawdata_stats/_shared/event_summary.csv"
RESULTS = PROJ / "results"

ev = pd.read_csv(EVENT)
ev["dataset_key"] = ev["dataset"].str.upper()

rows = []
for ds in ev["dataset"]:
    key = ds.upper()
    rec = {"dataset": ds, **ev[ev.dataset == ds].iloc[0].to_dict()}
    # --- univariate (landmark_none) ---
    f = RESULTS / "univariate/prompt/landmark_none" / ds / "field_cindex.csv"
    if f.exists():
        u = pd.read_csv(f)
        ok = u[u.status == "ok"] if "status" in u.columns else u
        rec["uni_n_fields"] = len(ok)
        rec["uni_mean"] = ok.c_index_mean.mean() if len(ok) else float("nan")
        rec["uni_max"] = ok.c_index_mean.max() if len(ok) else float("nan")
        rec["uni_p65"] = (ok.c_index_mean > 0.65).sum() if len(ok) else 0
        rec["uni_std_of_means"] = ok.c_index_mean.std() if len(ok) else float("nan")
        rec["uni_mean_foldstd"] = ok.c_index_std.mean() if len(ok) else float("nan")
        # degenerate per-fold values
        degen = 0
        for pf in ok.per_fold.dropna():
            vals = json.loads(pf) if isinstance(pf, str) else pf
            degen += sum(1 for v in vals if v in (0.0, 1.0))
        rec["uni_degen_folds"] = degen
    # --- greedy final cindex (landmark_none) ---
    f = RESULTS / "greedy/prompt/landmark_none" / ds / "cindex_by_n_fields.csv"
    if f.exists():
        g = pd.read_csv(f)
        last = g.iloc[-1]
        rec["greedy_n_fields"] = last.n_fields
        rec["greedy_mean"] = last.c_index_mean
        rec["greedy_std"] = last.c_index_std
    # --- A_manual ---
    f = RESULTS / f"A_manual/{ds}[gdc]" / "cindex.csv"
    if not f.exists():
        f = RESULTS / f"A_manual/{ds}" / "cindex.csv"
    if f.exists():
        a = pd.read_csv(f)
        rec["aman_rows"] = len(a)
        rec["aman_skipped_all"] = bool(a.skipped.all()) if "skipped" in a.columns else False
        rec["aman_max_val"] = a.val_c_index_mean.max()
        rec["aman_mean_val"] = a.val_c_index_mean.mean()
        rec["aman_max_std"] = a.val_c_index_std.max()
        rec["aman_has_test"] = (a.source == "test").any()
    rows.append(rec)

df = pd.DataFrame(rows)
out = PROJ / "results/_analysis"
out.mkdir(exist_ok=True)
df.to_csv(out / "event_impact_merged.csv", index=False)

# ---- correlations ----
print("=" * 100)
print("CORRELATIONS (Pearson) with n_event / event_rate / n_patients  [univariate landmark_none]")
print("=" * 100)
cols = ["uni_mean", "uni_max", "uni_std_of_means", "uni_mean_foldstd", "uni_degen_folds",
        "greedy_mean", "greedy_std", "aman_max_val", "aman_mean_val", "aman_max_std"]
for c in cols:
    if c in df and df[c].notna().sum() > 10:
        for pred in ["n_event", "event_rate", "n_patients"]:
            sub = df[[c, pred]].dropna()
            r = sub[c].corr(sub[pred])
            print(f"  {c:20s} vs {pred:12s}: r={r:+.3f}  (n={len(sub)})")
    print()

# ---- few-event vs rest: univariate fold std / degenerate folds ----
print("=" * 100)
print("GROUP COMPARISON: few events (<30) vs others  [univariate landmark_none]")
print("=" * 100)
few = df[df.n_event < 30]
many = df[df.n_event >= 30]
for c in ["uni_mean", "uni_max", "uni_std_of_means", "uni_mean_foldstd", "uni_p65"]:
    if c in df:
        print(f"  {c:20s}  few: {few[c].mean():.4f}   many: {many[c].mean():.4f}")
print(f"  uni_degen_folds total   few: {few.uni_degen_folds.sum():.0f}   many: {many.uni_degen_folds.sum():.0f}")
print(f"  datasets with any degenerate fold: few={int((few.uni_degen_folds>0).sum())} many={int((many.uni_degen_folds>0).sum())}")

# ---- table sorted by n_event ----
print()
print("=" * 100)
print("PER-DATASET SUMMARY (sorted by n_event)")
print("=" * 100)
show = df[["dataset", "n_patients", "n_event", "event_rate", "n_unknown",
           "uni_n_fields", "uni_mean", "uni_max", "uni_p65", "uni_mean_foldstd",
           "uni_degen_folds", "greedy_n_fields", "greedy_mean", "greedy_std",
           "aman_rows", "aman_skipped_all", "aman_max_val"]].sort_values("n_event")
print(show.round(3).to_string(index=False))

# ---- spurious top fields in few-event datasets ----
print()
print("=" * 100)
print("TOP FIELD (c-index>0.65) in few-event datasets vs many-event datasets")
print("=" * 100)
print(f"  few-event datasets: {(few.uni_p65>0).sum()} of {len(few)} have >0.65 fields")
print(f"  many-event datasets: {(many.uni_p65>0).sum()} of {len(many)} have >0.65 fields")
