"""Official GDC mapping vs scanned JSON field presence census."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import (
    DEFAULT_GDC_CASES_MAPPING,
    PROJECT_ROOT,
    RAWDATA_STATS_SHARED_DIR,
    dataset_field_dict_path,
    dataset_field_presence_path,
    dataset_field_presence_summary_path,
    shared_field_presence_mapping_census_path,
    shared_field_presence_not_in_table_path,
    shared_field_presence_path,
    shared_field_presence_summary_path,
)
from .scan import (
    count_dict_fields,
    load_json_field_dictionary,
    parse_field_dictionary,
)

STATUS_IN_TABLE_AND_DATA = "in_table_and_data"
STATUS_IN_TABLE_NOT_DATA = "in_table_not_data"
STATUS_NOT_IN_TABLE = "not_in_table"
STATUS_ORDER = {
    STATUS_IN_TABLE_AND_DATA: 0,
    STATUS_IN_TABLE_NOT_DATA: 1,
    STATUS_NOT_IN_TABLE: 2,
}
PRESENCE_COLUMNS = [
    "dataset",
    "mapping_field",
    "scan_field_path",
    "entity",
    "status",
    "n_cases",
]
SUMMARY_COLUMNS = [
    "dataset",
    "n_cases",
    "n_mapping_fields",
    "n_scanned_fields",
    "in_table_and_data",
    "in_table_not_data",
    "not_in_table",
    "source_scanned_fields",
]


def strip_array_markers(path: str) -> str:
    """Drop scan-style [] so paths match official mapping fields."""
    return str(path).replace("[]", "")


def align_scan_path_to_mapping(path: str) -> str:
    """Normalize a scanned field path onto the official mapping universe."""
    return strip_array_markers(path)


def load_official_mapping(mapping_csv=None) -> pd.DataFrame:
    path = Path(mapping_csv) if mapping_csv else DEFAULT_GDC_CASES_MAPPING
    df = pd.read_csv(path)
    required = {"field", "entity"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"mapping 缺少列 {sorted(missing)}: {path}")
    out = df.loc[:, ["field", "entity"]].copy()
    out["field"] = out["field"].astype(str)
    out["entity"] = out["entity"].fillna("").astype(str)
    if out["field"].duplicated().any():
        dupes = out.loc[out["field"].duplicated(), "field"].tolist()
        raise ValueError(f"mapping field 重复: {dupes[:10]}")
    return out.reset_index(drop=True)


def scanned_fields_from_dict(dict_data: dict) -> list[dict]:
    fields = parse_field_dictionary(dict_data)
    out = []
    seen = set()
    for fd in fields:
        scan_path = fd["field_path"]
        mapping_field = align_scan_path_to_mapping(scan_path)
        if mapping_field in seen:
            raise ValueError(f"扫描路径对齐后重复: {mapping_field}")
        seen.add(mapping_field)
        out.append(
            {
                "scan_field_path": scan_path,
                "mapping_field": mapping_field,
                "field_name": fd["field_name"],
                "section": fd["section"],
            }
        )
    return out


def census_dataset_presence(
    dataset_name: str,
    dict_data: dict,
    mapping_df: pd.DataFrame,
    source_scanned_fields: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    n_cases = int((dict_data.get("_meta") or {}).get("n_cases") or 0)
    scanned = scanned_fields_from_dict(dict_data)
    scanned_by_field = {row["mapping_field"]: row for row in scanned}
    mapping_fields = list(mapping_df["field"])
    entity_by_field = dict(zip(mapping_df["field"], mapping_df["entity"]))
    mapping_set = set(mapping_fields)

    rows = []
    for field in mapping_fields:
        scan_row = scanned_by_field.get(field)
        rows.append(
            {
                "dataset": dataset_name,
                "mapping_field": field,
                "scan_field_path": "" if scan_row is None else scan_row["scan_field_path"],
                "entity": entity_by_field.get(field, ""),
                "status": STATUS_IN_TABLE_AND_DATA if scan_row is not None else STATUS_IN_TABLE_NOT_DATA,
                "n_cases": n_cases,
            }
        )

    extra_fields = [row["mapping_field"] for row in scanned if row["mapping_field"] not in mapping_set]
    extra_fields.sort()
    for field in extra_fields:
        scan_row = scanned_by_field[field]
        rows.append(
            {
                "dataset": dataset_name,
                "mapping_field": field,
                "scan_field_path": scan_row["scan_field_path"],
                "entity": "",
                "status": STATUS_NOT_IN_TABLE,
                "n_cases": n_cases,
            }
        )

    presence = pd.DataFrame(rows, columns=PRESENCE_COLUMNS)
    presence["_status_rank"] = presence["status"].map(STATUS_ORDER)
    presence = presence.sort_values(["_status_rank", "mapping_field"], kind="mergesort").drop(columns=["_status_rank"])
    presence = presence.reset_index(drop=True)

    n_mapping_fields = len(mapping_fields)
    n_scanned_fields = count_dict_fields(dict_data)
    n_in_table_and_data = int((presence["status"] == STATUS_IN_TABLE_AND_DATA).sum())
    n_in_table_not_data = int((presence["status"] == STATUS_IN_TABLE_NOT_DATA).sum())
    n_not_in_table = int((presence["status"] == STATUS_NOT_IN_TABLE).sum())
    if n_in_table_and_data + n_in_table_not_data != n_mapping_fields:
        raise ValueError(
            f"{dataset_name}: in_table_and_data + in_table_not_data != n_mapping_fields "
            f"({n_in_table_and_data} + {n_in_table_not_data} != {n_mapping_fields})"
        )
    if n_in_table_and_data + n_not_in_table != n_scanned_fields:
        raise ValueError(
            f"{dataset_name}: in_table_and_data + not_in_table != n_scanned_fields "
            f"({n_in_table_and_data} + {n_not_in_table} != {n_scanned_fields})"
        )

    summary = {
        "dataset": dataset_name,
        "n_cases": n_cases,
        "n_mapping_fields": n_mapping_fields,
        "n_scanned_fields": n_scanned_fields,
        "in_table_and_data": n_in_table_and_data,
        "in_table_not_data": n_in_table_not_data,
        "not_in_table": n_not_in_table,
        "source_scanned_fields": source_scanned_fields or "",
    }
    return presence, summary


def write_json(data: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def build_mapping_census(
    mapping_df: pd.DataFrame,
    presence_frames: list[pd.DataFrame],
    dataset_names: list[str],
) -> pd.DataFrame:
    present = {}
    for df in presence_frames:
        hit = df.loc[df["status"] == STATUS_IN_TABLE_AND_DATA, ["dataset", "mapping_field"]]
        for dataset, field in hit.itertuples(index=False):
            present.setdefault(field, []).append(dataset)

    n_total = len(dataset_names)
    rows = []
    for field, entity in zip(mapping_df["field"], mapping_df["entity"]):
        datasets = [name for name in dataset_names if name in set(present.get(field, []))]
        rows.append(
            {
                "mapping_field": field,
                "entity": entity,
                "n_datasets_present": len(datasets),
                "n_datasets_total": n_total,
                "present_datasets": ",".join(datasets),
            }
        )
    return pd.DataFrame(rows)



def build_not_in_table_census(
    presence_frames: list[pd.DataFrame],
    dataset_names: list[str],
) -> pd.DataFrame:
    by_field = {}
    for df in presence_frames:
        extra = df.loc[
            df["status"] == STATUS_NOT_IN_TABLE,
            ["dataset", "mapping_field", "scan_field_path"],
        ]
        for dataset, field, scan_path in extra.itertuples(index=False):
            rec = by_field.setdefault(
                field,
                {"scan_field_path": scan_path, "datasets": []},
            )
            if rec["scan_field_path"] == "":
                rec["scan_field_path"] = scan_path
            rec["datasets"].append(dataset)

    n_total = len(dataset_names)
    rows = []
    for field in sorted(by_field):
        datasets = [name for name in dataset_names if name in set(by_field[field]["datasets"])]
        rows.append(
            {
                "mapping_field": field,
                "scan_field_path": by_field[field]["scan_field_path"],
                "n_datasets_present": len(datasets),
                "n_datasets_total": n_total,
                "present_datasets": ",".join(datasets),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "mapping_field",
            "scan_field_path",
            "n_datasets_present",
            "n_datasets_total",
            "present_datasets",
        ],
    )

def run_field_presence(args):
    datasets = load_dataset_configs(args.datasets_config)
    dataset_names = resolve_dataset_names(args.dataset, datasets)
    if not dataset_names:
        raise ValueError("请通过 --dataset 指定数据集，或使用 --dataset all")

    mapping_df = load_official_mapping(getattr(args, "mapping_csv", None))
    RAWDATA_STATS_SHARED_DIR.mkdir(parents=True, exist_ok=True)

    presence_frames = []
    summaries = []
    for name in dataset_names:
        print(f"\n######## Dataset: {name} ########")
        dict_path = dataset_field_dict_path(name)
        if not dict_path.exists():
            raise FileNotFoundError(
                f"未找到扫描字典: {dict_path}。请先运行 python projects/scripts/run_scan_fields.py --dataset {name}"
            )
        dict_data = load_json_field_dictionary(dict_path)
        try:
            source = str(dict_path.relative_to(PROJECT_ROOT))
        except ValueError:
            source = str(dict_path)
        presence, summary = census_dataset_presence(
            name,
            dict_data,
            mapping_df,
            source_scanned_fields=source,
        )
        out_csv = dataset_field_presence_path(name)
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        presence.to_csv(out_csv, index=False)
        write_json(summary, dataset_field_presence_summary_path(name))
        print(
            f"  n_cases={summary['n_cases']}  scanned={summary['n_scanned_fields']}  "
            f"in_table_and_data={summary['in_table_and_data']}  "
            f"in_table_not_data={summary['in_table_not_data']}  "
            f"not_in_table={summary['not_in_table']}"
        )
        print(f"  明细: {out_csv}")
        presence_frames.append(presence)
        summaries.append(summary)

    shared_presence = pd.concat(presence_frames, ignore_index=True)
    shared_presence.to_csv(shared_field_presence_path(), index=False)
    summary_df = pd.DataFrame(summaries, columns=SUMMARY_COLUMNS)
    summary_df.to_csv(shared_field_presence_summary_path(), index=False)
    census = build_mapping_census(mapping_df, presence_frames, dataset_names)
    census.to_csv(shared_field_presence_mapping_census_path(), index=False)
    extras = build_not_in_table_census(presence_frames, dataset_names)
    extras.to_csv(shared_field_presence_not_in_table_path(), index=False)
    print(f"\n跨数据集明细: {shared_field_presence_path()}")
    print(f"跨数据集计数: {shared_field_presence_summary_path()}")
    print(f"mapping 普查: {shared_field_presence_mapping_census_path()}")
    print(f"not_in_table 字段: {shared_field_presence_not_in_table_path()}")
