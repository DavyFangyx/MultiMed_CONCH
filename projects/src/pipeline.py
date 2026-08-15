"""
pipeline.py — JSON → Prompt CSV → CONCH Embedding 一键流水线

子命令:
  json2prompt  将 TCGA GDC JSON 转为 prompt CSV（默认 L0-L5 方案）
  encode       将 prompt CSV 编码为 CONCH embedding
  pipeline     先 json2prompt 后 encode，一键完成整条流水线
  baseline     将 clinical JSON 编码为 D0-D5 患者级 baseline 向量

默认路径 (均可通过参数覆盖):
  --datasets_config  .../CONCH-main/projects/datasets.json
  --dataset       可选；指定后输出到 projects/outputs/{dataset}/...
  --json_path     /data/lizhe/Medteam_projects/kindey_cancer_TCGA/clinical/clinical.cart.2026-03-17.json
  --template_dir  .../CONCH-main/projects/templates/l0_l5
  --prompt_dir    .../CONCH-main/projects/outputs/prompts
  --ckpt          .../CONCH/pytorch_model.bin
  --out           .../CONCH-main/projects/outputs/embeddings

─────────────────────────────────────
所有方案均在 template_dir/custom_schemes.json 中统一管理，
修改/增减字段直接编辑该文件即可，无需改动代码。
─────────────────────────────────────

用法示例:
conda activate trident
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main

  # 生成单个方案的 prompt CSV
python projects/scripts/run_pipeline.py json2prompt --scheme L0

  # 生成所有方案（由 custom_schemes.json 定义）
python projects/scripts/run_pipeline.py json2prompt --scheme all

  # 对单个方案编码
python projects/scripts/run_pipeline.py encode --scheme L0

  # 编码所有方案
python projects/scripts/run_pipeline.py encode --scheme all

  # 多数据集：指定一个数据集
python projects/scripts/run_pipeline.py pipeline --dataset TCGA-READ --scheme all

  # 多数据集：运行 datasets.json 中所有数据集
python projects/scripts/run_pipeline.py pipeline --dataset all --scheme all

  # 全流程：json→prompt→embedding（单方案）
python projects/scripts/run_pipeline.py pipeline --scheme L0

  # 全流程：所有方案
python projects/scripts/run_pipeline.py pipeline --scheme all

  # 覆盖默认路径示例
python projects/scripts/run_pipeline.py pipeline --scheme L0 \
    --json_path /my/clinical.json \
    --out /my/output/embeddings

  # 使用旧版 O/A/B/C/D 方案
  python projects/scripts/run_pipeline.py json2prompt --scheme O_simple --template_dir projects/templates/v1 --prompt_dir projects/outputs/prompts/v1

  # 生成 D0-D5 baseline（固定 onehot_ordinary 编码，连续值使用 Min-Max）
  python projects/scripts/run_pipeline.py baseline --dataset TCGA-READ --scheme all
"""

import argparse
from collections import Counter
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────
# 0. 默认路径常量（集中管理，修改一处即可）
# ─────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
WORKSPACE_ROOT = REPO_ROOT.parent

DEFAULT_JSON_PATH     = "/data/lizhe/Medteam_projects/kindey_cancer_TCGA/clinical/clinical.cart.2026-03-17.json"
DEFAULT_DATASETS_CONFIG = str(PROJECT_ROOT / "datasets.json")
DEFAULT_TEMPLATE_DIR  = str(PROJECT_ROOT / "templates/l0_l5")
DEFAULT_PROMPT_DIR    = str(PROJECT_ROOT / "outputs/prompts")
DEFAULT_CKPT          = str(WORKSPACE_ROOT / "CONCH/pytorch_model.bin")
DEFAULT_OUT_DIR       = str(PROJECT_ROOT / "outputs/embeddings")
DEFAULT_BASELINE_OUT_ROOT = str(PROJECT_ROOT / "outputs")
DEFAULT_GPU           = "7"
BASELINE_ENCODING_NAME = "onehot_ordinary"

# 所有方案均在 prompt_generate/templates/custom_schemes.json 中定义，
# 程序启动时由 load_custom_schemes() 动态注册到以下字典。
SCHEME_TEMPLATE    = {}  # 方案名 → 模板文件名
SCHEME_PROMPT_FILE = {}  # 方案名 → prompt CSV 文件名
SCHEME_DIRNAME     = {}  # 方案名 → embedding 输出子目录名
SCHEME_COLS        = {}  # 方案名 → prompt 列名列表（encode 阶段使用）
SCHEME_CONFIG      = {}  # 方案名 → {template_cols, placeholders, output_cols}

BASELINE_CONTINUOUS_FIELDS = {
    "AGE",
    "YEAR_OF_DIAGNOSIS",
    "AGE_AT_DIAGNOSIS",
    "LYMPH_NODES_TESTED",
    "LYMPH_NODES_POSITIVE",
    "BMI",
}

BASELINE_ORDINAL_FIELDS = {
    "TUMOR_GRADE",
    "AJCC_PATHOLOGIC_T",
    "AJCC_PATHOLOGIC_N",
    "AJCC_PATHOLOGIC_M",
    "AJCC_PATHOLOGIC_STAGE",
    "ECOG_PERFORMANCE_STATUS",
}

BASELINE_NOMINAL_FIELDS = {
    "SEX_AT_BIRTH",
    "RACE",
    "ETHNICITY",
    "PRIMARY_DIAGNOSIS",
    "MORPHOLOGY",
    "TISSUE_OR_ORGAN_OF_ORIGIN",
    "LATERALITY",
    "PRIOR_MALIGNANCY",
    "SYNCHRONOUS_MALIGNANCY",
    "PRIOR_TREATMENT",
    "AJCC_STAGING_SYSTEM_EDITION",
}

