"""S11：hgcn_clinic 任意方案编码 / landmark 取值一致性 / 冻结备份等价回归。

覆盖四件事：

1. 方案解析：L0-L5 与今天一致（manual/all 仍只展开 L0-L5），论文方案 /
   templates 自定义方案显式点名可用；
2. 字段分类：冻结三分法优先，其余按 D 向量同一份 GDC dictionary 结论
   （enum/boolean→nominal，integer/number→continuous）；提取器解析不了的字段
   保持 keep_none（对角 0 行），不抛错；
3. landmark 取值一致性：同患者同字段，hgcn 节点值的"有/无观测 + 原始值"
   与 prompt / baseline 链路（extract_values → prompts.csv）逐字段一致；
4. 冻结备份等价：L0-L5 重新编码的产物与仓库外备份逐值相等
   （备份/临床 JSON 缺失时 skip）。

全部用例只写 tmp_path，不碰 outputs/。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))

A_PIPELINE_ROOT = PROJECT_ROOT / "A_pipeline"
if str(A_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(A_PIPELINE_ROOT))

from common.fields import field_output_col, L5_PLACEHOLDER_BY_FIELD_PATH  # noqa: E402
from discovery.onehot import _load_gdc_dictionary  # noqa: E402

from src.baseline import (  # noqa: E402
    BASELINE_DICTIONARY_FIELD_TYPES,
    BASELINE_MISSING_TOKEN,
    BASELINE_OTHER_TOKEN,
    _aggregate_continuous_value,
    _canonical_nominal_value,
    _classify_field,
    _encode_ordinal_value,
    load_baseline_scheme_fields,
)
from src.config import (  # noqa: E402
    DEFAULT_TEXT_SCHEMES,
    PAPER_SCHEMES,
    SCHEME_FIELDS,
    load_custom_schemes,
    reset_scheme_registry,
)
from src.extract import extract_values  # noqa: E402
from src.hgcn_clinic import (  # noqa: E402
    HGCN_KEEP_NONE_TYPE,
    HGCN_SCHEME_FIELDS,
    artifact_field_name,
    field_type_name,
    load_hgcn_scheme_fields,
    resolve_hgcn_schemes,
    run_hgcn_clinic,
)
from src.json2prompt import run_json2prompt  # noqa: E402
from src.paths import DEFAULT_TEMPLATE_DIR, dataset_hgcn_clinic_dir  # noqa: E402


LEGACY_SCHEMES = list(DEFAULT_TEXT_SCHEMES)
BACKUP_ROOT = Path("/data/fangyuxuan/projects/medical_dl/backups/HGCN_clinic_2026-10-03")
DATASETS_CONFIG = A_PIPELINE_ROOT / "datasets.json"

# 字段银行字段：GDC 字典是 enum，但不在 extract_values 的词表里 -> 无值可提。
FIELD_BANK_FIELD = "diagnoses[].calgb_risk_group"


def _load_scheme_fields() -> None:
    reset_scheme_registry()
    load_custom_schemes(DEFAULT_TEMPLATE_DIR)
    load_baseline_scheme_fields(SCHEME_FIELDS)
    load_hgcn_scheme_fields(SCHEME_FIELDS)


# --------------------------------------------------------------------------
# 1. 方案解析 / 产物命名空间
# --------------------------------------------------------------------------


def test_resolve_hgcn_schemes_keeps_legacy_and_accepts_registered():
    _load_scheme_fields()
    assert resolve_hgcn_schemes("manual") == LEGACY_SCHEMES
    # `all` 保持旧行为：冻结产物树 outputs/{ds}/A_manual/HGCN_clinic/ 只属于 L0-L5
    assert resolve_hgcn_schemes("all") == LEGACY_SCHEMES
    # 论文方案 / templates 自定义方案显式点名（新命名空间）
    assert resolve_hgcn_schemes("paper") == list(PAPER_SCHEMES)
    assert resolve_hgcn_schemes("MULTISURV") == ["MULTISURV"]
    assert resolve_hgcn_schemes("Test_3_greedy_TCGA-LAML") == ["Test_3_greedy_TCGA-LAML"]
    with pytest.raises(ValueError):
        resolve_hgcn_schemes("NOT_A_REGISTERED_SCHEME")


def test_load_hgcn_scheme_fields_registers_every_loaded_scheme():
    _load_scheme_fields()
    assert set(HGCN_SCHEME_FIELDS) == set(SCHEME_FIELDS)
    for scheme in LEGACY_SCHEMES + ["MULTISURV", "Test_3_greedy_TCGA-LAML"]:
        assert HGCN_SCHEME_FIELDS[scheme] == list(SCHEME_FIELDS[scheme])


def test_artifact_field_name_keeps_frozen_placeholder_vocabulary():
    _load_scheme_fields()
    # L0-L5 = 冻结命名空间：沿用备份产物里的占位符
    assert artifact_field_name("L0", "demographic.age_at_index") == "AGE"
    assert artifact_field_name("L5", "follow_ups[].other_clinical_attributes[].bmi") == "BMI"
    assert artifact_field_name("L5", "diagnoses[].ajcc_pathologic_stage") == "AJCC_PATHOLOGIC_STAGE"
    # 其余方案 = 新命名空间：fields.json 字段路径
    assert artifact_field_name("MULTISURV", "project.project_id") == "project.project_id"
    assert artifact_field_name("Test_3_greedy_TCGA-LAML", FIELD_BANK_FIELD) == FIELD_BANK_FIELD
    # L0-L5 的字段全部落在占位符表内（不会退化成字段路径）
    for field in SCHEME_FIELDS["L5"]:
        assert L5_PLACEHOLDER_BY_FIELD_PATH.get(field), field


# --------------------------------------------------------------------------
# 2. 字段分类：冻结三分法 / GDC 字典 / keep_none
# --------------------------------------------------------------------------


def test_field_type_name_frozen_split_unchanged():
    _load_scheme_fields()
    assert field_type_name("diagnoses[].tumor_grade") == "ordinal"
    assert field_type_name("follow_ups[].ecog_performance_status") == "ordinal"
    assert field_type_name("demographic.age_at_index") == "continuous"
    assert field_type_name("follow_ups[].other_clinical_attributes[].bmi") == "continuous"
    assert field_type_name("demographic.sex_at_birth") == "nominal"
    assert field_type_name("diagnoses[].primary_diagnosis") == "nominal"


def test_field_type_name_new_dictionary_field_matches_d_vector_classification():
    _load_scheme_fields()
    # 提取器能解析、不在冻结三分法：与 D 向量共用同一份 GDC 字典结论
    assert field_type_name("project.project_id") == "nominal"
    assert field_type_name("derived.pharmaceutical_therapy") == "nominal"
    assert field_type_name("derived.radiation_therapy") == "nominal"
    assert field_type_name("exposures[].pack_years_smoked") == "continuous"
    assert field_type_name("derived.years_smoked") == "continuous"
    for field in ("project.project_id", "derived.years_smoked", "exposures[].pack_years_smoked"):
        assert field_type_name(field) == BASELINE_DICTIONARY_FIELD_TYPES[field]
    # 同一份 dictionary 的原始结论（共享机制，不是复制的第二套表）
    dictionary = _load_gdc_dictionary()
    assert _classify_field("project.project_id", dictionary) == "nominal"
    assert _classify_field(FIELD_BANK_FIELD, dictionary) == "nominal"


def test_field_type_name_unresolvable_stays_keep_none_without_crashing():
    _load_scheme_fields()
    # 字段银行字段（GDC 是 enum）在 A_pipeline 提取器里没有值 -> keep_none，不抛错
    assert field_type_name(FIELD_BANK_FIELD) == HGCN_KEEP_NONE_TYPE
    assert field_type_name("diagnoses[].icd_10_code") == HGCN_KEEP_NONE_TYPE
    assert field_type_name("follow_ups[].molecular_tests[].laboratory_test") == HGCN_KEEP_NONE_TYPE


# --------------------------------------------------------------------------
# 3. 自定义方案端到端：新字典字段有值，词表外字段 = keep_none 节点
# --------------------------------------------------------------------------


SCHEME_NAME = "Test_S11_mixed"
SCHEME_FIELDS_MIXED = [
    "demographic.sex_at_birth",            # 冻结 nominal
    "project.project_id",                  # 新字典 nominal（提取器可解析）
    "derived.pharmaceutical_therapy",      # 新字典 nominal（derived）
    FIELD_BANK_FIELD,                      # 提取器解析不了 -> keep_none
    "exposures[].pack_years_smoked",       # 新字典 continuous
]
KEEP_NONE_INDEX = SCHEME_FIELDS_MIXED.index(FIELD_BANK_FIELD)


def _write_scheme(template_dir: Path) -> None:
    scheme_dir = template_dir / SCHEME_NAME
    scheme_dir.mkdir(parents=True)
    (template_dir / "schemes.json").write_text(
        json.dumps({"_schemes": [SCHEME_NAME]}), encoding="utf-8"
    )
    (scheme_dir / "fields.json").write_text(
        json.dumps({"fields": SCHEME_FIELDS_MIXED, "source": "lizhe"}), encoding="utf-8"
    )
    header = ",".join(field_output_col(f) for f in SCHEME_FIELDS_MIXED)
    (scheme_dir / "template.csv").write_text(header + "\n", encoding="utf-8")


def _synthetic_cases() -> list[dict]:
    """两例：确诊在 100/200 天（有 timed 槽位），暴露无槽位（landmark 不裁剪）。"""
    return [
        {
            "submitter_id": "TCGA-XX-0001",
            "project": {"project_id": "TCGA-KICH"},
            "demographic": {
                "age_at_index": 60,
                "sex_at_birth": "female",
                "vital_status": "Alive",
                "days_to_last_follow_up": 700,
            },
            "diagnoses": [
                {
                    "diagnosis_is_primary_disease": "true",
                    "primary_diagnosis": "Adenocarcinoma",
                    "calgb_risk_group": "Favorable",
                    "days_to_diagnosis": 100,
                }
            ],
            "exposures": [{"pack_years_smoked": 12.5}],
            "follow_ups": [{"days_to_follow_up": 700}],
        },
        {
            "submitter_id": "TCGA-XX-0002",
            "project": {"project_id": "TCGA-KICH"},
            "demographic": {
                "age_at_index": 71,
                "sex_at_birth": "male",
                "vital_status": "Dead",
                "days_to_death": 900,
            },
            "diagnoses": [
                {
                    "diagnosis_is_primary_disease": "true",
                    "primary_diagnosis": "Adenocarcinoma",
                    "calgb_risk_group": "Adverse",
                    "days_to_diagnosis": 200,
                    "treatments": [
                        {
                            "treatment_type": "Pharmaceutical Therapy, NOS",
                            "treatment_or_therapy": "yes",
                            "days_to_treatment_start": 220,
                        }
                    ],
                }
            ],
            "exposures": [{"pack_years_smoked": 30}],
        },
    ]


def _run_custom_scheme(tmp_path: Path, **kwargs) -> Path:
    template_dir = tmp_path / "templates"
    _write_scheme(template_dir)
    _load_scheme_fields()
    load_custom_schemes(str(template_dir))
    load_hgcn_scheme_fields(SCHEME_FIELDS)

    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps(_synthetic_cases()), encoding="utf-8")
    out_root = tmp_path / "HGCN_clinic"
    shared = {
        "demographic.sex_at_birth": {
            BASELINE_MISSING_TOKEN: 0,
            BASELINE_OTHER_TOKEN: 1,
            "female": 2,
            "male": 3,
        }
    }
    run_hgcn_clinic(
        json_paths=str(cases_file),
        schemes=resolve_hgcn_schemes(SCHEME_NAME),
        out_root=str(out_root),
        shared_nominal_mappings=shared,
        mapping_scope={"type": "test"},
        nominal_min_count=1,
        **kwargs,
    )
    return out_root


def test_custom_scheme_encodes_new_dictionary_field_and_keep_none_node(tmp_path):
    out_root = _run_custom_scheme(tmp_path)
    scheme_dir = out_root / SCHEME_NAME
    ttt = joblib.load(scheme_dir / "ttt_cli_feas.pkl")
    t_cli = joblib.load(scheme_dir / "t_cli_feas.pkl")
    x_cli = joblib.load(scheme_dir / "x_cli.pkl")
    coverage = json.loads((scheme_dir / "coverage.json").read_text(encoding="utf-8"))
    schema = json.loads((scheme_dir / "field_schema.json").read_text(encoding="utf-8"))
    table = json.loads((scheme_dir / "encoding_table.json").read_text(encoding="utf-8"))

    assert sorted(ttt) == ["TCGA-XX-0001", "TCGA-XX-0002"]
    assert schema["fields"] == SCHEME_FIELDS_MIXED  # 新命名空间：字段路径
    assert schema["n_cli"] == len(SCHEME_FIELDS_MIXED)
    assert schema["field_types"][FIELD_BANK_FIELD] == HGCN_KEEP_NONE_TYPE
    assert schema["field_types"]["project.project_id"] == "nominal"
    assert schema["field_types"]["exposures[].pack_years_smoked"] == "continuous"

    # 词表外字段 -> 每例都缺观测；coverage 0%
    assert coverage[FIELD_BANK_FIELD]["n_observed"] == 0
    assert coverage[FIELD_BANK_FIELD]["n_missing"] == 2
    assert coverage[FIELD_BANK_FIELD]["percent_observed"] == 0.0

    project_mapping = table["nominal_mappings"]["project.project_id"]
    therapy_mapping = table["nominal_mappings"]["derived.pharmaceutical_therapy"]
    for patient_id, row in ttt.items():
        assert row[KEEP_NONE_INDEX] is None
        assert t_cli[patient_id][KEEP_NONE_INDEX] is None
        # keep_none 节点 = 对角 0 行（不是把缺失写成类别 0 / 数值 0）
        assert np.all(x_cli[patient_id][KEEP_NONE_INDEX] == 0.0)
        # 名义 / 连续节点取值正确
        assert row[0] == {"TCGA-XX-0001": 2.0, "TCGA-XX-0002": 3.0}[patient_id]
        assert row[4] == {"TCGA-XX-0001": 12.5, "TCGA-XX-0002": 30.0}[patient_id]
        # 两例 sex/pack_years 有区分度 -> minmax 后对角非零
        assert x_cli[patient_id][0, 0] != 0.0
        assert x_cli[patient_id][4, 4] != 0.0
        # project.project_id 两例同值 -> minmax 定值 0.0（t_cli 与 x_cli 对角一致）
        assert row[1] == float(project_mapping["tcga-kich"])
        assert t_cli[patient_id][1] == 0.0

    # 新字典字段的词表：shared 之外的按当前患者补拟合，写进 encoding_table
    assert project_mapping["tcga-kich"] == 2
    assert table["extra_nominal_mappings"]["fields"] == [
        "derived.pharmaceutical_therapy",
        "project.project_id",
    ]
    assert ttt["TCGA-XX-0002"][2] == float(therapy_mapping["yes"]) == 2.0
    assert ttt["TCGA-XX-0001"][2] is None  # 无 treatment 记录

    edge_index = joblib.load(scheme_dir / "edge_index_cli.pkl")
    n_cli = len(SCHEME_FIELDS_MIXED)
    assert edge_index.shape == (2, n_cli * (n_cli - 1))


def test_custom_scheme_landmark_routes_to_landmark_subdir(tmp_path):
    out_root = _run_custom_scheme(tmp_path, landmark_time=0, landmark_subdir="landmark_0")
    scheme_dir = out_root / SCHEME_NAME / "landmark_0"
    assert (scheme_dir / "x_cli.pkl").is_file()
    assert not (out_root / SCHEME_NAME / "x_cli.pkl").exists()
    schema = json.loads((scheme_dir / "field_schema.json").read_text(encoding="utf-8"))
    assert schema["landmark_time"] == 0
    assert "- landmark: t_hi <= 0 days" in (scheme_dir / "summary.md").read_text(encoding="utf-8")

    # 时间轴 mask 生效：确诊（100/200 天）与附属 treatment 在 t0 被丢弃
    ttt = joblib.load(scheme_dir / "ttt_cli_feas.pkl")
    assert ttt["TCGA-XX-0002"][2] is None  # pharmaceutical_therapy 来自 timed treatment
    # exposures 无槽位，landmark 不裁剪
    assert ttt["TCGA-XX-0001"][4] == 12.5
    # keep_none 节点依旧 0 观测
    assert all(row[KEEP_NONE_INDEX] is None for row in ttt.values())


# --------------------------------------------------------------------------
# 4. landmark 取值一致性：hgcn 节点 vs prompt / baseline 链路
# --------------------------------------------------------------------------


def _timed_case():
    """同 A_pipeline/tests/test_landmark_time.py：确诊 400 天，随访 700 天封顶。"""
    return {
        "submitter_id": "TCGA-XX-0001",
        "demographic": {
            "age_at_index": 60,
            "sex_at_birth": "male",
            "race": "white",
            "ethnicity": "not hispanic or latino",
            "vital_status": "Alive",
            "days_to_last_follow_up": 700,
        },
        "project": {"project_id": "TCGA-KICH"},
        "diagnoses": [
            {
                "diagnosis_is_primary_disease": "true",
                "primary_diagnosis": "Adenocarcinoma",
                "ajcc_pathologic_stage": "Stage IV",
                "prior_malignancy": "no",
                "days_to_diagnosis": 400,
                "treatments": [
                    {
                        "treatment_type": "Pharmaceutical Therapy, NOS",
                        "treatment_or_therapy": "yes",
                        "days_to_treatment_start": 420,
                    }
                ],
            }
        ],
        "follow_ups": [
            {
                "days_to_follow_up": 700,
                "ecog_performance_status": "1",
                "other_clinical_attributes": [{"bmi": 24.5, "days_to_comorbidity": 690}],
            }
        ],
    }


TIMED_FIELDS = [
    "diagnoses[].ajcc_pathologic_stage",
    "diagnoses[].prior_malignancy",
    "derived.pharmaceutical_therapy",
    "follow_ups[].ecog_performance_status",
    "follow_ups[].other_clinical_attributes[].bmi",
]


def _expected_node(field: str, values: dict):
    """prompt / baseline 同一套 helper 下的节点原始值（None = 缺观测）。"""
    raw = values.get(field)
    kind = field_type_name(field)
    if kind == "continuous":
        value = _aggregate_continuous_value(field, raw)
        return None if value is None else float(value)
    if kind == "ordinal":
        code = _encode_ordinal_value(field, raw)
        return float(code) if code > 0 else None
    return _canonical_nominal_value(raw)


@pytest.mark.parametrize("landmark_time", [None, 0, 365, 730])
def test_landmark_node_values_match_prompt_pipeline(tmp_path, landmark_time):
    _load_scheme_fields()
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps([_timed_case()]), encoding="utf-8")
    subdir = "" if landmark_time is None else f"landmark_{landmark_time}"
    fields = list(SCHEME_FIELDS["L5"])

    # prompt 链路：与 hgcn 同一个 extract_values，写 prompts.csv
    prompts_csv = Path(
        run_json2prompt(
            json_path=str(cases_file),
            scheme="L5",
            template_dir=DEFAULT_TEMPLATE_DIR,
            prompt_dir=str(tmp_path / "prompts"),
            landmark_time=landmark_time,
            landmark_subdir=subdir,
        )
    )
    prompts = pd.read_csv(prompts_csv).set_index("patient_id")
    tpl_df = pd.read_csv(Path(DEFAULT_TEMPLATE_DIR) / "L5" / "template.csv")
    templates = {
        field: str(tpl_df[field_output_col(field)].dropna().iloc[0]).strip() for field in fields
    }

    out_root = tmp_path / "HGCN_clinic"
    run_hgcn_clinic(
        json_paths=str(cases_file),
        schemes=["L5"],
        out_root=str(out_root),
        landmark_time=landmark_time,
        landmark_subdir=subdir,
    )
    scheme_dir = out_root / "L5" / subdir if subdir else out_root / "L5"
    ttt = joblib.load(scheme_dir / "ttt_cli_feas.pkl")
    table = json.loads((scheme_dir / "encoding_table.json").read_text(encoding="utf-8"))

    case = _timed_case()
    patient_id = case["submitter_id"]
    values = extract_values(case, landmark_time=landmark_time)
    row = ttt[patient_id]
    for index, field in enumerate(fields):
        expected = _expected_node(field, values)
        node = row[index]
        if expected is None or expected == BASELINE_MISSING_TOKEN:
            assert node is None, f"{field} @T={landmark_time}"
        elif field_type_name(field) == "nominal":
            mapping = table["nominal_mappings"][L5_PLACEHOLDER_BY_FIELD_PATH[field]]
            assert node == float(mapping.get(expected, mapping[BASELINE_OTHER_TOKEN]))
        else:
            assert node == expected, f"{field} @T={landmark_time}"
        # prompts.csv 的同一字段格 = 同一份 extract_values 渲染（逐字）
        cell = prompts.loc[patient_id, field_output_col(field)]
        assert cell == templates[field].replace("{}", str(values.get(field, "not reported")), 1)


@pytest.mark.parametrize(
    "landmark_time,expected_present",
    [(None, True), (0, False), (365, False), (730, True)],
)
def test_landmark_mask_flips_node_and_prompt_together(tmp_path, landmark_time, expected_present):
    """确诊 400 天 / 随访 700 天：T=730 全保留，T=0/365 全部裁掉（两链路同进同出）。"""
    _load_scheme_fields()
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps([_timed_case()]), encoding="utf-8")
    subdir = "" if landmark_time is None else f"landmark_{landmark_time}"

    prompts_csv = Path(
        run_json2prompt(
            json_path=str(cases_file),
            scheme="L5",
            template_dir=DEFAULT_TEMPLATE_DIR,
            prompt_dir=str(tmp_path / "prompts"),
            landmark_time=landmark_time,
            landmark_subdir=subdir,
        )
    )
    prompts = pd.read_csv(prompts_csv).set_index("patient_id")

    out_root = tmp_path / "HGCN_clinic"
    run_hgcn_clinic(
        json_paths=str(cases_file),
        schemes=["L5"],
        out_root=str(out_root),
        landmark_time=landmark_time,
        landmark_subdir=subdir,
    )
    scheme_dir = out_root / "L5" / subdir if subdir else out_root / "L5"
    ttt = joblib.load(scheme_dir / "ttt_cli_feas.pkl")

    values = extract_values(_timed_case(), landmark_time=landmark_time)
    assert values["diagnoses[].ajcc_pathologic_stage"] == ("Stage IV" if expected_present else "Stage X")
    fields = list(SCHEME_FIELDS["L5"])
    templates = {
        field: str(
            pd.read_csv(Path(DEFAULT_TEMPLATE_DIR) / "L5" / "template.csv")[
                field_output_col(field)
            ]
            .dropna()
            .iloc[0]
        ).strip()
        for field in fields
    }
    for field in [f for f in TIMED_FIELDS if f in fields]:
        node = ttt["TCGA-XX-0001"][fields.index(field)]
        assert (node is not None) is expected_present, field
        # 同一字段同一 landmark：prompts.csv 的格 = extract_values 的渲染（逐字）
        cell = prompts.loc["TCGA-XX-0001", field_output_col(field)]
        assert cell == templates[field].replace("{}", str(values.get(field, "not reported")), 1)
    # 无槽位的 demographic 字段两臂一致
    assert ttt["TCGA-XX-0001"][0] == 60.0


# --------------------------------------------------------------------------
# 5. 冻结备份等价（值级）
# --------------------------------------------------------------------------


def _lizhe_dataset(dataset: str):
    if not DATASETS_CONFIG.exists():
        return None
    entry = json.loads(DATASETS_CONFIG.read_text(encoding="utf-8")).get(dataset)
    if not entry:
        return None
    paths = [str(p) for p in entry.get("clinic_files") or []]
    if not paths or any(not Path(p).exists() for p in paths):
        return None
    return paths, list(entry.get("project_ids") or [])


@pytest.mark.skipif(not BACKUP_ROOT.is_dir(), reason="冻结备份不存在（仓库外）")
def test_l0_l5_value_equivalent_to_frozen_backup(tmp_path):
    dataset = "TCGA-KICH"
    loaded = _lizhe_dataset(dataset)
    if loaded is None:
        pytest.skip(f"{dataset} 临床 JSON 或 datasets.json 不可用")
    json_paths, project_ids = loaded

    out_root = dataset_hgcn_clinic_dir(dataset, base_root=str(tmp_path / "s11_hgcn_regress"))
    run_hgcn_clinic(
        json_paths=json_paths,
        schemes=["L0", "L5"],
        out_root=out_root,
        project_ids=project_ids,
        dataset_name=dataset,
    )

    for scheme in ("L0", "L5"):
        produced = Path(out_root) / scheme
        backup = BACKUP_ROOT / dataset / scheme
        assert backup.is_dir(), backup

        # pickle：逐患者、逐节点严格相等（含 None 位置）
        for name in ("ttt_cli_feas.pkl", "t_cli_feas.pkl", "x_cli.pkl"):
            left = joblib.load(produced / name)
            right = joblib.load(backup / name)
            assert set(left) == set(right), name
            for key in left:
                if isinstance(left[key], np.ndarray):
                    assert np.array_equal(left[key], right[key]), f"{name}:{key}"
                else:
                    assert left[key] == right[key], f"{name}:{key}"
        assert np.array_equal(
            joblib.load(produced / "edge_index_cli.pkl"),
            joblib.load(backup / "edge_index_cli.pkl"),
        )

        # JSON 元数据：逐键值相等
        for name in ("coverage.json", "encoding_table.json", "field_schema.json"):
            left = json.loads((produced / name).read_text(encoding="utf-8"))
            right = json.loads((backup / name).read_text(encoding="utf-8"))
            assert left == right, name

        # summary.md：只允许 "- output:" 一行不同（它记录本次输出根目录）
        def _lines(path):
            return [
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if not line.startswith("- output:")
            ]

        assert _lines(produced / "summary.md") == _lines(backup / "summary.md")
