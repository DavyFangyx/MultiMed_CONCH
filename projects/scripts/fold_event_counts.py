#!/usr/bin/env python3
"""Per-fold validation event counts for Test_2b arm_A (A_manual) runs, joined with dataset event tables."""
import glob
import re
import sys
from pathlib import Path

import pandas as pd

PROJ = Path("/data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects")
for _path in (PROJ, PROJ / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from common.paths import test_results_dir  # noqa: E402

ARM_A_RESULTS = test_results_dir("Test_2b/arm_A")  # 迁移前回退 results/A_manual
ev = pd.read_csv(PROJ / "rawdata_stats/_shared/event_summary.csv")

studies = ["tcga_dlbc", "tcga_pcpg", "tcga_gbm", "tcga_prad", "tcga_thca",
           "tcga_tgct", "tcga_kich", "tcga_read", "tcga_kirp", "tcga_brca"]

rows = []
for s in studies:
    ds = {"tcga_dlbc": "TCGA-DLBC", "tcga_pcpg": "TCGA-PCPG", "tcga_gbm": "TCGA-GBM",
          "tcga_prad": "TCGA-PRAD", "tcga_thca": "TCGA-THCA", "tcga_tgct": "TCGA-TGCT",
          "tcga_kich": "TCGA-KICH", "tcga_read": "TCGA-READ", "tcga_kirp": "TCGA-KIRP",
          "tcga_brca": "TCGA-BRCA"}[s]
    per = pd.read_csv(PROJ / f"rawdata_stats/{ds}/event_stats.csv")
    per["case"] = per.submitter_id
    n_tot = int(ev.loc[ev.dataset == ds, "n_event"].iloc[0])
    splits = sorted(glob.glob(str(ARM_A_RESULTS / "runs" / f"{s}__MULTISURV/mlp_clinic_mean/splits_*.csv")))
    per_fold = []
    for f in splits:
        df = pd.read_csv(f)
        vals = df["val"].dropna().astype(str).str.split(";").explode()
        # slide barcodes like TCGA-2A-A8VL-01Z-... -> patient id TCGA-2A-A8VL
        vals = vals.str.extract(r"^(TCGA-[A-Z0-9]{2}-[A-Z0-9]{4})", expand=False)
        m = per[per.case.isin(vals)]
        n_ev = int(m.event.sum())
        per_fold.append(n_ev)
    rows.append(dict(dataset=ds, n_event_total=n_tot, n_val_folds=len(per_fold),
                     val_events_per_fold=per_fold,
                     min_ev=min(per_fold), max_ev=max(per_fold)))
    print(f"{ds:10s} total_events={n_tot:4d}  val events/fold: {per_fold}")

df = pd.DataFrame(rows)
out = PROJ / "results/_analysis"
out.mkdir(exist_ok=True)
df.to_csv(out / "fold_event_counts.csv", index=False)
