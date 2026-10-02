#!/usr/bin/env python3
"""S5b / Test_1a off 臂：构建 `raw` 变体 Field Bank（字段表 = landmark_0 kept，取值 mask 关闭）。

定义（z_notes/Test_series_spec.md §5bis）：
    raw 变体 = 字段列表来自 landmark_0 field bank（同一顺序、同一模板），
               但取值提取 `landmark=False`（不施加 t0 槽位 mask，取值全集）。

产物（每个数据集）：
    outputs/_raw/{dataset}/field_bank/prompt/landmark_none/
        prompts.csv          # 全患者 × lm0 字段表的 prompt（mask off 取值）
        embeddings/pt/*.pt   # CONCH 文本编码（matrix [n_fields,512], mask, patient_id）
        field_index.json     # landmark_policy=off, field_list_source=landmark_0, ...
        raw_value_diff.json  # 与 lm0 bank 的逐 (患者,字段) 取值差异统计（审计用）

全局：outputs/_raw/_field_value_diff.csv（逐 (dataset,field) 差异计数，追加汇总）

硬校验（任一不满足即报错，不产出）：
    ① 字段表顺序与 lm0 field bank 的 field_index.json 完全一致；
    ② 患者集与 lm0 field bank 的 pt 文件集完全一致（两臂同患者集的前提）；
    ③ 取值差异只允许出现在 timed family 字段（diagnoses[]/follow_ups[] 系）；
       非 timed family 字段出现差异 = 提取逻辑异常。

运行环境：conda env conch（编码）。用法：
    conda activate conch
    python scripts/s5b_build_raw_field_bank.py --dataset all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for item in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from common.clinical_io import load_clinical_cases
from common.datasets import (
    get_dataset_clinic_files,
    get_dataset_project_ids,
    load_dataset_configs,
    resolve_dataset_names,
)
from common.paths import DEFAULT_CKPT, DEFAULT_DATASETS_CONFIG, PROJECT_ROOT as PATHS_PROJECT_ROOT
from discovery.field_bank import generate_field_bank_prompt_row, load_field_bank_template
from discovery.landmark import timed_family_for_field

RAW_BANK_ROOT = PATHS_PROJECT_ROOT / "outputs" / "_raw"
RAW_TAG = "landmark_none"  # 取值 mask 状态 off 的规范 tag
DIFF_CSV = RAW_BANK_ROOT / "_field_value_diff.csv"


def raw_bank_dir(dataset: str, encoding: str = "prompt") -> Path:
    return RAW_BANK_ROOT / dataset / "field_bank" / encoding / RAW_TAG


def lm0_bank_dir(dataset: str, encoding: str = "prompt") -> Path:
    return PATHS_PROJECT_ROOT / "outputs" / dataset / "field_bank" / encoding / "landmark_0"


def tcga_datasets(args) -> list[str]:
    datasets = load_dataset_configs(args.datasets_config)
    names = resolve_dataset_names(args.dataset, datasets)
    if not names:
        names = [item for item in datasets if str(item).startswith(("TCGA-", "TCGA_"))]
    return [
        name
        for name in names
        if str(name).startswith(("TCGA-", "TCGA_"))
    ]


def build_prompt_rows(dataset: str, datasets: dict) -> tuple[list[dict], dict, list[str]]:
    cfg = load_field_bank_template(dataset, require_templates=True, landmark_tag="landmark_0")
    cases = load_clinical_cases(
        get_dataset_clinic_files(dataset, datasets),
        project_ids=get_dataset_project_ids(dataset, datasets),
    )
    records = [
        generate_field_bank_prompt_row(case, cfg, landmark=False, landmark_time=None)
        for case in cases
        if "submitter_id" in case
    ]
    return records, cfg, [rec["patient_id"] for rec in records]


def diff_against_lm0(records: list[dict], cfg: dict, dataset: str) -> tuple[dict, list[dict]]:
    """逐 (患者,字段) 比较 raw 取值与 lm0 bank 的 prompts.csv。返回 (summary, per-field rows)。"""
    lm_bank = lm0_bank_dir(dataset)
    lm_prompts = pd.read_csv(lm_bank / "prompts.csv")
    cols = [col for col in cfg["output_cols"]]
    lm_by_patient = lm_prompts.set_index("patient_id")
    changed_cells = 0
    changed_patients = 0
    per_field = {col: 0 for col in cols}
    samples: dict[str, str] = {}
    for rec in records:
        pid = rec["patient_id"]
        row_changed = False
        if pid not in lm_by_patient.index:
            raise KeyError(f"{dataset}: {pid} 不在 lm0 bank prompts.csv 中")
        lm_row = lm_by_patient.loc[pid]
        for col in cols:
            left, right = str(rec[col]), str(lm_row[col])
            if left != right:
                per_field[col] += 1
                changed_cells += 1
                row_changed = True
                if col not in samples:
                    samples[col] = f"{pid}: {right!r} -> {left!r}"
        if row_changed:
            changed_patients += 1
    field_rows = []
    for col, field_path in zip(cfg["output_cols"], cfg["fields"]):
        family, _ = timed_family_for_field(field_path)
        field_rows.append(
            {
                "dataset": dataset,
                "field": field_path,
                "output_col": col,
                "family": family or "",
                "timed_family": bool(family),
                "changed_cells": int(per_field[col]),
                "n_patients": len(records),
                "sample_change": samples.get(col, ""),
            }
        )
    summary = {
        "dataset": dataset,
        "n_patients": len(records),
        "n_fields": len(cols),
        "changed_cells": changed_cells,
        "changed_patients": changed_patients,
        "changed_fields": sorted(
            row["field"] for row in field_rows if row["changed_cells"] > 0
        ),
        "untimed_changed_fields": sorted(
            row["field"] for row in field_rows if row["changed_cells"] > 0 and not row["timed_family"]
        ),
    }
    return summary, field_rows


_ENCODER_CACHE: dict[str, tuple] = {}


def _get_encoder(ckpt: str):
    """加载一次 CONCH，多个数据集复用（33 次重复加载 ~3 分钟且反复占用显存）。"""
    key = str(ckpt)
    if key not in _ENCODER_CACHE:
        from discovery.field_bank import _lazy_import_conch

        torch_mod, create_model_from_pretrained, get_tokenizer = _lazy_import_conch()
        device = torch_mod.device("cuda" if torch_mod.cuda.is_available() else "cpu")
        model, _ = create_model_from_pretrained(model_cfg="conch_ViT-B-16", checkpoint_path=ckpt)
        model = model.to(device).eval()
        _ENCODER_CACHE[key] = (torch_mod, model, get_tokenizer(), device)
    return _ENCODER_CACHE[key]


def encode_records(dataset: str, records: list[dict], cfg: dict, *, batch_size: int, ckpt: str) -> np.ndarray:
    torch_mod, model, tokenizer, device = _get_encoder(ckpt)

    patient_prompts = [[rec[col] for col in cfg["output_cols"]] for rec in records]
    flat_prompts = [sentence for sentences in patient_prompts for sentence in sentences]
    encoded = tokenizer(flat_prompts, padding=True, truncation=True, return_tensors="pt")
    all_tokens = encoded["input_ids"]
    chunks = []
    from tqdm import tqdm

    with torch_mod.inference_mode():
        for i in tqdm(range(0, len(flat_prompts), batch_size), desc=f"Encode raw {dataset}"):
            tokens = all_tokens[i : i + batch_size].to(device)
            feats = model.encode_text(tokens, embed_cls=False)
            feats = feats / feats.norm(dim=-1, keepdim=True)
            chunks.append(feats.cpu().float().numpy())
    return np.concatenate(chunks, axis=0).reshape(len(records), len(cfg["output_cols"]), -1)


def write_bank(
    dataset: str,
    records: list[dict],
    cfg: dict,
    embeddings: np.ndarray,
    *,
    ckpt: str,
) -> Path:
    out_dir = raw_bank_dir(dataset)
    pt_dir = out_dir / "embeddings" / "pt"
    pt_dir.mkdir(parents=True, exist_ok=True)
    import torch

    for rec, emb in zip(records, embeddings):
        mask = [bool(rec["_mask"][col]) for col in cfg["output_cols"]]
        payload = {
            "matrix": torch.from_numpy(emb),
            "mask": torch.tensor(mask, dtype=torch.bool),
            "patient_id": rec["patient_id"],
        }
        torch.save(payload, pt_dir / f"{rec['patient_id']}.pt")

    prompt_rows = []
    for rec in records:
        row = {"patient_id": rec["patient_id"]}
        row.update({col: rec[col] for col in cfg["output_cols"]})
        prompt_rows.append(row)
    pd.DataFrame(prompt_rows).to_csv(out_dir / "prompts.csv", index=False)

    index = {
        "dataset": dataset,
        "fields": list(cfg["fields"]),
        "n_fields": len(cfg["fields"]),
        "embed_dim": int(embeddings.shape[-1]),
        "encoder": "CONCH",
        "ckpt": str(ckpt),
        "missing_policy": "placeholder_sentence",
        "landmark_policy": "off",
        "landmark_time": None,
        "extraction_mask": "off",
        "field_list_source": "landmark_0",
        "variant": "raw",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_patients": len(records),
    }
    with open(out_dir / "field_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return out_dir


def verify_against_lm0(dataset: str, records: list[dict], cfg: dict) -> None:
    lm_bank = lm0_bank_dir(dataset)
    lm_index = json.loads((lm_bank / "field_index.json").read_text(encoding="utf-8"))
    if list(lm_index.get("fields") or []) != list(cfg["fields"]):
        raise ValueError(
            f"{dataset}: raw 变体字段表与 lm0 field bank 不一致（raw 必须 = lm0 kept 字段集，同序）"
        )
    raw_ids = {rec["patient_id"] for rec in records}
    lm_ids = {path.stem for path in (lm_bank / "embeddings" / "pt").glob("*.pt")}
    if raw_ids != lm_ids:
        missing = sorted(lm_ids - raw_ids)[:5]
        extra = sorted(raw_ids - lm_ids)[:5]
        raise ValueError(
            f"{dataset}: raw 变体患者集与 lm0 field bank 不一致 "
            f"(lm0 缺 {missing}, raw 多 {extra}; n_lm0={len(lm_ids)} n_raw={len(raw_ids)})"
        )


def append_diff_csv(rows: list[dict]) -> None:
    if not rows:
        return
    DIFF_CSV.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    if DIFF_CSV.exists():
        old = pd.read_csv(DIFF_CSV)
        df = pd.concat([old[~old["dataset"].isin(df["dataset"])], df], ignore_index=True)
    df.sort_values(["dataset", "field"]).to_csv(DIFF_CSV, index=False)


def build_one(args, dataset: str, datasets: dict) -> dict:
    out_dir = raw_bank_dir(dataset)
    if args.overwrite and out_dir.exists():
        import shutil

        shutil.rmtree(out_dir)
    records, cfg, patient_ids = build_prompt_rows(dataset, datasets)
    verify_against_lm0(dataset, records, cfg)
    summary, field_rows = diff_against_lm0(records, cfg, dataset)
    if summary["untimed_changed_fields"]:
        raise ValueError(
            f"{dataset}: 非 timed family 字段出现 mask 取值差异（提取逻辑异常）: "
            f"{summary['untimed_changed_fields']}"
        )
    index_path = out_dir / "field_index.json"
    if index_path.exists() and not args.overwrite:
        old = json.loads(index_path.read_text(encoding="utf-8"))
        if int(old.get("n_patients") or -1) == len(records):
            print(f"[s5b] skip {dataset}: 已存在（{index_path}）")
            return {"dataset": dataset, "skipped": True, **summary}

    embeddings = encode_records(
        dataset, records, cfg, batch_size=args.batch_size, ckpt=args.ckpt
    )
    write_bank(dataset, records, cfg, embeddings, ckpt=args.ckpt)
    with open(out_dir / "raw_value_diff.json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "fields": field_rows}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(
        f"[s5b] {dataset}: fields={summary['n_fields']} patients={summary['n_patients']} "
        f"changed_cells={summary['changed_cells']} changed_patients={summary['changed_patients']} "
        f"changed_fields={len(summary['changed_fields'])}"
    )
    return {"dataset": dataset, "skipped": False, **summary, "field_rows": field_rows}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="构建 Test_1a off 臂 raw 变体 Field Bank（mask off）")
    parser.add_argument("--dataset", required=True, help="数据集名；支持 all / 逗号分隔；只取 TCGA- 前缀")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--encoding", default="prompt")
    parser.add_argument("--ckpt", default=str(DEFAULT_CKPT))
    parser.add_argument("--batch_size", type=int, default=256)
    parser.add_argument("--device", default=None, help="CUDA_VISIBLE_DEVICES；默认不覆盖环境变量")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    if args.device is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(args.device)
    datasets = load_dataset_configs(args.datasets_config)
    names = tcga_datasets(args)
    if not names:
        raise ValueError("--dataset 解析为空")
    print(f"[s5b] datasets={len(names)}: {','.join(names)}")
    all_field_rows: list[dict] = []
    summaries = []
    for name in names:
        result = build_one(args, name, datasets)
        summaries.append(result)
        all_field_rows.extend(result.get("field_rows") or [])
    append_diff_csv(all_field_rows)
    print("[s5b] summary:")
    for item in summaries:
        print(
            f"  {item['dataset']}: fields={item['n_fields']} patients={item['n_patients']} "
            f"changed_cells={item['changed_cells']} changed_patients={item['changed_patients']}"
        )
    print(f"[s5b] diff csv: {DIFF_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
