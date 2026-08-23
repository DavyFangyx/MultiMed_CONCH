"""Generate L0-L5 / v1 prompt CSVs from clinical JSON."""

from pathlib import Path

import pandas as pd

from common.clinical_io import load_clinical_cases, normalize_json_paths

from .config import SCHEME_CONFIG, resolve_scheme_template_file
from .extract import extract_values


def generate_prompt_row(case: dict, templates: dict, scheme: str) -> dict:
    cfg = SCHEME_CONFIG[scheme]
    vals = extract_values(case)
    row = {"patient_id": case["submitter_id"]}
    for tpl_col, placeholder, out_col in zip(
        cfg["template_cols"], cfg["placeholders"], cfg["output_cols"]
    ):
        tpl_str = templates[tpl_col]
        if placeholder:
            tpl_str = tpl_str.replace(placeholder, vals.get(placeholder, "not reported"))
        row[out_col] = tpl_str
    return row


def run_json2prompt(
    json_path,
    scheme: str,
    template_dir: str,
    prompt_dir: str,
    project_ids: list | None = None,
    dataset_name: str | None = None,
):
    cfg = SCHEME_CONFIG[scheme]
    template_file = resolve_scheme_template_file(scheme, template_dir)
    output_file = Path(prompt_dir) / scheme / "prompts.csv"
    json_paths = normalize_json_paths(json_path)

    print(f"\n{'='*55}")
    print(f"[json2prompt] 方案 {scheme}")
    if dataset_name:
        print(f"  Dataset : {dataset_name}")
    print(f"  JSON    : {json_paths}")
    print(f"  模板    : {template_file}")
    print(f"  输出    : {output_file}")
    print(f"{'='*55}")

    print("\n[1/3] 读取 JSON ...")
    cases = load_clinical_cases(json_paths, project_ids=project_ids)

    print("[2/3] 读取模板 ...")
    tpl_df = pd.read_csv(template_file)
    templates = {}
    for col in cfg["template_cols"]:
        if col not in tpl_df.columns:
            raise ValueError(
                f"模板文件缺少列: '{col}'，请确认 {template_file.name} 与方案 {scheme} 对应。"
            )
        col_values = tpl_df[col].dropna().tolist()
        sentence = str(col_values[0]).strip() if col_values else ""
        if not sentence:
            raise ValueError(f"模板列 '{col}' 为空，请检查模板文件。")
        templates[col] = sentence
        print(f"      {col}: {templates[col]}")

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
