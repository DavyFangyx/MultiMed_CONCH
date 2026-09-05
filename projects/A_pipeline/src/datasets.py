"""Dataset jobs for A_pipeline. Registry helpers come from src/common."""

from __future__ import annotations

from common.datasets import (
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

__all__ = [
    "dataset_jobs",
    "get_dataset_clinic_files",
    "get_dataset_project_ids",
    "load_dataset_configs",
    "resolve_dataset_names",
]


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
