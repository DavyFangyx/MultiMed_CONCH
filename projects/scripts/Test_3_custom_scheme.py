"""Test_3 三臂对照: 从 field bank 模板生成 A_pipeline 自定义方案。

用途(见 z_notes/Test_series_spec.md §7.2):
  臂 B' = 工作完整组合 × bank 模板 × landmark_0   (--from-scheme <WORK>)
  臂 C  = 贪婪最优组合 × bank 模板 × landmark_0   (--from-greedy <result.json>)

模板来源: templates/field_bank/{dataset}/**landmark_0**/FIELD_BANK.csv 的 template 列
（与搜索结果所用的 prompt bank 同源；顶层 FIELD_BANK.csv 是旧口径，句子不同）。
字段无 landmark_0 bank 模板时回退到该工作自身 template.csv 的句子（记录进 Test_3_meta.json
的 fallback_fields），保证字段集与工作组合完全一致(控制变量)，只换模板。

生成的方案目录写入 A_pipeline/templates/{name}/ 并登记进该目录 schemes.json 的 `_schemes`
（A_pipeline load_custom_schemes 只按名单加载；不登记则方案不可用，见 R14 笔记）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "scripts", ROOT / "A_pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import Test_3_common as C  # noqa: E402
from common.fields import field_output_col  # noqa: E402

BANK_TEMPLATES = ROOT / "templates" / "field_bank"
A_TEMPLATES = ROOT / "A_pipeline" / "templates"
SCHEMES_JSON = A_TEMPLATES / "schemes.json"
LANDMARK_TAG = f"landmark_{C.LANDMARK_TIME}"


def load_bank_templates(dataset: str, landmark_tag: str = LANDMARK_TAG) -> dict[str, str]:
    """landmark_0 bank 模板（与 prompt bank 同源）；缺表时报错而非静默回落。"""
    path = BANK_TEMPLATES / dataset / landmark_tag / "FIELD_BANK.csv"
    if not path.exists():
        raise SystemExit(f"[test_3] 缺 {landmark_tag} bank 模板表: {path}")
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
        raise SystemExit(f"[test_3] 方案 {scheme} 不存在于 A_pipeline/templates/")
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
    if not Path(result_json).exists():
        raise SystemExit(f"[test_3] 缺搜索 result.json: {result_json}")
    data = json.loads(Path(result_json).read_text(encoding="utf-8"))
    subset = data.get("recommended_subset") or data.get("best_subset")
    if not subset:
        raise SystemExit(f"[test_3] result.json 缺 recommended_subset/best_subset: {result_json}")
    algo = data.get("algorithm", "greedy")
    return [str(f).strip() for f in subset], algo


def register_scheme(name: str, schemes_json: Path = SCHEMES_JSON) -> bool:
    """把方案名登记进 schemes.json 的 _schemes（幂等）；A_pipeline 只加载名单内的方案。"""
    payload = json.loads(schemes_json.read_text(encoding="utf-8"))
    names = list(payload.get("_schemes") or [])
    if name in names:
        return False
    names.append(name)
    payload["_schemes"] = names
    schemes_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def build_scheme(name: str, dataset: str, fields: list[str], bank_tpl: dict[str, str],
                 scheme_tpl: dict[str, str], source_note: str, *, register: bool = True,
                 landmark_tag: str = LANDMARK_TAG) -> Path:
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
                raise SystemExit(f"[test_3] 字段 {field} 无 bank 模板且无方案模板, 无法生成")
            fallback.append(field)
        columns.append(field_output_col(field))
        sentences.append(sentence)

    fields_json = {
        "description": f"Test_3 对照方案 {name} (来源: {source_note})",
        "prompt_file": "prompts.csv",
        "dirname": name,
        "source": "gdc",
        "fields": fields,
        "datasets": [dataset],
    }
    (out / "fields.json").write_text(
        json.dumps(fields_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame([sentences], columns=columns).to_csv(out / "template.csv", index=False)
    (out / "Test_3_meta.json").write_text(
        json.dumps({"dataset": dataset, "name": name, "landmark_tag": landmark_tag,
                    "n_fields": len(fields), "bank_template_fields": len(fields) - len(fallback),
                    "fallback_fields": fallback, "source": source_note},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    registered = register_scheme(name) if register else False
    print(f"[test_3] 生成方案 {name}: {len(fields)} 字段, bank 模板 "
          f"{len(fields) - len(fallback)}, fallback {len(fallback)}: {fallback}"
          f"{'；已登记 schemes.json' if registered else ''}")
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Test_3 三臂对照: bank 模板自定义方案生成")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--name", required=True, help="新方案名(如 Test_3_MULTISURV_TCGA-ACC)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-scheme", help="工作方案名(臂 B'): 字段列表取自该方案")
    src.add_argument("--from-greedy", type=Path, help="selection result.json(臂 C)")
    parser.add_argument("--no-register", action="store_true", help="只生成目录, 不登记 schemes.json")
    args = parser.parse_args(argv)

    bank_tpl = load_bank_templates(args.dataset)
    scheme_tpl: dict[str, str] = {}
    if args.from_scheme:
        fields, scheme_tpl = load_scheme(args.from_scheme)
        note = f"work={args.from_scheme} bank模板({LANDMARK_TAG})"
    else:
        fields, algo = load_greedy_fields(args.from_greedy)
        note = f"greedy={args.from_greedy} algo={algo} bank模板({LANDMARK_TAG})"
    build_scheme(args.name, args.dataset, fields, bank_tpl, scheme_tpl, note,
                 register=not args.no_register)


if __name__ == "__main__":
    main()
