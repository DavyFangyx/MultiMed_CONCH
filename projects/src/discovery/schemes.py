"""Compose L2 / L3 / L5 clinic embeddings from Field Bank prompt sentences."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import (
    DEFAULT_CKPT,
    DEFAULT_GPU,
    dataset_field_bank_dir,
    dataset_scheme_dir,
    landmark_tag_from_args,
    scheme_run_tag,
    shared_l5_groups_path,
    validate_scheme,
)
from .field_bank import _lazy_import_conch, load_field_bank_template
from .landmark import iter_landmark_args, landmark_policy, parse_landmark_options


CONCH_MAX_TEXT_TOKENS = 127
L2_EMPTY_TEXT = "Clinical information is not reported."
L5_MISSING_TEMPLATE = "The {group} information is not reported."
L5_GROUP_COLUMNS = ("group", "field_path")


def load_l5_groups(path: Path | None = None) -> dict[str, list[str]]:
    csv_path = Path(path or shared_l5_groups_path())
    if not csv_path.exists():
        raise FileNotFoundError(f"未找到 L5 语义分组表: {csv_path}")
    df = pd.read_csv(csv_path)
    missing = [col for col in L5_GROUP_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"L5 分组表缺少列 {missing}: {csv_path}")
    groups: dict[str, list[str]] = {}
    seen_fields: set[str] = set()
    for row in df.itertuples(index=False):
        group = str(getattr(row, "group", "")).strip()
        field_path = str(getattr(row, "field_path", "")).strip()
        if not group or not field_path:
            continue
        if field_path in seen_fields:
            raise ValueError(f"L5 分组表字段重复: {field_path}")
        seen_fields.add(field_path)
        groups.setdefault(group, []).append(field_path)
    if not groups:
        raise ValueError(f"L5 分组表为空: {csv_path}")
    return groups


def l5_group_lookup(groups: dict[str, list[str]] | None = None) -> dict[str, str]:
    groups = groups or load_l5_groups()
    return {field: group for group, fields in groups.items() for field in fields}


def require_l5_groups_for_fields(fields: list[str], groups: dict[str, list[str]] | None = None) -> dict[str, str]:
    lookup = l5_group_lookup(groups)
    missing = [field for field in fields if field not in lookup]
    if missing:
        preview = ", ".join(missing[:8])
        more = "" if len(missing) <= 8 else f" ... (+{len(missing) - 8})"
        raise ValueError(f"L5 分组表缺少字段: {preview}{more}")
    return lookup


def count_conch_tokens(tokenizer, text: str) -> int:
    encoded = tokenizer(
        str(text or ""),
        add_special_tokens=True,
        truncation=False,
        padding=False,
    )
    ids = encoded["input_ids"]
    if hasattr(ids, "tolist"):
        ids = ids.tolist()
    if ids and isinstance(ids[0], list):
        ids = ids[0]
    return len(ids)


def pack_token_windows(
    sentences: list[str],
    token_count_fn,
    max_tokens: int = CONCH_MAX_TEXT_TOKENS,
) -> list[str]:
    windows: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        text = str(sentence or "").strip()
        if not text:
            continue
        candidate = " ".join(current + [text]) if current else text
        n_tokens = int(token_count_fn(candidate))
        if current and n_tokens > max_tokens:
            windows.append(" ".join(current))
            current = [text]
            continue
        current.append(text)
    if current:
        windows.append(" ".join(current))
    return windows


def compose_l2_texts(sentences: list[str]) -> tuple[list[str], list[bool]]:
    present = [str(text).strip() for text in sentences if str(text or "").strip()]
    if not present:
        return [L2_EMPTY_TEXT], [False]
    return [" ".join(present)], [True]


def compose_l3_texts(
    sentences: list[str],
    token_count_fn,
    max_tokens: int = CONCH_MAX_TEXT_TOKENS,
) -> tuple[list[str], list[bool]]:
    present = [str(text).strip() for text in sentences if str(text or "").strip()]
    windows = pack_token_windows(present, token_count_fn, max_tokens=max_tokens)
    if not windows:
        return [], []
    return windows, [True] * len(windows)


def compose_l5_texts(
    field_texts: dict[str, str],
    field_present: dict[str, bool],
    groups: dict[str, list[str]],
) -> tuple[list[str], list[bool], list[str]]:
    texts: list[str] = []
    mask: list[bool] = []
    used_groups: list[str] = []
    for group, group_fields in groups.items():
        local_fields = [field for field in group_fields if field in field_texts]
        if not local_fields:
            continue
        present_sentences = [
            str(field_texts[field]).strip()
            for field in local_fields
            if field_present.get(field) and str(field_texts.get(field) or "").strip()
        ]
        used_groups.append(group)
        if present_sentences:
            texts.append(" ".join(present_sentences))
            mask.append(True)
        else:
            texts.append(L5_MISSING_TEMPLATE.format(group=group.replace("_", " ")))
            mask.append(False)
    if not used_groups:
        raise ValueError("该数据集没有可映射到 L5 分组的字段")
    return texts, mask, used_groups


def _missing_placeholder(template: str) -> str:
    return str(template).replace("{}", "not reported", 1)


def _is_present_sentence(sentence: str, template: str) -> bool:
    text = str(sentence or "").strip()
    if not text:
        return False
    return text != _missing_placeholder(template).strip()


def load_l1_prompt_rows(dataset_name: str, landmark_tag: str) -> tuple[pd.DataFrame, dict]:
    cfg = load_field_bank_template(dataset_name, require_templates=True, landmark_tag=landmark_tag)
    prompt_path = dataset_field_bank_dir(dataset_name, "prompt", landmark_tag) / "prompts.csv"
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"未找到 Field Bank prompt 基座: {prompt_path}。请先完成 python scripts/run_field_bank.py "
            f"--dataset {dataset_name} --encoding prompt --landmark_time <T|none>"
        )
    df = pd.read_csv(prompt_path)
    if df.empty or "patient_id" not in df.columns:
        raise ValueError(f"L1 prompts.csv 缺少 patient_id 或为空: {prompt_path}")
    missing_cols = [col for col in cfg["output_cols"] if col not in df.columns]
    if missing_cols:
        raise ValueError(f"{prompt_path} 缺少 Field Bank 列: {missing_cols[:8]}")
    return df, cfg


def iter_present_field_sentences(row, cfg: dict) -> tuple[list[str], dict[str, str], dict[str, bool]]:
    sentences = []
    field_texts = {}
    field_present = {}
    templates = cfg["templates"]
    mapping = getattr(row, "_asdict", None)
    values = mapping() if callable(mapping) else {col: getattr(row, col) for col in cfg["output_cols"]}
    for field_path, out_col in zip(cfg["fields"], cfg["output_cols"]):
        raw = values.get(out_col, "")
        sentence = "" if pd.isna(raw) else str(raw)
        present = _is_present_sentence(sentence, templates[field_path])
        field_texts[field_path] = sentence
        field_present[field_path] = present
        if present:
            sentences.append(sentence.strip())
    return sentences, field_texts, field_present


def _pad_texts(texts: list[str], mask: list[bool], width: int) -> tuple[list[str], list[bool]]:
    width = max(int(width), 1)
    padded_texts = list(texts[:width])
    padded_mask = list(mask[:width])
    while len(padded_texts) < width:
        padded_texts.append("")
        padded_mask.append(False)
    return padded_texts, padded_mask


def compose_scheme_rows(
    prompt_df: pd.DataFrame,
    cfg: dict,
    scheme: str,
    *,
    token_count_fn=None,
    groups: dict[str, list[str]] | None = None,
) -> tuple[list[str], list[list[str]], list[list[bool]], list[str]]:
    scheme = validate_scheme(scheme)
    if scheme == "L3" and token_count_fn is None:
        raise ValueError("L3 需要 tokenizer / token_count_fn 才能按 127 token 切窗")
    if scheme == "L5":
        groups = groups or load_l5_groups()
        require_l5_groups_for_fields(cfg["fields"], groups)
        l5_columns = [group for group, fields in groups.items() if any(field in cfg["fields"] for field in fields)]
    else:
        l5_columns = []

    patient_ids = [str(value) for value in prompt_df["patient_id"].tolist()]
    composed_rows: list[list[str]] = []
    composed_masks: list[list[bool]] = []
    columns: list[str] | None = None
    for row in prompt_df.itertuples(index=False):
        sentences, field_texts, field_present = iter_present_field_sentences(row, cfg)
        if scheme == "L2":
            texts, mask = compose_l2_texts(sentences)
            columns = ["text"]
        elif scheme == "L3":
            texts, mask = compose_l3_texts(sentences, token_count_fn)
        else:
            texts, mask, used = compose_l5_texts(field_texts, field_present, groups)
            if used != l5_columns:
                raise ValueError(f"L5 分组列不一致: {used} vs {l5_columns}")
            columns = l5_columns
        composed_rows.append(texts)
        composed_masks.append(mask)

    if scheme == "L3":
        width = max((len(row) for row in composed_rows), default=1)
        width = max(int(width), 1)
        padded_rows = []
        padded_masks = []
        for texts, mask in zip(composed_rows, composed_masks):
            texts, mask = _pad_texts(texts, mask, width)
            padded_rows.append(texts)
            padded_masks.append(mask)
        composed_rows, composed_masks = padded_rows, padded_masks
        columns = [f"window_{i:02d}" for i in range(width)]
    elif scheme == "L2":
        columns = ["text"]
    else:
        columns = columns or []
    return patient_ids, composed_rows, composed_masks, columns


def _write_prompt_table(path: Path, patient_ids: list[str], columns: list[str], rows: list[list[str]]) -> None:
    payload = [{"patient_id": pid, **dict(zip(columns, values))} for pid, values in zip(patient_ids, rows)]
    pd.DataFrame(payload).to_csv(path, index=False)


def _encode_texts(texts: list[str], model, tokenizer, device, batch_size: int, torch):
    import numpy as np

    n = len(texts)
    embeddings = [None] * n
    nonempty_idx = [i for i, text in enumerate(texts) if str(text or "").strip()]
    if nonempty_idx:
        nonempty_texts = [texts[i] for i in nonempty_idx]
        encoded = tokenizer(nonempty_texts, padding=True, truncation=True, return_tensors="pt")
        all_tokens = encoded["input_ids"]
        feats_out = []
        with torch.inference_mode():
            for start in range(0, len(nonempty_texts), batch_size):
                tokens = all_tokens[start : start + batch_size].to(device)
                feats = model.encode_text(tokens, embed_cls=False)
                feats = feats / feats.norm(dim=-1, keepdim=True)
                feats_out.append(feats.cpu().float().numpy())
        stacked = np.concatenate(feats_out, axis=0)
        for src_i, feat in zip(nonempty_idx, stacked):
            embeddings[src_i] = feat
    dim = next((vec.shape[-1] for vec in embeddings if vec is not None), 512)
    matrix = np.zeros((n, dim), dtype="float32")
    for i, vec in enumerate(embeddings):
        if vec is not None:
            matrix[i] = vec
    return matrix


def _save_patient_pts(pt_dir: Path, patient_ids: list[str], matrices, masks, torch) -> None:
    pt_dir.mkdir(parents=True, exist_ok=True)
    for patient_id, matrix, mask in zip(patient_ids, matrices, masks):
        payload = {
            "matrix": torch.from_numpy(matrix),
            "mask": torch.tensor(mask, dtype=torch.bool),
            "patient_id": patient_id,
        }
        torch.save(payload, pt_dir / f"{patient_id}.pt")


def encode_scheme_dataset(
    dataset_name: str,
    scheme: str,
    landmark_tag: str,
    *,
    use_landmark: bool,
    landmark_time,
    ckpt: str,
    batch_size: int,
    prompts_only: bool,
    groups: dict[str, list[str]] | None = None,
    tokenizer=None,
    token_count_fn=None,
    encode_batch_fn=None,
    prompt_df: pd.DataFrame | None = None,
    cfg: dict | None = None,
    out_dir: Path | None = None,
) -> dict:
    scheme = validate_scheme(scheme)
    if prompt_df is None or cfg is None:
        prompt_df, cfg = load_l1_prompt_rows(dataset_name, landmark_tag)
    run_tag = scheme_run_tag(landmark_tag, scheme)
    source_dir = dataset_field_bank_dir(dataset_name, "prompt", landmark_tag)
    out_dir = Path(out_dir or dataset_scheme_dir(dataset_name, scheme, landmark_tag))
    out_dir.mkdir(parents=True, exist_ok=True)

    if scheme == "L3" and token_count_fn is None:
        if tokenizer is None:
            _, _, get_tokenizer = _lazy_import_conch()
            tokenizer = get_tokenizer()
        token_count_fn = lambda text, _tokenizer=tokenizer: count_conch_tokens(_tokenizer, text)

    patient_ids, composed_rows, composed_masks, columns = compose_scheme_rows(
        prompt_df,
        cfg,
        scheme,
        token_count_fn=token_count_fn,
        groups=groups,
    )
    width = max(len(columns), 1)
    prompt_path = out_dir / "prompts.csv"
    _write_prompt_table(prompt_path, patient_ids, columns, composed_rows)
    print(f"✅ {scheme} prompts.csv: {prompt_path}  ({len(patient_ids)} 行)")

    index = {
        "dataset": dataset_name,
        "scheme": scheme,
        "scheme_run_tag": run_tag,
        "source_encoding": "prompt",
        "source_field_bank_dir": str(source_dir),
        "fields": cfg["fields"],
        "n_fields": len(cfg["fields"]),
        "n_tokens": width,
        "token_names": columns,
        "embed_dim": 512,
        "encoder": "CONCH",
        "ckpt": str(ckpt),
        "missing_policy": "skip_present_sentences" if scheme != "L5" else "group_placeholder_sentence",
        "landmark_policy": landmark_policy(use_landmark),
        "landmark_time": landmark_time,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_patients": len(patient_ids),
    }
    if scheme == "L3":
        index["max_tokens"] = CONCH_MAX_TEXT_TOKENS
        index["window_policy"] = "greedy_complete_sentences_le_127"
    if scheme == "L5":
        index["groups"] = columns
        index["groups_csv"] = str(shared_l5_groups_path())

    index_path = out_dir / "field_index.json"
    if prompts_only:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return {"out_dir": str(out_dir), "n_patients": len(patient_ids), "n_tokens": width}

    torch, create_model_from_pretrained, get_tokenizer = _lazy_import_conch()
    flat_texts = [text for row in composed_rows for text in row]
    if encode_batch_fn is not None:
        matrix = encode_batch_fn(flat_texts)
    else:
        os.environ["CUDA_VISIBLE_DEVICES"] = DEFAULT_GPU
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model, _ = create_model_from_pretrained(model_cfg="conch_ViT-B-16", checkpoint_path=ckpt)
        model = model.to(device).eval()
        if tokenizer is None:
            tokenizer = get_tokenizer()
        matrix = _encode_texts(flat_texts, model, tokenizer, device, batch_size, torch)
    matrices = matrix.reshape(len(patient_ids), width, -1)
    index["embed_dim"] = int(matrices.shape[-1])
    pt_dir = out_dir / "embeddings" / "pt"
    _save_patient_pts(pt_dir, patient_ids, matrices, composed_masks, torch)
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"✅ {scheme} field_index.json: {index_path}")
    print(f"✅ {scheme} pt dir: {pt_dir}")
    return {"out_dir": str(out_dir), "n_patients": len(patient_ids), "n_tokens": width}


def run_schemes(args) -> None:
    scheme_arg = str(getattr(args, "scheme", "all") or "all").strip()
    schemes = ["L2", "L3", "L5"] if scheme_arg == "all" else [validate_scheme(scheme_arg)]
    datasets = load_dataset_configs(args.datasets_config)
    names = resolve_dataset_names(args.dataset, datasets)
    if not names:
        raise ValueError("schemes 需要 --dataset，例如 --dataset TCGA-READ 或 --dataset all")
    groups = load_l5_groups() if "L5" in schemes else None
    tokenizer = None
    encode_batch_fn = None
    prompts_only = bool(getattr(args, "prompts_only", False))
    ckpt = getattr(args, "ckpt", DEFAULT_CKPT)
    batch_size = int(getattr(args, "batch_size", 64))
    if (not prompts_only) or ("L3" in schemes):
        torch, create_model_from_pretrained, get_tokenizer = _lazy_import_conch()
        tokenizer = get_tokenizer()
        if not prompts_only:
            os.environ["CUDA_VISIBLE_DEVICES"] = DEFAULT_GPU
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model, _ = create_model_from_pretrained(model_cfg="conch_ViT-B-16", checkpoint_path=ckpt)
            model = model.to(device).eval()

            def encode_batch_fn(texts, _model=model, _tokenizer=tokenizer, _device=device, _torch=torch, _bs=batch_size):
                return _encode_texts(texts, _model, _tokenizer, _device, _bs, _torch)

    for name in names:
        for landmark_args in iter_landmark_args(
            args,
            scan_roots=dataset_field_bank_dir(name, "prompt", "landmark_none").parent,
            context=f"schemes {name}",
        ):
            use_landmark, landmark_time = parse_landmark_options(landmark_args)
            tag = landmark_tag_from_args(landmark_args)
            print(f"\n######## Dataset: {name}  {tag} ########")
            for scheme in schemes:
                encode_scheme_dataset(
                    name,
                    scheme,
                    tag,
                    use_landmark=use_landmark,
                    landmark_time=landmark_time,
                    ckpt=ckpt,
                    batch_size=batch_size,
                    prompts_only=prompts_only,
                    groups=groups,
                    tokenizer=tokenizer,
                    encode_batch_fn=encode_batch_fn,
                )
