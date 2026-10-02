"""Test_1a 泄露审计：逐字段量化「t0 时刻不可得」的患者比例（规格 z_notes/Test_series_spec.md §5）。

口径（spec §2.1 / §5.2）
------------------------
``leak_rate(f, D) = 1 − n_valid_t0 / n_valid_none``

- ``n_valid_none`` / ``n_valid_t0``：landmark 关闭 / ``landmark_0`` 下**该字段取到有效值的患者数**。
  取患者数而非取值条数：Field Bank 的缺失 mask 本身是「患者 × 字段」级
  （``generate_field_bank_prompt_row`` 里 ``valid = bool(valid_vals)``），且 spec §2.1 把
  leak_rate 定义为「该字段在 t0 时刻不可得的**患者**比例」。
- 有效值判定沿用 ``discovery.field_bank.extract_field_bank_raw_values``（Field Bank 同一套规则），
  逐患者、双臂各抽一次。
- ``family`` = ``discovery.landmark.timed_family_for_field``；只有 timed 家族会被 t0 mask 掉。
- 特判：
  - ``project.project_id``：常数 → ``leak_rate = 0``；
  - ``derived.*``：audit 其**底层槽位**（``common.fields.field_gdc_path`` 给出的 source path），
    底层家族无时点（如 exposures）时 mask 不存在，``leak_rate = 0``；
  - 不在 ``rawdata_stats/{dataset}/landmark_0/kept_fields.json`` 的字段标 ``not_in_bank``
    （「无依据」问题的证据，不跳过审计）。
- ``n_valid_none == 0``：``leak_rate = NaN`` 且 ``leak_rate_undefined = true``（分母无意义）。

范围（spec §2.4；用户决议 2026-09-30，执行日志 R1）
--------------------------------------------------
审计**只跑绑定允许的 (dataset, scheme) 组合**，不再做 35 × 10 全交叉：

- ``HGCN_*`` 六个方案各绑定其对应癌种（``HGCN_DATASET_BY_SCHEME``），**禁止**跑其他队列；
- 泛癌种四方案（MULTISURV / SURVPGC / MMSURV / INTEGRATIVE_DNN）暂按全部 33 TCGA（未解决问题 U2）；
- TCGA 之外的外部数据集（CPTAC、MMRF）一律不纳入；
- 组合数 = 4 × 33 + 6 = 138。

绑定关系由本模块声明，**不读** ``A_pipeline/templates/{scheme}/fields.json`` 的 ``datasets`` 键
（那是旧的错误全绑定：每个方案都写 33 个 TCGA）。

产物
----
``results/leak_audit/{dataset}/{scheme}.json`` 逐字段明细；
``results/leak_audit/leak_audit_summary.csv`` (dataset, scheme) 级聚合 + 并列 n_event/event_rate。
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from common.datasets import (
    get_dataset_clinic_files,
    get_dataset_project_ids,
    load_dataset_configs,
    resolve_dataset_names,
)
from common.fields import field_gdc_path
from common.paths import DEFAULT_DATASETS_CONFIG, PROJECT_ROOT, RESULTS_ROOT
from discovery.field_bank import extract_field_bank_raw_values, load_kept_fields
from discovery.landmark import patient_landmark, timed_family_for_field
from discovery.longitudinal import SOURCE_FIELDS, is_derived_field


# spec §2.4：A_pipeline 的 10 个论文方案（与 results_display/scripts/FigA_Other_Paper_Works.py 一致）
LEAK_SCHEMES = (
    "MULTISURV",
    "SURVPGC",
    "MMSURV",
    "INTEGRATIVE_DNN",
    "HGCN_KIRC",
    "HGCN_LIHC",
    "HGCN_ESCA",
    "HGCN_LUSC",
    "HGCN_LUAD",
    "HGCN_UCEC",
)

# ---------------------------------------------------------------------------
# 方案 × 数据集绑定（spec §2.4 + 用户决议 2026-09-30 / 执行日志 R1）
#
# HGCN_* 六方案各绑定其对应癌种；泛癌种四方案暂按全部 33 TCGA；CPTAC / MMRF 剔除。
# 注意：这里**不读** A_pipeline/templates/{scheme}/fields.json 的 "datasets" 键——
# 该键是旧的全绑定（每个方案都列 33 个 TCGA），已作废。
# ---------------------------------------------------------------------------
TCGA_PREFIX = "TCGA"

# TCGA 之外的外部数据集，本阶段一律不纳入（spec §2.4；Test_4c 数据轴阶段再议）
EXCLUDED_DATASETS = ("CPTAC", "MMRF")

# HGCN_*：方案 → 其唯一允许的癌种队列（注册名。TCGA_LIHC 为下划线，见 S1 偏差 5）
HGCN_DATASET_BY_SCHEME = {
    "HGCN_KIRC": "TCGA-KIRC",
    "HGCN_LIHC": "TCGA_LIHC",
    "HGCN_ESCA": "TCGA-ESCA",
    "HGCN_LUSC": "TCGA-LUSC",
    "HGCN_LUAD": "TCGA-LUAD",
    "HGCN_UCEC": "TCGA-UCEC",
}

# 泛癌种方案：暂按全部 33 TCGA（spec §12 U2 未解决）
PAN_CANCER_SCHEMES = ("MULTISURV", "SURVPGC", "MMSURV", "INTEGRATIVE_DNN")

BINDING_SPEC = "spec"  # 按 §2.4 绑定（默认）
BINDING_ALL = "all"    # 仅用于 ad-hoc 方案：全部 TCGA × 全部方案（CPTAC/MMRF 仍剔除）
BINDING_KINDS = ("hgcn_cancer", "pan_cancer", "pan_cancer_default", "all")

DEFAULT_TEMPLATES_ROOT = PROJECT_ROOT / "A_pipeline" / "templates"
DEFAULT_OUTPUT_ROOT = RESULTS_ROOT / "leak_audit"
DEFAULT_EVENT_SUMMARY = PROJECT_ROOT / "rawdata_stats" / "_shared" / "event_summary.csv"
SUMMARY_FILENAME = "leak_audit_summary.csv"

# 主时间点 t0（spec §2.5）
LANDMARK_T0 = 0

COORDINATE_FIELD = "project.project_id"

MODE_PLAIN = "plain"
MODE_CONSTANT = "constant"
MODE_DERIVED_SLOT = "derived_slot"
MODE_LONGITUDINAL_DERIVED = "longitudinal_derived"

FIELD_KEYS = [
    "field",
    "family",
    "n_valid_none",
    "n_valid_t0",
    "leak_rate",
    "not_in_bank",
]

SUMMARY_COLUMNS = [
    "dataset",
    "scheme",
    "n_fields",
    "n_leaky",
    "leaky_ratio",
    "mean_leak_rate",
    "n_not_in_bank",
    "n_leak_rate_undefined",
    "n_event",
    "event_rate",
]


def tcga_dataset_names(dataset_names) -> list[str]:
    """本阶段的审计队列 = 注册表里除 CPTAC/MMRF 外的 TCGA 队列（spec §2.4，33 个）。

    不硬编码名单：从传入的注册表（datasets.json 的键）按「TCGA 前缀 + 不在排除集」推出。
    """
    names: list[str] = []
    for raw in dataset_names or ():
        name = str(raw or "").strip()
        if not name or name in EXCLUDED_DATASETS:
            continue
        if not name.upper().startswith(TCGA_PREFIX):
            continue
        if name not in names:
            names.append(name)
    return sorted(names)


def scheme_dataset_binding(scheme: str, dataset_names) -> dict:
    """按 spec §2.4 解析单个方案的允许队列，返回 {scheme, kind, datasets}。

    - HGCN_* → 仅其对应癌种（绑定队列未注册 / 被剔除时直接报错，不静默降级）；
    - 已知泛癌种方案 → 全部 33 TCGA；
    - 其余未登记方案 → 同样按全部 TCGA 处理，但 kind 标 ``pan_cancer_default``，
      便于事后识别「未在 §2.4 登记却跑了 33 队列」的方案。
    """
    name = str(scheme or "").strip()
    registry = [str(item).strip() for item in (dataset_names or ()) if str(item).strip()]
    tcga = tcga_dataset_names(registry)
    bound = HGCN_DATASET_BY_SCHEME.get(name)
    if bound is not None:
        if bound not in registry:
            raise ValueError(f"{name} 绑定的队列 {bound} 不在数据集注册表中（spec §2.4）")
        if bound in EXCLUDED_DATASETS or bound not in tcga:
            raise ValueError(
                f"{name} 绑定的队列 {bound} 不在本阶段 33 TCGA 范围内（spec §2.4）"
            )
        return {"scheme": name, "kind": "hgcn_cancer", "datasets": [bound]}
    kind = "pan_cancer" if name in PAN_CANCER_SCHEMES else "pan_cancer_default"
    return {"scheme": name, "kind": kind, "datasets": list(tcga)}


def build_audit_plan(
    dataset_names,
    schemes,
    *,
    binding: str = BINDING_SPEC,
) -> list[tuple[str, str]]:
    """(dataset, scheme) 执行计划，按 §2.4 绑定过滤；``binding=all`` 只放宽方案绑定。

    外部数据集（CPTAC/MMRF）在两种模式下都剔除——数据集范围由 §2.4 锁定，不随绑定模式变化。
    """
    if binding not in (BINDING_SPEC, BINDING_ALL):
        raise ValueError(f"未知 binding: {binding}（可用 {BINDING_SPEC}/{BINDING_ALL}）")
    registry = [str(item).strip() for item in (dataset_names or ()) if str(item).strip()]
    tcga = tcga_dataset_names(registry)
    scheme_names = [str(item).strip() for item in (schemes or ()) if str(item).strip()]
    allowed: dict[str, list[str]] = {}
    for scheme in scheme_names:
        if binding == BINDING_ALL:
            allowed[scheme] = list(tcga)
        else:
            allowed[scheme] = scheme_dataset_binding(scheme, registry)["datasets"]
    return [
        (name, scheme)
        for name in tcga
        for scheme in scheme_names
        if name in allowed.get(scheme, ())
    ]


def plan_datasets(plan: list[tuple[str, str]]) -> list[str]:
    """计划里出现的数据集（保序去重）。"""
    ordered: list[str] = []
    for name, _ in plan:
        if name not in ordered:
            ordered.append(name)
    return ordered


def plan_schemes(plan: list[tuple[str, str]]) -> list[str]:
    """计划里出现的方案（保序去重）。"""
    ordered: list[str] = []
    for _, scheme in plan:
        if scheme not in ordered:
            ordered.append(scheme)
    return ordered


def load_scheme_fields(scheme: str, templates_root: Path | str = DEFAULT_TEMPLATES_ROOT) -> list[str]:
    path = Path(templates_root) / str(scheme) / "fields.json"
    if not path.exists():
        raise FileNotFoundError(f"未找到方案字段表: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        fields = payload.get("fields")
    elif isinstance(payload, list):
        fields = payload
    else:
        raise ValueError(f"无法解析方案字段表: {path}")
    if not isinstance(fields, list) or not fields:
        raise ValueError(f"{path} 的 fields 为空")
    ordered: list[str] = []
    seen: set[str] = set()
    for item in fields:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def resolve_audited_path(field_path: str) -> tuple[str, str]:
    """把方案字段解析为审计对象：返回 (实际审计的字段路径, 模式)。"""
    field_path = str(field_path or "").strip()
    if field_path == COORDINATE_FIELD:
        return field_path, MODE_CONSTANT
    if is_derived_field(field_path):
        return str(SOURCE_FIELDS.get(field_path) or field_path), MODE_LONGITUDINAL_DERIVED
    if field_path.startswith("derived."):
        return str(field_gdc_path(field_path)), MODE_DERIVED_SLOT
    return field_path, MODE_PLAIN


def patient_landmark_states(cases: list[dict], landmark_time: int = LANDMARK_T0) -> list[dict]:
    """逐患者算一次 landmark 记录，供所有字段复用（等价于 landmark=True + landmark_time）。"""
    return [patient_landmark(case, landmark_time) for case in cases]


def count_valid_patients(
    cases: list[dict],
    states: list[dict],
    field_path: str,
    *,
    masked: bool,
) -> tuple[int, int]:
    """返回 (取到有效值的患者数, 有效值条数)。masked=True 时用 landmark_0 记录。"""
    n_patients = 0
    n_values = 0
    for case, state in zip(cases, states):
        landmark_arg = state if masked else False
        values = extract_field_bank_raw_values(
            case, field_path, landmark=landmark_arg, landmark_time=LANDMARK_T0
        )
        if values:
            n_patients += 1
            n_values += len(values)
    return n_patients, n_values


def _leak_rate(n_valid_none: int, n_valid_t0: int) -> float:
    if n_valid_none <= 0:
        return float("nan")
    return 1.0 - (float(n_valid_t0) / float(n_valid_none))


def audit_field(cases: list[dict], states: list[dict], field_path: str) -> dict:
    """审计单个 (dataset, field)：返回 spec §5.3 要求的逐字段记录。"""
    audited_path, mode = resolve_audited_path(field_path)
    family, _ = timed_family_for_field(audited_path)
    n_none, v_none = count_valid_patients(cases, states, audited_path, masked=False)

    mask_applicable = True
    if mode == MODE_CONSTANT or family is None:
        # 常数 / 无时点家族：t0 mask 不作用于该字段的底层槽位，信息不会因 t0 丢失。
        n_t0, v_t0 = n_none, v_none
        mask_applicable = False
    else:
        n_t0, v_t0 = count_valid_patients(cases, states, audited_path, masked=True)

    rate = _leak_rate(n_none, n_t0)
    return {
        "field": str(field_path),
        "family": family,
        "n_valid_none": int(n_none),
        "n_valid_t0": int(n_t0),
        "leak_rate": rate,
        "leak_rate_undefined": bool(math.isnan(rate)),
        "audited_path": audited_path,
        "audit_mode": mode,
        "mask_applicable": bool(mask_applicable),
        "n_values_none": int(v_none),
        "n_values_t0": int(v_t0),
        "not_in_bank": False,
    }


def summarize_fields(field_rows: list[dict]) -> dict:
    rates = [row["leak_rate"] for row in field_rows if not row.get("leak_rate_undefined")]
    n_leaky = sum(1 for rate in rates if rate > 0)
    return {
        "n_fields": len(field_rows),
        "n_leaky": int(n_leaky),
        "leaky_ratio": (float(n_leaky) / float(len(field_rows))) if field_rows else float("nan"),
        "mean_leak_rate": (sum(rates) / float(len(rates))) if rates else float("nan"),
        "n_not_in_bank": int(sum(1 for row in field_rows if row.get("not_in_bank"))),
        "n_leak_rate_undefined": int(
            sum(1 for row in field_rows if row.get("leak_rate_undefined"))
        ),
    }


def build_scheme_payload(
    dataset_name: str,
    scheme: str,
    field_rows: list[dict],
    *,
    kept_fields: set[str] | None,
    n_patients: int,
    binding: dict | None = None,
) -> dict:
    rows = []
    for row in field_rows:
        item = dict(row)
        item["not_in_bank"] = bool(kept_fields is not None and row["field"] not in kept_fields)
        rows.append(item)
    summary = summarize_fields(rows)
    payload = {
        "dataset": dataset_name,
        "scheme": scheme,
        "landmark_time": LANDMARK_T0,
        "n_patients": int(n_patients),
        "kept_fields_available": bool(kept_fields is not None),
        "value_unit": "patients_with_valid_value",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if binding is not None:
        # spec §2.4：该方案被允许的队列（HGCN_* 只允许其癌种）
        payload["scheme_binding"] = str(binding.get("kind") or "")
        payload["binding_datasets"] = [str(item) for item in binding.get("datasets") or []]
    payload.update(summary)
    payload["fields"] = rows
    return payload


def load_kept_fields_set(dataset_name: str) -> set[str] | None:
    """读 rawdata_stats/{dataset}/landmark_0/kept_fields.json；缺失返回 None。"""
    try:
        payload = load_kept_fields(dataset_name=dataset_name, landmark_tag="landmark_0")
    except FileNotFoundError:
        return None
    entry = payload.get(dataset_name) or {}
    fields = entry.get("fields") if isinstance(entry, dict) else None
    if not isinstance(fields, list):
        return None
    return {str(item) for item in fields}


def _json_dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=True)
        handle.write("\n")


def audit_dataset(
    dataset_name: str,
    cases: list[dict],
    schemes: list[str],
    fields_by_scheme: dict[str, list[str]],
    *,
    kept_fields: set[str] | None = None,
    landmark_time: int = LANDMARK_T0,
    bindings: dict[str, dict] | None = None,
) -> list[dict]:
    """审计一个数据集上被绑定的方案，返回 JSON payload 列表（不写盘）。

    ``schemes`` 必须已经是该数据集按 §2.4 绑定过滤后的方案列表（见 ``build_audit_plan``）。
    """
    # 方案间字段大量重复：按字段去重只算一次双臂计数
    states = patient_landmark_states(cases, landmark_time)
    cache: dict[str, dict] = {}
    payloads = []
    for scheme in schemes:
        rows = []
        for field_path in fields_by_scheme[scheme]:
            if field_path not in cache:
                cache[field_path] = audit_field(cases, states, field_path)
            rows.append(cache[field_path])
        payloads.append(
            build_scheme_payload(
                dataset_name,
                scheme,
                rows,
                kept_fields=kept_fields,
                n_patients=len(cases),
                binding=(bindings or {}).get(scheme),
            )
        )
    return payloads


def load_event_summary(path: Path | str = DEFAULT_EVENT_SUMMARY) -> dict[str, dict]:
    """读 rawdata_stats/_shared/event_summary.csv（dataset -> n_event/event_rate）。"""
    path = Path(path)
    if not path.exists():
        return {}
    table: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = str(row.get("dataset") or "").strip()
            if not name:
                continue
            table[name] = {
                "n_event": row.get("n_event", ""),
                "event_rate": row.get("event_rate", ""),
            }
    return table


def _fmt_rate(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return f"{float(value):.6f}"


def summary_rows(
    payloads: list[dict],
    events: dict[str, dict] | None = None,
) -> list[dict]:
    events = events or {}
    rows = []
    for payload in payloads:
        event = events.get(payload["dataset"], {})
        rows.append(
            {
                "dataset": payload["dataset"],
                "scheme": payload["scheme"],
                "n_fields": payload["n_fields"],
                "n_leaky": payload["n_leaky"],
                "leaky_ratio": _fmt_rate(payload["leaky_ratio"]),
                "mean_leak_rate": _fmt_rate(payload["mean_leak_rate"]),
                "n_not_in_bank": payload["n_not_in_bank"],
                "n_leak_rate_undefined": payload["n_leak_rate_undefined"],
                "n_event": event.get("n_event", ""),
                "event_rate": event.get("event_rate", ""),
            }
        )
    rows.sort(key=lambda row: (row["dataset"], row["scheme"]))
    return rows


def write_summary_csv(path: Path | str, rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in SUMMARY_COLUMNS})
    return path


def prune_stale_outputs(
    out_dir: Path | str,
    plan: list[tuple[str, str]],
) -> list[str]:
    """删掉不在计划内的 ``{dataset}/{scheme}.json`` 与因此空掉的队列目录。

    绑定变更后（S2b）旧产物必须清干净，否则 CPTAC/MMRF 与 HGCN_* 跨癌种文件会留在盘上。
    只删本模块自己写出的 ``*.json``（两层的 ``{dataset}/{scheme}.json``）；返回被删的相对路径。
    """
    out_root = Path(out_dir)
    if not out_root.exists():
        return []
    planned = {f"{dataset}/{scheme}.json" for dataset, scheme in plan}
    removed: list[str] = []
    for path in sorted(out_root.glob("*/*.json")):
        rel = f"{path.parent.name}/{path.name}"
        if rel not in planned:
            path.unlink()
            removed.append(rel)
    for child in sorted(item for item in out_root.iterdir() if item.is_dir()):
        try:
            child.rmdir()  # 只删空目录
        except OSError:
            continue
        removed.append(f"{child.name}/")
    return removed


def run_audit(
    *,
    datasets_config: Path | str = DEFAULT_DATASETS_CONFIG,
    dataset: str = "all",
    schemes: list[str] | None = None,
    templates_root: Path | str = DEFAULT_TEMPLATES_ROOT,
    out_dir: Path | str = DEFAULT_OUTPUT_ROOT,
    event_summary: Path | str = DEFAULT_EVENT_SUMMARY,
    landmark_time: int = LANDMARK_T0,
    binding: str = BINDING_SPEC,
    prune: bool = False,
    quiet: bool = False,
) -> dict:
    """跑 Test_1a 审计（按 §2.4 绑定）并落盘。

    返回 {"out_dir", "summary_csv", "n_datasets", "n_payloads", "n_schemes", "n_pairs", "binding"}。
    """
    from common.clinical_io import load_clinical_cases

    scheme_names = list(schemes or LEAK_SCHEMES)
    configs = load_dataset_configs(str(datasets_config))
    names = resolve_dataset_names(dataset, configs)
    if not names:
        raise ValueError("Test_1a 审计需要 --dataset，例如 --dataset all 或 --dataset TCGA-BRCA")

    plan = build_audit_plan(names, scheme_names, binding=binding)
    if not plan:
        raise ValueError(
            "空审计计划：所选数据集均不在本阶段范围（spec §2.4：仅 33 TCGA，"
            f"CPTAC/MMRF 已剔除；数据集={names}）"
        )
    plan_names = plan_datasets(plan)
    plan_scheme_names = plan_schemes(plan)
    bindings = {
        scheme: scheme_dataset_binding(scheme, names) for scheme in plan_scheme_names
    }
    fields_by_scheme = {
        scheme: load_scheme_fields(scheme, templates_root) for scheme in plan_scheme_names
    }
    out_root = Path(out_dir)
    if prune:
        removed = prune_stale_outputs(out_root, plan)
        if not quiet and removed:
            print(f"清理旧产物 {len(removed)} 项: {', '.join(removed[:8])}"
                  + (" …" if len(removed) > 8 else ""))
    payloads: list[dict] = []
    for name in plan_names:
        dataset_schemes = [scheme for item, scheme in plan if item == name]
        if not quiet:
            print(f"\n######## leak audit: {name}  ({len(dataset_schemes)} 方案) ########")
        cases = load_clinical_cases(
            get_dataset_clinic_files(name, configs),
            project_ids=get_dataset_project_ids(name, configs),
        )
        kept_fields = load_kept_fields_set(name)
        dataset_payloads = audit_dataset(
            name,
            cases,
            dataset_schemes,
            fields_by_scheme,
            kept_fields=kept_fields,
            landmark_time=landmark_time,
            bindings=bindings,
        )
        for payload in dataset_payloads:
            _json_dump(out_root / name / f"{payload['scheme']}.json", payload)
            if not quiet:
                print(
                    "  {scheme:16s} n_fields={n_fields:2d} n_leaky={n_leaky:2d} "
                    "leaky_ratio={leaky_ratio:.2f} mean_leak_rate={mean_leak_rate}".format(
                        scheme=payload["scheme"],
                        n_fields=payload["n_fields"],
                        n_leaky=payload["n_leaky"],
                        leaky_ratio=payload["leaky_ratio"],
                        mean_leak_rate=(
                            "nan"
                            if math.isnan(payload["mean_leak_rate"])
                            else f"{payload['mean_leak_rate']:.3f}"
                        ),
                    )
                )
        payloads.extend(dataset_payloads)

    events = load_event_summary(event_summary)
    rows = summary_rows(payloads, events)
    summary_path = write_summary_csv(out_root / SUMMARY_FILENAME, rows)
    if not quiet:
        print(f"\n✅ 逐字段明细: {out_root}/{{dataset}}/{{scheme}}.json  ({len(payloads)} 个文件)")
        print(f"✅ 汇总: {summary_path}  ({len(rows)} 行)")
    return {
        "out_dir": out_root,
        "summary_csv": summary_path,
        "n_datasets": len(plan_names),
        "n_payloads": len(payloads),
        "n_schemes": len(plan_scheme_names),
        "n_pairs": len(plan),
        "binding": binding,
    }
