"""Encode L0-L5 / registered-scheme clinic fields as HGCN-style graph nodes."""

from __future__ import annotations

from pathlib import Path
import json

import joblib
import numpy as np

from .config import DEFAULT_TEXT_SCHEMES, resolve_scheme_names
from .baseline import (
    BASELINE_CONTINUOUS_FIELDS,
    BASELINE_DICTIONARY_FIELD_TYPES,
    BASELINE_MISSING_TOKEN,
    BASELINE_NOMINAL_FIELDS,
    BASELINE_ORDINAL_FIELDS,
    BASELINE_OTHER_TOKEN,
    BASELINE_SCHEME_FIELDS,
    _aggregate_continuous_value,
    _canonical_nominal_value,
    _encode_ordinal_value,
    _fit_category_mappings,
    build_patient_rows,
    fit_nominal_mappings,
    global_mapping_dir,
)
from .landmark import landmark_dir
from common.clinical_io import load_clinical_cases, normalize_json_paths
from common.fields import (
    HUMAN_SCHEME_FIELDS,
    L5_FIELD_PATH_BY_PLACEHOLDER,
    L5_PLACEHOLDER_BY_FIELD_PATH,
)


HGCN_PAD_DIM = 1024
HGCN_MINMAX_NAME = "symmetric_to_unit"
HGCN_MISSING_POLICY = "keep_none"
HGCN_NOMINAL_ENCODING = "integer_index_from_d_series_mapping"

# 提取器（extract_values / 32 字段词表）解析不了的方案字段保持缺观测：
# 对角 0 行、coverage 记 0% observed，不抛错也不造类别 0。
HGCN_KEEP_NONE_TYPE = "keep_none"

# L0-L5 = 冻结命名空间：产物节点名沿用备份里的占位符（AGE / SEX_AT_BIRTH / …）。
HGCN_LEGACY_PLACEHOLDER_SCHEMES = tuple(DEFAULT_TEXT_SCHEMES)

HGCN_SCHEME_FIELDS = {}

ORDINAL_ENCODER_NAMES = {
    "diagnoses[].tumor_grade": "_encode_tumor_grade",
    "diagnoses[].ajcc_pathologic_t": "_encode_t_stage",
    "diagnoses[].ajcc_pathologic_n": "_encode_n_stage",
    "diagnoses[].ajcc_pathologic_m": "_encode_m_stage",
    "diagnoses[].ajcc_pathologic_stage": "_encode_overall_stage",
    "follow_ups[].ecog_performance_status": "_encode_ecog",
}


def load_hgcn_scheme_fields(text_scheme_fields: dict[str, list[str]]) -> None:
    """注册全部已加载方案：L0-L5 + 论文方案 + templates 下的自定义方案。

    与 baseline 同一条装载路径（config.load_custom_schemes → SCHEME_FIELDS），
    字段列表全部来自各方案自己的 fields.json。
    """
    HGCN_SCHEME_FIELDS.clear()
    for name in HGCN_LEGACY_PLACEHOLDER_SCHEMES:
        if name not in text_scheme_fields:
            raise ValueError(f"缺少文本方案 {name}，无法注册 HGCN clinic 字段")
    for name, fields in text_scheme_fields.items():
        HGCN_SCHEME_FIELDS[name] = list(fields)

MISSING_DIAGONAL_NOTE = (
    "x_cli 缺观测的对角位置保持 0.0，含义是这个节点没有写入观测值，"
    "不是把缺失编码成类别 0 / 数值 0。"
)


def resolve_hgcn_schemes(scheme: str) -> list[str]:
    """L0-L5 与今天完全一致；此外接受任意已注册方案（fields.json 驱动）。

    `manual` / `all` 都只展开 L0-L5（`all` 保持旧行为）：既有产物树
    outputs/{ds}/A_manual/HGCN_clinic/ 属于 L0-L5，论文 / 自定义方案必须显式
    点名（或 `--scheme paper`），避免默认命令把新方案写进冻结目录。
    """
    if scheme in ("manual", "all"):
        missing = [name for name in HGCN_LEGACY_PLACEHOLDER_SCHEMES if name not in HGCN_SCHEME_FIELDS]
        if missing:
            raise ValueError(f"缺少 L0-L5 方案注册: {missing}")
        return list(HGCN_LEGACY_PLACEHOLDER_SCHEMES)
    names = resolve_scheme_names(scheme)
    unsupported = [name for name in names if name not in HGCN_SCHEME_FIELDS]
    if unsupported:
        raise ValueError(f"hgcn_clinic 无法编码方案 {unsupported}: 缺少字段注册")
    return names


def artifact_field_name(scheme: str, field: str) -> str:
    """节点在产物里的名字（coverage / encoding_table / field_schema / summary）。

    L0-L5 = 冻结命名空间：沿用备份产物的占位符（AGE / SEX_AT_BIRTH / …），与
    outputs/{ds}/A_manual/HGCN_clinic/L{0-5}/ 的冻结产物逐字一致；
    其余方案 = 新命名空间：直接用 fields.json 的字段路径。
    """
    if scheme in HGCN_LEGACY_PLACEHOLDER_SCHEMES:
        return L5_PLACEHOLDER_BY_FIELD_PATH.get(field, field)
    return field


