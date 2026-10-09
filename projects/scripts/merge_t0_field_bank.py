#!/usr/bin/env python3
"""Test_1a merged t0 臂：噪声本底归零（原名 s5c_merge_t0_bank.py，2026-10-09 收尾改名）：构建 merged t0 臂 Field Bank（未改动单元格复用 off 臂行）。

背景（2026-10-08 探针结论）：
    两臂同句子的编码差异 = batch_size 不同（t0=64 / off=256）的 GEMM 浮点舍入（~7e-7）。
    未改动单元格文本逐字相同 → 直接复制 off 臂矩阵行后两臂输入位同，下游 MLP 重训位确定
    （同 seed/k/输入两跑逐位相同）→ 未改动字段 Δc 精确 0，左组噪声本底归零。
    padding 宽度分歧机制在当前 15 集未激活（两臂宽度相同；s5b 侧已有硬校验防再犯）。

产物（每个数据集）：
    outputs/_merged/{dataset}/field_bank/prompt/landmark_0/
        embeddings/pt/*.pt   # matrix 行：文本未改动 → off 臂行；文本改动/off 缺列 → t0 臂行
        prompts.csv          # 复制 t0 臂版（溯源）
        field_index.json     # t0 臂元数据 + variant/merge_stats
        merged_cell_map.json # 逐字段合并统计（审计，对照 raw_value_diff.json）

硬校验（任一不满足即报错，不产出）：
    ① 患者集与 off 臂 pt 文件集完全一致（两臂同患者集的前提）；
    ② prompts.csv 患者集与 pt 文件集一致、无重复，且矩阵行数与各自 prompts.csv 列数一致；
    ③ 文本改动的字段必须全是 timed family 字段（非 timed family 出现差异 = 提取逻辑异常）。

运行环境：conda env conch（仅 torch 读写，纯 CPU）。用法：
    python scripts/merge_t0_field_bank.py --dataset TCGA-BLCA,TCGA-COAD,TCGA-STAD
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for item in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import DEFAULT_DATASETS_CONFIG, LANDMARK_OFF_TAG, PROJECT_ROOT as PATHS_PROJECT_ROOT
from discovery.landmark import timed_family_for_field

MERGED_ROOT = PATHS_PROJECT_ROOT / "outputs" / "_merged"
T0_TAG = "landmark_0"


def t0_bank_dir(dataset: str, encoding: str = "prompt") -> Path:
    return PATHS_PROJECT_ROOT / "outputs" / dataset / "field_bank" / encoding / T0_TAG


def _off_tag_on_disk(dataset: str, encoding: str = "prompt") -> str:
    """off 臂目录 tag = 现行常量 LANDMARK_OFF_TAG(no_mask)。"""
    return LANDMARK_OFF_TAG


def off_bank_dir(dataset: str, encoding: str = "prompt") -> Path:
    return PATHS_PROJECT_ROOT / "outputs" / "_raw" / dataset / "field_bank" / encoding / _off_tag_on_disk(dataset, encoding)


def merged_bank_dir(dataset: str, encoding: str = "prompt") -> Path:
    return MERGED_ROOT / dataset / "field_bank" / encoding / T0_TAG


def tcga_datasets(args) -> list[str]:
    datasets = load_dataset_configs(args.datasets_config)
    names = resolve_dataset_names(args.dataset, datasets)
    if not names:
        names = [item for item in datasets if str(item).startswith(("TCGA-", "TCGA_"))]
    return [name for name in names if str(name).startswith(("TCGA-", "TCGA_"))]


def merge_one(args, dataset: str) -> dict:
    import torch

    t0_dir = t0_bank_dir(dataset)
    off_dir = off_bank_dir(dataset)
    out_dir = merged_bank_dir(dataset)
    if not (t0_dir / "field_index.json").exists():
        raise FileNotFoundError(f"{dataset}: 缺 t0 臂 bank（{t0_dir}）")
    if not (off_dir / "field_index.json").exists():
        raise FileNotFoundError(f"{dataset}: 缺 off 臂 bank（{off_dir}），先跑 scripts/build_raw_field_bank.py")

    if out_dir.exists() and not args.overwrite:
        index_path = out_dir / "field_index.json"
        if index_path.exists():
            old = json.loads(index_path.read_text(encoding="utf-8"))
            t0_index = json.loads((t0_dir / "field_index.json").read_text(encoding="utf-8"))
            off_index = json.loads((off_dir / "field_index.json").read_text(encoding="utf-8"))
            # 2026-10-09 指纹化: 患者数 + 两臂模板指纹一致才复用
            if (int(old.get("n_patients") or -1) == int(t0_index.get("n_patients") or -1)
                    and old.get("t0_template_sha256") == t0_index.get("template_sha256")
                    and old.get("off_template_sha256") == off_index.get("template_sha256")):
                print(f"[s5c] skip {dataset}: 已存在且指纹一致（{out_dir}）")
                return {"dataset": dataset, "skipped": True}
        shutil.rmtree(out_dir)
    elif out_dir.exists():
        shutil.rmtree(out_dir)

    t0_index = json.loads((t0_dir / "field_index.json").read_text(encoding="utf-8"))
    t0_p = pd.read_csv(t0_dir / "prompts.csv", dtype=str).fillna("")
    off_p = pd.read_csv(off_dir / "prompts.csv", dtype=str).fillna("")
    t0_cols = [c for c in t0_p.columns if c != "patient_id"]
    off_cols = [c for c in off_p.columns if c != "patient_id"]
    if len(t0_cols) != len(t0_index.get("fields") or []):
        raise ValueError(
            f"{dataset}: t0 prompts 列数 {len(t0_cols)} != field_index fields 数 {len(t0_index.get('fields') or [])}"
        )

    # 硬校验①：患者集一致（pt 文件 stem 集合）
    t0_ids = {p.stem for p in (t0_dir / "embeddings" / "pt").glob("*.pt")}
    off_ids = {p.stem for p in (off_dir / "embeddings" / "pt").glob("*.pt")}
    if t0_ids != off_ids:
        missing = sorted(off_ids - t0_ids)[:5]
        extra = sorted(t0_ids - off_ids)[:5]
        raise ValueError(
            f"{dataset}: t0/off 患者集不一致 (off 缺 {missing}, off 多 {extra}; "
            f"n_t0={len(t0_ids)} n_off={len(off_ids)})"
        )

    # 硬校验②：prompts 患者集与 pt 一致、无重复
    if set(t0_p["patient_id"]) != t0_ids or t0_p["patient_id"].nunique() != len(t0_p):
        raise ValueError(f"{dataset}: t0 prompts.csv 患者集与 pt 文件集不一致")
    if set(off_p["patient_id"]) != t0_ids or off_p["patient_id"].nunique() != len(off_p):
        raise ValueError(f"{dataset}: off prompts.csv 患者集与 pt 文件集不一致")

    pids = sorted(t0_ids)
    t0_p = t0_p.set_index("patient_id").loc[pids]
    off_p = off_p.set_index("patient_id").loc[pids]
    off_colmap = {name: i for i, name in enumerate(off_cols)}

    # 逐字段文本差异统计（只统计两臂共有列；off 缺列 = only_t0，不算 changed）
    per_col: dict[str, dict] = {}
    for c in t0_cols:
        if c in off_colmap:
            per_col[c] = {"changed": int((t0_p[c] != off_p[c]).sum()), "only_t0": False}
        else:
            per_col[c] = {"changed": 0, "only_t0": True}

    # 硬校验③：文本改动的字段必须全是 timed family
    untimed_changed = []
    for col, field_path in zip(t0_cols, t0_index["fields"]):
        family, _ = timed_family_for_field(field_path)
        if per_col[col]["changed"] and not family:
            untimed_changed.append(f"{field_path} ({col}) changed={per_col[col]['changed']}")
    if untimed_changed:
        raise ValueError(f"{dataset}: 非 timed family 字段出现文本改动（提取逻辑异常）: {untimed_changed}")

    pt_dir = out_dir / "embeddings" / "pt"
    pt_dir.mkdir(parents=True, exist_ok=True)
    n_copied = 0
    n_kept_differ = 0
    n_kept_missing = 0
    for pid in pids:
        t0_payload = torch.load(t0_dir / "embeddings" / "pt" / f"{pid}.pt", map_location="cpu")
        off_payload = torch.load(off_dir / "embeddings" / "pt" / f"{pid}.pt", map_location="cpu")
        t0_m = t0_payload["matrix"].numpy().astype(np.float32)
        off_m = off_payload["matrix"].numpy().astype(np.float32)
        if t0_m.shape[0] != len(t0_cols) or off_m.shape[0] != len(off_cols):
            raise ValueError(
                f"{dataset}/{pid}: 矩阵行数不匹配 "
                f"(t0 {t0_m.shape[0]}/{len(t0_cols)}, off {off_m.shape[0]}/{len(off_cols)})"
            )
        merged = t0_m.copy()
        for j, col in enumerate(t0_cols):
            i = off_colmap.get(col)
            if i is None:
                n_kept_missing += 1
                continue
            if t0_p.loc[pid, col] == off_p.loc[pid, col]:
                merged[j] = off_m[i]
                n_copied += 1
            else:
                n_kept_differ += 1
        torch.save(
            {"matrix": torch.from_numpy(merged), "mask": t0_payload["mask"], "patient_id": pid},
            pt_dir / f"{pid}.pt",
        )

    shutil.copyfile(t0_dir / "prompts.csv", out_dir / "prompts.csv")
    index = dict(t0_index)
    index.update(
        {
            "variant": "merged_from_raw_off",
            "source_t0_bank": str(t0_dir),
            "source_off_bank": str(off_dir),
            # 2026-10-09 指纹化: skip 守卫的新鲜度判据
            "t0_template_sha256": t0_index.get("template_sha256"),
            "off_template_sha256": json.loads(
                (off_dir / "field_index.json").read_text(encoding="utf-8")
            ).get("template_sha256"),
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "merge_stats": {
                "n_patients": len(pids),
                "n_fields": len(t0_cols),
                "n_cells_total": len(pids) * len(t0_cols),
                "n_cells_copied": n_copied,
                "n_cells_kept_text_differ": n_kept_differ,
                "n_cells_kept_col_missing": n_kept_missing,
                "n_fields_only_t0": sum(1 for info in per_col.values() if info["only_t0"]),
                "n_fields_only_off": len([c for c in off_cols if c not in set(t0_cols)]),
                "changed_fields": sorted(
                    field_path
                    for col, field_path in zip(t0_cols, t0_index["fields"])
                    if per_col[col]["changed"]
                ),
                "untimed_changed_fields": [],
            },
        }
    )
    with open(out_dir / "field_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write("\n")

    cell_map = []
    for col, field_path in zip(t0_cols, t0_index["fields"]):
        family, _ = timed_family_for_field(field_path)
        info = per_col[col]
        cell_map.append(
            {
                "dataset": dataset,
                "field": field_path,
                "output_col": col,
                "family": family or "",
                "timed_family": bool(family),
                "changed_cells": info["changed"],
                "n_patients": len(pids),
                "only_t0": info["only_t0"],
            }
        )
    with open(out_dir / "merged_cell_map.json", "w", encoding="utf-8") as f:
        json.dump({"dataset": dataset, "fields": cell_map}, f, ensure_ascii=False, indent=2)
        f.write("\n")

    stats = index["merge_stats"]
    warnings = []
    if stats["n_fields_only_t0"]:
        warnings.append(f"{stats['n_fields_only_t0']} 个 t0-only 字段无法替换（等待 raw bank 重建）")
    if stats["n_fields_only_off"]:
        warnings.append(f"{stats['n_fields_only_off']} 个 off-only 字段未参与")
    print(
        f"[s5c] {dataset}: patients={len(pids)} fields={len(t0_cols)} "
        f"copied={n_copied} kept_text_differ={n_kept_differ} kept_col_missing={n_kept_missing} "
        f"changed_fields={len(stats['changed_fields'])}"
        + (" | 警告: " + "; ".join(warnings) if warnings else "")
    )
    return {"dataset": dataset, "skipped": False, **stats}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="构建 Test_1a merged t0 臂 Field Bank（未改动单元格复用 off 臂行）")
    parser.add_argument("--dataset", required=True, help="数据集名；支持 all / 逗号分隔；只取 TCGA- 前缀")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    names = tcga_datasets(args)
    if not names:
        raise ValueError("--dataset 解析为空")
    print(f"[s5c] datasets={len(names)}: {','.join(names)}")
    summaries = []
    for name in names:
        summaries.append(merge_one(args, name))
    if not any(not item.get("skipped") for item in summaries):
        print("[s5c] 全部已存在（重跑用 --overwrite）")
    print("[s5c] out root:", MERGED_ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
