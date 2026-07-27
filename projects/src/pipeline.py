"""
pipeline.py — JSON → Prompt CSV → CONCH Embedding 一键流水线

子命令:
  json2prompt  将 TCGA GDC JSON 转为 prompt CSV（默认 L0-L5 方案）
  encode       将 prompt CSV 编码为 CONCH embedding
  pipeline     先 json2prompt 后 encode，一键完成整条流水线

默认路径 (均可通过参数覆盖):
  --json_path     /data/lizhe/Medteam_projects/kindey_cancer_TCGA/clinical/clinical.cart.2026-03-17.json
  --template_dir  .../CONCH-main/projects/templates/l0_l5
  --prompt_dir    .../CONCH-main/projects/outputs/prompts
  --filtered_csv  .../SurvPGC/patients_index/filtered_patient_id.csv
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
"""

import argparse
import json
import os
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
DEFAULT_TEMPLATE_DIR  = str(PROJECT_ROOT / "templates/l0_l5")
DEFAULT_PROMPT_DIR    = str(PROJECT_ROOT / "outputs/prompts")
DEFAULT_FILTERED_CSV  = "/data/fangyuxuan/projects/medical_dl/SurvPGC/patients_index/filtered_patient_id.csv"
DEFAULT_CKPT          = str(WORKSPACE_ROOT / "CONCH/pytorch_model.bin")
DEFAULT_OUT_DIR       = str(PROJECT_ROOT / "outputs/embeddings")
DEFAULT_GPU           = "7"

# 所有方案均在 prompt_generate/templates/custom_schemes.json 中定义，
# 程序启动时由 load_custom_schemes() 动态注册到以下字典。
SCHEME_TEMPLATE    = {}  # 方案名 → 模板文件名
SCHEME_PROMPT_FILE = {}  # 方案名 → prompt CSV 文件名
SCHEME_DIRNAME     = {}  # 方案名 → embedding 输出子目录名
SCHEME_COLS        = {}  # 方案名 → prompt 列名列表（encode 阶段使用）
SCHEME_CONFIG      = {}  # 方案名 → {template_cols, placeholders, output_cols}


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

def run_json2prompt(json_path: str, scheme: str, template_dir: str, prompt_dir: str):
    cfg = SCHEME_CONFIG[scheme]
    template_file = Path(template_dir) / SCHEME_TEMPLATE[scheme]
    output_file   = Path(prompt_dir)   / SCHEME_PROMPT_FILE[scheme]

    print(f"\n{'='*55}")
    print(f"[json2prompt] 方案 {scheme}")
    print(f"  JSON    : {json_path}")
    print(f"  模板    : {template_file}")
    print(f"  输出    : {output_file}")
    print(f"{'='*55}")

    # 读取 JSON
    print(f"\n[1/3] 读取 JSON ...")
    with open(json_path, "r", encoding="utf-8") as f:
        cases = json.load(f)
    print(f"      共 {len(cases)} 个病例")

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


def run_encode(scheme: str, prompt_dir: str, filtered_csv: str,
               ckpt: str, out_dir: str, batch_size: int = 64):
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

    # 读取筛选患者表
    print(f"\n[1/4] 读取筛选患者表: {filtered_csv}")
    filter_df = pd.read_csv(filtered_csv)
    assert "patient_id" in filter_df.columns, "filtered_csv 必须含 patient_id 列"
    valid_patients = set(filter_df["patient_id"].astype(str).tolist())
    print(f"      筛选患者数: {len(valid_patients)}")

    # 读取 prompt CSV
    print(f"\n[2/4] 读取 prompt CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"      原始病例数: {len(df)}")

    missing_cols = [c for c in prompt_cols if c not in df.columns]
    if missing_cols:
        raise ValueError(f"prompt CSV 缺少以下列（方案 {scheme}）：{missing_cols}")

    df_filtered = df[df["patient_id"].astype(str).isin(valid_patients)].reset_index(drop=True)
    print(f"      过滤后病例数: {len(df_filtered)}")

    missing_patients = valid_patients - set(df_filtered["patient_id"].astype(str))
    if missing_patients:
        print(f"\n      ⚠️  {len(missing_patients)} 个患者在 prompt CSV 中未找到（显示前10个）:")
        for p in sorted(missing_patients)[:10]:
            print(f"         {p}")

    patient_ids = df_filtered["patient_id"].astype(str).tolist()
    patient_prompts = _build_patient_prompt_matrix(df_filtered, prompt_cols)

    if not patient_ids:
        print("\n      过滤后无患者，跳过编码。")
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
    print(f"[3/4] 加载 CONCH: {ckpt}")
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
    print(f"\n[4/4] 按患者 ID 保存文件 → {out_subdir}")
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
# 4. CLI 入口
# ─────────────────────────────────────────────────────────

def _add_common_args(p: argparse.ArgumentParser):
    p.add_argument("--scheme", default="all",
                   help="方案名（all = 运行 JSON 中所有方案；或指定单个方案名，如 O/A/B/C/D/A1）")
    p.add_argument("--json_path",    default=DEFAULT_JSON_PATH,
                   help="TCGA GDC 原始 JSON 文件路径")
    p.add_argument("--template_dir", default=DEFAULT_TEMPLATE_DIR,
                   help="模板 CSV 所在目录")
    p.add_argument("--prompt_dir",   default=DEFAULT_PROMPT_DIR,
                   help="prompt CSV 输入/输出目录")
    p.add_argument("--filtered_csv", default=DEFAULT_FILTERED_CSV,
                   help="筛选患者表路径（含 patient_id 列）")
    p.add_argument("--ckpt",         default=DEFAULT_CKPT,
                   help="CONCH pytorch_model.bin 路径")
    p.add_argument("--out",          default=DEFAULT_OUT_DIR,
                   help="embedding 输出根目录")
    p.add_argument("--batch_size",   type=int, default=64,
                   help="编码时的 batch size（默认: 64）")


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

    args = parser.parse_args()

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

    if args.cmd in ("json2prompt", "pipeline"):
        for s in schemes:
            run_json2prompt(
                json_path    = args.json_path,
                scheme       = s,
                template_dir = args.template_dir,
                prompt_dir   = args.prompt_dir,
            )

    if args.cmd in ("encode", "pipeline"):
        for s in schemes:
            run_encode(
                scheme       = s,
                prompt_dir   = args.prompt_dir,
                filtered_csv = args.filtered_csv,
                ckpt         = args.ckpt,
                out_dir      = args.out,
                batch_size   = args.batch_size,
            )


if __name__ == "__main__":
    main()