def field_type_name(field: str) -> str:
    """节点类型：冻结三分法优先，其余按 D 向量同一套 GDC 字典结论，无法解析 → keep_none。"""
    if field in BASELINE_CONTINUOUS_FIELDS:
        return "continuous"
    if field in BASELINE_ORDINAL_FIELDS:
        return "ordinal"
    if field in BASELINE_NOMINAL_FIELDS:
        return "nominal"
    if field in HUMAN_SCHEME_FIELDS:
        # 提取器能解析、但不在冻结三分法里的字段（project.project_id / derived.* 等）：
        # 复用 baseline 对同一份 GDC dictionary 的分类（enum/boolean→nominal，integer/number→continuous）。
        return BASELINE_DICTIONARY_FIELD_TYPES[field]
    # 提取器解析不了（例如 Test_3 字段银行的 diagnoses[].calgb_risk_group）：keep_none，不抛错。
    return HGCN_KEEP_NONE_TYPE


def encode_raw_row(row: dict, fields: list[str], nominal_mappings: dict) -> list[float | None]:
    encoded: list[float | None] = []
    for field in fields:
        raw_value = row.get(field)
        kind = field_type_name(field)
        if kind == HGCN_KEEP_NONE_TYPE:
            # 提取器解析不了的字段：无论 row 里有没有同名键，都按缺观测处理。
            encoded.append(None)
            continue
        if kind == "continuous":
            value = _aggregate_continuous_value(field, raw_value)
            encoded.append(float(value) if value is not None else None)
            continue
        if kind == "ordinal":
            code = _encode_ordinal_value(field, raw_value)
            encoded.append(float(code) if code > 0 else None)
            continue
        if kind == "nominal":
            value = _canonical_nominal_value(raw_value)
            if value == BASELINE_MISSING_TOKEN:
                encoded.append(None)
            else:
                mapping = nominal_mappings[field]
                encoded.append(float(mapping.get(value, mapping[BASELINE_OTHER_TOKEN])))
            continue
        raise KeyError(f"未知 HGCN clinic 字段类型: {field} -> {kind}")
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
        # 共享词表用 D 组占位键（SEX_AT_BIRTH…），方案字段是 GDC 路径（demographic.sex_at_birth…），
        # 统一归一化成 GDC 路径后再返回。
        L5_FIELD_PATH_BY_PLACEHOLDER.get(field, field): {
            str(key): int(index) for key, index in mapping.items()
        }
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
        if field_type_name(field) == "nominal" and field in nominal_mappings
    }


def _scheme_ordinal_encoders(fields: list[str]) -> dict:
    return {
        field: ORDINAL_ENCODER_NAMES[field]
        for field in fields
        if field in BASELINE_ORDINAL_FIELDS
    }


def _scheme_extra_nominal_mappings(
    patient_rows: list[dict],
    fields: list[str],
    nominal_mappings: dict,
    min_count: int,
) -> dict:
    """方案里不在共享/冻结词表内的 nominal 字段：按当前患者拟合（与 D 向量同一口径）。"""
    extras = [
        field
        for field in fields
        if field_type_name(field) == "nominal" and field not in nominal_mappings
    ]
    if not extras:
        return {}
    return _fit_category_mappings(patient_rows, extras, min_count=min_count, collapse_rare=True)


