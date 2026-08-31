"""Encode L0-L5 clinic fields as HGCN-style graph nodes."""

from __future__ import annotations

from pathlib import Path
import json

import joblib
import numpy as np

from .baseline import (
    BASELINE_CONTINUOUS_FIELDS,
    BASELINE_MISSING_TOKEN,
    BASELINE_NOMINAL_FIELDS,
    BASELINE_ORDINAL_FIELDS,
    BASELINE_OTHER_TOKEN,
    BASELINE_SCHEME_FIELDS,
    _aggregate_continuous_value,
    _canonical_nominal_value,
    _encode_ordinal_value,
    build_patient_rows,
    fit_nominal_mappings,
    global_mapping_dir,
)
from .clinical_io import load_clinical_cases, normalize_json_paths


HGCN_PAD_DIM = 1024
HGCN_MINMAX_NAME = "symmetric_to_unit"
HGCN_MISSING_POLICY = "keep_none"
HGCN_NOMINAL_ENCODING = "integer_index_from_d_series_mapping"

HGCN_SCHEME_FIELDS = {
    "L0": BASELINE_SCHEME_FIELDS["D0"],
    "L1": BASELINE_SCHEME_FIELDS["D1"],
    "L2": BASELINE_SCHEME_FIELDS["D2"],
    "L3": BASELINE_SCHEME_FIELDS["D3"],
    "L4": BASELINE_SCHEME_FIELDS["D4"],
    "L5": BASELINE_SCHEME_FIELDS["D5"],
}

ORDINAL_ENCODER_NAMES = {
    "TUMOR_GRADE": "_encode_tumor_grade",
    "AJCC_PATHOLOGIC_T": "_encode_t_stage",
    "AJCC_PATHOLOGIC_N": "_encode_n_stage",
    "AJCC_PATHOLOGIC_M": "_encode_m_stage",
    "AJCC_PATHOLOGIC_STAGE": "_encode_overall_stage",
    "ECOG_PERFORMANCE_STATUS": "_encode_ecog",
}

MISSING_DIAGONAL_NOTE = (
    "x_cli 缺观测的对角位置保持 0.0，含义是这个节点没有写入观测值，"
    "不是把缺失编码成类别 0 / 数值 0。"
)


def resolve_hgcn_schemes(scheme: str) -> list[str]:
    known = list(HGCN_SCHEME_FIELDS.keys())
    if scheme == "all":
        return known
    if scheme not in HGCN_SCHEME_FIELDS:
        raise ValueError(f"未知 HGCN clinic 方案: '{scheme}'。可用方案: {sorted(known)}")
    return [scheme]


def field_type_name(field: str) -> str:
    if field in BASELINE_CONTINUOUS_FIELDS:
        return "continuous"
    if field in BASELINE_ORDINAL_FIELDS:
        return "ordinal"
    if field in BASELINE_NOMINAL_FIELDS:
        return "nominal"
    raise KeyError(f"未知 HGCN clinic 字段: {field}")


def encode_raw_row(row: dict, fields: list[str], nominal_mappings: dict) -> list[float | None]:
    encoded: list[float | None] = []
    for field in fields:
        raw_value = row.get(field)
        if field in BASELINE_CONTINUOUS_FIELDS:
            value = _aggregate_continuous_value(field, raw_value)
            encoded.append(float(value) if value is not None else None)
            continue
        if field in BASELINE_ORDINAL_FIELDS:
            code = _encode_ordinal_value(field, raw_value)
            encoded.append(float(code) if code > 0 else None)
            continue
        if field in BASELINE_NOMINAL_FIELDS:
            value = _canonical_nominal_value(raw_value)
            if value == BASELINE_MISSING_TOKEN:
                encoded.append(None)
            else:
                mapping = nominal_mappings[field]
                encoded.append(float(mapping.get(value, mapping[BASELINE_OTHER_TOKEN])))
            continue
        raise KeyError(f"未知 HGCN clinic 字段: {field}")
    return encoded


def minmax_symmetric(
    values_by_patient: dict[str, list[float | None]],
    n_cli: int,
) -> dict[str, list[float | None]]:
    mins: list[float | None] = [None] * n_cli
    maxs: list[float | None] = [None] * n_cli
    for row in values_by_patient.values():
        for i, value in enumerate(row):
            if value is None:
                continue
            number = float(value)
            if mins[i] is None or number < mins[i]:
                mins[i] = number
            if maxs[i] is None or number > maxs[i]:
                maxs[i] = number

    scaled: dict[str, list[float | None]] = {}
    for patient_id, row in values_by_patient.items():
        new_row: list[float | None] = []
        for i, value in enumerate(row):
            if value is None:
                new_row.append(None)
                continue
            vmin = mins[i]
            vmax = maxs[i]
            if vmin is None or vmax is None:
                new_row.append(None)
            elif vmax == vmin:
                new_row.append(0.0)
            else:
                new_row.append(float((float(value) - (vmax + vmin) / 2.0) / (vmax - vmin) * 2.0))
        scaled[patient_id] = new_row
    return scaled