BASELINE_SCHEME_FIELDS = {
    "D0": [
        "AGE", "SEX_AT_BIRTH", "RACE", "ETHNICITY",
    ],
    "D1": [
        "AGE", "SEX_AT_BIRTH", "RACE", "ETHNICITY",
        "PRIMARY_DIAGNOSIS", "MORPHOLOGY", "TISSUE_OR_ORGAN_OF_ORIGIN",
        "LATERALITY", "YEAR_OF_DIAGNOSIS", "AGE_AT_DIAGNOSIS",
    ],
    "D2": [
        "AGE", "SEX_AT_BIRTH", "RACE", "ETHNICITY",
        "PRIMARY_DIAGNOSIS", "MORPHOLOGY", "TISSUE_OR_ORGAN_OF_ORIGIN",
        "LATERALITY", "YEAR_OF_DIAGNOSIS", "AGE_AT_DIAGNOSIS",
        "TUMOR_GRADE", "PRIOR_MALIGNANCY",
        "SYNCHRONOUS_MALIGNANCY", "PRIOR_TREATMENT",
    ],
    "D3": [
        "AGE", "SEX_AT_BIRTH", "RACE", "ETHNICITY",
        "PRIMARY_DIAGNOSIS", "MORPHOLOGY", "TISSUE_OR_ORGAN_OF_ORIGIN",
        "LATERALITY", "YEAR_OF_DIAGNOSIS", "AGE_AT_DIAGNOSIS",
        "TUMOR_GRADE", "PRIOR_MALIGNANCY",
        "SYNCHRONOUS_MALIGNANCY", "PRIOR_TREATMENT",
        "AJCC_PATHOLOGIC_T", "AJCC_PATHOLOGIC_N",
        "AJCC_PATHOLOGIC_M", "AJCC_PATHOLOGIC_STAGE",
        "AJCC_STAGING_SYSTEM_EDITION",
    ],
    "D4": [
        "AGE", "SEX_AT_BIRTH", "RACE", "ETHNICITY",
        "PRIMARY_DIAGNOSIS", "MORPHOLOGY", "TISSUE_OR_ORGAN_OF_ORIGIN",
        "LATERALITY", "YEAR_OF_DIAGNOSIS", "AGE_AT_DIAGNOSIS",
        "TUMOR_GRADE", "PRIOR_MALIGNANCY",
        "SYNCHRONOUS_MALIGNANCY", "PRIOR_TREATMENT",
        "AJCC_PATHOLOGIC_T", "AJCC_PATHOLOGIC_N",
        "AJCC_PATHOLOGIC_M", "AJCC_PATHOLOGIC_STAGE",
        "AJCC_STAGING_SYSTEM_EDITION",
        "LYMPH_NODES_TESTED", "LYMPH_NODES_POSITIVE",
    ],
    "D5": [
        "AGE", "SEX_AT_BIRTH", "RACE", "ETHNICITY",
        "PRIMARY_DIAGNOSIS", "MORPHOLOGY", "TISSUE_OR_ORGAN_OF_ORIGIN",
        "LATERALITY", "YEAR_OF_DIAGNOSIS", "AGE_AT_DIAGNOSIS",
        "TUMOR_GRADE", "PRIOR_MALIGNANCY",
        "SYNCHRONOUS_MALIGNANCY", "PRIOR_TREATMENT",
        "AJCC_PATHOLOGIC_T", "AJCC_PATHOLOGIC_N",
        "AJCC_PATHOLOGIC_M", "AJCC_PATHOLOGIC_STAGE",
        "AJCC_STAGING_SYSTEM_EDITION",
        "LYMPH_NODES_TESTED", "LYMPH_NODES_POSITIVE",
        "ECOG_PERFORMANCE_STATUS", "BMI",
    ],
}

BASELINE_MISSING_TOKEN = "__MISSING__"
BASELINE_OTHER_TOKEN = "__OTHER__"


