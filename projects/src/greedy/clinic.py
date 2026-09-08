"""Dispatch a materialized subset embedding directory to Clinic_Analyzer."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pandas as pd

from common.paths import (
    RESULTS_ROOT,
    encoding_and_landmark_tag_from_path,
    experiment_from_path,
    result_experiment_name,
    dataset_greedy_run_dir,
    dataset_univariate_run_dir,
    require_landmark_tag,
    validate_encoding,
)

from .data import display_to_study


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ANALYZER_DIR = PROJECT_ROOT / "Clinic_Analyzer"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results"
LEGACY_ANALYZER_RESULTS_DIR = DEFAULT_ANALYZER_DIR / "results"
DEFAULT_SURVPGC_PYTHON = Path("/data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python")

ANALYZER_MODALITIES = (
    "mlp_clinic_mean",
    "mlp_clinic_flatten",
    "snn_clinic_mean",
    "snn_clinic_flatten",
    "clinic_cox",
    "survgc_f",
    "survpgc_f",
)
MULTIMODAL_MODALITIES = ("survgc_f", "survpgc_f")
MULTIMODAL_STUDIES = (
    "tcga_brca",
    "tcga_coad",
    "tcga_kirc",
    "tcga_kirp",
    "tcga_lihc",
)
MULTIMODAL_DISPLAY = "BRCA, COAD, KIRC, KIRP, LIHC"
DEFAULT_INNER_MODALITY = "mlp_clinic_flatten"
DEFAULT_OUTER_MODALITIES = (
    "mlp_clinic_mean",
    "mlp_clinic_flatten",
    "snn_clinic_mean",
    "snn_clinic_flatten",
)
DEFAULT_MULTIMODAL_OUTER_MODALITIES = DEFAULT_OUTER_MODALITIES + ("survgc_f", "survpgc_f")


def default_outer_modalities_for(dataset: str) -> tuple[str, ...]:
    study = display_to_study(dataset)
    if study in MULTIMODAL_STUDIES:
        return DEFAULT_MULTIMODAL_OUTER_MODALITIES
    return DEFAULT_OUTER_MODALITIES


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


def ensure_modalities_allowed(dataset: str, modalities: list[str] | tuple[str, ...] | str) -> None:
    if isinstance(modalities, str):
        items = [modalities]
    else:
        items = [item for item in modalities if item]
    blocked = [item for item in items if item in MULTIMODAL_MODALITIES]
    if not blocked:
        return
    study = display_to_study(dataset)
    if study in MULTIMODAL_STUDIES:
        return
    blocked_text = ", ".join(dict.fromkeys(blocked))
    raise ValueError(
        f"{blocked_text} 只支持 {MULTIMODAL_DISPLAY}；"
        f"{dataset} 只能用 clinic 单模态 (mlp/snn/cox clinic)"
    )


def analyzer_run_name(dataset: str, scheme: str) -> str:
    return f"{display_to_study(dataset)}__{scheme}"


def _relative_to_results(path: Path, results_dir_base: Path | str | None = None) -> Path:
    path = Path(path)
    for root in (RESULTS_ROOT, DEFAULT_RESULTS_DIR):
        try:
            return path.relative_to(root)
        except ValueError:
            continue
    if results_dir_base is not None:
        try:
            return path.relative_to(Path(results_dir_base))
        except ValueError:
            pass
    return path


def analyzer_exp_group(
    *,
    dataset: str,
    encoding: str,
    landmark_tag: str | None,
    experiment: str | None = None,
    kind: str = "greedy",
    results_dir_base: Path | str | None = None,
) -> str:
    out_dir = analyzer_results_dir(
        dataset=dataset,
        encoding=encoding,
        landmark_tag=landmark_tag,
        scheme="__scheme__",
        modality="__modality__",
        experiment=experiment,
        kind=kind,
        results_dir_base=results_dir_base,
    )
    rel = _relative_to_results(out_dir, results_dir_base)
    return rel.parent.parent.as_posix()


def analyzer_results_dir(
    *,
    dataset: str,
    encoding: str,
    landmark_tag: str | None,
    scheme: str,
    modality: str,
    experiment: str | None = None,
    kind: str = "greedy",
    results_dir_base: Path | str | None = None,
) -> Path:
    kind_value = str(kind or "greedy").strip().lower()
    if kind_value in {"univariate", "longitudinal_univariate"}:
        path = dataset_univariate_run_dir(
            dataset, encoding, landmark_tag, scheme, modality, experiment=experiment
        )
    else:
        path = dataset_greedy_run_dir(
            dataset, encoding, landmark_tag, scheme, modality, experiment=experiment
        )
    if results_dir_base is None:
        return path
    rel = _relative_to_results(path, results_dir_base)
    return Path(results_dir_base) / rel


def _infer_encoding_and_landmark(clinic_dir: Path | str | None, encoding: str | None, landmark_tag: str | None):
    inferred_encoding, inferred_tag = encoding_and_landmark_tag_from_path(clinic_dir or "")
    encoding_value = validate_encoding(encoding or inferred_encoding or "prompt")
    tag = require_landmark_tag(landmark_tag or inferred_tag)
    return encoding_value, tag


def _legacy_flat_run_dir(
    *,
    dataset: str,
    scheme: str,
    modality: str,
    experiment: str | None = None,
    kind: str = "greedy",
    results_dir_base: Path | str | None = None,
) -> Path:
    base = Path(results_dir_base) if results_dir_base else DEFAULT_RESULTS_DIR
    if str(kind).startswith("univariate"):
        exp_group = result_experiment_name("univariate", experiment)
    else:
        exp_group = result_experiment_name("greedy", experiment)
    return base / exp_group / analyzer_run_name(dataset, scheme) / modality


def results_dir(
    analyzer_dir: Path,
    exp_group: str,
    run_name: str,
    modality: str,
    results_dir_base: Path | str | None = None,
) -> Path:
    base = Path(results_dir_base) if results_dir_base else DEFAULT_RESULTS_DIR
    return base / exp_group / run_name / modality


def _has_cindex_files(path: Path) -> bool:
    return bool(list(path.glob("test_result*.csv")) + list(path.glob("val_result_fold*.csv")))


def _existing_result_dir(
    out_dir: Path,
    *,
    analyzer_dir: Path,
    exp_group: str,
    run_name: str,
    modality: str,
    extra_candidates: list[Path] | None = None,
) -> Path | None:
    candidates = [Path(out_dir)]
    for extra in extra_candidates or []:
        extra = Path(extra)
        if extra not in candidates:
            candidates.append(extra)
    legacy = LEGACY_ANALYZER_RESULTS_DIR / exp_group / run_name / modality
    if Path(analyzer_dir).resolve() != DEFAULT_ANALYZER_DIR.resolve():
        legacy = Path(analyzer_dir) / "results" / exp_group / run_name / modality
    if legacy not in candidates:
        candidates.append(legacy)
    for candidate in candidates:
        if _has_cindex_files(candidate):
            return candidate
    return None


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
    exp_group: str | None = None,
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
    results_dir_base: Path | str | None = None,
    encoding: str | None = None,
    landmark_tag: str | None = None,
    experiment: str | None = None,
    kind: str | None = None,
) -> dict:
    analyzer_dir = Path(analyzer_dir or DEFAULT_ANALYZER_DIR)
    python_exe = Path(python_exe or DEFAULT_SURVPGC_PYTHON)
    ensure_modalities_allowed(dataset, modality)
    extra_args = list(extra_args or [])
    if results_dir_base is None and "--results_dir" in extra_args:
        flag_idx = extra_args.index("--results_dir")
        if flag_idx + 1 < len(extra_args):
            results_dir_base = extra_args[flag_idx + 1]
    if results_dir_base is None:
        results_dir_base = DEFAULT_RESULTS_DIR
    encoding_value, tag = _infer_encoding_and_landmark(clinic_dir, encoding, landmark_tag)
    experiment_value = experiment if experiment is not None else experiment_from_path(clinic_dir)
    kind_hint = str(kind or exp_group or "greedy")
    kind_value = "univariate" if "univariate" in kind_hint else "greedy"
    nested_exp_group = analyzer_exp_group(
        dataset=dataset,
        encoding=encoding_value,
        landmark_tag=tag,
        experiment=experiment_value,
        kind=kind_value,
        results_dir_base=results_dir_base,
    )
    nested_out_dir = analyzer_results_dir(
        dataset=dataset,
        encoding=encoding_value,
        landmark_tag=tag,
        scheme=scheme,
        modality=modality,
        experiment=experiment_value,
        kind=kind_value,
        results_dir_base=results_dir_base,
    )
    legacy_run_name = analyzer_run_name(dataset, scheme)
    extra_candidates = []
    if exp_group in {None, "", "greedy", "univariate", "longitudinal", "longitudinal_greedy", "longitudinal_univariate"}:
        exp_group = nested_exp_group
        run_name = scheme
        out_dir = nested_out_dir
        extra_candidates.append(
            _legacy_flat_run_dir(
                dataset=dataset,
                scheme=scheme,
                modality=modality,
                experiment=experiment_value,
                kind=kind_value,
                results_dir_base=results_dir_base,
            )
        )
    else:
        run_name = scheme if "/" in str(exp_group) else legacy_run_name
        out_dir = results_dir(
            analyzer_dir,
            exp_group,
            run_name,
            modality,
            results_dir_base=results_dir_base,
        )
    reuse_dir = _existing_result_dir(
        out_dir,
        analyzer_dir=analyzer_dir,
        exp_group=exp_group,
        run_name=run_name,
        modality=modality,
        extra_candidates=extra_candidates,
    )
    if reuse and reuse_dir is not None:
        payload = read_cindex(reuse_dir, prefer_val=prefer_val)
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
    if results_dir_base is not None and "--results_dir" not in extra_args:
        extra_args.extend(["--results_dir", str(results_dir_base)])
    if extra_args:
        cmd.extend(list(extra_args))

    if split_dir is not None:
        cmd.extend(["--split_dir", str(split_dir)])

    env = os.environ.copy()
    proc = subprocess.run(
        cmd,
        cwd=str(analyzer_dir),
        env=env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
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
        tail = (proc.stdout or "").strip()[-2000:]
        extra = f"\n{tail}" if tail else ""
        raise RuntimeError(
            f"Clinic_Analyzer failed for {scheme} (exit {proc.returncode}). "
            f"See {job_log or out_dir}.{extra}"
        )
    payload = read_cindex(out_dir, prefer_val=prefer_val)
    payload.update({"skipped": False, "clinic_dir": str(clinic_dir), "run_name": run_name, "modality": modality})
    if job_log:
        write_job_record(Path(job_log), {**log, **payload})
    return payload
