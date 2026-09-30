"""H2 三臂对照: 从 Field Bank 模板生成 A_pipeline 自定义方案。

用途(见 z_notes/H_series_spec.md §7.2):
  臂 B' = 工作完整组合 × bank 模板 × landmark_0   (--from-scheme <WORK>)
  臂 C  = 贪婪最优组合 × bank 模板 × landmark_0   (--from-greedy <result.json>)

模板来源: templates/field_bank/{dataset}/FIELD_BANK.csv 的 template 列。
字段无 bank 模板时回退到该工作自身 template.csv 的句子(记录进 h2_meta.json 的 fallback_fields),
保证字段集与工作组合完全一致(控制变量),只换模板。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "A_pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common.fields import field_output_col  # noqa: E402

BANK_TEMPLATES = ROOT / "templates" / "field_bank"
A_TEMPLATES = ROOT / "A_pipeline" / "templates"


def load_bank_templates(dataset: str) -> dict[str, str]:
    path = BANK_TEMPLATES / dataset / "FIELD_BANK.csv"
    if not path.exists():
        raise SystemExit(f"[h2] 缺 bank 模板表: {path}")
    df = pd.read_csv(path)
    tpl: dict[str, str] = {}
    for _, row in df.iterrows():
        sentence = str(row.get("template", "") or "").strip()
        if sentence:
            tpl[str(row["field"]).strip()] = sentence
    return tpl


def load_scheme(scheme: str) -> tuple[list[str], dict[str, str]]:
    fields_path = A_TEMPLATES / scheme / "fields.json"
    tpl_path = A_TEMPLATES / scheme / "template.csv"
    if not fields_path.exists() or not tpl_path.exists():
        raise SystemExit(f"[h2] 方案 {scheme} 不存在于 A_pipeline/templates/")
    cfg = json.loads(fields_path.read_text(encoding="utf-8"))
    fields = [str(f).strip() for f in cfg.get("fields", [])]
    df = pd.read_csv(tpl_path)
    scheme_tpl: dict[str, str] = {}
    for col in df.columns:
        values = [str(v).strip() for v in df[col].dropna().tolist()]
        if col.endswith("_template") and values and values[0]:
            scheme_tpl[col] = values[0]
    return fields, scheme_tpl


def load_greedy_fields(result_json: Path) -> tuple[list[str], str]:
    data = json.loads(result_json.read_text(encoding="utf-8"))
    subset = data.get("recommended_subset") or data.get("best_subset")
    if not subset:
        raise SystemExit(f"[h2] result.json 缺 recommended_subset/best_subset: {result_json}")
    algo = data.get("algorithm", "greedy")
    return [str(f).strip() for f in subset], algo


def build_scheme(name: str, dataset: str, fields: list[str],
                 bank_tpl: dict[str, str], scheme_tpl: dict[str, str], source_note: str) -> Path:
    out = A_TEMPLATES / name
    out.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    sentences: list[str] = []
    fallback: list[str] = []
    for field in fields:
        if field in bank_tpl:
            sentence = bank_tpl[field]
        else:
            sentence = scheme_tpl.get(field_output_col(field))
            if not sentence:
                raise SystemExit(f"[h2] 字段 {field} 无 bank 模板且无方案模板, 无法生成")
            fallback.append(field)
        columns.append(field_output_col(field))
        sentences.append(sentence)

    fields_json = {
        "description": f"H2 对照方案 {name} (来源: {source_note})",
        "prompt_file": "prompts.csv",
        "dirname": name,
        "source": "gdc",
        "fields": fields,
        "datasets": [dataset],
    }
    (out / "fields.json").write_text(
        json.dumps(fields_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame([sentences], columns=columns).to_csv(out / "template.csv", index=False)
    (out / "h2_meta.json").write_text(
        json.dumps({"dataset": dataset, "name": name, "n_fields": len(fields),
                    "fallback_fields": fallback}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"[h2] 生成方案 {name}: {len(fields)} 字段, fallback {len(fallback)}: {fallback}")
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="H2 三臂对照: bank 模板自定义方案生成")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--name", required=True, help="新方案名(如 H2_MULTISURV_TCGA-ACC)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-scheme", help="工作方案名(臂 B'): 字段列表取自该方案")
    src.add_argument("--from-greedy", type=Path, help="selection result.json(臂 C)")
    args = parser.parse_args(argv)

    bank_tpl = load_bank_templates(args.dataset)
    scheme_tpl: dict[str, str] = {}
    if args.from_scheme:
        fields, scheme_tpl = load_scheme(args.from_scheme)
        note = f"work={args.from_scheme} bank模板"
    else:
        fields, algo = load_greedy_fields(args.from_greedy)
        note = f"greedy={args.from_greedy} algo={algo}"
    build_scheme(args.name, args.dataset, fields, bank_tpl, scheme_tpl, note)


if __name__ == "__main__":
    main()