def load_dataset_configs(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"数据集配置不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"数据集配置必须是 JSON object: {path}")
    return data


def resolve_dataset_names(dataset_arg: str, datasets: dict) -> list:
    if not dataset_arg:
        return []
    if dataset_arg == "all":
        return list(datasets.keys())

    names = [x.strip() for x in dataset_arg.split(",") if x.strip()]
    unknown = [x for x in names if x not in datasets]
    if unknown:
        raise ValueError(f"未知 dataset: {unknown}; 可用: {sorted(datasets)}")
    return names


def dataset_prompt_dir(dataset_name: str) -> str:
    return str(PROJECT_ROOT / "outputs" / dataset_name / "prompts")


def dataset_embedding_dir(dataset_name: str) -> str:
    return str(PROJECT_ROOT / "outputs" / dataset_name / "embeddings")


def dataset_baseline_embedding_dir(dataset_name: str, base_root: str) -> str:
    root = Path(base_root) / dataset_name
    return str(root / "embeddings")


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


# ─────────────────────────────────────────────────────────
# 0b. 自定义方案加载（运行时从 custom_schemes.json 注册）
# ─────────────────────────────────────────────────────────

def load_custom_schemes(template_dir: str) -> None:
    """读取 template_dir/custom_schemes.json，将自定义方案注册到各全局查找字典。

    JSON 格式（每个键为方案名，值为方案配置）：
    {
      "A1": {
        "description": "A方案去掉年龄字段（可选说明）",
        "template_file": "A1_template.csv",
        "prompt_file":   "tcga_ki_prompt_A1.csv",
        "dirname":       "A1_no_age_prompt",
        "template_cols": ["SEX_TEMPLATE", "PRIMARY_SITE_TEMPLATE", ...],
        "placeholders":  ["SEX", "PRIMARY_SITE", ...],
        "output_cols":   ["sex_template", "primary_site_template", ...]
      }
    }
    template_cols / placeholders / output_cols 三者长度必须相同。
    placeholders 中空字符串 "" 表示该列固定文本，不做占位符替换。
    """
    cfg_file = Path(template_dir) / "custom_schemes.json"
    if not cfg_file.exists():
        return

    with open(cfg_file, "r", encoding="utf-8") as f:
        custom: dict = json.load(f)

    required_keys = {"template_file", "prompt_file", "dirname",
                     "template_cols", "placeholders", "output_cols"}
    for name, cfg in custom.items():
        if name.startswith("_"):  # 跳过注释/元数据键（如 _comment）
            continue
        missing = required_keys - cfg.keys()
        if missing:
            raise ValueError(
                f"custom_schemes.json 中方案 '{name}' 缺少必要字段: {missing}"
            )
        if not (len(cfg["template_cols"]) == len(cfg["placeholders"]) == len(cfg["output_cols"])):
            raise ValueError(
                f"方案 '{name}' 的 template_cols / placeholders / output_cols 长度不一致。"
            )
        SCHEME_TEMPLATE[name]    = cfg["template_file"]
        SCHEME_PROMPT_FILE[name] = cfg["prompt_file"]
        SCHEME_DIRNAME[name]     = cfg["dirname"]
        SCHEME_COLS[name]        = list(cfg["output_cols"])
        SCHEME_CONFIG[name] = {
            "template_cols": list(cfg["template_cols"]),
            "placeholders":  list(cfg["placeholders"]),
            "output_cols":   list(cfg["output_cols"]),
        }

    if custom:
        loaded = [k for k in custom.keys() if not k.startswith("_")]
        print(f"[方案配置] 已加载 {len(loaded)} 个: {loaded}  （来自 {cfg_file}）")


# ─────────────────────────────────────────────────────────
# 1. JSON 字段解析工具函数
# ─────────────────────────────────────────────────────────

def _clean(val, fallback="not reported") -> str:
    if val is None:
        return fallback
    s = str(val).strip()
    if s.lower() in ("", "not reported", "unknown", "not applicable", "--"):
        return fallback
    return s


def get_primary_diagnosis(diagnoses: list) -> dict:
    if not diagnoses:
        return {}
    for d in diagnoses:
        if str(d.get("diagnosis_is_primary_disease", "")).lower() == "true":
            return d
    return diagnoses[0]


def _unique_join(values: list, fallback="not reported") -> str:
    vals = [_clean(v, "") for v in values]
    vals = sorted({x for x in vals if x})
    return ", ".join(vals) if vals else fallback


def get_treatments(case: dict) -> list:
    treatments = case.get("treatments", [])
    if not treatments:
        for d in case.get("diagnoses", []):
            treatments = d.get("treatments", [])
            if treatments:
                break
    return treatments or []


def get_pathology_details(case: dict) -> list:
    details = []
    for d in case.get("diagnoses", []):
        details.extend(d.get("pathology_details", []) or [])
    return details


def get_follow_ups(case: dict) -> list:
    return case.get("follow_ups", []) or []


def get_other_clinical_attributes(case: dict) -> list:
    attrs = []
    for f in get_follow_ups(case):
        attrs.extend(f.get("other_clinical_attributes", []) or [])
    return attrs


def extract_values(case: dict) -> dict:
    diag = get_primary_diagnosis(case.get("diagnoses", []))
    treatments = get_treatments(case)
    pathology_details = get_pathology_details(case)
    follow_ups = get_follow_ups(case)
    other_attrs = get_other_clinical_attributes(case)

    def _treatment_vals(key):
        return _unique_join([t.get(key, "") for t in treatments])

    def _pathology_vals(key):
        return _unique_join([p.get(key, "") for p in pathology_details])

    def _followup_vals(key):
        return _unique_join([f.get(key, "") for f in follow_ups])

    def _other_attr_vals(key):
        return _unique_join([a.get(key, "") for a in other_attrs])

    # O 方案专用：SUBTYPE 优先用 primary_diagnosis，退而其次用 disease_type
    _subtype = diag.get("primary_diagnosis", "") or case.get("disease_type", "")
    subtype = _clean(_subtype, "Unknown Neoplasm")

    # O 方案专用：EDITION 需去掉序数词后缀（"7th" → "7"）
    _edition_raw = diag.get("ajcc_staging_system_edition", "")
    if _edition_raw:
        edition = str(_edition_raw).replace("th", "").replace("st", "").replace("nd", "").replace("rd", "").strip()
    else:
        edition = "6"

    return {
        # O 方案专用键
        "SUBTYPE":                   subtype,
        "TUMORSTAGE":                _clean(diag.get("ajcc_pathologic_stage", ""), "Stage X"),
        "EDITION":                   edition,
        "RACE":                      _clean(case.get("demographic", {}).get("race", ""), "not reported"),
        "DIAGNOSIS":                 _clean(diag.get("primary_diagnosis", ""), "Unknown Neoplasm"),
        # A/B/C/D 共用键
        "AGE":                       _clean(case.get("demographic", {}).get("age_at_index"), "unknown"),
        "SEX":                       _clean(case.get("demographic", {}).get("gender", ""), "not reported"),
        "SEX_AT_BIRTH":              _clean(case.get("demographic", {}).get("sex_at_birth", ""), "not reported"),
        "ETHNICITY":                 _clean(case.get("demographic", {}).get("ethnicity", ""), "not reported"),
        "PRIMARY_SITE":              _clean(case.get("primary_site", ""), "not reported"),
        "PRIMARY_DIAGNOSIS":         _clean(diag.get("primary_diagnosis", ""), "Unknown Neoplasm"),
        "MORPHOLOGY":                _clean(diag.get("morphology", ""), "not reported"),
        "TISSUE_OR_ORGAN_OF_ORIGIN": _clean(diag.get("tissue_or_organ_of_origin", ""), "not reported"),
        "LATERALITY":                _clean(diag.get("laterality", ""), "not reported"),
        "YEAR_OF_DIAGNOSIS":         _clean(diag.get("year_of_diagnosis", ""), "not reported"),
        "AGE_AT_DIAGNOSIS":          _clean(diag.get("age_at_diagnosis", ""), "unknown"),
        "AJCC_PATHOLOGIC_STAGE":     _clean(diag.get("ajcc_pathologic_stage", ""), "Stage X"),
        "AJCC_PATHOLOGIC_T":         _clean(diag.get("ajcc_pathologic_t", ""), "TX"),
        "AJCC_PATHOLOGIC_N":         _clean(diag.get("ajcc_pathologic_n", ""), "NX"),
        "AJCC_PATHOLOGIC_M":         _clean(diag.get("ajcc_pathologic_m", ""), "MX"),
        "AJCC_STAGING_SYSTEM_EDITION": _clean(diag.get("ajcc_staging_system_edition", ""), "not reported"),
        "TUMOR_GRADE":               _clean(diag.get("tumor_grade", ""), "not reported"),
        "PRIOR_MALIGNANCY":          _clean(diag.get("prior_malignancy", ""), "not reported"),
        "SYNCHRONOUS_MALIGNANCY":    _clean(diag.get("synchronous_malignancy", ""), "not reported"),
        "TREATMENT_TYPE":            _treatment_vals("treatment_type"),
        "TREATMENT_OR_THERAPY":      _treatment_vals("treatment_or_therapy"),
        "TREATMENT_INTENT_TYPE":     _treatment_vals("treatment_intent_type"),
        "PRIOR_TREATMENT":           _clean(diag.get("prior_treatment", ""), "not reported"),
        "TOBACCO_SMOKING_STATUS":    _clean(diag.get("tobacco_smoking_status", ""), "not reported"),
        "PROGRESSION_OR_RECURRENCE": _clean(diag.get("progression_or_recurrence", ""), "not reported"),
        "LYMPH_NODES_TESTED":        _pathology_vals("lymph_nodes_tested"),
        "LYMPH_NODES_POSITIVE":      _pathology_vals("lymph_nodes_positive"),
        "ECOG_PERFORMANCE_STATUS":   _followup_vals("ecog_performance_status"),
        "BMI":                       _other_attr_vals("bmi"),
    }


def generate_prompt_row(case: dict, templates: dict, scheme: str) -> dict:
    cfg = SCHEME_CONFIG[scheme]
    vals = extract_values(case)
    row = {"patient_id": case["submitter_id"]}
    for tpl_col, placeholder, out_col in zip(
        cfg["template_cols"], cfg["placeholders"], cfg["output_cols"]
    ):
        tpl_str = templates[tpl_col]
        # placeholder 为空表示该列是固定句式，无需替换
        if placeholder:
            tpl_str = tpl_str.replace(placeholder, vals.get(placeholder, "not reported"))
        row[out_col] = tpl_str
    return row


# ─────────────────────────────────────────────────────────
# 2. json2prompt 核心逻辑
# ─────────────────────────────────────────────────────────

def _normalize_json_paths(json_paths) -> list:
    if isinstance(json_paths, (str, Path)):
        return [str(json_paths)]
    return [str(x) for x in json_paths]


def _match_case_project(case: dict, project_ids: list) -> bool:
    if not project_ids:
        return True
    project_id = str(case.get("project", {}).get("project_id", "")).strip()
    return project_id in set(project_ids)


def load_clinical_cases(json_paths, project_ids: list | None = None) -> list:
    paths = _normalize_json_paths(json_paths)
    cases_by_patient = {}
    total, skipped, duplicated = 0, 0, 0
    project_filtered = 0
    project_ids = list(project_ids or [])

    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            cases = json.load(f)
        print(f"      {path}: {len(cases)} 个病例")
        total += len(cases)

        for case in cases:
            pid = str(case.get("submitter_id", "")).strip()
            if not pid:
                skipped += 1
                continue
            if not _match_case_project(case, project_ids):
                project_filtered += 1
                continue
            if pid in cases_by_patient:
                duplicated += 1
                continue
            cases_by_patient[pid] = case

    print(f"      合计病例数: {total}")
    if project_ids:
        print(f"      project_id 过滤: {project_ids}")
        print(f"      project_id 过滤掉病例数: {project_filtered}")
    print(f"      去重后病例数: {len(cases_by_patient)}")
    if duplicated:
        print(f"      重复 submitter_id: {duplicated} 个，保留首次出现记录")
    if skipped:
        print(f"      跳过缺少 submitter_id: {skipped} 个")

    return list(cases_by_patient.values())


def run_json2prompt(json_path: str, scheme: str, template_dir: str, prompt_dir: str,
                    project_ids: list | None = None):
    cfg = SCHEME_CONFIG[scheme]
    template_file = Path(template_dir) / SCHEME_TEMPLATE[scheme]
    output_file   = Path(prompt_dir)   / SCHEME_PROMPT_FILE[scheme]
    json_paths = _normalize_json_paths(json_path)

    print(f"\n{'='*55}")
    print(f"[json2prompt] 方案 {scheme}")
    print(f"  JSON    : {json_paths}")
    print(f"  模板    : {template_file}")
    print(f"  输出    : {output_file}")
    print(f"{'='*55}")

    # 读取 JSON
    print(f"\n[1/3] 读取 JSON ...")
    cases = load_clinical_cases(json_paths, project_ids=project_ids)

    # 读取模板
    print(f"[2/3] 读取模板 ...")
    tpl_df = pd.read_csv(template_file)
    templates = {}
    for col in cfg["template_cols"]:
        if col not in tpl_df.columns:
            raise ValueError(f"模板文件缺少列: '{col}'，请确认 {template_file.name} 与方案 {scheme} 对应。")
        col_values = tpl_df[col].dropna().tolist()
        if not col_values:
            raise ValueError(f"模板列 '{col}' 为空，请检查模板文件。")
        templates[col] = col_values[0]
        print(f"      {col}: {templates[col]}")

    # 逐病例生成
    print("[3/3] 生成 prompts ...")
    records, skipped = [], 0
    for case in cases:
        if "submitter_id" not in case:
            skipped += 1
            continue
        records.append(generate_prompt_row(case, templates, scheme))
    if skipped:
        print(f"      跳过 {skipped} 个缺少 submitter_id 的条目")

    out_cols = ["patient_id"] + cfg["output_cols"]
    out_df = pd.DataFrame(records, columns=out_cols)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output_file, index=False)
    print(f"\n✅ 保存完成: {output_file}  ({len(out_df)} 行，{len(out_cols)-1} 个 prompt 列)")
    print(out_df.head(2).to_string())
    return str(output_file)