def diagonal_pad(values: list[float | None], dim: int = HGCN_PAD_DIM) -> np.ndarray:
    n_cli = len(values)
    x_cli = np.zeros((n_cli, dim), dtype=np.float32)
    for i, value in enumerate(values):
        if value is not None:
            x_cli[i, i] = np.float32(value)
    return x_cli


def full_connect_edges(n_cli: int) -> np.ndarray:
    start: list[int] = []
    end: list[int] = []
    for i in range(n_cli):
        for j in range(n_cli):
            if i != j:
                start.append(j)
                end.append(i)
    return np.array([start, end], dtype=np.int64)


def _load_d_series_nominal_mappings(mapping_path: Path | None = None) -> tuple[dict | None, dict | None]:
    path = Path(mapping_path) if mapping_path else global_mapping_dir() / "category_mapping.json"
    if not path.exists():
        return None, None
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    mappings = {
        field: {str(key): int(index) for key, index in mapping.items()}
        for field, mapping in payload["fields"].items()
    }
    scope = dict(payload.get("mapping_scope") or {})
    scope.setdefault("type", "d_series_mapping_file")
    scope["path"] = str(path)
    return mappings, scope


def prepare_hgcn_nominal_mappings(
    jobs: list[dict],
    min_count: int = 5,
) -> tuple[dict | None, dict | None]:
    mappings, scope = _load_d_series_nominal_mappings()
    if mappings is not None:
        mapping_path = global_mapping_dir() / "category_mapping.json"
        print(f"[hgcn_clinic] 复用 D 组名义词表: {mapping_path}")
        return mappings, scope
    if len(jobs) <= 1:
        return None, None

    print(f"\n{'=' * 55}")
    print("[hgcn_clinic] 构建多数据集共享名义词表")
    print(f"  频次阈值 : >= {min_count}")
    print(f"{'=' * 55}")
    merged_rows = []
    dataset_names = []
    for job in jobs:
        if job["name"]:
            print(f"  -> 收集 {job['name']} 患者用于共享 nominal 词表")
            dataset_names.append(job["name"])
        cases = load_clinical_cases(job["json_paths"], project_ids=job["project_ids"])
        merged_rows.extend(build_patient_rows(cases))
    mappings = fit_nominal_mappings(
        merged_rows,
        min_count=min_count,
        collapse_rare=True,
    )
    scope = {
        "type": "global_selected_datasets",
        "datasets": dataset_names,
        "patient_count": len(merged_rows),
    }
    return mappings, scope


def _scheme_nominal_mappings(fields: list[str], nominal_mappings: dict) -> dict:
    return {
        field: dict(nominal_mappings[field])
        for field in fields
        if field in BASELINE_NOMINAL_FIELDS
    }


def _scheme_ordinal_encoders(fields: list[str]) -> dict:
    return {
        field: ORDINAL_ENCODER_NAMES[field]
        for field in fields
        if field in BASELINE_ORDINAL_FIELDS
    }


def _coverage_from_raw(values_by_patient: dict[str, list[float | None]], fields: list[str]) -> dict:
    n_patients = len(values_by_patient)
    coverage = {}
    for i, field in enumerate(fields):
        n_observed = sum(row[i] is not None for row in values_by_patient.values())
        n_missing = n_patients - n_observed
        percent_observed = 0.0 if n_patients == 0 else 100.0 * n_observed / n_patients
        coverage[field] = {
            "n_observed": n_observed,
            "n_missing": n_missing,
            "percent_observed": percent_observed,
        }
    return coverage


