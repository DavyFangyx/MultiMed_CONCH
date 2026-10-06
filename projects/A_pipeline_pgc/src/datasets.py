"""Dataset jobs for the standalone PGC line. Registry helpers come from local common.

从 A_pipeline/src/datasets.py 复制并按线裁剪：只有 lizhe 一个数据源，
`expand_source_jobs` 不再做双源分组（源恒为 "lizhe"）。
"""

from __future__ import annotations

from common.datasets import (
    DATASET_ALIASES,
    canonical_dataset_name,
    get_dataset_clinic_files,
    get_dataset_project_ids,
    load_dataset_configs,
    resolve_dataset_names,
)
from .paths import (
    dataset_baseline_embedding_dir,
    dataset_embedding_dir,
    dataset_prompt_dir,
)

SOURCE_NAME = "lizhe"

__all__ = [
    "SOURCE_NAME",
    "dataset_jobs",
    "get_dataset_clinic_files",
    "get_dataset_project_ids",
    "load_dataset_configs",
    "resolve_dataset_names",
    "load_source_dataset_configs",
    "expand_source_jobs",
]


def load_source_dataset_configs(config: str) -> dict[str, dict]:
    """本线只有一个数据源,保留 dict 形状（{"lizhe": {...}}）便于调用方复用。"""
    return {SOURCE_NAME: load_dataset_configs(config)}


def _names_in_source(dataset_arg: str | None, datasets: dict) -> list[str]:
    if not dataset_arg or dataset_arg == "all":
        return list(datasets.keys())

    names = []
    for raw in dataset_arg.split(","):
        raw = raw.strip()
        if not raw:
            continue
        canonical = canonical_dataset_name(raw, datasets)
        canonical = DATASET_ALIASES.get(canonical, canonical)
        if canonical in datasets and canonical not in names:
            names.append(canonical)
    return names


def _unknown_requested_names(dataset_arg: str | None, datasets: dict) -> list[str]:
    if not dataset_arg or dataset_arg == "all":
        return []
    unknown = []
    for raw in dataset_arg.split(","):
        raw = raw.strip()
        if not raw:
            continue
        canonical = canonical_dataset_name(raw, datasets)
        canonical = DATASET_ALIASES.get(canonical, canonical)
        if canonical not in datasets:
            unknown.append(raw)
    return unknown


def _bound_names(scheme: str, datasets: dict) -> list[str] | None:
    from .config import scheme_bound_datasets

    bound = scheme_bound_datasets(scheme)
    if bound is None:
        return None
    return [name for name in bound if name in datasets]


def expand_source_jobs(
    dataset_arg: str | None,
    schemes: list[str],
    source_datasets: dict[str, dict],
    *,
    json_path: str,
    prompt_dir: str,
    out_dir: str,
    baseline_out: str,
) -> list[dict]:
    from .config import schemes_for_dataset

    if not dataset_arg:
        return [
            {
                "name": None,
                "source": None,
                "json_paths": [json_path],
                "project_ids": [],
                "prompt_dir": prompt_dir,
                "out_dir": out_dir,
                "baseline_out_dir": baseline_out,
                "schemes": list(schemes),
                "datasets": {},
            }
        ]

    datasets = source_datasets.get(SOURCE_NAME) or {}
    unknown = _unknown_requested_names(dataset_arg, datasets)
    if unknown:
        raise ValueError(f"未知 dataset: {unknown}; 可用: {sorted(datasets)}")

    grouped: dict[str, dict] = {}
    for scheme in schemes:
        bound = _bound_names(scheme, datasets)
        if bound is None:
            names = _names_in_source(dataset_arg, datasets)
        elif dataset_arg == "all":
            names = bound
        else:
            requested = set(_names_in_source(dataset_arg, datasets))
            names = [name for name in bound if name in requested]
        for name in names:
            if not schemes_for_dataset([scheme], name, datasets):
                continue
            job = grouped.get(name)
            if job is None:
                job = {
                    "name": name,
                    "source": SOURCE_NAME,
                    "json_paths": get_dataset_clinic_files(name, datasets),
                    "project_ids": get_dataset_project_ids(name, datasets),
                    "prompt_dir": dataset_prompt_dir(name),
                    "out_dir": dataset_embedding_dir(name),
                    "baseline_out_dir": dataset_baseline_embedding_dir(name, baseline_out),
                    "schemes": [],
                    "datasets": datasets,
                }
                grouped[name] = job
            if scheme not in job["schemes"]:
                job["schemes"].append(scheme)

    jobs = list(grouped.values())
    jobs.sort(key=lambda job: job["name"] or "")
    return jobs


def dataset_jobs(
    dataset_arg: str | None,
    datasets: dict,
    *,
    json_path: str,
    prompt_dir: str,
    out_dir: str,
    baseline_out: str,
) -> list[dict]:
    names = resolve_dataset_names(dataset_arg, datasets)
    if not names:
        return [
            {
                "name": None,
                "json_paths": [json_path],
                "project_ids": [],
                "prompt_dir": prompt_dir,
                "out_dir": out_dir,
                "baseline_out_dir": baseline_out,
            }
        ]
    return [
        {
            "name": name,
            "json_paths": get_dataset_clinic_files(name, datasets),
            "project_ids": get_dataset_project_ids(name, datasets),
            "prompt_dir": dataset_prompt_dir(name),
            "out_dir": dataset_embedding_dir(name),
            "baseline_out_dir": dataset_baseline_embedding_dir(name, baseline_out),
        }
        for name in names
    ]
