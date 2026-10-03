"""值来源时点追溯：Test_2a 泄露审计新口径的核心实现（spec §2.1 / §5.2）。

口径（唯一依据 = spec §2.1，用户 2026-09-30 纠错）::

    leak_rate(f, D) = #{患者: 该患者实际进入模型的值来自 t_hi > 0 的槽位}
                      / #{患者: 管线产出有效值}

与旧实现（``1 − n_valid_t0/n_valid_none``，已作废）的三点区别：

1. **取值逻辑 = 论文管线**：逐患者调用 ``A_pipeline/src/extract.py`` 的
   ``extract_values(case, landmark_time=None)``（**不做任何泄露处理**），得到"实际进入模型的值"。
   本模块同时用一份**镜像实现**给出同一字段的**来源实体**（哪些 JSON 对象贡献了这个值），
   两者逐患者比对，不一致即报错——保证追溯对象与管线取值严格对应（``verify``）。
2. **判据 = 来源槽位时点**：来源实体映射到 ``src/time_stats.py`` 的时间槽
   （t_record 区间上界 ``t_hi``，与 Test_2b landmark 三要件同一套机制）。
   **任一来历槽位 ``t_hi > 0`` 即该患者泄露**——覆盖旧口径漏掉的
   "t0 有值、但管线取的是更晚值"；无时点家族的字段（demographic / exposures /
   family_histories 等）恒不泄露。
3. **分母 = 管线产出有效值的患者**（值不是该字段的缺失占位符）；分母为 0 时 ``leak_rate = NaN``。

判定规则（逐患者，分母内）::

    has_future_source : 来源槽位在 t0 门控下不放行                  → 计入 n_leak（分子）
                        = 有限 t_hi > 0（spec §2.1）
                        ∪ lo_only（t_hi = +∞；time_axis.md §4.1「任何有限 T 都不放行」）
    has_unlocated_source : 来源槽位 unlocated / non_informative（无 t_hi）→ 不判泄露（另计）
    has_untimed_source   : 来源实体不在时间模型（无槽位）            → 不泄露
    n_no_source          : 有效值但无任何可追溯实体（如 project_id）  → 不泄露

分子只取「可证 t0 不可得」的槽位；「无法定位」（unlocated/non_informative）单独计数，
不混入 leak_rate（口径=spec §2.1 的 `t_hi > 0`），但逐字段并列
``n_t0_blocked`` = 泄露 ∪ 未定位（= 该值在 t0 landmark 门控下会被丢弃的患者数）。

``derived.*`` 字段追到底层槽位：按 A_pipeline 自己的派生逻辑
（``_therapy_flag`` 按 ``treatment_type`` 精确匹配；``_years_smoked`` 按 exposures 分支），
而不是旧实现的"源路径 raw 值"近似。

两种取值模式（逐字段记录在 ``audit_mode``）：

- ``a_pipeline``：字段在 ``A_pipeline/src/extract.py`` 的取值表内 → 用管线实际取值（spec §2.1 要求）；
- ``field_bank``：字段只在 Field Bank / univariate 宇宙（如 Test_1a 的 kept 字段、
  ``diagnoses[].tumor_focality``）→ 用 Field Bank 的 raw 取值逻辑
  （``extract_field_bank_raw_values(landmark=False)``，与 Test_1a off 臂同源），判据不变。

本模块只读复用 A_pipeline / discovery 的代码，不改动它们的实现。
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

from common.fields import (
    field_gdc_path,
    get_follow_ups,
    get_other_clinical_attributes,
    get_pathology_details,
    get_primary_diagnosis,
    parse_field_path,
    unique_join,
)
from common.missingness import classify_raw_value, clean_value
from common.paths import PROJECT_ROOT
from common.types import to_numeric
from discovery.field_bank import extract_field_bank_value
from discovery.landmark import timed_family_for_field
from time_stats import (
    EXCLUDED_LANDMARK_STATUSES,
    TIME_FAMILIES,
    extract_patient_time_record,
)


MODE_A_PIPELINE = "a_pipeline"
MODE_FIELD_BANK = "field_bank"

# 无时点家族（不在 time_stats 的六族里）：值不会因时点丢失，恒不泄露
UNTIMED_FAMILIES = ("demographic", "exposures", "family_histories", "project")

_A_PIPELINE_SRC = PROJECT_ROOT / "A_pipeline" / "src"
_A_PIPELINE_PKG = "a_pipeline_src"


def a_pipeline_extract():
    """以包名 ``a_pipeline_src`` 加载 ``A_pipeline/src``（避免与 projects/src 的 ``src`` 冲突）。

    只读复用：不修改 A_pipeline 的任何文件；其 ``__init__`` 会把 projects/src 接进 sys.path。
    """
    if _A_PIPELINE_PKG not in sys.modules:
        init = _A_PIPELINE_SRC / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            _A_PIPELINE_PKG, init, submodule_search_locations=[str(_A_PIPELINE_SRC)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[_A_PIPELINE_PKG] = module
        spec.loader.exec_module(module)
    return importlib.import_module(_A_PIPELINE_PKG + ".extract")


def a_pipeline_field_names() -> frozenset[str]:
    """``extract_values`` 实际产出的字段集合（动态取，不硬编码）。"""
    extract = a_pipeline_extract()
    return frozenset(extract.extract_values({}))


def pipeline_values(case: dict) -> dict:
    """论文管线的实际取值（``landmark_time=None`` = 无泄露处理）。"""
    return a_pipeline_extract().extract_values(case, landmark_time=None)


# ---------------------------------------------------------------------------
# 来源槽位
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SourceSlot:
    """一个来源实体的时点记录。``slotted=False`` = 该实体不在时间模型里（无槽位）。

    ``status`` 取 time_stats 的 RECORD_STATUS（point / bounded / lo_only / unlocated /
    non_informative），``t_hi`` = 有限 ``record_hi``（lo_only / 未定位为 None）。
    """

    family: str | None
    index: int | None
    status: str | None
    t_hi: float | None
    slotted: bool

    @property
    def is_future(self) -> bool:
        """该来源槽位在 t0 门控下不放行（值来自「未来」或无法证其 t0 已存在）。

        口径：``t_hi > 0`` 判泄露（spec §2.1）；``lo_only``（``t_hi = +∞``）按
        ``z_notes/time_axis/time_axis.md`` §4.1「任何有限 T 都不放行」同样判泄露；
        ``unlocated`` / ``non_informative`` 无 t_hi，不判泄露（另计 ``n_unlocated_source``）。
        """
        if not self.slotted:
            return False
        if self.status in EXCLUDED_LANDMARK_STATUSES:
            return False
        if self.t_hi is None:
            return True
        return float(self.t_hi) > 0

    @property
    def is_unlocated(self) -> bool:
        return bool(self.slotted and self.status in EXCLUDED_LANDMARK_STATUSES)

    @property
    def is_lo_only(self) -> bool:
        return bool(
            self.slotted
            and self.status not in EXCLUDED_LANDMARK_STATUSES
            and self.t_hi is None
        )

    def as_dict(self) -> dict:
        return {
            "family": self.family,
            "slot": self.index,
            "status": self.status,
            "t_hi": self.t_hi,
            "slotted": self.slotted,
        }


UNSLOTTED = SourceSlot(family=None, index=None, status=None, t_hi=None, slotted=False)


def _finite_hi(t_hi):
    if t_hi is None:
        return None
    if t_hi == float("inf") or t_hi == float("-inf"):
        return None
    return float(t_hi)


def case_slot_index(case: dict) -> dict[str, dict[int, SourceSlot]]:
    """{family: {id(obj): SourceSlot}}：时间模型的槽位，按对象身份索引。"""
    record = extract_patient_time_record(case)
    index: dict[str, dict[int, SourceSlot]] = {family: {} for family in TIME_FAMILIES}
    for family, slots in (record.get("_slots") or {}).items():
        bucket = index.setdefault(family, {})
        for position, slot in enumerate(slots or [], start=1):
            if not isinstance(slot, dict):
                continue
            obj = slot.get("obj")
            if not isinstance(obj, dict):
                continue
            status = slot.get("record_status")
            t_hi = _finite_hi(slot.get("record_hi"))
            bucket[id(obj)] = SourceSlot(
                family=family, index=position, status=status, t_hi=t_hi, slotted=True
            )
    return index


def _slot_for(index, family: str | None, obj) -> SourceSlot:
    """对象 → 来源槽位；不在时间模型（无槽位）时返回未定位记录（family 仅作标签）。"""
    if isinstance(obj, dict) and family:
        found = index.get(family, {}).get(id(obj))
        if found is not None:
            return found
    if family is None:
        return UNSLOTTED
    return SourceSlot(family=family, index=None, status=None, t_hi=None, slotted=False)


# ---------------------------------------------------------------------------
# 逐病例上下文
# ---------------------------------------------------------------------------
@dataclass
class CaseContext:
    case: dict
    slots: dict[str, dict[int, SourceSlot]]
    primary_diagnosis: dict
    values: dict = dataclass_field(default_factory=dict)

    def slot(self, family: str | None, obj) -> SourceSlot:
        return _slot_for(self.slots, family, obj)


def case_context(case: dict, *, with_pipeline_values: bool = True) -> CaseContext:
    return CaseContext(
        case=case,
        slots=case_slot_index(case),
        primary_diagnosis=get_primary_diagnosis(list(case.get("diagnoses") or [])),
        values=pipeline_values(case) if with_pipeline_values else {},
    )


def case_contexts(cases: list[dict], *, with_pipeline_values: bool = True) -> list[CaseContext]:
    return [case_context(case, with_pipeline_values=with_pipeline_values) for case in cases]


# ---------------------------------------------------------------------------
# 字段取值规格（镜像 A_pipeline/src/extract.py）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ValueSpec:
    """一个 A_pipeline 字段的取值方式（与 extract.py 逐行对应）。"""

    kind: str
    keys: tuple
    placeholder: str
    family: str | None = None          # join 类：贡献值的实体家族
    slot_family: str | None = None     # join 类：实体在时间模型里的家族（默认同 family）
    treatment_type: str | None = None  # therapy 类


PHARMA_TREATMENT_TYPE = "pharmaceutical therapy, nos"
RADIATION_TREATMENT_TYPE = "radiation therapy, nos"

_A_PIPELINE_SPECS: dict[str, ValueSpec] = {
    "demographic.age_at_index": ValueSpec("case_clean", ("demographic", "age_at_index"), "unknown"),
    "demographic.sex_at_birth": ValueSpec(
        "case_first",
        (("demographic", "sex_at_birth"), ("demographic", "gender")),
        "not reported",
    ),
    "demographic.race": ValueSpec("case_clean", ("demographic", "race"), "not reported"),
    "demographic.ethnicity": ValueSpec("case_clean", ("demographic", "ethnicity"), "not reported"),
    "project.project_id": ValueSpec("case_clean", ("project", "project_id"), "not reported"),
    "diagnoses[].primary_diagnosis": ValueSpec(
        "primary_diag_clean", ("primary_diagnosis",), "Unknown Neoplasm"
    ),
    "diagnoses[].morphology": ValueSpec("primary_diag_clean", ("morphology",), "not reported"),
    "diagnoses[].tissue_or_organ_of_origin": ValueSpec(
        "primary_diag_clean", ("tissue_or_organ_of_origin",), "not reported"
    ),
    "diagnoses[].laterality": ValueSpec("primary_diag_clean", ("laterality",), "not reported"),
    "diagnoses[].year_of_diagnosis": ValueSpec(
        "primary_diag_clean", ("year_of_diagnosis",), "not reported"
    ),
    "diagnoses[].age_at_diagnosis": ValueSpec(
        "primary_diag_clean", ("age_at_diagnosis",), "unknown"
    ),
    "diagnoses[].tumor_grade": ValueSpec("primary_diag_clean", ("tumor_grade",), "not reported"),
    "diagnoses[].prior_malignancy": ValueSpec(
        "primary_diag_clean", ("prior_malignancy",), "not reported"
    ),
    "diagnoses[].synchronous_malignancy": ValueSpec(
        "primary_diag_clean", ("synchronous_malignancy",), "not reported"
    ),
    "diagnoses[].prior_treatment": ValueSpec(
        "primary_diag_clean", ("prior_treatment",), "not reported"
    ),
    "diagnoses[].ajcc_pathologic_t": ValueSpec(
        "primary_diag_clean", ("ajcc_pathologic_t",), "TX"
    ),
    "diagnoses[].ajcc_pathologic_n": ValueSpec(
        "primary_diag_clean", ("ajcc_pathologic_n",), "NX"
    ),
    "diagnoses[].ajcc_pathologic_m": ValueSpec(
        "primary_diag_clean", ("ajcc_pathologic_m",), "MX"
    ),
    "diagnoses[].ajcc_pathologic_stage": ValueSpec(
        "primary_diag_first",
        (("ajcc_pathologic_stage",), ("figo_stage",)),
        "Stage X",
    ),
    "diagnoses[].ajcc_staging_system_edition": ValueSpec(
        "primary_diag_first",
        (("ajcc_staging_system_edition",), ("figo_staging_edition_year",)),
        "not reported",
    ),
    "diagnoses[].site_of_resection_or_biopsy": ValueSpec(
        "primary_diag_clean", ("site_of_resection_or_biopsy",), "not reported"
    ),
    "diagnoses[].pathology_details[].lymph_nodes_tested": ValueSpec(
        "join",
        ("lymph_nodes_tested",),
        "not reported",
        family="diagnoses_pathology_details",
        slot_family="diagnoses_pathology_details",
    ),
    "diagnoses[].pathology_details[].lymph_nodes_positive": ValueSpec(
        "join",
        ("lymph_nodes_positive",),
        "not reported",
        family="diagnoses_pathology_details",
        slot_family="diagnoses_pathology_details",
    ),
    "follow_ups[].ecog_performance_status": ValueSpec(
        "join",
        ("ecog_performance_status",),
        "not reported",
        family="follow_ups",
        slot_family="follow_ups",
    ),
    "follow_ups[].other_clinical_attributes[].bmi": ValueSpec(
        "join",
        ("bmi",),
        "not reported",
        family="follow_ups_other_clinical_attributes",
        slot_family="follow_ups_other_clinical_attributes",
    ),
    "exposures[].pack_years_smoked": ValueSpec(
        "join", ("pack_years_smoked",), "unknown", family="exposures"
    ),
    "exposures[].cigarettes_per_day": ValueSpec(
        "join", ("cigarettes_per_day",), "unknown", family="exposures"
    ),
    "exposures[].alcohol_history": ValueSpec(
        "join", ("alcohol_history",), "not reported", family="exposures"
    ),
    "derived.pharmaceutical_therapy": ValueSpec(
        "therapy",
        (),
        "unknown",
        family="diagnoses_treatments",
        slot_family="diagnoses_treatments",
        treatment_type=PHARMA_TREATMENT_TYPE,
    ),
    "derived.radiation_therapy": ValueSpec(
        "therapy",
        (),
        "unknown",
        family="diagnoses_treatments",
        slot_family="diagnoses_treatments",
        treatment_type=RADIATION_TREATMENT_TYPE,
    ),
    "derived.years_smoked": ValueSpec("years_smoked", (), "unknown", family="exposures"),
}


def a_pipeline_spec(field_path: str) -> ValueSpec | None:
    return _A_PIPELINE_SPECS.get(str(field_path or "").strip())


# ---------------------------------------------------------------------------
# 逐字段来源（FieldProvenance）
# ---------------------------------------------------------------------------
@dataclass
class FieldProvenance:
    field: str
    value: str
    valid: bool
    mode: str
    sources: list[SourceSlot]
    placeholder: str
    traceable: bool

    @property
    def has_future_source(self) -> bool:
        """t0 门控不放行的来源（有限 t_hi > 0 或 lo_only）→ 计入 leak_rate 分子。"""
        return any(source.is_future for source in self.sources)

    @property
    def has_lo_only_source(self) -> bool:
        """来源槽位上界失守（t_hi = +∞）：按 time_axis.md §4.1 判泄露，单独计数以便追溯。"""
        return any(source.is_lo_only for source in self.sources)

    @property
    def has_unlocated_source(self) -> bool:
        """来源槽位 unlocated / non_informative（无 t_hi，不判泄露，单独计数）。"""
        return any(source.is_unlocated for source in self.sources)

    @property
    def has_untimed_source(self) -> bool:
        """来源实体不在时间模型（无槽位）。"""
        return any(not source.slotted for source in self.sources)


def _first_nonempty(values, fallback: str) -> str:
    for value in values:
        cleaned = clean_value(value, "")
        if cleaned:
            return cleaned
    return fallback


def _case_path(case: dict, keys: tuple):
    node = case
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _ordered_diagnoses(case: dict) -> list[dict]:
    """与 A_pipeline.extract._ordered_diagnoses 同步（primary 在前）。"""
    diagnoses = list(case.get("diagnoses") or [])
    if not diagnoses:
        return []
    primary = get_primary_diagnosis(diagnoses)
    rest = [item for item in diagnoses if item is not primary]
    return [primary, *rest]


def _all_treatments(case: dict) -> list[dict]:
    """与 A_pipeline.extract._all_treatments 同步（含 case 级 treatments）。"""
    treatments: list[dict] = []
    for diagnosis in _ordered_diagnoses(case):
        treatments.extend(diagnosis.get("treatments", []) or [])
    treatments.extend(case.get("treatments", []) or [])
    return treatments


def _format_number(value) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def _join_objects(case: dict, family: str) -> list[dict]:
    if family == "diagnoses_pathology_details":
        objects = get_pathology_details(case)
    elif family == "follow_ups":
        objects = get_follow_ups(case)
    elif family == "follow_ups_other_clinical_attributes":
        objects = get_other_clinical_attributes(case)
    elif family == "exposures":
        objects = list(case.get("exposures") or [])
    else:
        raise ValueError(f"未知 join 家族: {family}")
    return [item for item in objects if isinstance(item, dict)]


def _provenance_spec(
    spec: ValueSpec, ctx: CaseContext
) -> tuple[str, list[SourceSlot]]:
    """镜像 A_pipeline 的取值并给出贡献值的来源实体。"""
    case = ctx.case
    diag = ctx.primary_diagnosis
    slot_family = spec.slot_family or spec.family

    if spec.kind == "case_clean":
        return clean_value(_case_path(case, spec.keys), spec.placeholder), []

    if spec.kind == "case_first":
        values = [_case_path(case, keys) for keys in spec.keys]
        return _first_nonempty(values, spec.placeholder), []

    if spec.kind == "primary_diag_clean":
        return clean_value(diag.get(spec.keys[0], ""), spec.placeholder), [
            ctx.slot("diagnoses", diag)
        ]

    if spec.kind == "primary_diag_first":
        values = [diag.get(keys[0], "") for keys in spec.keys]
        return _first_nonempty(values, spec.placeholder), [ctx.slot("diagnoses", diag)]

    if spec.kind == "join":
        key = spec.keys[0]
        objects = _join_objects(case, spec.family)
        contributing = [
            obj for obj in objects if clean_value(obj.get(key, ""), "")
        ]
        value = unique_join([obj.get(key) for obj in objects], spec.placeholder)
        return value, [ctx.slot(slot_family, obj) for obj in contributing]

    if spec.kind == "therapy":
        matched: list[dict] = []
        tokens: list[str] = []
        for treatment in _all_treatments(case):
            if not isinstance(treatment, dict):
                continue
            if str(treatment.get("treatment_type", "")).strip().lower() != spec.treatment_type:
                continue
            token = clean_value(treatment.get("treatment_or_therapy", ""), "")
            if token:
                matched.append(treatment)
                tokens.append(token.lower())
        if any(token == "yes" for token in tokens):
            value = "yes"
        elif any(token == "no" for token in tokens):
            value = "no"
        else:
            value = spec.placeholder
        return value, [ctx.slot(slot_family, obj) for obj in matched]

    if spec.kind == "years_smoked":
        return _years_smoked_provenance(ctx)

    raise ValueError(f"未知取值规格: {spec.kind}")


def _years_smoked_provenance(ctx: CaseContext) -> tuple[str, list[SourceSlot]]:
    """镜像 A_pipeline.extract._years_smoked（含分支来源：暴露记录 / 诊断年）。"""
    case = ctx.case
    diag = ctx.primary_diagnosis
    year_of_diagnosis = clean_value(diag.get("year_of_diagnosis", ""), "not reported")
    age_at_index = clean_value((case.get("demographic") or {}).get("age_at_index"), "unknown")
    exposure_slot = lambda obj: ctx.slot("exposures", obj)  # noqa: E731

    for exposure in case.get("exposures") or []:
        if not isinstance(exposure, dict):
            continue
        duration = to_numeric(exposure.get("exposure_duration_years"))
        if duration is not None:
            return _format_number(duration), [exposure_slot(exposure)]

        onset_year = to_numeric(exposure.get("tobacco_smoking_onset_year"))
        quit_year = to_numeric(exposure.get("tobacco_smoking_quit_year"))
        diagnosis_year = to_numeric(year_of_diagnosis)
        if onset_year is not None and quit_year is not None:
            return _format_number(quit_year - onset_year), [exposure_slot(exposure)]
        if onset_year is not None and diagnosis_year is not None:
            # 该分支读的是主诊断的 year_of_diagnosis：来源加上诊断槽位
            return _format_number(diagnosis_year - onset_year), [
                exposure_slot(exposure),
                ctx.slot("diagnoses", diag),
            ]

        age_at_onset = to_numeric(exposure.get("age_at_onset"))
        index_age = to_numeric(age_at_index)
        if age_at_onset is not None and index_age is not None:
            return _format_number(index_age - age_at_onset), [exposure_slot(exposure)]
    return "unknown", []


def a_pipeline_provenance(field_path: str, ctx: CaseContext) -> FieldProvenance:
    """A_pipeline 取值 + 来源槽位追溯（含与管线取值的逐病例一致性校验）。"""
    field = str(field_path or "").strip()
    spec = a_pipeline_spec(field)
    if spec is None:
        raise KeyError(f"{field} 不在 A_pipeline 取值表内（extract_values）")
    value, sources = _provenance_spec(spec, ctx)
    if ctx.values:
        expected = ctx.values.get(field, spec.placeholder)
        if str(value) != str(expected):
            raise RuntimeError(
                f"值来源镜像与 A_pipeline 取值不一致: field={field} "
                f"mirror={value!r} pipeline={expected!r}"
            )
    family, _ = timed_family_for_field(field_gdc_path(field))
    return FieldProvenance(
        field=field,
        value=str(value),
        valid=str(value) != spec.placeholder,
        mode=MODE_A_PIPELINE,
        sources=list(sources),
        placeholder=spec.placeholder,
        traceable=not (family is None and not sources),
    )


# ---------------------------------------------------------------------------
# Field Bank 取值模式的来源追溯（Test_1a kept 字段宇宙）
# ---------------------------------------------------------------------------
def _iter_path_values(root: dict, field_path: str) -> list[tuple[dict, object]]:
    """(持有该键的实体, 叶子值) 列表——与 ``extract_path_values`` 同序遍历。"""
    holders: list[tuple[object, dict]] = [(root, root)]
    for key, is_array in parse_field_path(field_path):
        nxt: list[tuple[object, dict]] = []
        for node, holder in holders:
            if not isinstance(node, dict) or key not in node:
                continue
            value = node[key]
            if is_array:
                if isinstance(value, list):
                    nxt.extend(
                        (item, item if isinstance(item, dict) else holder)
                        for item in value
                    )
            else:
                nxt.append((value, node))
        holders = nxt
    return [(holder, value) for value, holder in holders]


def _field_bank_contributors(
    field: str, ctx: CaseContext
) -> tuple[str, bool, list[SourceSlot]]:
    """镜像 ``field_bank._valid_raw_values``（family=None 的无 mask 分支）。

    返回 (镜像取值, 是否有效, 来源实体槽位)。
    """
    family, _ = timed_family_for_field(field)
    if field == "diagnoses[]" or field.startswith("diagnoses[]."):
        remainder = field[len("diagnoses[]"):].lstrip(".")
        leaf = field.split(".")[-1].replace("[]", "")
        if "." not in remainder and leaf:
            primary = ctx.primary_diagnosis
            if primary and leaf in primary:
                value = primary.get(leaf)
                ok = classify_raw_value(value) == "valid"
                return (
                    unique_join([value], "not reported") if ok else "not reported",
                    ok,
                    [ctx.slot("diagnoses", primary)] if ok else [],
                )
    slot_family = family if family in ctx.slots else None
    pairs = [
        (holder, value)
        for holder, value in _iter_path_values(ctx.case, field)
        if classify_raw_value(value) == "valid"
    ]
    value = unique_join([item for _, item in pairs], "not reported")
    return value, bool(pairs), [_slot_for(ctx.slots, slot_family, holder) for holder, _ in pairs]


def field_bank_provenance(field_path: str, ctx: CaseContext) -> FieldProvenance:
    """Field Bank 取值（``landmark=False``，与 Test_1a off 臂同源）+ 来源槽位追溯。

    取值直接调用 Field Bank 自身的 ``extract_field_bank_value``（只读复用），
    来源实体由 ``_field_bank_contributors`` 同规则给出并与其比对，不一致即报错。
    """
    field = str(field_path or "").strip()
    value, valid = extract_field_bank_value(ctx.case, field, landmark=False)
    mirror_value, mirror_valid, sources = _field_bank_contributors(field, ctx)
    if (str(mirror_value), bool(mirror_valid)) != (str(value), bool(valid)):
        raise RuntimeError(
            f"值来源镜像与 Field Bank 取值不一致: field={field} "
            f"mirror=({mirror_value!r},{mirror_valid}) field_bank=({value!r},{valid})"
        )
    return FieldProvenance(
        field=field,
        value=str(value),
        valid=bool(valid),
        mode=MODE_FIELD_BANK,
        sources=list(sources),
        placeholder="not reported",
        traceable=True,
    )


def field_provenance(field_path: str, ctx: CaseContext) -> FieldProvenance:
    """统一入口：A_pipeline 取值表内的字段走管线口径，其余走 Field Bank 口径。"""
    field = str(field_path or "").strip()
    if a_pipeline_spec(field) is not None:
        return a_pipeline_provenance(field, ctx)
    return field_bank_provenance(field, ctx)


def audit_modes_for_fields(fields) -> dict[str, str]:
    """{field: a_pipeline|field_bank}（不接触数据，用于计划/报告）。"""
    return {
        str(field): (
            MODE_A_PIPELINE if a_pipeline_spec(field) is not None else MODE_FIELD_BANK
        )
        for field in fields
    }


# ---------------------------------------------------------------------------
# 字段家族（报告用；derived.* 取底层槽位路径）
# ---------------------------------------------------------------------------
def audited_slot_path(field_path: str) -> str:
    """审计对象路径：``derived.*`` → 底层槽位路径（``field_gdc_path``），其余原样。"""
    return str(field_gdc_path(str(field_path or "").strip()))


def field_family(field_path: str) -> tuple[str | None, str]:
    """(来源槽位家族, 底层槽位路径)——与 ``timed_family_for_field`` 同口径。"""
    path = audited_slot_path(field_path)
    family, remainder = timed_family_for_field(path)
    return family, path


__all__ = [
    "MODE_A_PIPELINE",
    "MODE_FIELD_BANK",
    "TIME_FAMILIES",
    "UNTIMED_FAMILIES",
    "CaseContext",
    "FieldProvenance",
    "SourceSlot",
    "a_pipeline_extract",
    "a_pipeline_field_names",
    "a_pipeline_provenance",
    "a_pipeline_spec",
    "audit_modes_for_fields",
    "audited_slot_path",
    "case_context",
    "case_contexts",
    "case_slot_index",
    "field_bank_provenance",
    "field_family",
    "field_provenance",
    "pipeline_values",
]
