"""
S10b: offline Q-metric recompute (IBS / time-dependent AUC@24,60 / IPCW c-index).

Recomputes the Q-axis metrics for ALREADY COMPLETED runs from their saved
per-fold artifacts - no training, no writes into results/, outputs/ or configs/:

  - source=metrics_input_dump : the run wrote `fold{fold}_metrics_input.pkl`
    (Clinic_Analyzer/utils/core_utils.py::_summary hook, S10b).  The dump holds
    the raw row-level inputs of _calculate_metrics plus the metrics it returned,
    so the offline recompute is the diff=0 path.
  - source=pkl_recompute     : older runs, only `split_{fold}_results.pkl`
    (case-level, 12-char case ids) + `test_result.csv` exist.  Discrete models
    rebuild survival curves from the saved hazard logits; cox models need a
    no-grad forward pass over the train/test splits with s_{fold}_checkpoint.pt
    (Breslow baseline), mirroring SurvPGC
    results_display/scripts/Table1_CoxBreslow_Forward.py.

Metrics follow the shared conventions in Clinic_Analyzer/utils/survival_metrics.py
(verbatim port of SurvPGC utils/survival_metrics.py):
  - IBS grid [1..60] months, NaN unless test_min <= 1 and test_max >= 60
  - landmark AUC at 24/60 months, NaN unless the landmark is inside the test
    follow-up AND n_events >= MIN_EVENTS_FOR_AUC[landmark]
  - estimate = risk direction (1 - S) for cumulative_dynamic_auc

Self-check: c-index recomputed from the saved risks must equal test_result.csv's
test_cindex (abs diff <= CINDEX_TOLERANCE); mismatching confs are flagged with
[FAIL] and listed in the closing summary (they need investigation).

Usage (SurvPGC env):
  /data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python \
    results_display/scripts/Test_5_q_recompute.py \
    --results-root results/Test_2b/arm_B --limit 3 --folds 0,1

Cox runs (clinic_cox, ...) are only forward-passed on --cox-device cpu by
default; never point this at a busy GPU.
"""

from __future__ import annotations

import argparse
import ast
import csv
import math
import os
import pickle
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ANALYZER_DIR = PROJECT_ROOT / "Clinic_Analyzer"
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ANALYZER_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYZER_DIR))

from sksurv.metrics import (  # noqa: E402
    brier_score,
    concordance_index_censored,
    concordance_index_ipcw,
)
from sksurv.util import Surv  # noqa: E402

from utils.survival_metrics import (  # noqa: E402
    AUC_LANDMARK_MONTHS,
    IBS_GRID_MONTHS,
    MIN_EVENTS_FOR_AUC,
    breslow_survival,
    compute_ibs,
    compute_landmark_aucs,
    interpolate_survival,
    survival_columns_from_logits,
)

DEFAULT_RESULTS_ROOTS = ("results/Test_2b/arm_B",)
DEFAULT_OUT = "results_display/Test_5_invariance/q_metrics.csv"
DEFAULT_MODALITIES = (
    "mlp_clinic_flatten",
    "snn_clinic_flatten",
    "clinic_cox",
    "survgc_f",
    "survpgc_f",
)
Q_COLUMNS = [
    "study",
    "scheme",
    "modality",
    "fold",
    "ibs",
    "auc24",
    "auc60",
    "iauc",
    "n_events_24",
    "n_events_60",
    "cindex_recomputed",
    "cindex_csv",
    "abs_diff",
    "source",
]
DUMP_NAME_TEMPLATE = "fold{fold}_metrics_input.pkl"
CINDEX_TOLERANCE = 1e-8
COX_BAG_LOSS = "cox_surv"


# ---------------------------------------------------------------------------
# small filesystem / config helpers (pure, importable)
# ---------------------------------------------------------------------------


@contextmanager
def _chdir(path: Path):
    cwd = os.getcwd()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(cwd)


def parse_experiment_txt(path: Path) -> dict:
    """experiment.txt is a python dict literal (ast.literal_eval)."""
    return ast.literal_eval(Path(path).read_text(encoding="utf-8"))


def read_effective_config(path: Path) -> dict:
    """effective_config.txt is KEY=VALUE lines; missing file -> {}."""
    config: dict[str, str] = {}
    path = Path(path)
    if not path.is_file():
        return config
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        config[key.strip()] = value.strip().strip('"').strip("'")
    return config


def parse_conf_name(name: str) -> tuple[str, str]:
    """`{study}__{scheme}__landmark_*` -> (study, scheme) with the landmark kept.

    The landmark token is folded into `scheme` (e.g. 'SURVPGC__landmark_0') so
    that landmark_0 / landmark_none confs of the same study never collide.
    """
    tokens = [token for token in str(name).split("__") if token]
    if not tokens:
        return str(name), ""
    study = tokens[0]
    scheme = "__".join(tokens[1:]) if len(tokens) > 1 else ""
    return study, scheme


