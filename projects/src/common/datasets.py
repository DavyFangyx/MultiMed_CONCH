"""Dataset registry helpers shared by scheme and discovery workflows."""

from __future__ import annotations

import json
from pathlib import Path

from .paths import (
    dataset_baseline_embedding_dir,
    dataset_embedding_dir,
    dataset_prompt_dir,
)


def load_dataset_configs(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"数据集配置不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"数据集配置必须是 JSON object: {path}")
    return data


def resolve_dataset_names(dataset_arg: str | None, datasets: dict) -> list[str]:
    if not dataset_arg:
        return []
    if dataset_arg == "all":
        return list(datasets.keys())

    names = [x.strip() for x in dataset_arg.split(",") if x.strip()]
    unknown = [x for x in names if x not in datasets]
    if unknown:
        raise ValueError(f"未知 dataset: {unknown}; 可用: {sorted(datasets)}")
    return names


def get_dataset_config(dataset_name: str, datasets: dict) -> dict:
    return dict(datasets[dataset_name])


def get_dataset_clinic_files(dataset_name: str, datasets: dict) -> list:
    cfg = datasets[dataset_name]
    files = cfg.get("clinic_files", [])
    if not files:
        raise ValueError(f"dataset '{dataset_name}' 没有配置 clinic_files")
    return list(files)


def get_dataset_project_ids(dataset_name: str, datasets: dict) -> list:
    cfg = datasets[dataset_name]
    return list(cfg.get("project_ids", []))


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
