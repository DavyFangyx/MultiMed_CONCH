"""Encode L0-L5 / paper-scheme prompt CSVs with CONCH."""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .paths import DEFAULT_GPU, REPO_ROOT

from .config import SCHEME_COLS, SCHEME_DIRNAME


def _lazy_import_conch():
    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    import torch
    from conch.open_clip_custom import create_model_from_pretrained, get_tokenizer

    return torch, create_model_from_pretrained, get_tokenizer


def _build_patient_prompt_matrix(df: pd.DataFrame, prompt_cols: list) -> list:
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

    csv_path = Path(prompt_dir) / scheme / "prompts.csv"
    out_subdir = Path(out_dir) / SCHEME_DIRNAME[scheme]
    prompt_cols = SCHEME_COLS[scheme]

    print(f"\n{'='*55}")
    print(f"[encode] 方案 {scheme}")
    print(f"  prompt CSV : {csv_path}")
    print(f"  输出目录   : {out_subdir}")
    print(f"  可见 GPU   : {DEFAULT_GPU}")
    print(f"{'='*55}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  设备: {device}")

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

    print(f"[2/3] 加载 CONCH: {ckpt}")
    model, _ = create_model_from_pretrained(model_cfg="conch_ViT-B-16", checkpoint_path=ckpt)
    model = model.to(device).eval()
    tokenizer = get_tokenizer()

    encoded = tokenizer(flat_prompts, padding=True, truncation=True, return_tensors="pt")
    all_tokens = encoded["input_ids"]
    all_embeddings = []
    with torch.inference_mode():
        for i in tqdm(range(0, len(flat_prompts), batch_size), desc="Encoding"):
            tokens = all_tokens[i : i + batch_size].to(device)
            feats = model.encode_text(tokens, embed_cls=False)
            feats = feats / feats.norm(dim=-1, keepdim=True)
            all_embeddings.append(feats.cpu().float().numpy())
    embeddings = np.concatenate(all_embeddings, axis=0)
    embeddings = embeddings.reshape(len(patient_ids), num_prompt_fields, -1)
    print(f"      Embedding shape: {embeddings.shape}")

    print(f"\n[3/3] 按患者 ID 保存文件 → {out_subdir}")
    pt_dir = out_subdir / "embeddings" / "pt"
    pt_dir.mkdir(parents=True, exist_ok=True)
    for pid, emb in tqdm(zip(patient_ids, embeddings), total=len(patient_ids), desc="保存每患者文件"):
        tensor = torch.from_numpy(emb)
        torch.save(tensor, pt_dir / f"{pid}.pt")

    print("\n" + "=" * 55)
    print(f"✅  方案 {scheme} 编码完成")
    print(f"   患者数   : {len(patient_ids)}")
    print(f"   Prompt 数 : {num_prompt_fields}")
    print(f"   PT 目录  : {pt_dir}")
    print("=" * 55)
