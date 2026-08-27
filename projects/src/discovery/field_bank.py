"""Field Bank templates, prompt generation, and encoding."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from common.clinical_io import load_clinical_cases
from common.datasets import get_dataset_clinic_files, get_dataset_project_ids, load_dataset_configs, resolve_dataset_names
from common.fields import extract_path_values, get_primary_diagnosis, unique_join
from common.missingness import classify_raw_value, clean_value
from .converters import convert_value, known_converters
from common.paths import (
    DEFAULT_CKPT,
    DEFAULT_GPU,
    REPO_ROOT,
    dataset_field_bank_dir,
    dataset_field_bank_template_dir,
    dataset_kept_fields_path,
)


def field_bank_output_col(field_path: str) -> str:
    return str(field_path).replace(".", "_").replace("[]", "") + "_template"


def _clean_text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return ""
    return str(value).strip()


TEMPLATE_COLUMNS = ["field", "example", "convert", "unit", "template"]


def _is_long_template(df: pd.DataFrame) -> bool:
    cols = {str(c).strip().lower() for c in df.columns}
    return {"field", "template"}.issubset(cols)


def _row_attr(row, name: str) -> str:
    mapping = {str(k).strip().lower(): k for k in getattr(row, "_fields", ())}
    key = mapping.get(name)
    if key is None:
        return ""
    return _clean_text(getattr(row, key, ""))


def _read_existing_templates(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    old = pd.read_csv(path)
    if old.empty:
        return {}
    preserved = {}
    if _is_long_template(old):
        for row in old.itertuples(index=False):
            field = _row_attr(row, "field")
            if not field:
                continue
            preserved[field] = {
                "example": _row_attr(row, "example"),
                "convert": _row_attr(row, "convert"),
                "unit": _row_attr(row, "unit"),
                "template": _row_attr(row, "template"),
            }
        return preserved
    first = old.iloc[0]
    for col in old.columns:
        preserved[str(col)] = {"template": _clean_text(first[col])}
    return preserved


def write_field_bank_template_skeleton(
    dataset_name: str,
    fields: list[str],
    out_dir: Path | None = None,
    examples: dict[str, str] | None = None,
) -> Path:
    out_dir = Path(out_dir or dataset_field_bank_template_dir(dataset_name))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "FIELD_BANK.csv"
    map_path = out_dir / "FIELD_BANK_columns.json"
    fields = sorted(fields)
    preserved = _read_existing_templates(out_path)
    examples = examples or {}

    rows = []
    for field in fields:
        old = preserved.get(field, {})
        rows.append(
            {
                "field": field,
                "example": examples.get(field) or old.get("example", ""),
                "convert": old.get("convert", ""),
                "unit": old.get("unit", ""),
                "template": old.get("template", ""),
            }
        )
    pd.DataFrame(rows, columns=TEMPLATE_COLUMNS).to_csv(out_path, index=False)
    mapping = [
        {
            "field_path": field,
            "output_col": field_bank_output_col(field),
        }
        for field in fields
    ]
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "dataset": dataset_name,
                "note": (
                    "人工编辑 template.csv。先看 example 的原始取值，再裁定 convert/unit，最后填 template。"
                    "convert 填 converters.py 清单中的函数名；空则原样填 {}。"
                    "example 和 unit 不进入编码。"
                    "本 JSON 只记录 field_path 到 prompts.csv 输出列名的对照。"
                ),
                "fields": mapping,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")
    print(f"✅ FIELD_BANK 模板: {out_path}  字段数={len(fields)}")
    print(f"✅ FIELD_BANK 列对照: {map_path}")
    return out_path



def _normalize_kept_payload(payload, dataset_name: str | None = None, path: Path | None = None) -> dict:
    if isinstance(payload, dict) and "fields" in payload:
        return payload
    if isinstance(payload, dict) and dataset_name and dataset_name in payload:
        return payload[dataset_name]
    raise ValueError(f"无法从 {path} 读取 {dataset_name or 'dataset'} 的 kept fields")


def load_kept_fields(dataset_name: str | None = None, path: Path | None = None) -> dict:
    if path is not None:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"未找到 {path}。请先运行 python projects/scripts/run_field_filter.py --dataset all"
            )
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if dataset_name:
            return {dataset_name: _normalize_kept_payload(payload, dataset_name, path)}
        if isinstance(payload, dict) and "fields" in payload:
            raise ValueError(f"{path} 是单数据集 kept_fields.json，请同时传入 dataset_name")
        return payload

    if not dataset_name:
        raise ValueError("load_kept_fields 需要 dataset_name 或显式 path")
    path = dataset_kept_fields_path(dataset_name)
    if not path.exists():
        raise FileNotFoundError(
            f"未找到 {path}。请先运行 python projects/scripts/run_field_filter.py --dataset {dataset_name}"
        )
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return {dataset_name: _normalize_kept_payload(payload, dataset_name, path)}


def _fill_template(template: str, value: str) -> str:
    return str(template).replace("{}", str(value), 1)


def load_field_bank_template(dataset_name: str) -> dict:
    template_dir = dataset_field_bank_template_dir(dataset_name)
    template_file = template_dir / "FIELD_BANK.csv"
    map_path = template_dir / "FIELD_BANK_columns.json"
    if not template_file.exists():
        raise FileNotFoundError(
            f"未找到 FIELD_BANK 模板: {template_file}。请先跑 run_field_filter.py --write_templates，再填写 template 列。"
        )
    tpl_df = pd.read_csv(template_file)
    if tpl_df.empty:
        raise ValueError(f"FIELD_BANK 模板为空: {template_file}")
    if not _is_long_template(tpl_df):
        raise ValueError(
            f"FIELD_BANK 模板必须是长表，列为 field,example,convert,unit,template: {template_file}"
        )

    col_map = {}
    if map_path.exists():
        with open(map_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        for item in payload.get("fields", []):
            field_path = str(item.get("field_path") or "")
            if field_path:
                col_map[field_path] = item

    fields = []
    output_cols = []
    templates = {}
    converts = {}
    empty_fields = []
    seen = set()
    for row in tpl_df.itertuples(index=False):
        field_path = _row_attr(row, "field")
        sentence = _row_attr(row, "template")
        convert = _row_attr(row, "convert")
        if not field_path:
            continue
        if field_path in seen:
            raise ValueError(f"FIELD_BANK 模板字段重复: {field_path} ({template_file})")
        seen.add(field_path)
        if convert.lower() not in known_converters():
            known = ", ".join(sorted(x for x in known_converters() if x))
            raise ValueError(
                f"字段 {field_path} 的 convert={convert!r} 无效。允许值为空或 {known}"
            )
        item = col_map.get(field_path, {})
        output_col = str(item.get("output_col") or field_bank_output_col(field_path))
        if not sentence:
            empty_fields.append(field_path)
        fields.append(field_path)
        output_cols.append(output_col)
        templates[field_path] = sentence
        converts[field_path] = convert.lower()
    if empty_fields:
        raise ValueError(
            f"FIELD_BANK 模板 template 列仍为空（{len(empty_fields)} 个字段），请先填写 {template_file} 后再编码。"
        )
    return {
        "template_file": template_file,
        "fields": fields,
        "output_cols": output_cols,
        "templates": templates,
        "converts": converts,
    }


def extract_field_bank_value(case: dict, field_path: str) -> tuple[str, bool]:
    raw_vals = extract_path_values(case, field_path)
    if not raw_vals:
        return "not reported", False
    if field_path.startswith("diagnoses[]") and isinstance(case.get("diagnoses"), list):
        primary = get_primary_diagnosis(case.get("diagnoses", []))
        remainder = field_path[len("diagnoses[]"):].lstrip(".")
        leaf = field_path.split(".")[-1].replace("[]", "")
        if primary and "." not in remainder and leaf in primary:
            state = classify_raw_value(primary.get(leaf))
            return clean_value(primary.get(leaf), "not reported"), state == "valid"
    states = [classify_raw_value(v) for v in raw_vals]
    valid_vals = [v for v, st in zip(raw_vals, states) if st == "valid"]
    if not valid_vals:
        return "not reported", False
    return unique_join(valid_vals, fallback="not reported"), True


def generate_field_bank_prompt_row(case: dict, cfg: dict) -> dict:
    row = {"patient_id": case["submitter_id"]}
    mask = {}
    converts = cfg.get("converts") or {}
    for out_col, field_path in zip(cfg["output_cols"], cfg["fields"]):
        value, valid = extract_field_bank_value(case, field_path)
        if valid:
            value = convert_value(value, converts.get(field_path, ""))
        row[out_col] = _fill_template(cfg["templates"][field_path], value)
        mask[out_col] = valid
    row["_mask"] = mask
    return row


def _lazy_import_conch():
    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    import torch
    from conch.open_clip_custom import create_model_from_pretrained, get_tokenizer

    return torch, create_model_from_pretrained, get_tokenizer


def run_field_bank(args):
    datasets = load_dataset_configs(args.datasets_config)
    names = resolve_dataset_names(args.dataset, datasets)
    if not names:
        raise ValueError("FIELD_BANK 需要 --dataset，例如 --dataset TCGA-READ 或 --dataset all")

    for name in names:
        print(f"\n######## Dataset: {name} ########")
        kept = load_kept_fields(
            dataset_name=name,
            path=Path(args.kept_fields) if args.kept_fields else None,
        )
        if name not in kept:
            raise ValueError(f"{name} 不在 {args.kept_fields or dataset_kept_fields_path(name)} 中。请先跑 run_field_filter.py")
        cfg = load_field_bank_template(name)
        expected = list(kept[name]["fields"])
        if cfg["fields"] != expected:
            print("  ⚠️  模板字段与 kept_fields.json 不完全一致，以模板当前行为准。")

        cases = load_clinical_cases(
            get_dataset_clinic_files(name, datasets),
            project_ids=get_dataset_project_ids(name, datasets),
        )
        records = [generate_field_bank_prompt_row(case, cfg) for case in cases if "submitter_id" in case]
        out_dir = dataset_field_bank_dir(name)
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = out_dir / "prompts.csv"
        prompt_rows = []
        for rec in records:
            row = {"patient_id": rec["patient_id"]}
            row.update({col: rec[col] for col in cfg["output_cols"]})
            prompt_rows.append(row)
        pd.DataFrame(prompt_rows).to_csv(prompt_path, index=False)
        print(f"✅ prompts.csv: {prompt_path}  ({len(prompt_rows)} 行)")

        if args.prompts_only:
            continue

        os.environ["CUDA_VISIBLE_DEVICES"] = DEFAULT_GPU
        torch, create_model_from_pretrained, get_tokenizer = _lazy_import_conch()
        from tqdm import tqdm

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model, _ = create_model_from_pretrained(model_cfg="conch_ViT-B-16", checkpoint_path=args.ckpt)
        model = model.to(device).eval()
        tokenizer = get_tokenizer()

        patient_ids = [rec["patient_id"] for rec in records]
        patient_prompts = [[rec[col] for col in cfg["output_cols"]] for rec in records]
        flat_prompts = [sentence for sentences in patient_prompts for sentence in sentences]
        encoded = tokenizer(flat_prompts, padding=True, truncation=True, return_tensors="pt")
        all_tokens = encoded["input_ids"]
        all_embeddings = []
        with torch.inference_mode():
            for i in tqdm(range(0, len(flat_prompts), args.batch_size), desc=f"Encoding {name}"):
                tokens = all_tokens[i : i + args.batch_size].to(device)
                feats = model.encode_text(tokens, embed_cls=False)
                feats = feats / feats.norm(dim=-1, keepdim=True)
                all_embeddings.append(feats.cpu().float().numpy())
        embeddings = np.concatenate(all_embeddings, axis=0).reshape(len(patient_ids), len(cfg["fields"]), -1)

        pt_dir = out_dir / "embeddings" / "pt"
        pt_dir.mkdir(parents=True, exist_ok=True)
        for rec, emb in zip(records, embeddings):
            mask = [bool(rec["_mask"][col]) for col in cfg["output_cols"]]
            payload = {
                "matrix": torch.from_numpy(emb),
                "mask": torch.tensor(mask, dtype=torch.bool),
                "patient_id": rec["patient_id"],
            }
            torch.save(payload, pt_dir / f"{rec['patient_id']}.pt")

        index = {
            "dataset": name,
            "fields": cfg["fields"],
            "n_fields": len(cfg["fields"]),
            "embed_dim": int(embeddings.shape[-1]),
            "encoder": "CONCH",
            "ckpt": str(args.ckpt),
            "missing_policy": "placeholder_sentence",
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n_patients": len(patient_ids),
        }
        index_path = out_dir / "field_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"✅ field_index.json: {index_path}")
        print(f"✅ pt dir: {pt_dir}")