def resolve_label_file(
    experiment: dict,
    conf_dir: Path,
    modality_dir: Path,
    extra_dirs: Sequence[Path] = (),
) -> Path | None:
    """Locate the label CSV the run used.

    Copied run trees (Test_2b/...) keep experiment.txt pointing at the original
    results/A_manual_landmark/labels/... path, so fall back to a `labels/` dir
    found by walking up from the run dir (arm_B/labels/<basename>).
    """
    raw = str(experiment.get("label_file") or "")
    name = Path(raw).name
    candidates: list[Path] = []
    if raw:
        candidates.append(Path(raw))
    for extra in extra_dirs:
        if name:
            candidates.append(Path(extra) / name)
    anchors = [
        modality_dir.parent,
        conf_dir,
        conf_dir.parent,
        conf_dir.parent.parent,
        conf_dir.parent.parent.parent,
    ]
    for anchor in anchors:
        if name:
            candidates.append(anchor / "labels" / name)
            candidates.append(anchor / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunRef:
    root: Path
    conf_dir: Path
    modality_dir: Path
    study: str
    scheme: str
    modality: str

    @property
    def conf_key(self) -> str:
        return str(self.modality_dir)


def discover_run_dirs(roots: Iterable[Path], modalities: Sequence[str]) -> list[RunRef]:
    """Find `<...>/{conf_dir}/{modality}/` dirs holding split_*_results.pkl."""
    wanted = set(modalities)
    refs: dict[str, RunRef] = {}
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            print(f"[WARN] results root does not exist: {root}")
            continue
        for marker in root.rglob("split_*_results.pkl"):
            modality_dir = marker.parent
            if modality_dir.name not in wanted:
                continue
            conf_dir = modality_dir.parent
            study, scheme = parse_conf_name(conf_dir.name)
            ref = RunRef(
                root=root,
                conf_dir=conf_dir,
                modality_dir=modality_dir,
                study=study,
                scheme=scheme,
                modality=modality_dir.name,
            )
            refs.setdefault(ref.conf_key, ref)
    return sorted(refs.values(), key=lambda r: (str(r.root), str(r.conf_dir), r.modality))


def list_folds(modality_dir: Path) -> list[int]:
    folds = []
    for pkl in Path(modality_dir).glob("split_*_results.pkl"):
        if pkl.name.endswith("_val.pkl"):
            continue
        try:
            folds.append(int(pkl.name.split("_")[1]))
        except (IndexError, ValueError):
            continue
    return sorted(set(folds))


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------


def load_fold_pkl(path: Path) -> dict:
    """split_{fold}_results.pkl: dict case_id -> {time, risk, censorship, clinical, logits}."""
    with Path(path).open("rb") as handle:
        patients = pickle.load(handle)
    case_ids = list(patients)
    times = np.array([patients[i]["time"] for i in case_ids], dtype=np.float64)
    censorships = np.array([patients[i]["censorship"] for i in case_ids], dtype=np.float64)
    risks = np.array([patients[i]["risk"] for i in case_ids], dtype=np.float64)
    logits = None
    try:
        logits = np.stack(
            [np.asarray(patients[i]["logits"], dtype=np.float64) for i in case_ids]
        )
    except (KeyError, TypeError, ValueError):
        logits = None
    return {
        "case_ids": case_ids,
        "times": times,
        "censorships": censorships,
        "risks": risks,
        "logits": logits,
    }


def load_csv_cindex_by_fold(csv_path: Path) -> dict[int, float]:
    """test_result.csv is indexed by fold (0..k-1)."""
    import pandas as pd

    csv_path = Path(csv_path)
    if not csv_path.is_file():
        return {}
    # the file has no header name for the index column; index_col=0 reads it
    try:
        frame = pd.read_csv(csv_path, index_col=0)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[WARN] cannot read {csv_path}: {exc}")
        return {}
    out: dict[int, float] = {}
    for index, row in frame.iterrows():
        try:
            fold = int(float(index))
        except (TypeError, ValueError):
            continue
        raw = row.get("test_cindex", "")
        try:
            out[fold] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


def read_metrics_input_dump(path: Path) -> dict | None:
    path = Path(path)
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        return pickle.load(handle)


# ---------------------------------------------------------------------------
# cohort / dataset factory rebuild
# ---------------------------------------------------------------------------


def build_survival_dataset_factory(
    *,
    study: str,
    label_file: Path,
    clinical_file: str | None,
    modality: str,
    label_col: str = "survival_months",
    n_bins: int = 4,
    seed: int = 0,
    num_patches: int = 4096,
    type_of_path: str = "combine",
    omics_dir: str | None = None,
    data_dir: str | None = None,
    gene_dir: str | None = None,
    eps: float = 1e-6,
    print_info: bool = False,
):
    """Rebuild SurvivalDatasetFactory exactly like Clinic_Analyzer/main.py:121.

    The factory code reads relative paths for some defaults, so build it with
    cwd=Clinic_Analyzer (same trick as SurvPGC Table1_IBS_AUC.py).  Read-only:
    only the label/clinical CSVs are read.
    """
    from datasets.dataset_survival import SurvivalDatasetFactory

    with _chdir(ANALYZER_DIR):
        return SurvivalDatasetFactory(
            study=study,
            label_file=str(label_file),
            omics_dir=omics_dir,
            data_dir=data_dir,
            clinical_file=clinical_file,
            seed=int(seed),
            print_info=print_info,
            n_bins=int(n_bins),
            label_col=label_col,
            eps=eps,
            num_patches=int(num_patches),
            type_of_pathway=type_of_path,
            modality=modality,
            gene_dir=gene_dir,
        )


def edges_from_factory(factory) -> np.ndarray:
    """dataset_factory.bins[1:] - the survival-column bin edges (core_utils.py:594)."""
    return np.asarray(factory.bins[1:], dtype=np.float64)


def cohort_arrays_from_splits_csv(
    splits_csv: Path,
    label_data,
    label_col: str,
    censorship_var: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Mirror _extract_survival_metadata (core_utils.py:332-361) offline.

    The run-dir splits_{fold}.csv holds SLIDE ids; the online loaders' metadata
    is label_data rows whose case_id is in the split (case-id lookups come from
    the split_dir csv).  Slide -> case_id via label_data's slide_id column,
    falling back to slide_id[:12] (the case_id convention of _summary).
    """
    import pandas as pd

    splits = pd.read_csv(splits_csv)
    slide_to_case = dict(
        zip(label_data["slide_id"].astype(str), label_data["case_id"].astype(str))
    )
    parts = []
    for key in ("train", "val", "test"):
        if key not in splits.columns:
            continue
        slides = [str(value) for value in splits[key].dropna().tolist()]
        case_ids = sorted({slide_to_case.get(slide, slide[:12]) for slide in slides})
        parts.append(label_data[label_data["case_id"].isin(case_ids)])
    if not parts:
        empty = np.empty(0, dtype=np.float64)
        return empty, empty
    cohort = pd.concat(parts, ignore_index=True)
    return (
        cohort[label_col].to_numpy(dtype=np.float64),
        cohort[censorship_var].to_numpy(dtype=np.float64),
    )


def cohort_arrays_from_patients_df(patients_df, label_col: str, censorship_var: str):
    """Fallback cohort: full study patients_df (no splits csv available)."""
    return (
        patients_df[label_col].to_numpy(dtype=np.float64),
        patients_df[censorship_var].to_numpy(dtype=np.float64),
    )


def cohort_surv_from_splits_csv(factory, splits_csv: Path) -> tuple:
    """(cohort_surv, times, censorships) built from the fold's splits csv."""
    times, censorships = cohort_arrays_from_splits_csv(
        splits_csv, factory.label_data, factory.label_col, factory.censorship_var
    )
    return build_surv(times, censorships), times, censorships


# ---------------------------------------------------------------------------
# pure metric core - mirrors Clinic_Analyzer/utils/core_utils.py::_calculate_metrics
# ---------------------------------------------------------------------------


def build_surv(times, censorships) -> Surv:
    """Surv object with event = 1 - censorship (same call as the online path)."""
    return Surv.from_arrays(
        event=(1.0 - np.asarray(censorships, dtype=np.float64)) > 0.5,
        time=np.asarray(times, dtype=np.float64),
    )


def risk_from_logits(logits: np.ndarray) -> np.ndarray:
    """_calculate_risk nll branch: risk = -sum(S(t_j)) over the survival columns."""
    survival = survival_columns_from_logits(logits)
    return -np.sum(survival, axis=1, dtype=np.float64)


def cindex_from_risk(times, censorships, risks, tied_tol: float = 1e-08) -> float:
    return float(
        concordance_index_censored(
            (1.0 - np.asarray(censorships, dtype=np.float64)) > 0.5,
            np.asarray(times, dtype=np.float64),
            np.asarray(risks, dtype=np.float64),
            tied_tol=tied_tol,
        )[0]
    )


def drop_nan_risk_rows(times, censorships, risks, risk_by_bin=None) -> dict:
    """Filter 1 of _calculate_metrics (core_utils.py:597-604).

    Rows with a NaN risk are deleted from every array (risk_by_bin rows too).
    """
    all_risk_scores = np.asarray(risks, dtype=np.float64)
    all_censorships = np.asarray(censorships, dtype=np.float64)
    all_event_times = np.asarray(times, dtype=np.float64)
    all_risk_by_bin_scores = (
        None if risk_by_bin is None else np.asarray(risk_by_bin, dtype=np.float64)
    )
    nan_mask = np.argwhere(np.isnan(all_risk_scores))
    all_risk_scores = np.delete(all_risk_scores, nan_mask)
    all_censorships = np.delete(all_censorships, nan_mask)
    all_event_times = np.delete(all_event_times, nan_mask)
    if all_risk_by_bin_scores is not None:
        all_risk_by_bin_scores = np.delete(all_risk_by_bin_scores, nan_mask, axis=0)
    return {
        "times": all_event_times,
        "censorships": all_censorships,
        "risks": all_risk_scores,
        "risk_by_bin": all_risk_by_bin_scores,
        "n_nan_rows": int(nan_mask.shape[0]),
    }


def drop_negative_time_rows(filtered: dict, cohort_times=None, cohort_events=None) -> dict:
    """Filter 2 of _calculate_metrics (core_utils.py:617-630).

    Negative observed times (BRCA data quirk) leave the IPCW metric path; the
    cohort Surv is time>=0-filtered too, but ONLY inside this conditional block
    (i.e. only when the test fold itself had a negative time).
    """
    all_risk_scores = filtered["risks"]
    all_censorships = filtered["censorships"]
    all_event_times = filtered["times"]
    all_risk_by_bin_scores = filtered["risk_by_bin"]
    keep = all_event_times >= 0.0
    cohort_filtered = False
    if not keep.all():
        all_risk_scores = all_risk_scores[keep]
        all_censorships = all_censorships[keep]
        all_event_times = all_event_times[keep]
        if all_risk_by_bin_scores is not None:
            all_risk_by_bin_scores = all_risk_by_bin_scores[keep]
        if cohort_times is not None:
            cohort_keep = np.asarray(cohort_times, dtype=np.float64) >= 0.0
            if not cohort_keep.all():
                cohort_filtered = True
                cohort_times = np.asarray(cohort_times, dtype=np.float64)[cohort_keep]
                cohort_events = np.asarray(cohort_events, dtype=bool)[cohort_keep]
    return {
        "times": all_event_times,
        "censorships": all_censorships,
        "risks": all_risk_scores,
        "risk_by_bin": all_risk_by_bin_scores,
        "cohort_times": None if cohort_times is None else np.asarray(cohort_times, dtype=np.float64),
        "cohort_events": None if cohort_events is None else np.asarray(cohort_events, dtype=bool),
        "cohort_neg_filtered": cohort_filtered,
        "n_nan_rows": int(filtered.get("n_nan_rows", 0)),
        "n_negative_rows": int((~keep).sum()),
    }


def apply_metric_filters(
    times, censorships, risks, risk_by_bin=None, cohort_times=None, cohort_events=None
) -> dict:
    """Both _calculate_metrics row filters in online order (NaN then negative)."""
    return drop_negative_time_rows(
        drop_nan_risk_rows(times, censorships, risks, risk_by_bin=risk_by_bin),
        cohort_times=cohort_times,
        cohort_events=cohort_events,
    )


def calculate_metrics_mirror(
    edges,
    cohort_surv,
    times,
    censorships,
    risks,
    risk_by_bin=None,
    train_survival_risks=None,
) -> tuple:
    """Offline twin of core_utils.py::_calculate_metrics.

    Returns the same tuple (c_index, c_index_ipcw, BS, IBS, iauc, iauc_list);
    keep the order and the early-return semantics identical to the online code.
    """
    edges = np.asarray(edges, dtype=np.float64)
    cohort_times = None
    cohort_events = None
    if cohort_surv is not None:
        cohort_times = np.asarray(cohort_surv["time"], dtype=np.float64)
        cohort_events = np.asarray(cohort_surv["event"], dtype=bool)

    # c-index is computed on the NaN-dropped / pre-negative-filter arrays (the
    # online control-flow gate: it feeds best-epoch + optuna decisions)
    nan_filtered = drop_nan_risk_rows(times, censorships, risks, risk_by_bin=risk_by_bin)
    try:
        c_index = concordance_index_censored(
            (1 - nan_filtered["censorships"]).astype(bool),
            nan_filtered["times"],
            nan_filtered["risks"],
            tied_tol=1e-08,
        )[0]
    except ValueError:
        c_index = 0.0
    c_index_ipcw, BS, IBS, iauc, iauc_list = 0., 0., 0., 0., 0.

    filtered = drop_negative_time_rows(
        nan_filtered, cohort_times=cohort_times, cohort_events=cohort_events
    )
    all_risk_scores = filtered["risks"]
    all_censorships = filtered["censorships"]
    all_event_times = filtered["times"]
    all_risk_by_bin_scores = filtered["risk_by_bin"]
    survival_train = cohort_surv
    if filtered["cohort_neg_filtered"]:
        survival_train = Surv.from_arrays(
            event=filtered["cohort_events"], time=filtered["cohort_times"]
        )

    try:
        survival_test = Surv.from_arrays(
            event=(1 - all_censorships).astype(bool), time=all_event_times
        )
    except Exception:
        return c_index, c_index_ipcw, BS, IBS, iauc, iauc_list

    try:
        c_index_ipcw = concordance_index_ipcw(
            survival_train, survival_test, estimate=all_risk_scores
        )[0]
    except Exception:
        c_index_ipcw = 0.0

    if survival_train is None:
        return c_index, c_index_ipcw, BS, IBS, iauc, iauc_list

    estimate_grid = None
    estimate_landmarks = None
    if all_risk_by_bin_scores is not None:
        estimate_grid = interpolate_survival(all_risk_by_bin_scores, edges, IBS_GRID_MONTHS)
        estimate_landmarks = 1.0 - interpolate_survival(
            all_risk_by_bin_scores, edges, np.asarray(AUC_LANDMARK_MONTHS, dtype=np.float64)
        )
    elif train_survival_risks is not None:
        train_times, train_events, train_risks = train_survival_risks
        estimate_grid = breslow_survival(
            train_times, train_events, train_risks, all_risk_scores, IBS_GRID_MONTHS
        )
        estimate_landmarks = 1.0 - breslow_survival(
            train_times,
            train_events,
            train_risks,
            all_risk_scores,
            np.asarray(AUC_LANDMARK_MONTHS, dtype=np.float64),
        )

    if estimate_grid is None:
        return c_index, c_index_ipcw, BS, IBS, iauc, iauc_list

    test_min = float(all_event_times.min())
    test_max = float(all_event_times.max())

    if test_min <= 1.0 and test_max >= 60.0:
        try:
            _, BS = brier_score(
                survival_train, survival_test, estimate=estimate_grid, times=IBS_GRID_MONTHS
            )
            IBS = compute_ibs(survival_train, survival_test, estimate_grid, IBS_GRID_MONTHS)
            if not np.isfinite(IBS):
                IBS = float("nan")
        except Exception:
            BS = 0.
            IBS = float("nan")
    else:
        BS, IBS = 0., float("nan")

    available_landmarks = []
    for landmark in AUC_LANDMARK_MONTHS:
        n_events = int(
            (((1.0 - all_censorships) > 0.5) & (all_event_times <= landmark)).sum()
        )
        if (
            test_min <= landmark <= test_max
            and n_events >= MIN_EVENTS_FOR_AUC.get(landmark, 5)
        ):
            available_landmarks.append(landmark)

    iauc_list = [float("nan")] * len(AUC_LANDMARK_MONTHS)
    iauc = float("nan")
    if available_landmarks:
        try:
            columns = [AUC_LANDMARK_MONTHS.index(lm) for lm in available_landmarks]
            estimate = estimate_landmarks[:, columns]
            aucs = compute_landmark_aucs(
                survival_train, survival_test, estimate, available_landmarks
            )
            for landmark, value in zip(available_landmarks, aucs):
                iauc_list[AUC_LANDMARK_MONTHS.index(landmark)] = value
            finite = [value for value in iauc_list if np.isfinite(value)]
            iauc = float(np.mean(finite)) if finite else float("nan")
        except Exception:
            iauc = float("nan")
            iauc_list = [float("nan")] * len(AUC_LANDMARK_MONTHS)

    return c_index, c_index_ipcw, BS, IBS, iauc, iauc_list


def fold_q_metrics(
    edges,
    cohort_surv,
    times,
    censorships,
    risks,
    risk_by_bin=None,
    train_survival_risks=None,
) -> dict:
    """Mirror + reporting extras (n_events per landmark, auc24/auc60)."""
    c_index, c_index_ipcw, BS, IBS, iauc, iauc_list = calculate_metrics_mirror(
        edges,
        cohort_surv,
        times,
        censorships,
        risks,
        risk_by_bin=risk_by_bin,
        train_survival_risks=train_survival_risks,
    )
    filtered = apply_metric_filters(times, censorships, risks, risk_by_bin=risk_by_bin)
    events = (1.0 - filtered["censorships"]) > 0.5
    n_events = {
        int(landmark): int((events & (filtered["times"] <= landmark)).sum())
        for landmark in AUC_LANDMARK_MONTHS
    }
    auc_by_landmark = {}
    if isinstance(iauc_list, (list, tuple, np.ndarray)) and len(iauc_list) == len(AUC_LANDMARK_MONTHS):
        for landmark, value in zip(AUC_LANDMARK_MONTHS, iauc_list):
            auc_by_landmark[int(landmark)] = float(value)
    return {
        "cindex": float(c_index),
        "cindex_ipcw": float(c_index_ipcw),
        "bs": BS,
        "ibs": IBS,
        "iauc": iauc,
        "iauc_list": list(iauc_list) if isinstance(iauc_list, (list, tuple, np.ndarray)) else iauc_list,
        "auc24": auc_by_landmark.get(24, float("nan")),
        "auc60": auc_by_landmark.get(60, float("nan")),
        "n_events_24": n_events.get(24, 0),
        "n_events_60": n_events.get(60, 0),
    }


def metrics_from_dump(dump: dict) -> dict:
    """Diff=0 path: recompute from the payload saved by _summary."""
    cohort_surv = None
    if dump.get("survival_train_time") is not None:
        cohort_surv = Surv.from_arrays(
            event=np.asarray(dump["survival_train_event"], dtype=bool),
            time=np.asarray(dump["survival_train_time"], dtype=np.float64),
        )
    train_survival_risks = dump.get("train_survival_risks")
    return fold_q_metrics(
        np.asarray(dump["edges"], dtype=np.float64),
        cohort_surv,
        dump["all_event_times"],
        dump["all_censorships"],
        dump["all_risk_scores"],
        risk_by_bin=dump.get("all_risk_by_bin_scores"),
        train_survival_risks=None if train_survival_risks is None else tuple(train_survival_risks),
    )


# ---------------------------------------------------------------------------
# row construction
# ---------------------------------------------------------------------------


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, float):
        return "" if math.isnan(value) else repr(value)
    return value


def make_q_row(
    *,
    study: str,
    scheme: str,
    modality: str,
    fold: int,
    metrics: dict,
    cindex_csv: float | None,
    source: str,
) -> dict:
    cindex_recomputed = float(metrics["cindex"])
    abs_diff = "" if cindex_csv is None else abs(cindex_recomputed - float(cindex_csv))
    return {
        "study": study,
        "scheme": scheme,
        "modality": modality,
        "fold": int(fold),
        "ibs": _csv_value(float(metrics["ibs"])),
        "auc24": _csv_value(float(metrics["auc24"])),
        "auc60": _csv_value(float(metrics["auc60"])),
        "iauc": _csv_value(float(metrics["iauc"])),
        "n_events_24": int(metrics["n_events_24"]),
        "n_events_60": int(metrics["n_events_60"]),
        "cindex_recomputed": _csv_value(cindex_recomputed),
        "cindex_csv": _csv_value(None if cindex_csv is None else float(cindex_csv)),
        "abs_diff": _csv_value(None if abs_diff == "" else float(abs_diff)),
        "source": source,
    }


# ---------------------------------------------------------------------------
# per-conf computation
# ---------------------------------------------------------------------------


def _resolve_label_col_n_bins(experiment: dict, config: dict) -> tuple[str, int]:
    label_col = config.get("LABEL_COL") or experiment.get("label_col") or "survival_months"
    try:
        n_bins = int(float(config.get("N_CLASSES", 4)))
    except (TypeError, ValueError):
        n_bins = 4
    return label_col, n_bins


def prepare_conf(ref: RunRef, extra_label_dirs: Sequence[Path] = ()) -> dict:
    """Load experiment settings and rebuild the dataset factory for one conf.

    experiment.txt / effective_config.txt live in the modality run dir
    (`.../{conf}/{modality}/`); the conf dir itself only holds the modality
    subdirs.  Fall back to the conf dir for older layouts.
    """
    experiment_path = ref.modality_dir / "experiment.txt"
    if not experiment_path.is_file():
        experiment_path = ref.conf_dir / "experiment.txt"
    if not experiment_path.is_file():
        raise FileNotFoundError(f"missing experiment.txt under {ref.conf_dir}")
    experiment = parse_experiment_txt(experiment_path)
    config = read_effective_config(ref.modality_dir / "effective_config.txt")
    if not config:
        config = read_effective_config(ref.conf_dir / "effective_config.txt")
    label_col, n_bins = _resolve_label_col_n_bins(experiment, config)
    label_file = resolve_label_file(experiment, ref.conf_dir, ref.modality_dir, extra_label_dirs)
    if label_file is None:
        raise FileNotFoundError(
            f"label file not found (experiment label_file={experiment.get('label_file')})"
        )
    factory = build_survival_dataset_factory(
        study=experiment.get("experiment", ref.study),
        label_file=label_file,
        clinical_file=experiment.get("clinical_file"),
        modality=ref.modality,
        label_col=label_col,
        n_bins=n_bins,
        seed=int(experiment.get("seed", 0) or 0),
        num_patches=int(experiment.get("num_patches", 4096) or 4096),
        type_of_path=experiment.get("type_of_path", "combine") or "combine",
        omics_dir=experiment.get("omics_dir"),
        data_dir=experiment.get("data_root_dir"),
        gene_dir=experiment.get("gene_dir"),
    )
    return {
        "experiment": experiment,
        "config": config,
        "label_col": label_col,
        "n_bins": n_bins,
        "label_file": label_file,
        "factory": factory,
    }


def compute_fold_from_artifacts(ref: RunRef, conf: dict, fold: int) -> tuple[dict, str]:
    """Recompute one fold from saved artifacts (dump preferred, pkl fallback)."""
    dump_path = ref.modality_dir / DUMP_NAME_TEMPLATE.format(fold=fold)
    dump = read_metrics_input_dump(dump_path)
    if dump is not None:
        return metrics_from_dump(dump), "metrics_input_dump"

    factory = conf["factory"]
    is_cox = conf["experiment"].get("bag_loss") == COX_BAG_LOSS
    artifacts = load_fold_pkl(ref.modality_dir / f"split_{fold}_results.pkl")
    times = artifacts["times"]
    censorships = artifacts["censorships"]
    risks = artifacts["risks"]
    risk_by_bin = None
    if not is_cox and artifacts["logits"] is not None:
        risk_by_bin = survival_columns_from_logits(artifacts["logits"])

    cohort_surv = None
    splits_csv = ref.modality_dir / f"splits_{fold}.csv"
    if splits_csv.is_file():
        cohort_surv, _, _ = cohort_surv_from_splits_csv(factory, splits_csv)
    else:
        cohort_times, cohort_censorships = cohort_arrays_from_patients_df(
            factory.patients_df, factory.label_col, factory.censorship_var
        )
        cohort_surv = build_surv(cohort_times, cohort_censorships)

    train_survival_risks = None
    if is_cox:
        train_survival_risks, test_forward = collect_cox_fold(ref, conf, fold)
        if test_forward is not None:
            times, censorships, risks = test_forward

    metrics = fold_q_metrics(
        edges_from_factory(factory),
        cohort_surv,
        times,
        censorships,
        risks,
        risk_by_bin=risk_by_bin,
        train_survival_risks=train_survival_risks,
    )
    return metrics, "pkl_recompute"


# ---------------------------------------------------------------------------
# cox forward path (cpu by default; never touches a busy GPU)
# ---------------------------------------------------------------------------


def _build_cox_args(ref: RunRef, conf: dict, factory, cox_device: str):
    """Minimal args namespace for return_splits/_get_split_loader/_summary."""
    import torch
    from types import SimpleNamespace

    experiment = conf["experiment"]
    device = torch.device("cuda" if cox_device != "cpu" else "cpu")
    return SimpleNamespace(
        modality=ref.modality,
        bag_loss=experiment.get("bag_loss"),
        return_attn=False,
        study=experiment.get("experiment", ref.study),
        label_col=conf["label_col"],
        n_classes=conf["n_bins"],
        # model construction mirrors core_utils._init_model (cox branch)
        clinic_dir=experiment.get("clinic_dir"),
        data_root_dir=experiment.get("data_root_dir"),
        gene_dir=experiment.get("gene_dir"),
        omics_dir=experiment.get("omics_dir"),
        encoding_dim=1024,
        single_model_size="small",
        alpha_surv=0.5,
        beta_surv=0.3,
        batch_size=1,
        weighted_sample=False,
        num_patches=int(experiment.get("num_patches", 4096) or 4096),
        seed=int(experiment.get("seed", 0) or 0),
        type_of_path=experiment.get("type_of_path", "combine") or "combine",
        results_dir=str(ref.modality_dir),  # never written to (read-only run)
        device=device,
        dataset_factory=factory,
    )


def _build_cox_model(args, state_dict=None):
    """Mirror _init_model's clinic_cox branch (no _print_network -> no writes)."""
    from models.model_single_clinic import CoxClinic
    from utils.core_utils import _infer_clinic_shape

    clinic_num_tokens, clinic_feat_dim = _infer_clinic_shape(args.clinic_dir)
    model = CoxClinic(input_dim=clinic_feat_dim, clinic_num_tokens=clinic_num_tokens)
    if state_dict is not None:
        model.load_state_dict(state_dict)
    return model


def _cox_train_csv(ref: RunRef, conf: dict, fold: int) -> Path:
    """The csv return_splits() should read: the online split_dir file (case ids).

    Falls back to a /tmp csv rebuilt from the run dir's slide-id csv when the
    original split dir is gone (never writes next to the artifacts).
    """
    split_dir = conf["experiment"].get("split_dir")
    if split_dir:
        candidate = Path(split_dir) / f"splits_{fold}.csv"
        if candidate.is_file():
            return candidate
    import pandas as pd

    run_csv = ref.modality_dir / f"splits_{fold}.csv"
    frame = pd.read_csv(run_csv)
    tmp_dir = Path(tempfile.gettempdir()) / "s10b_cox_splits"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / f"{ref.conf_dir.name}__{ref.modality}__splits_{fold}.csv"
    for column in ("train", "val", "test"):
        if column in frame.columns:
            frame[column] = [
                str(value)[:12] if isinstance(value, str) else value
                for value in frame[column]
            ]
    frame.to_csv(out)
    return out


def collect_cox_fold(ref: RunRef, conf: dict, fold: int, cox_device: str = "cpu"):
    """No-grad forward pass for a cox fold.

    Returns ((train_times, train_events, train_risks), test_forward) where
    test_forward = (times, censorships, risks) is only returned when the saved
    pkl is incomplete (clinic_cox saves a single full-batch row, see
    Table1_CoxBreslow_Forward.py) - otherwise None and the pkl risks are used.
    """
    import torch
    from utils.core_utils import (
        _collect_train_survival_risks,
        _get_split_loader,
        _init_loss_function,
    )

    args = _build_cox_args(ref, conf, conf["factory"], cox_device)
    checkpoint_path = ref.modality_dir / f"s_{fold}_checkpoint.pt"
    checkpoint = torch.load(str(checkpoint_path), map_location="cpu", weights_only=False)
    if isinstance(checkpoint, torch.nn.Module):
        model = checkpoint
    else:
        model = _build_cox_model(args, state_dict=checkpoint)
    model.to(args.device)
    model.eval()
    args.dataset_factory = conf["factory"]

    csv_path = _cox_train_csv(ref, conf, fold)
    train_split, _, test_split = conf["factory"].return_splits(
        args, csv_path=str(csv_path), fold=fold
    )
    loss_fn = _init_loss_function(args)
    loader_kwargs = dict(
        training=False,
        testing=False,
        weighted=False,
        batch_size=1,
        disable_cox_batch_override=True,  # per-patient: the online full-batch
        # loader collapses patient_results to one row per batch
    )
    train_loader = _get_split_loader(args, train_split, **loader_kwargs)
    train_times, train_events, train_risks = _collect_train_survival_risks(
        args, model, train_loader, loss_fn
    )

    test_forward = None
    pkl_path = ref.modality_dir / f"split_{fold}_results.pkl"
    artifacts = load_fold_pkl(pkl_path)
    if len(artifacts["times"]) < 2:
        test_loader = _get_split_loader(args, test_split, **loader_kwargs)
        test_times, test_events, test_risks = _collect_train_survival_risks(
            args, model, test_loader, loss_fn
        )
        test_forward = (
            test_times,
            (~np.asarray(test_events, dtype=bool)).astype(np.float64),
            test_risks,
        )
    return (train_times, train_events, train_risks), test_forward


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def _split_cli_list(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for value in values or []:
        out.extend(part.strip() for part in str(value).split(",") if part.strip())
    return out


def _abs_paths(values: Sequence[str]) -> list[Path]:
    paths = []
    for value in values:
        path = Path(value)
        paths.append(path if path.is_absolute() else (Path.cwd() / path))
    return paths


def recompute(
    roots: Sequence[Path],
    out_path: Path,
    modalities: Sequence[str],
    folds: Sequence[int] | None = None,
    limit: int | None = None,
    cox_device: str = "cpu",
    labels_dirs: Sequence[Path] = (),
    conf_filters: Sequence[str] = (),
    quiet: bool = False,
) -> list[dict]:
    refs = discover_run_dirs(roots, modalities)
    if conf_filters:
        refs = [
            ref
            for ref in refs
            if any(token in f"{ref.study}__{ref.scheme}" or token in ref.conf_dir.name for token in conf_filters)
        ]
    if limit is not None:
        refs = refs[: int(limit)]
    rows: list[dict] = []
    failures: list[str] = []
    dump_diffs: list[tuple[str, float]] = []
    conf_cache: dict[str, dict] = {}

    for ref in refs:
        tag = f"{ref.study}__{ref.scheme}/{ref.modality}"
        try:
            if ref.conf_key not in conf_cache:
                conf_cache[ref.conf_key] = prepare_conf(ref, labels_dirs)
            conf = conf_cache[ref.conf_key]
        except Exception as exc:
            print(f"[SKIP] {tag}: cannot prepare conf ({exc})")
            continue

        cindex_csv = load_csv_cindex_by_fold(ref.modality_dir / "test_result.csv")
        use_folds = list(folds) if folds else list_folds(ref.modality_dir)
        for fold in use_folds:
            pkl_path = ref.modality_dir / f"split_{fold}_results.pkl"
            if not pkl_path.is_file():
                print(f"[WARN] {tag} fold {fold}: missing {pkl_path.name}")
                continue
            try:
                metrics, source = compute_fold_from_artifacts(ref, conf, fold)
            except Exception as exc:
                print(f"[FAIL] {tag} fold {fold}: recompute error ({exc})")
                failures.append(f"{tag} fold {fold}: {exc}")
                continue
            row = make_q_row(
                study=ref.study,
                scheme=ref.scheme,
                modality=ref.modality,
                fold=fold,
                metrics=metrics,
                cindex_csv=cindex_csv.get(fold),
                source=source,
            )
            rows.append(row)
            if source == "metrics_input_dump":
                dump = read_metrics_input_dump(
                    ref.modality_dir / DUMP_NAME_TEMPLATE.format(fold=fold)
                )
                if dump and "metrics" in dump:
                    other = dump["metrics"]
                    for key in ("cindex", "ibs", "iauc"):
                        if key not in other:
                            continue
                        a, b = float(metrics[key]), float(other[key])
                        if math.isnan(a) and math.isnan(b):
                            continue
                        diff = 0.0 if (a == b) else abs(a - b)
                        dump_diffs.append((f"{tag} fold {fold} {key}", diff))
            if not quiet:
                diff = row["abs_diff"]
                print(
                    f"[FOLD] {tag} fold {fold} source={source} ibs={row['ibs']} "
                    f"auc24={row['auc24']} auc60={row['auc60']} "
                    f"cindex={row['cindex_recomputed']} csv_diff={diff}"
                )
            if row["abs_diff"] != "" and float(row["abs_diff"]) > CINDEX_TOLERANCE:
                msg = (
                    f"{tag} fold {fold}: cindex self-check |{row['cindex_recomputed']}"
                    f" - {row['cindex_csv']}| = {row['abs_diff']} > {CINDEX_TOLERANCE}"
                )
                failures.append(msg)
                print(f"[FAIL] {msg}")

    write_rows(out_path, rows)

    print(
        f"\n[SUMMARY] refs={len(refs)} rows={len(rows)} "
        f"dumps={'yes' if any(r['source'] == 'metrics_input_dump' for r in rows) else 'no'}"
    )
    if dump_diffs:
        worst = max(dump_diffs, key=lambda item: item[1])
        print(f"[SUMMARY] metrics_input_dump diff (recomputed vs dumped): worst {worst}")
    if failures:
        print(f"[SUMMARY] {len(failures)} self-check failure(s) - investigate:")
        for message in failures:
            print(f"  - {message}")
    else:
        print("[SUMMARY] all cindex self-checks within tolerance")
    return rows


def write_rows(out_path: Path, rows: Sequence[dict]) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=Q_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"[WRITE] {out_path} ({len(rows)} rows)")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline Q-metric recompute (IBS / AUC24,60 / IPCW c-index)"
    )
    parser.add_argument(
        "--results-root",
        nargs="+",
        default=[str(PROJECT_ROOT / path) for path in DEFAULT_RESULTS_ROOTS],
        help="one or more results roots (comma-separated or space-separated)",
    )
    parser.add_argument(
        "--out", default=str(PROJECT_ROOT / DEFAULT_OUT), help="output q_metrics.csv"
    )
    parser.add_argument(
        "--modalities",
        nargs="+",
        default=[",".join(DEFAULT_MODALITIES)],
        help="comma-separated modality dir names to scan",
    )
    parser.add_argument("--cox-device", default="cpu", help="cpu (default) or a GPU index")
    parser.add_argument("--limit", type=int, default=None, help="max confs (smoke runs)")
    parser.add_argument("--folds", default=None, help="comma-separated folds (default: all)")
    parser.add_argument(
        "--confs",
        nargs="+",
        default=(),
        help="only confs whose study__scheme contains one of these substrings",
    )
    parser.add_argument(
        "--labels-dir",
        nargs="*",
        default=(),
        help="extra dirs to search for the label csv by basename",
    )
    parser.add_argument("--quiet", action="store_true", help="only print the summary")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.cox_device == "cpu":
        # pin CPU before torch is imported anywhere (device picks up
        # torch.cuda.is_available() inside core_utils)
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    else:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(args.cox_device)
    folds = None
    if args.folds:
        folds = [int(part) for part in _split_cli_list([args.folds])]
    roots = _abs_paths(_split_cli_list(args.results_root))
    out_path = _abs_paths([args.out])[0]
    modalities = _split_cli_list(args.modalities)
    labels_dirs = _abs_paths(_split_cli_list(args.labels_dir))
    recompute(
        roots=roots,
        out_path=out_path,
        modalities=modalities,
        folds=folds,
        limit=args.limit,
        cox_device=args.cox_device,
        labels_dirs=labels_dirs,
        conf_filters=_split_cli_list(args.confs),
        quiet=args.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
