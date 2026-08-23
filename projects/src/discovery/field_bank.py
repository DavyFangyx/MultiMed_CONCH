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
from common.paths import (
    DEFAULT_CKPT,
    DEFAULT_FIELD_BANK_TEMPLATE_DIR,
    DEFAULT_GPU,
    REGISTRY_DIR,
    REPO_ROOT,
    dataset_field_bank_dir,
)


def field_bank_placeholder(field_path: str) -> str:
    leaf = str(field_path).split(".")[-1].replace("[]", "")
    return leaf.upper()


def field_bank_output_col(field_path: str) -> str:
    return str(field_path).replace(".", "_").replace("[]", "") + "_template"


def write_field_bank_template_skeleton(dataset_name: str, fields: list[str], out_dir: Path | None = None) -> Path:
    out_dir = Path(out_dir or DEFAULT_FIELD_BANK_TEMPLATE_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{dataset_name}_FIELD_BANK_template.csv"
    map_path = out_dir / f"{dataset_name}_FIELD_BANK_columns.json"
    fields = sorted(fields)

    preserved = {}
    if out_path.exists():
        old = pd.read_csv(out_path)
        if len(old) >= 1:
            preserved = {
                col: ("" if pd.isna(old.iloc[0][col]) else str(old.iloc[0][col]))
                for col in old.columns
                if col in fields
            }

    sentence_row = {col: preserved.get(col, "") for col in fields}
    pd.DataFrame([sentence_row], columns=fields).to_csv(out_path, index=False)
    mapping = [
        {
            "field_path": field,
            "template_col": field,
            "placeholder": field_bank_placeholder(field),
            "output_col": field_bank_output_col(field),
        }
        for field in fields
    ]
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump({"dataset": dataset_name, "fields": mapping}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    filled = sum(1 for v in sentence_row.values() if str(v).strip())
    print(
        f"✅ FIELD_BANK 模板: {out_path}  列数={len(fields)}，已填句子={filled}\n"
        f"✅ FIELD_BANK 列对照: {map_path}"
    )
    return out_path


def load_active_fields(path: Path | None = None) -> dict:
    path = Path(path or (REGISTRY_DIR / "active_fields.json"))
    if not path.exists():
        raise FileNotFoundError(
            f"未找到 {path}。请先运行 python projects/scripts/run_field_filter.py --dataset all"
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_field_bank_template(dataset_name: str) -> dict:
    template_file = DEFAULT_FIELD_BANK_TEMPLATE_DIR / f"{dataset_name}_FIELD_BANK_template.csv"
    map_path = DEFAULT_FIELD_BANK_TEMPLATE_DIR / f"{dataset_name}_FIELD_BANK_columns.json"
    if not template_file.exists():
        raise FileNotFoundError(
            f"未找到 FIELD_BANK 模板: {template_file}。请先跑 run_field_filter.py --write_templates，再填写第二行句子。"
        )
    tpl_df = pd.read_csv(template_file)
    col_map = {}
    if map_path.exists():
        with open(map_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        for item in payload.get("fields", []):
            col_map[str(item.get("template_col") or item.get("field_path"))] = item

    fields = []
    placeholders = []
    output_cols = []
    templates = {}
    empty_cols = []
    for col in tpl_df.columns:
        item = col_map.get(col, {})
        field_path = str(item.get("field_path") or col)
        placeholder = str(item.get("placeholder") or field_bank_placeholder(field_path))
        output_col = str(item.get("output_col") or field_bank_output_col(field_path))
        sentence = ""
        if len(tpl_df):
            raw = tpl_df.iloc[0][col]
            sentence = "" if pd.isna(raw) else str(raw).strip()
        if not sentence:
            empty_cols.append(col)
        fields.append(field_path)
        placeholders.append(placeholder)
        output_cols.append(output_col)
        templates[col] = sentence
    if empty_cols:
        raise ValueError(
            f"FIELD_BANK 模板第二行仍为空（{len(empty_cols)} 列），请先填写 {template_file} 后再编码。"
        )
    return {
        "template_file": template_file,
        "template_cols": list(tpl_df.columns),
        "fields": fields,
        "placeholders": placeholders,
        "output_cols": output_cols,
        "templates": templates,
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
    for tpl_col, placeholder, out_col, field_path in zip(
        cfg["template_cols"], cfg["placeholders"], cfg["output_cols"], cfg["fields"]
    ):
        value, valid = extract_field_bank_value(case, field_path)
        tpl_str = cfg["templates"][tpl_col]
        row[out_col] = tpl_str.replace(placeholder, value) if placeholder else tpl_str
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

    active = load_active_fields(Path(args.active_fields) if args.active_fields else None)

    for name in names:
        print(f"\n######## Dataset: {name} ########")
        if name not in active:
            raise ValueError(f"{name} 不在 active_fields.json 中。请先跑 run_field_filter.py")
        cfg = load_field_bank_template(name)
        expected = list(active[name]["fields"])
        if cfg["fields"] != expected:
            print("  ⚠️  模板字段与 active_fields.json 不完全一致，以模板当前列为准。")

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

        pt_dir = out_dir / "pt"
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