def _write_json(path: Path, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _write_summary(
    path: Path,
    *,
    dataset_name: str,
    scheme: str,
    n_cli: int,
    n_patients: int,
    fields: list[str],
    coverage: dict,
    scheme_dir: Path,
) -> None:
    lines = [
        f"# HGCN clinic {scheme}",
        "",
        f"- dataset: {dataset_name}",
        f"- scheme: {scheme}",
        f"- n_patients: {n_patients}",
        f"- n_cli: {n_cli}",
        f"- pad_dim: {HGCN_PAD_DIM}",
        f"- minmax: {HGCN_MINMAX_NAME}",
        f"- missing_policy: {HGCN_MISSING_POLICY}",
        f"- nominal_encoding: {HGCN_NOMINAL_ENCODING}",
        f"- output: {scheme_dir}",
        "",
        "## Fields",
        "",
        "| field | type | n_observed | n_missing | percent_observed |",
        "|---|---|---:|---:|---:|",
    ]
    for field in fields:
        cov = coverage[field]
        lines.append(
            f"| {field} | {field_type_name(field)} | {cov['n_observed']} | "
            f"{cov['n_missing']} | {cov['percent_observed']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Missing",
            "",
            "ttt_cli_feas / t_cli_feas 的缺失位置保持 None，不填中位数、众数或 0 类。",
            MISSING_DIAGONAL_NOTE,
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_hgcn_clinic(
    json_paths,
    schemes: list[str],
    out_root: str,
    project_ids: list | None = None,
    nominal_min_count: int = 5,
    shared_nominal_mappings: dict | None = None,
    mapping_scope: dict | None = None,
    dataset_name: str | None = None,
):
    dataset_label = dataset_name or "custom"
    print(f"\n{'=' * 55}")
    print("[hgcn_clinic] HGCN clinic 图节点编码")
    print(f"  数据集   : {dataset_label}")
    print(f"  JSON     : {normalize_json_paths(json_paths)}")
    print(f"  方案     : {schemes}")
    print(f"  输出根目录 : {out_root}")
    print(f"{'=' * 55}")

    print("\n[1/3] 读取 JSON ...")
    cases = load_clinical_cases(json_paths, project_ids=project_ids)
    patient_rows = build_patient_rows(cases)
    print(f"      患者数: {len(patient_rows)}")

    if shared_nominal_mappings is not None:
        nominal_mappings = shared_nominal_mappings
        mapping_source = mapping_scope or {"type": "shared"}
    else:
        loaded_mappings, loaded_scope = _load_d_series_nominal_mappings()
        if loaded_mappings is not None:
            nominal_mappings = loaded_mappings
            mapping_source = loaded_scope
            print(f"      名义词表: {mapping_source.get('path')}")
        else:
            nominal_mappings = fit_nominal_mappings(
                patient_rows,
                min_count=nominal_min_count,
                collapse_rare=True,
            )
            mapping_source = {
                "type": "fit_current_patients",
                "patient_count": len(patient_rows),
                "nominal_min_count": nominal_min_count,
            }
            print("      名义词表: 当前队列拟合")

    print("\n[2/3] 按方案编码图节点 ...")
    out_root_path = Path(out_root)
    for scheme in schemes:
        fields = list(HGCN_SCHEME_FIELDS[scheme])
        n_cli = len(fields)
        scheme_dir = out_root_path / scheme
        scheme_dir.mkdir(parents=True, exist_ok=True)

        ttt_cli_feas = {}
        for row in patient_rows:
            ttt_cli_feas[row["patient_id"]] = encode_raw_row(row, fields, nominal_mappings)
        t_cli_feas = minmax_symmetric(ttt_cli_feas, n_cli)
        x_cli = {
            patient_id: diagonal_pad(values, dim=HGCN_PAD_DIM)
            for patient_id, values in t_cli_feas.items()
        }
        edge_index_cli = full_connect_edges(n_cli)
        coverage = _coverage_from_raw(ttt_cli_feas, fields)
        scheme_nominal = _scheme_nominal_mappings(fields, nominal_mappings)
        scheme_ordinal = _scheme_ordinal_encoders(fields)

        joblib.dump(ttt_cli_feas, scheme_dir / "ttt_cli_feas.pkl")
        joblib.dump(t_cli_feas, scheme_dir / "t_cli_feas.pkl")
        joblib.dump(x_cli, scheme_dir / "x_cli.pkl")
        joblib.dump(edge_index_cli, scheme_dir / "edge_index_cli.pkl")

        _write_json(
            scheme_dir / "encoding_table.json",
            {
                "scheme": scheme,
                "nominal_encoding": HGCN_NOMINAL_ENCODING,
                "missing_token": BASELINE_MISSING_TOKEN,
                "other_token": BASELINE_OTHER_TOKEN,
                "mapping_scope": mapping_source,
                "nominal_mappings": scheme_nominal,
                "ordinal_encoders": scheme_ordinal,
            },
        )
        _write_json(scheme_dir / "coverage.json", coverage)
        _write_json(
            scheme_dir / "field_schema.json",
            {
                "dataset": dataset_label,
                "scheme": scheme,
                "n_cli": n_cli,
                "fields": fields,
                "field_types": {field: field_type_name(field) for field in fields},
                "pad_dim": HGCN_PAD_DIM,
                "minmax": HGCN_MINMAX_NAME,
                "missing_policy": HGCN_MISSING_POLICY,
                "nominal_encoding": HGCN_NOMINAL_ENCODING,
                "patient_id_field": "submitter_id",
                "n_patients": len(patient_rows),
                "missing_note": MISSING_DIAGONAL_NOTE,
            },
        )
        _write_summary(
            scheme_dir / "summary.md",
            dataset_name=dataset_label,
            scheme=scheme,
            n_cli=n_cli,
            n_patients=len(patient_rows),
            fields=fields,
            coverage=coverage,
            scheme_dir=scheme_dir,
        )

        print(f"\n      {scheme}: 病人数={len(patient_rows)}  N_cli={n_cli}")
        print(f"        输出目录: {scheme_dir}")
        for field in fields:
            percent = coverage[field]["percent_observed"]
            print(
                f"        {field}: {percent:.1f}% observed "
                f"({coverage[field]['n_observed']}/{len(patient_rows)})"
            )

    print("\n[3/3] 完成")
    print("=" * 55)
    print("[hgcn_clinic] 编码完成")
    print(f"   数据集   : {dataset_label}")
    print(f"   患者数   : {len(patient_rows)}")
    print(f"   输出根目录 : {out_root_path}")
    print("=" * 55)