# ─────────────────────────────────────────────────────────
# 3. encode 核心逻辑
# ─────────────────────────────────────────────────────────

def _lazy_import_conch():
    """延迟导入 CONCH，避免在仅执行 json2prompt 时加载 torch"""
    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    import torch
    from conch.open_clip_custom import create_model_from_pretrained, get_tokenizer
    return torch, create_model_from_pretrained, get_tokenizer


def _build_patient_prompt_matrix(df: pd.DataFrame, prompt_cols: list) -> list:
    """按 prompt_cols 顺序为每位患者构建逐句 prompt 列表。"""
    patient_prompts = []
    for _, row in df.iterrows():
        sentences = []
        for col in prompt_cols:
            val = row[col] if col in row.index else ""
            if pd.isna(val):
                val = ""
            sentences.append(str(val).strip())
        patient_prompts.append(sentences)
    return patient_prompts


def run_encode(scheme: str, prompt_dir: str, ckpt: str, out_dir: str, batch_size: int = 64):
    os.environ["CUDA_VISIBLE_DEVICES"] = DEFAULT_GPU
    torch, create_model_from_pretrained, get_tokenizer = _lazy_import_conch()
    from tqdm import tqdm

    csv_path    = Path(prompt_dir) / SCHEME_PROMPT_FILE[scheme]
    out_subdir  = Path(out_dir)    / SCHEME_DIRNAME[scheme]
    prompt_cols = SCHEME_COLS[scheme]

    print(f"\n{'='*55}")
    print(f"[encode] 方案 {scheme}")
    print(f"  prompt CSV : {csv_path}")
    print(f"  输出目录   : {out_subdir}")
    print(f"  可见 GPU   : {DEFAULT_GPU}")
    print(f"{'='*55}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  设备: {device}")

    # 读取 prompt CSV
    print(f"\n[1/3] 读取 prompt CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"      病例数: {len(df)}")

    missing_cols = [c for c in prompt_cols if c not in df.columns]
    if missing_cols:
        raise ValueError(f"prompt CSV 缺少以下列（方案 {scheme}）：{missing_cols}")

    patient_ids = df["patient_id"].astype(str).tolist()
    patient_prompts = _build_patient_prompt_matrix(df, prompt_cols)

    if not patient_ids:
        print("\n      prompt CSV 中无患者，跳过编码。")
        return

    num_prompt_fields = len(prompt_cols)
    flat_prompts = [sentence for sentences in patient_prompts for sentence in sentences]

    print("\n  Prompt 预览（前 2 位患者，每句独立编码）:")
    for pid, sentences in zip(patient_ids[:2], patient_prompts[:2]):
        print(f"  [{pid}]")
        for col, sentence in zip(prompt_cols, sentences):
            print(f"    {col}: {sentence}")
        print()

    # 加载模型
    print(f"[2/3] 加载 CONCH: {ckpt}")
    model, _ = create_model_from_pretrained(model_cfg="conch_ViT-B-16", checkpoint_path=ckpt)
    model = model.to(device).eval()
    tokenizer = get_tokenizer()

    # 编码
    encoded    = tokenizer(flat_prompts, padding=True, truncation=True, return_tensors="pt")
    all_tokens = encoded["input_ids"]
    all_embeddings = []
    with torch.inference_mode():
        for i in tqdm(range(0, len(flat_prompts), batch_size), desc="Encoding"):
            tokens = all_tokens[i : i + batch_size].to(device)
            feats  = model.encode_text(tokens, embed_cls=False)
            feats  = feats / feats.norm(dim=-1, keepdim=True)
            all_embeddings.append(feats.cpu().float().numpy())
    embeddings = np.concatenate(all_embeddings, axis=0)
    embeddings = embeddings.reshape(len(patient_ids), num_prompt_fields, -1)
    print(f"      Embedding shape: {embeddings.shape}")

    # 保存
    print(f"\n[3/3] 按患者 ID 保存文件 → {out_subdir}")
    pt_dir = out_subdir / "pt"
    pt_dir.mkdir(parents=True, exist_ok=True)

    for pid, emb in tqdm(
        zip(patient_ids, embeddings),
        total=len(patient_ids),
        desc="保存每患者文件"
    ):
        tensor = torch.from_numpy(emb)
        torch.save(tensor, pt_dir / f"{pid}.pt")

    print("\n" + "=" * 55)
    print(f"✅  方案 {scheme} 编码完成")
    print(f"   患者数   : {len(patient_ids)}")
    print(f"   Prompt 数 : {num_prompt_fields}")
    print(f"   PT 目录  : {pt_dir}")
    print("=" * 55)


# ─────────────────────────────────────────────────────────
# 4. baseline 核心逻辑
# ─────────────────────────────────────────────────────────

def _split_collapsed_values(raw_value) -> list[str]:
    if raw_value is None:
        return []
    text = str(raw_value).strip()
    if not text:
        return []
    return [x.strip() for x in text.split(",") if str(x).strip()]


def _is_missing_baseline_token(token: str) -> bool:
    cleaned = " ".join(str(token).strip().lower().split())
    return cleaned in {
        "",
        "not reported",
        "unknown",
        "not applicable",
        "--",
        "stage x",
        "tx",
        "nx",
        "mx",
    }


def _canonical_nominal_value(raw_value) -> str:
    tokens = []
    for token in _split_collapsed_values(raw_value):
        cleaned = " ".join(str(token).strip().lower().split())
        if not _is_missing_baseline_token(cleaned):
            tokens.append(cleaned)
    uniq = sorted(set(tokens))
    return " | ".join(uniq) if uniq else BASELINE_MISSING_TOKEN


def _extract_numeric_values(raw_value) -> list[float]:
    nums = []
    for token in _split_collapsed_values(raw_value):
        cleaned = token.strip()
        if _is_missing_baseline_token(cleaned):
            continue
        match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
        if match:
            nums.append(float(match.group(0)))
    return nums


def _aggregate_continuous_value(field: str, raw_value) -> float | None:
    nums = _extract_numeric_values(raw_value)
    if not nums:
        return None
    if field == "AGE_AT_DIAGNOSIS":
        nums = [x / 365.25 if x > 365 else x for x in nums]
    return float(np.median(nums))


def _fit_continuous_stats(patient_rows: list[dict]) -> dict:
    stats = {}
    for field in sorted(BASELINE_CONTINUOUS_FIELDS):
        vals = [
            v for v in (_aggregate_continuous_value(field, row.get(field)) for row in patient_rows)
            if v is not None
        ]
        if vals:
            stats[field] = {
                "median": float(np.median(vals)),
                "min": float(np.min(vals)),
                "max": float(np.max(vals)),
            }
        else:
            stats[field] = {"median": 0.0, "min": 0.0, "max": 0.0}
    return stats


def _normalize_continuous_value(field: str, raw_value, stats: dict) -> float:
    field_stats = stats[field]
    value = _aggregate_continuous_value(field, raw_value)
    if value is None:
        value = float(field_stats["median"])
    vmin = float(field_stats["min"])
    vmax = float(field_stats["max"])
    if vmax <= vmin:
        return 0.0
    return float((value - vmin) / (vmax - vmin))


def _encode_tumor_grade(token: str) -> int:
    compact = token.lower().replace(" ", "")
    match = re.search(r"g([1-4])", compact)
    return int(match.group(1)) if match else 0


def _encode_t_stage(token: str) -> int:
    compact = token.lower().replace(" ", "")
    match = re.search(r"t(is|[0-4])", compact)
    if not match:
        return 0
    stage = match.group(1)
    if stage == "is":
        return 1
    return int(stage) + 2


def _encode_n_stage(token: str) -> int:
    compact = token.lower().replace(" ", "")
    match = re.search(r"n([0-3])", compact)
    return int(match.group(1)) + 1 if match else 0


def _encode_m_stage(token: str) -> int:
    compact = token.lower().replace(" ", "")
    match = re.search(r"m([0-1])", compact)
    return int(match.group(1)) + 1 if match else 0


def _encode_overall_stage(token: str) -> int:
    compact = token.lower().replace(" ", "")
    compact = compact.replace("stage", "")
    if not compact:
        return 0
    if compact.startswith("iv"):
        return 5
    if compact.startswith("iii"):
        return 4
    if compact.startswith("ii"):
        return 3
    if compact.startswith("i"):
        return 2
    if compact.startswith("0"):
        return 1
    return 0


def _encode_ecog(token: str) -> int:
    compact = token.lower().replace(" ", "")
    match = re.search(r"([0-5])", compact)
    return int(match.group(1)) + 1 if match else 0


def _encode_ordinal_value(field: str, raw_value) -> int:
    encoders = {
        "TUMOR_GRADE": _encode_tumor_grade,
        "AJCC_PATHOLOGIC_T": _encode_t_stage,
        "AJCC_PATHOLOGIC_N": _encode_n_stage,
        "AJCC_PATHOLOGIC_M": _encode_m_stage,
        "AJCC_PATHOLOGIC_STAGE": _encode_overall_stage,
        "ECOG_PERFORMANCE_STATUS": _encode_ecog,
    }
    encoder = encoders[field]
    codes = []
    for token in _split_collapsed_values(raw_value):
        if _is_missing_baseline_token(token):
            continue
        code = encoder(token)
        if code > 0:
            codes.append(code)
    return max(codes) if codes else 0


def _count_nominal_categories(patient_rows: list[dict]) -> dict[str, Counter]:
    counts = {}
    for field in sorted(BASELINE_NOMINAL_FIELDS):
        counter = Counter()
        for row in patient_rows:
            value = _canonical_nominal_value(row.get(field))
            if value != BASELINE_MISSING_TOKEN:
                counter[value] += 1
        counts[field] = counter
    return counts


def _fit_nominal_mappings(
    patient_rows: list[dict],
    *,
    min_count: int = 1,
    collapse_rare: bool = False,
) -> dict:
    mappings = {}
    counts = _count_nominal_categories(patient_rows)
    for field in sorted(BASELINE_NOMINAL_FIELDS):
        if collapse_rare:
            categories = sorted(
                category
                for category, count in counts[field].items()
                if count >= min_count
            )
        else:
            categories = sorted(counts[field])
        mapping = {
            BASELINE_MISSING_TOKEN: 0,
            BASELINE_OTHER_TOKEN: 1,
        }
        for category in categories:
            mapping[category] = len(mapping)
        mappings[field] = mapping
    return mappings


def _encode_nominal_value(field: str, raw_value, mappings: dict) -> int:
    mapping = mappings[field]
    value = _canonical_nominal_value(raw_value)
    if value == BASELINE_MISSING_TOKEN:
        return mapping[BASELINE_MISSING_TOKEN]
    return mapping.get(value, mapping[BASELINE_OTHER_TOKEN])


def _build_baseline_vector(
    row: dict,
    fields: list[str],
    continuous_stats: dict,
    nominal_mappings: dict,
) -> np.ndarray:
    vec = []
    for field in fields:
        if field in BASELINE_CONTINUOUS_FIELDS:
            vec.append(_normalize_continuous_value(field, row.get(field), continuous_stats))
        elif field in BASELINE_ORDINAL_FIELDS:
            vec.append(float(_encode_ordinal_value(field, row.get(field))))
        elif field in BASELINE_NOMINAL_FIELDS:
            code = _encode_nominal_value(field, row.get(field), nominal_mappings)
            onehot = np.zeros(len(nominal_mappings[field]), dtype=np.float32)
            onehot[code] = 1.0
            vec.extend(onehot.tolist())
        else:
            raise KeyError(f"未知 baseline 字段: {field}")
    return np.asarray(vec, dtype=np.float32)


def _build_baseline_feature_schema(nominal_mappings: dict) -> dict:
    schemas = {}
    for scheme, fields in BASELINE_SCHEME_FIELDS.items():
        cursor = 0
        features = []
        for field in fields:
            if field in BASELINE_NOMINAL_FIELDS:
                dim = len(nominal_mappings[field])
            else:
                dim = 1
            feature = {
                "field": field,
                "field_type": (
                    "continuous" if field in BASELINE_CONTINUOUS_FIELDS else
                    "ordinal" if field in BASELINE_ORDINAL_FIELDS else
                    "nominal"
                ),
                "start": cursor,
                "dim": dim,
            }
            if field in BASELINE_NOMINAL_FIELDS:
                feature["categories"] = [
                    key for key, _ in sorted(nominal_mappings[field].items(), key=lambda kv: kv[1])
                ]
            features.append(feature)
            cursor += dim
        schemas[scheme] = {
            "output_dim": cursor,
            "features": features,
        }
    return schemas


def _save_baseline_metadata(
    metadata_dir: Path,
    encoding: str,
    continuous_stats: dict,
    nominal_mappings: dict,
    feature_schema: dict,
    nominal_min_count: int | None = None,
    mapping_scope: dict | None = None,
    save_nominal_mapping: bool = True,
    save_feature_schema: bool = True,
    global_metadata_dir: Path | None = None,
) -> None:
    metadata_dir.mkdir(parents=True, exist_ok=True)

    normalization_stats = {
        "encoding": encoding,
        "continuous_method": "minmax",
        "fields": continuous_stats,
    }
    category_mapping = {
        "encoding": encoding,
        "missing_token": BASELINE_MISSING_TOKEN,
        "other_token": BASELINE_OTHER_TOKEN,
        "nominal_min_count": nominal_min_count,
        "mapping_scope": mapping_scope,
        "fields": nominal_mappings,
    }
    schema_payload = {
        "encoding": encoding,
        "schemes": feature_schema,
    }

    with open(metadata_dir / "normalization_stats.json", "w", encoding="utf-8") as f:
        json.dump(normalization_stats, f, ensure_ascii=False, indent=2)
    if save_nominal_mapping:
        with open(metadata_dir / "category_mapping.json", "w", encoding="utf-8") as f:
            json.dump(category_mapping, f, ensure_ascii=False, indent=2)
    if save_feature_schema:
        with open(metadata_dir / "feature_schema.json", "w", encoding="utf-8") as f:
            json.dump(schema_payload, f, ensure_ascii=False, indent=2)
    if global_metadata_dir is not None:
        ref_payload = {
            "encoding": encoding,
            "global_metadata_dir": str(global_metadata_dir),
            "category_mapping_json": str(global_metadata_dir / "category_mapping.json"),
            "feature_schema_json": str(global_metadata_dir / "feature_schema.json"),
        }
        with open(metadata_dir / "global_metadata_ref.json", "w", encoding="utf-8") as f:
            json.dump(ref_payload, f, ensure_ascii=False, indent=2)


def _save_global_baseline_metadata(
    metadata_dir: Path,
    nominal_mappings: dict,
    feature_schema: dict,
    nominal_min_count: int,
    dataset_names: list[str],
    patient_count: int,
) -> None:
    metadata_dir.mkdir(parents=True, exist_ok=True)
    category_mapping = {
        "encoding": BASELINE_ENCODING_NAME,
        "missing_token": BASELINE_MISSING_TOKEN,
        "other_token": BASELINE_OTHER_TOKEN,
        "nominal_min_count": nominal_min_count,
        "mapping_scope": {
            "type": "global_selected_datasets",
            "datasets": dataset_names,
            "patient_count": patient_count,
        },
        "fields": nominal_mappings,
    }
    schema_payload = {
        "encoding": BASELINE_ENCODING_NAME,
        "schemes": feature_schema,
    }
    with open(metadata_dir / "category_mapping.json", "w", encoding="utf-8") as f:
        json.dump(category_mapping, f, ensure_ascii=False, indent=2)
    with open(metadata_dir / "feature_schema.json", "w", encoding="utf-8") as f:
        json.dump(schema_payload, f, ensure_ascii=False, indent=2)


def _load_baseline_metadata(metadata_dir: str) -> tuple[dict, dict]:
    meta = Path(metadata_dir)
    stats_path = meta / "normalization_stats.json"
    mapping_path = meta / "category_mapping.json"
    if not stats_path.exists():
        raise FileNotFoundError(f"baseline metadata 缺少 {stats_path.name}: {meta}")
    if not mapping_path.exists():
        ref_path = meta / "global_metadata_ref.json"
        if ref_path.exists():
            with open(ref_path, "r", encoding="utf-8") as f:
                ref_payload = json.load(f)
            mapping_path = Path(ref_payload["category_mapping_json"])
        else:
            raise FileNotFoundError(
                f"baseline metadata 不完整: 需要 {stats_path.name} 和 {mapping_path.name}，当前目录 {meta}"
            )
    with open(stats_path, "r", encoding="utf-8") as f:
        stats_payload = json.load(f)
    with open(mapping_path, "r", encoding="utf-8") as f:
        mapping_payload = json.load(f)
    return dict(stats_payload["fields"]), dict(mapping_payload["fields"])

def _build_patient_rows(cases: list[dict]) -> list[dict]:
    rows = []
    for case in cases:
        row = {"patient_id": str(case["submitter_id"]).strip()}
        row.update(extract_values(case))
        rows.append(row)
    return rows


def run_baseline_encode(
    json_paths,
    schemes: list[str],
    out_root: str,
    project_ids: list | None = None,
    stats_dir: str | None = None,
    nominal_min_count: int = 5,
    shared_nominal_mappings: dict | None = None,
    mapping_scope: dict | None = None,
    global_metadata_dir: str | None = None,
):
    try:
        import torch
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "baseline 输出为 .pt 文件，当前 Python 环境缺少 torch。请切换到包含 torch 的环境后重试。"
        ) from exc

    print(f"\n{'='*55}")
    print(f"[baseline] 编码方式 {BASELINE_ENCODING_NAME}")
    print(f"  JSON     : {_normalize_json_paths(json_paths)}")
    print(f"  输出根目录 : {out_root}")
    if stats_dir:
        print(f"  复用统计量 : {stats_dir}")
    else:
        print("  复用统计量 : 否（当前运行数据拟合）")
    print(f"  nominal 阈值: >= {nominal_min_count} 保留，否则合并到 {BASELINE_OTHER_TOKEN}")
    print(f"{'='*55}")

    print("\n[1/3] 读取 JSON ...")
    cases = load_clinical_cases(json_paths, project_ids=project_ids)
    patient_rows = _build_patient_rows(cases)
    print(f"      患者数: {len(patient_rows)}")

    if stats_dir:
        continuous_stats, nominal_mappings = _load_baseline_metadata(stats_dir)
    else:
        continuous_stats = _fit_continuous_stats(patient_rows)
        if shared_nominal_mappings is not None:
            nominal_mappings = shared_nominal_mappings
        else:
            nominal_mappings = _fit_nominal_mappings(
                patient_rows,
                min_count=nominal_min_count,
                collapse_rare=True,
            )

    feature_schema = _build_baseline_feature_schema(nominal_mappings)
    metadata_dir = Path(out_root) / "metadata"

    print("\n[2/3] 保存 metadata ...")
    _save_baseline_metadata(
        metadata_dir=metadata_dir,
        encoding=BASELINE_ENCODING_NAME,
        continuous_stats=continuous_stats,
        nominal_mappings=nominal_mappings,
        feature_schema=feature_schema,
        nominal_min_count=nominal_min_count,
        mapping_scope=mapping_scope,
        save_nominal_mapping=(global_metadata_dir is None),
        save_feature_schema=(global_metadata_dir is None),
        global_metadata_dir=(Path(global_metadata_dir) if global_metadata_dir else None),
    )
    print(f"      metadata: {metadata_dir}")

    print("\n[3/3] 逐患者写入 .pt ...")
    for scheme in schemes:
        pt_dir = Path(out_root) / scheme / "pt"
        pt_dir.mkdir(parents=True, exist_ok=True)
        fields = BASELINE_SCHEME_FIELDS[scheme]
        for row in patient_rows:
            vector = _build_baseline_vector(
                row=row,
                fields=fields,
                continuous_stats=continuous_stats,
                nominal_mappings=nominal_mappings,
            )
            torch.save(torch.from_numpy(vector), pt_dir / f"{row['patient_id']}.pt")
        print(f"      {scheme}: {pt_dir}  (dim={feature_schema[scheme]['output_dim']})")

    print("\n" + "=" * 55)
    print(f"✅  baseline 编码完成（{BASELINE_ENCODING_NAME}）")
    print(f"   患者数   : {len(patient_rows)}")
    print(f"   metadata : {metadata_dir}")
    print("=" * 55)