def _artifact_named_mapping(mapping: dict, scheme: str) -> dict:
    """把映射键换成产物节点名（L0-L5 → 占位符；其余 → 字段路径），保持插入顺序。"""
    return {artifact_field_name(scheme, key): value for key, value in mapping.items()}


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
    display_fields: list[str],
    coverage: dict,
    scheme_dir: Path,
    landmark_time=None,
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
    ]
    if landmark_time is not None:
        lines.append(f"- landmark: t_hi <= {int(landmark_time)} days")
    lines.extend(
        [
            "",
            "## Fields",
            "",
            "| field | type | n_observed | n_missing | percent_observed |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for display_field, field in zip(display_fields, fields):
        cov = coverage[display_field]
        lines.append(
            f"| {display_field} | {field_type_name(field)} | {cov['n_observed']} | "
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
    landmark_time=None,
    landmark_subdir: str = "",
):
    dataset_label = dataset_name or "custom"
    print(f"\n{'=' * 55}")
    print("[hgcn_clinic] HGCN clinic 图节点编码")
    print(f"  数据集   : {dataset_label}")
    print(f"  JSON     : {normalize_json_paths(json_paths)}")
    print(f"  方案     : {schemes}")
    print(f"  输出根目录 : {out_root}")
    if landmark_time is not None:
        print(f"  landmark : t_hi <= {int(landmark_time)} days  -> {landmark_subdir or 'landmark'}")
    print(f"{'=' * 55}")

    print("\n[1/3] 读取 JSON ...")
    cases = load_clinical_cases(json_paths, project_ids=project_ids)
    # landmark 与 prompt / baseline 同一条：值级 mask（t_hi <= T）后再取字段值。
    patient_rows = build_patient_rows(
        cases,
        landmark_time=landmark_time,
        dataset_name=dataset_name,
    )
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
        display_fields = [artifact_field_name(scheme, field) for field in fields]
        n_cli = len(fields)
        # landmark 臂落 {scheme}/landmark_{T}/；不传 landmark 时与旧布局逐字一致。
        scheme_dir = landmark_dir(out_root_path / scheme, landmark_subdir)
        scheme_dir.mkdir(parents=True, exist_ok=True)

        # 方案里不在共享/冻结词表内的 nominal 字段：按当前患者补拟合（L0-L5 恒为空）。
        extra_mappings = _scheme_extra_nominal_mappings(
            patient_rows, fields, nominal_mappings, nominal_min_count
        )
        scheme_mappings = {**nominal_mappings, **extra_mappings} if extra_mappings else nominal_mappings

        ttt_cli_feas = {}
        for row in patient_rows:
            ttt_cli_feas[row["patient_id"]] = encode_raw_row(row, fields, scheme_mappings)
        t_cli_feas = minmax_symmetric(ttt_cli_feas, n_cli)
        x_cli = {
            patient_id: diagonal_pad(values, dim=HGCN_PAD_DIM)
            for patient_id, values in t_cli_feas.items()
        }
        edge_index_cli = full_connect_edges(n_cli)
        coverage = _coverage_from_raw(ttt_cli_feas, display_fields)
        scheme_nominal = _artifact_named_mapping(
            _scheme_nominal_mappings(fields, scheme_mappings), scheme
        )
        scheme_ordinal = _artifact_named_mapping(_scheme_ordinal_encoders(fields), scheme)

        joblib.dump(ttt_cli_feas, scheme_dir / "ttt_cli_feas.pkl")
        joblib.dump(t_cli_feas, scheme_dir / "t_cli_feas.pkl")
        joblib.dump(x_cli, scheme_dir / "x_cli.pkl")
        joblib.dump(edge_index_cli, scheme_dir / "edge_index_cli.pkl")

        encoding_table = {
            "scheme": scheme,
            "nominal_encoding": HGCN_NOMINAL_ENCODING,
            "missing_token": BASELINE_MISSING_TOKEN,
            "other_token": BASELINE_OTHER_TOKEN,
            "mapping_scope": mapping_source,
            "nominal_mappings": scheme_nominal,
            "ordinal_encoders": scheme_ordinal,
        }
        if extra_mappings:
            encoding_table["extra_nominal_mappings"] = {
                "type": "fit_current_patients",
                "fields": [artifact_field_name(scheme, field) for field in extra_mappings],
                "nominal_min_count": nominal_min_count,
            }
        _write_json(scheme_dir / "encoding_table.json", encoding_table)
        _write_json(scheme_dir / "coverage.json", coverage)
        field_schema = {
            "dataset": dataset_label,
            "scheme": scheme,
            "n_cli": n_cli,
            "fields": display_fields,
            "field_types": {
                display_field: field_type_name(field)
                for display_field, field in zip(display_fields, fields)
            },
            "pad_dim": HGCN_PAD_DIM,
            "minmax": HGCN_MINMAX_NAME,
            "missing_policy": HGCN_MISSING_POLICY,
            "nominal_encoding": HGCN_NOMINAL_ENCODING,
            "patient_id_field": "submitter_id",
            "n_patients": len(patient_rows),
            "missing_note": MISSING_DIAGONAL_NOTE,
        }
        if landmark_time is not None:
            field_schema["landmark_time"] = int(landmark_time)
        _write_json(scheme_dir / "field_schema.json", field_schema)
        _write_summary(
            scheme_dir / "summary.md",
            dataset_name=dataset_label,
            scheme=scheme,
            n_cli=n_cli,
            n_patients=len(patient_rows),
            fields=fields,
            display_fields=display_fields,
            coverage=coverage,
            scheme_dir=scheme_dir,
            landmark_time=landmark_time,
        )

        print(f"\n      {scheme}: 病人数={len(patient_rows)}  N_cli={n_cli}")
        print(f"        输出目录: {scheme_dir}")
        for display_field in display_fields:
            percent = coverage[display_field]["percent_observed"]
            print(
                f"        {display_field}: {percent:.1f}% observed "
                f"({coverage[display_field]['n_observed']}/{len(patient_rows)})"
            )

    print("\n[3/3] 完成")
    print("=" * 55)
    print("[hgcn_clinic] 编码完成")
    print(f"   数据集   : {dataset_label}")
    print(f"   患者数   : {len(patient_rows)}")
    print(f"   输出根目录 : {out_root_path}")
    print("=" * 55)
