"""Dispatch a materialized subset embedding directory to Clinic_Analyzer."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from itertools import count

import pandas as pd

from .data import display_to_study


DEFAULT_ANALYZER_DIR = Path(__file__).resolve().parents[2] / "Clinic_Analyzer"
DEFAULT_SURVPGC_PYTHON = Path("/data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python")

ANALYZER_MODALITIES = (
    "mlp_clinic_mean",
    "mlp_clinic_flatten",
    "snn_clinic_mean",
    "snn_clinic_flatten",
    "survgc_f",
    "survpgc_f",
)
DEFAULT_INNER_MODALITY = "mlp_clinic_flatten"
DEFAULT_OUTER_MODALITIES = (
    "mlp_clinic_mean",
    "mlp_clinic_flatten",
    "snn_clinic_mean",
    "snn_clinic_flatten",
)

_WORKER_COUNTER = count(1)


def _worker_log_path() -> Path | None:
    stem = os.environ.get("GREEDY_LOG_STEM", "").strip()
    workers_raw = os.environ.get("GREEDY_WORKERS", "1").strip() or "1"
    try:
        workers = max(int(workers_raw), 1)
    except ValueError:
        workers = 1
    if not stem or workers <= 1:
        return None
    worker_id = ((next(_WORKER_COUNTER) - 1) % workers) + 1
    return Path(f"{stem}_{worker_id}.log")

def parse_modalities(raw: str | None, *, allow_empty: bool = False) -> list[str]:
    if raw is None:
        return []
    modalities = [item.strip() for item in str(raw).split(",") if item.strip()]
    if not modalities:
        if allow_empty:
            return []
        raise ValueError("modality is empty")
    unknown = [item for item in modalities if item not in ANALYZER_MODALITIES]
    if unknown:
        valid = ", ".join(ANALYZER_MODALITIES)
        raise ValueError(f"unsupported modality: {unknown}. expected one of: {valid}")
    return modalities


def parse_one_modality(raw: str | None) -> str:
    modalities = parse_modalities(raw)
    if len(modalities) != 1:
        raise ValueError(f"inner modality must be exactly one model, got: {modalities}")
    return modalities[0]


def results_dir(analyzer_dir: Path, exp_group: str, run_name: str, modality: str) -> Path:
    return Path(analyzer_dir) / "results" / exp_group / run_name / modality


def read_cindex(result_dir: Path, prefer_val: bool = True) -> dict:
    result_dir = Path(result_dir)
    val_files = sorted(result_dir.glob("val_result_fold*.csv"))
    test_files = sorted(result_dir.glob("test_result*.csv"))
    val_scores = []
    for path in val_files:
        df = pd.read_csv(path)
        if "val_cindex" in df.columns and len(df):
            val_scores.append(float(df["val_cindex"].iloc[-1]))
    test_scores = []
    if test_files:
        df = pd.read_csv(test_files[0])
        col = "test_cindex" if "test_cindex" in df.columns else df.columns[-1]
        test_scores = [float(x) for x in df[col].tolist() if pd.notna(x)]
    if prefer_val and val_scores:
        scores = val_scores
        source = "val"
    elif test_scores:
        scores = test_scores
        source = "test"
    elif val_scores:
        scores = val_scores
        source = "val"
    else:
        raise FileNotFoundError(f"no c-index result under {result_dir}")

    def _mean_std(values):
        if not values:
            return None, 0.0
        mean = float(sum(values) / len(values))
        if len(values) == 1:
            return mean, 0.0
        var = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return mean, float(var ** 0.5)

    mean, std = _mean_std(scores)
    test_mean, test_std = _mean_std(test_scores or scores)
    val_mean, val_std = _mean_std(val_scores or scores)
    return {
        "c_index_mean": mean,
        "c_index_std": std,
        "per_fold": scores,
        "source": source,
        "results_dir": str(result_dir),
        "val_c_index_mean": val_mean,
        "val_c_index_std": val_std,
        "val_per_fold": val_scores,
        "test_c_index_mean": test_mean,
        "test_c_index_std": test_std,
        "test_per_fold": test_scores or scores,
    }


def write_job_record(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def evaluate_clinic_dir(
    clinic_dir: Path | str,
    *,
    dataset: str,
    scheme: str,
    modality: str = DEFAULT_INNER_MODALITY,
    exp_group: str = "greedy",
    python_exe: Path | str | None = None,
    analyzer_dir: Path | str | None = None,
    k: int = 5,
    k_start: int = 0,
    k_end: int | None = None,
    max_epochs: int | None = None,
    seed: int = 0,
    extra_args: list[str] | None = None,
    prefer_val: bool = True,
    reuse: bool = True,
    job_log: Path | str | None = None,
    split_dir: Path | str | None = None,
) -> dict:
    analyzer_dir = Path(analyzer_dir or DEFAULT_ANALYZER_DIR)
    python_exe = Path(python_exe or DEFAULT_SURVPGC_PYTHON)
    study = display_to_study(dataset)
    run_name = f"{study}__{scheme}"
    out_dir = results_dir(analyzer_dir, exp_group, run_name, modality)
    existing = list(out_dir.glob("test_result*.csv")) + list(out_dir.glob("val_result_fold*.csv"))
    if reuse and existing:
        payload = read_cindex(out_dir, prefer_val=prefer_val)
        payload.update({"skipped": True, "clinic_dir": str(clinic_dir), "run_name": run_name, "modality": modality})
        if job_log:
            write_job_record(Path(job_log), payload)
        return payload

    cmd = [
        str(python_exe),
        str(analyzer_dir / "evaluate.py"),
        "--clinic_dir",
        str(clinic_dir),
        "--modality",
        modality,
        "--exp_group",
        exp_group,
        "--run_name",
        run_name,
        "--k",
        str(k),
        "--k_start",
        str(k_start),
        "--seed",
        str(seed),
        "--wandb_mode",
        "disabled",
    ]
    if k_end is not None:
        cmd.extend(["--k_end", str(k_end)])
    if max_epochs is not None:
        cmd.extend(["--max_epochs", str(max_epochs)])
    if extra_args:
        cmd.extend(list(extra_args))

    if split_dir is not None:
        cmd.extend(["--split_dir", str(split_dir)])

    env = os.environ.copy()
    worker_log = _worker_log_path()
    log_handle = None
    run_kwargs = {
        "cwd": str(analyzer_dir),
        "env": env,
        "check": False,
        "text": True,
    }
    if worker_log is not None:
        worker_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = worker_log.open("a", encoding="utf-8")
        header = f"\n===== {scheme} {modality} =====\n"
        log_handle.write(header)
        log_handle.flush()
        run_kwargs.update({"stdout": log_handle, "stderr": subprocess.STDOUT})
    proc = subprocess.run(
        cmd,
        **run_kwargs,
    )
    if log_handle is not None:
        log_handle.close()
    log = {
        "cmd": cmd,
        "returncode": proc.returncode,
        "clinic_dir": str(clinic_dir),
        "run_name": run_name,
        "modality": modality,
        "results_dir": str(out_dir),
    }
    if job_log:
        write_job_record(Path(job_log), log)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Clinic_Analyzer failed for {scheme} (exit {proc.returncode}). "
            f"See {job_log or out_dir}."
        )
    payload = read_cindex(out_dir, prefer_val=prefer_val)
    payload.update({"skipped": False, "clinic_dir": str(clinic_dir), "run_name": run_name, "modality": modality})
    if job_log:
        write_job_record(Path(job_log), {**log, **payload})
    return payload