# ─────────────────────────────────────────────────────────
# 5. CLI 入口
# ─────────────────────────────────────────────────────────

def _add_common_args(p: argparse.ArgumentParser):
    p.add_argument("--scheme", default="all",
                   help="方案名；文本流程支持 L0-L5 / 自定义方案，baseline 流程支持 D0-D5。all 表示运行当前命令支持的全部方案。")
    p.add_argument("--dataset", default=None,
                   help="数据集名；支持 all 或逗号分隔列表。为空时使用 --json_path 单数据集模式。")
    p.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG,
                   help="数据集 clinical JSON 配置文件")
    p.add_argument("--json_path",    default=DEFAULT_JSON_PATH,
                   help="TCGA GDC 原始 JSON 文件路径")
    p.add_argument("--template_dir", default=DEFAULT_TEMPLATE_DIR,
                   help="模板 CSV 所在目录")
    p.add_argument("--prompt_dir",   default=DEFAULT_PROMPT_DIR,
                   help="prompt CSV 输入/输出目录")
    p.add_argument("--ckpt",         default=DEFAULT_CKPT,
                   help="CONCH pytorch_model.bin 路径")
    p.add_argument("--out",          default=DEFAULT_OUT_DIR,
                   help="embedding 输出根目录")
    p.add_argument("--batch_size",   type=int, default=64,
                   help="编码时的 batch size（默认: 64）")
    p.add_argument("--baseline_out", default=DEFAULT_BASELINE_OUT_ROOT,
                   help="baseline 输出根目录；固定写入 {baseline_out}/{dataset}/embeddings/")
    p.add_argument("--baseline_stats_dir", default=None,
                   help="可选；复用已有 baseline metadata 目录（内含 normalization_stats.json / category_mapping.json）")
    p.add_argument("--baseline_nominal_min_count", type=int, default=5,
                   help="固定混合编码策略下，名义类别最小保留频次；低于该阈值的类别合并为 OTHER（默认: 5）")


