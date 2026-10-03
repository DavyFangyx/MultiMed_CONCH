"""Test_2a 泄露审计（新口径，spec §2.1 / §5.2）：逐字段量化「进入模型的值来自未来」的患者比例。

口径（唯一依据 = spec §2.1；用户 2026-09-30 纠错，执行日志 R9 / S2c）
------------------------------------------------------------------
::

    leak_rate(f, D) = #{患者: 该患者实际进入模型的值来自 t_hi > 0 的槽位}
                      / #{患者: 管线产出有效值}

- **取值 = 论文管线**：直接调用 ``A_pipeline/src/extract.py`` 的 ``extract_values(case, landmark_time=None)``
  （无泄露处理），得到"实际进入模型的值"；来源实体由 ``leak.provenance`` 镜像追溯并逐患者比对
  （不一致即报错）。**不再**用旧的 ``1 − n_valid_t0/n_valid_none``（S2b 旧数已作废）。
- **判据 = 来源槽位时点**：来源实体映射到 ``src/time_stats.py`` 的时间槽（``t_hi`` = t_record 上界）。
  任一来历槽位 ``t_hi > 0`` → 该患者泄露；无时点家族（demographic / exposures / family_histories …）
  恒不泄露。槽位状态按 ``z_notes/time_axis/time_axis.md`` §4.1 逐条处理：
  ``point``/``bounded`` 有限 ``t_hi > 0`` → 泄露；``lo_only``（``t_hi = +∞``，「任何有限 T 都不放行」）
  → 泄露；``unlocated``/``non_informative``（无 t_hi，无法断言未来）**不判泄露**，
  单列 ``n_unlocated_source`` 并给出 ``n_t0_blocked`` = 泄露 ∪ 未定位
  （= 该值在 t0 landmark 门控下会被丢弃的患者数，供与旧口径对照）。
- **分母 = 管线产出有效值的患者数**（值 ≠ 该字段缺失占位符）；分母 0 → ``leak_rate = NaN`` 且
  ``leak_rate_undefined = true``。
- 字段级「泄露字段」判据：``n_leak > 0``（即 ``leak_rate > 0``），无人工阈值。
- ``derived.*`` 追到底层槽位（同 A_pipeline 自身的派生逻辑）。

范围（spec §2.4；用户决议 2026-09-30，执行日志 R1）
--------------------------------------------------
审计**只跑绑定允许的 (dataset, scheme) 组合**，不做 35 × 10 全交叉：

- ``HGCN_*`` 六个方案各绑定其对应癌种（``HGCN_DATASET_BY_SCHEME``），**禁止**跑其他队列；
- 泛癌种四方案（MULTISURV / SURVPGC / MMSURV / INTEGRATIVE_DNN）暂按全部 33 TCGA（未解决问题 U2）；
- TCGA 之外的外部数据集（CPTAC、MMRF）一律不纳入；
- 组合数 = 4 × 33 + 6 = 138。

绑定关系由本模块声明，**不读** ``A_pipeline/templates/{scheme}/fields.json`` 的 ``datasets`` 键
（那是旧的错误全绑定：每个方案都写 33 个 TCGA）。

产物
----
- ``results/Test_2a_leak_audit/{dataset}/{scheme}.json``：138 个方案级逐字段明细；
- ``results/Test_2a_leak_audit/leak_audit_summary.csv``：(dataset, scheme) 级聚合 + n_event/event_rate；
- ``results/Test_2a_leak_audit/{dataset}/G1_{md5(field_idx)}.json``：Test_1a 消费的逐字段审计
  （33 数据集 × 各自 landmark_0 kept 字段；scheme 名 = ``greedy.embeddings.subset_scheme_name``）。
  产物不含时间戳（保证同命令重跑逐字节一致）。
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

from common.datasets import (
    get_dataset_clinic_files,
    get_dataset_project_ids,
    load_dataset_configs,
    resolve_dataset_names,
)
from common.paths import DEFAULT_DATASETS_CONFIG, PROJECT_ROOT, test_results_dir
from discovery.field_bank import load_kept_fields

from . import provenance
from .provenance import case_contexts, field_provenance


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
DEFAULT_OUTPUT_ROOT = test_results_dir("Test_2a_leak_audit")
DEFAULT_EVENT_SUMMARY = PROJECT_ROOT / "rawdata_stats" / "_shared" / "event_summary.csv"
SUMMARY_FILENAME = "leak_audit_summary.csv"

# 主时间点 t0（spec §2.5）；本口径下只作为报告的参照时点，不再参与 t0/tN 两次抽取比较
LANDMARK_T0 = 0

# 产物审计口径标签（确定性；不写时间戳以保证重跑逐字节一致）
AUDIT_VERSION = "S2c: value provenance by source-slot t_hi"

SUMMARY_COLUMNS = [
    "dataset",
    "scheme",
    "n_fields",
    "n_leaky",
    "leaky_ratio",
    "mean_leak_rate",
    "n_leak_total",
    "n_valid_total",
    "n_t0_blocked_total",
    "n_fields_a_pipeline",
    "n_fields_field_bank",
    "n_not_in_bank",
    "n_leak_rate_undefined",
    "n_event",
    "event_rate",
]

FIELD_KEYS = [
    "field",
    "family",
    "audited_path",
    "audit_mode",
    "placeholder",
    "n_patients",
    "n_valid",
    "n_leak",
    "leak_rate",
    "leak_rate_undefined",
    "n_lo_only_source",
    "n_unlocated_source",
    "n_untimed_source",
    "n_no_source",
    "n_t0_blocked",
    "n_future_sources",
    "source_slot_families",
    "source_slot_statuses",
    "max_source_t_hi",
    "not_in_bank",
]

G1_SCHEME_RE = re.compile(r"^G1_[0-9a-f]{10}\.json$")


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
    registry=None,
) -> list[tuple[str, str]]:
    """(dataset, scheme) 执行计划，按 §2.4 绑定过滤；``binding=all`` 只放宽方案绑定。

    ``dataset_names`` = 本次选中的数据集；``registry`` = 数据集注册表全表
    （datasets.json 的键）。绑定关系（HGCN_* 对应癌种）按**注册表全表**解析，
    否则单队列运行（``--dataset TCGA-BRCA``）会因「绑定的队列不在注册表中」误报。
    不传 ``registry`` 时退回用 ``dataset_names``（向后兼容，等价于全表运行）。

    外部数据集（CPTAC/MMRF）在两种模式下都剔除——数据集范围由 §2.4 锁定，不随绑定模式变化。
    """
    if binding not in (BINDING_SPEC, BINDING_ALL):
        raise ValueError(f"未知 binding: {binding}（可用 {BINDING_SPEC}/{BINDING_ALL}）")
    registry = [
        str(item).strip()
        for item in (registry if registry is not None else dataset_names) or ()
        if str(item).strip()
    ]
    selected = [
        str(item).strip() for item in (dataset_names or ()) if str(item).strip()
    ]
    tcga_registry = set(tcga_dataset_names(registry))
    # 本阶段范围 = 选中的 TCGA 队列（顺序按 dataset_names，且必须在注册表全表内）
    tcga = [name for name in selected if name in tcga_registry]
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


# ---------------------------------------------------------------------------
# 逐字段审计（新口径）
# ---------------------------------------------------------------------------
def audit_field(contexts: list, field_path: str) -> dict:
    """审计单个 (dataset, field)：值来源槽位 ``t_hi > 0`` 的患者比例。

    ``contexts`` = ``provenance.case_contexts(cases)``（含 A_pipeline 管线取值）。
    """
    field = str(field_path or "").strip()
    audited_path = provenance.audited_slot_path(field)
    family, _ = provenance.field_family(field)
    spec = provenance.a_pipeline_spec(field)
    mode = provenance.MODE_A_PIPELINE if spec is not None else provenance.MODE_FIELD_BANK
    placeholder = spec.placeholder if spec is not None else "not reported"

    n_valid = 0
    n_leak = 0
    n_lo_only = 0
    n_unlocated = 0
    n_untimed = 0
    n_no_source = 0
    n_t0_blocked = 0
    n_future_sources = 0
    future_families: set[str] = set()
    future_statuses: set[str] = set()
    max_hi: float | None = None
    for ctx in contexts:
        item = field_provenance(field, ctx)
        if not item.valid:
            continue
        n_valid += 1
        if item.has_future_source:
            n_leak += 1
            for source in item.sources:
                if not source.is_future:
                    continue
                n_future_sources += 1
                if source.family:
                    future_families.add(str(source.family))
                if source.status:
                    future_statuses.add(str(source.status))
                if source.t_hi is not None and (max_hi is None or source.t_hi > max_hi):
                    max_hi = float(source.t_hi)
        if item.has_lo_only_source:
            n_lo_only += 1
        if item.has_unlocated_source:
            n_unlocated += 1
        if item.has_future_source or item.has_unlocated_source:
            n_t0_blocked += 1
        if item.has_untimed_source:
            n_untimed += 1
        if not item.sources:
            n_no_source += 1

    rate = float("nan") if n_valid == 0 else (float(n_leak) / float(n_valid))
    return {
        "field": field,
        "family": family,
        "audited_path": audited_path,
        "audit_mode": mode,
        "placeholder": placeholder,
        "n_patients": int(len(contexts)),
        "n_valid": int(n_valid),
        "n_leak": int(n_leak),
        "leak_rate": rate,
        "leak_rate_undefined": bool(n_valid == 0),
        "n_lo_only_source": int(n_lo_only),
        "n_unlocated_source": int(n_unlocated),
        "n_untimed_source": int(n_untimed),
        "n_no_source": int(n_no_source),
        "n_t0_blocked": int(n_t0_blocked),
        "n_future_sources": int(n_future_sources),
        "source_slot_families": sorted(future_families),
        "source_slot_statuses": sorted(future_statuses),
        "max_source_t_hi": max_hi,
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
        "n_leak_total": int(sum(int(row.get("n_leak") or 0) for row in field_rows)),
        "n_valid_total": int(sum(int(row.get("n_valid") or 0) for row in field_rows)),
        "n_t0_blocked_total": int(
            sum(int(row.get("n_t0_blocked") or 0) for row in field_rows)
        ),
        "n_fields_a_pipeline": int(
            sum(1 for row in field_rows if row.get("audit_mode") == provenance.MODE_A_PIPELINE)
        ),
        "n_fields_field_bank": int(
            sum(1 for row in field_rows if row.get("audit_mode") == provenance.MODE_FIELD_BANK)
        ),
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
        "leak_definition": "value_provenance: source slot t_hi > 0",
        "audit_version": AUDIT_VERSION,
    }
    if binding is not None:
        # spec §2.4：该方案被允许的队列（HGCN_* 只允许其癌种）
        payload["scheme_binding"] = str(binding.get("kind") or "")
        payload["binding_datasets"] = [str(item) for item in binding.get("datasets") or []]
    payload.update(summary)
    payload["fields"] = rows
    return payload


def load_kept_fields_list(dataset_name: str) -> list[str] | None:
    """读 rawdata_stats/{dataset}/landmark_0/kept_fields.json 的字段有序表；缺失返回 None。"""
    try:
        payload = load_kept_fields(dataset_name=dataset_name, landmark_tag="landmark_0")
    except FileNotFoundError:
        return None
    entry = payload.get(dataset_name) or {}
    fields = entry.get("fields") if isinstance(entry, dict) else None
    if not isinstance(fields, list):
        return None
    ordered: list[str] = []
    seen: set[str] = set()
    for item in fields:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def load_kept_fields_set(dataset_name: str) -> set[str] | None:
    """读 rawdata_stats/{dataset}/landmark_0/kept_fields.json；缺失返回 None。"""
    ordered = load_kept_fields_list(dataset_name)
    if ordered is None:
        return None
    return set(ordered)


def g1_scheme_name(field_idx: int) -> str:
    """Test_1a 消费的单字段方案名：``greedy.embeddings.subset_scheme_name([idx])``。"""
    from greedy.embeddings import subset_scheme_name

    return subset_scheme_name([int(field_idx)])


def build_g1_payload(
    dataset_name: str,
    field_idx: int,
    row: dict,
    *,
    n_patients: int,
) -> dict:
    """Test_1a 逐字段审计产物（schema 对齐 ``Test_1a_field_level.py::load_leak_rates``）。"""
    payload = {
        "dataset": dataset_name,
        "scheme": g1_scheme_name(field_idx),
        "scope": "test_1a_kept_field",
        "field_idx": int(field_idx),
        "field": str(row["field"]),
        "landmark_time": LANDMARK_T0,
        "n_patients": int(n_patients),
        "value_unit": "patients_with_valid_value",
        "leak_definition": "value_provenance: source slot t_hi > 0",
        "audit_version": AUDIT_VERSION,
        "n_fields": 1,
        "n_leaky": int(1 if (not row.get("leak_rate_undefined") and row.get("n_leak")) else 0),
        "n_leak_total": int(row.get("n_leak") or 0),
        "n_valid_total": int(row.get("n_valid") or 0),
        "n_t0_blocked_total": int(row.get("n_t0_blocked") or 0),
        "leak_rate": row.get("leak_rate"),
        "leak_rate_undefined": bool(row.get("leak_rate_undefined")),
        "n_valid": int(row.get("n_valid") or 0),
        "n_leak": int(row.get("n_leak") or 0),
        "family": row.get("family"),
        "audited_path": row.get("audited_path"),
        "audit_mode": row.get("audit_mode"),
    }
    payload["fields"] = [dict(row)]
    return payload


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
    kept_field_list: list[str] | None = None,
    bindings: dict[str, dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """审计一个数据集上被绑定的方案（不写盘）。

    返回 ``(scheme_payloads, g1_payloads)``；``schemes`` 必须已按 §2.4 绑定过滤
    （见 ``build_audit_plan``）。
    """
    contexts = case_contexts(cases)
    # 方案间 / 方案与 kept 字段间大量重复：按字段去重各算一次
    cache: dict[str, dict] = {}

    def row_for(field_path: str) -> dict:
        if field_path not in cache:
            cache[field_path] = audit_field(contexts, field_path)
        return cache[field_path]

    kept_fields = set(kept_field_list) if kept_field_list is not None else None
    payloads = []
    for scheme in schemes:
        rows = [row_for(field_path) for field_path in fields_by_scheme[scheme]]
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

    g1_payloads: list[dict] = []
    if kept_field_list is not None:
        for idx, field_path in enumerate(kept_field_list):
            g1_payloads.append(
                build_g1_payload(
                    dataset_name, idx, row_for(field_path), n_patients=len(cases)
                )
            )
    return payloads, g1_payloads


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
                "n_leak_total": payload["n_leak_total"],
                "n_valid_total": payload["n_valid_total"],
                "n_t0_blocked_total": payload["n_t0_blocked_total"],
                "n_fields_a_pipeline": payload["n_fields_a_pipeline"],
                "n_fields_field_bank": payload["n_fields_field_bank"],
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

    绑定变更后（S2b/S2c）旧产物必须清干净，否则 CPTAC/MMRF 与 HGCN_* 跨癌种文件会留在盘上。
    ``G1_*.json``（Test_1a 逐字段审计）不在方案的清除范围内，单独保留。
    只删本模块自己写出的 ``*.json``；返回被删的相对路径。
    """
    out_root = Path(out_dir)
    if not out_root.exists():
        return []
    planned = {f"{dataset}/{scheme}.json" for dataset, scheme in plan}
    removed: list[str] = []
    for path in sorted(out_root.glob("*/*.json")):
        rel = f"{path.parent.name}/{path.name}"
        if rel in planned or G1_SCHEME_RE.match(path.name):
            continue
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
    binding: str = BINDING_SPEC,
    prune: bool = False,
    g1: bool = True,
    quiet: bool = False,
) -> dict:
    """跑 Test_2a 泄露审计（新口径，按 §2.4 绑定）并落盘。

    返回 {"out_dir", "summary_csv", "n_datasets", "n_payloads", "n_g1_payloads",
    "n_schemes", "n_pairs", "binding"}。
    """
    from common.clinical_io import load_clinical_cases

    scheme_names = list(schemes or LEAK_SCHEMES)
    configs = load_dataset_configs(str(datasets_config))
    names = resolve_dataset_names(dataset, configs)
    if not names:
        raise ValueError("Test_2a 审计需要 --dataset，例如 --dataset all 或 --dataset TCGA-BRCA")

    registry_all = resolve_dataset_names("all", configs)
    plan = build_audit_plan(names, scheme_names, binding=binding, registry=registry_all)
    if not plan:
        raise ValueError(
            "空审计计划：所选数据集均不在本阶段范围（spec §2.4：仅 33 TCGA，"
            f"CPTAC/MMRF 已剔除；数据集={names}）"
        )
    plan_names = plan_datasets(plan)
    plan_scheme_names = plan_schemes(plan)
    bindings = {
        scheme: scheme_dataset_binding(scheme, registry_all)
        for scheme in plan_scheme_names
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
    n_g1 = 0
    for name in plan_names:
        dataset_schemes = [scheme for item, scheme in plan if item == name]
        if not quiet:
            print(f"\n######## leak audit: {name}  ({len(dataset_schemes)} 方案) ########")
        cases = load_clinical_cases(
            get_dataset_clinic_files(name, configs),
            project_ids=get_dataset_project_ids(name, configs),
        )
        kept_field_list = load_kept_fields_list(name)
        dataset_payloads, g1_payloads = audit_dataset(
            name,
            cases,
            dataset_schemes,
            fields_by_scheme,
            kept_field_list=kept_field_list if g1 else None,
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
        for payload in g1_payloads:
            _json_dump(out_root / name / f"{payload['scheme']}.json", payload)
        n_g1 += len(g1_payloads)
        if not quiet:
            print(f"  kept 字段逐字段审计: {len(kept_field_list or [])} 个 G1_*.json")
        payloads.extend(dataset_payloads)

    events = load_event_summary(event_summary)
    rows = summary_rows(payloads, events)
    summary_path = write_summary_csv(out_root / SUMMARY_FILENAME, rows)
    if not quiet:
        print(f"\n✅ 逐字段明细: {out_root}/{{dataset}}/{{scheme}}.json  ({len(payloads)} 个文件)")
        print(f"✅ Test_1a 逐字段审计: {n_g1} 个 G1_*.json")
        print(f"✅ 汇总: {summary_path}  ({len(rows)} 行)")
    return {
        "out_dir": out_root,
        "summary_csv": summary_path,
        "n_datasets": len(plan_names),
        "n_payloads": len(payloads),
        "n_g1_payloads": n_g1,
        "n_schemes": len(plan_scheme_names),
        "n_pairs": len(plan),
        "binding": binding,
    }