def main():
    parser = argparse.ArgumentParser(
        description="Clinical Pipeline: JSON → Prompt CSV → CONCH Embedding",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── 子命令: json2prompt ─────────────────────────────
    p_j = sub.add_parser("json2prompt", help="JSON → prompt CSV")
    _add_common_args(p_j)

    # ── 子命令: encode ──────────────────────────────────
    p_e = sub.add_parser("encode", help="prompt CSV → CONCH embedding")
    _add_common_args(p_e)

    # ── 子命令: pipeline ────────────────────────────────
    p_p = sub.add_parser("pipeline", help="json2prompt + encode 全流程")
    _add_common_args(p_p)

    # ── 子命令: baseline ───────────────────────────────
    p_b = sub.add_parser("baseline", help="JSON → D0-D5 患者级 baseline 向量")
    _add_common_args(p_b)

    args = parser.parse_args()
    if args.cmd == "baseline":
        known_schemes = set(BASELINE_SCHEME_FIELDS.keys())
        if args.scheme != "all" and args.scheme not in known_schemes:
            parser.error(
                f"未知 baseline 方案: '{args.scheme}'。\n"
                f"  可用方案: {sorted(known_schemes)}"
            )
        schemes = list(BASELINE_SCHEME_FIELDS.keys()) if args.scheme == "all" else [args.scheme]
    else:
        # 加载自定义方案（注册到全局字典）
        load_custom_schemes(args.template_dir)

        # 验证方案名称
        known_schemes = set(SCHEME_CONFIG.keys())
        if args.scheme != "all" and args.scheme not in known_schemes:
            parser.error(
                f"未知方案: '{args.scheme}'。\n"
                f"  已注册方案: {sorted(known_schemes)}\n"
                f"  如需添加新方案，请在 {args.template_dir}/custom_schemes.json 中定义。"
            )
        schemes = list(SCHEME_CONFIG.keys()) if args.scheme == "all" else [args.scheme]

    datasets = load_dataset_configs(args.datasets_config)
    dataset_names = resolve_dataset_names(args.dataset, datasets)

    if not dataset_names:
        single_baseline_out = args.baseline_out
        dataset_jobs = [
            {
                "name": None,
                "json_paths": [args.json_path],
                "project_ids": [],
                "prompt_dir": args.prompt_dir,
                "out_dir": args.out,
                "baseline_out_dir": single_baseline_out,
            }
        ]
    else:
        dataset_jobs = [
            {
                "name": name,
                "json_paths": get_dataset_clinic_files(name, datasets),
                "project_ids": get_dataset_project_ids(name, datasets),
                "prompt_dir": dataset_prompt_dir(name),
                "out_dir": dataset_embedding_dir(name),
                "baseline_out_dir": dataset_baseline_embedding_dir(name, args.baseline_out),
            }
            for name in dataset_names
        ]

    shared_nominal_mappings = None
    shared_mapping_scope = None
    global_mapping_dir = None
    if (
        args.cmd == "baseline"
        and len(dataset_jobs) > 1
        and not args.baseline_stats_dir
    ):
        print(f"\n{'='*55}")
        print("[baseline] 构建多数据集共享混合编码 metadata")
        print(f"  统计范围 : {dataset_names}")
        print(f"  频次阈值 : >= {args.baseline_nominal_min_count}")
        print(f"{'='*55}")

        merged_rows = []
        for job in dataset_jobs:
            print(f"  -> 收集 {job['name']} 患者用于共享 nominal 词表")
            cases = load_clinical_cases(job["json_paths"], project_ids=job["project_ids"])
            merged_rows.extend(_build_patient_rows(cases))

        shared_nominal_mappings = _fit_nominal_mappings(
            merged_rows,
            min_count=args.baseline_nominal_min_count,
            collapse_rare=True,
        )
        shared_mapping_scope = {
            "type": "global_selected_datasets",
            "datasets": dataset_names,
            "patient_count": len(merged_rows),
        }

        global_mapping_dir = PROJECT_ROOT / "outputs" / "baseline_onehot_mapping_tables"
        _save_global_baseline_metadata(
            metadata_dir=global_mapping_dir,
            nominal_mappings=shared_nominal_mappings,
            feature_schema=_build_baseline_feature_schema(shared_nominal_mappings),
            nominal_min_count=args.baseline_nominal_min_count,
            dataset_names=dataset_names,
            patient_count=len(merged_rows),
        )
        print(f"  共享 mapping 已保存: {global_mapping_dir / 'category_mapping.json'}")

    for job in dataset_jobs:
        if job["name"]:
            print(f"\n######## Dataset: {job['name']} ########")

        if args.cmd in ("json2prompt", "pipeline"):
            for s in schemes:
                run_json2prompt(
                    json_path    = job["json_paths"],
                    scheme       = s,
                    template_dir = args.template_dir,
                    prompt_dir   = job["prompt_dir"],
                    project_ids  = job["project_ids"],
                )

        if args.cmd in ("encode", "pipeline"):
            for s in schemes:
                run_encode(
                    scheme       = s,
                    prompt_dir   = job["prompt_dir"],
                    ckpt         = args.ckpt,
                    out_dir      = job["out_dir"],
                    batch_size   = args.batch_size,
                )

        if args.cmd == "baseline":
            run_baseline_encode(
                json_paths  = job["json_paths"],
                schemes     = schemes,
                out_root    = job["baseline_out_dir"],
                project_ids = job["project_ids"],
                stats_dir   = args.baseline_stats_dir,
                nominal_min_count = args.baseline_nominal_min_count,
                shared_nominal_mappings = shared_nominal_mappings,
                mapping_scope = shared_mapping_scope,
                global_metadata_dir = (
                    str(global_mapping_dir)
                    if shared_nominal_mappings is not None and shared_mapping_scope is not None
                    else None
                ),
            )


if __name__ == "__main__":
    main()
