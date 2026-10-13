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
from common.fingerprint import file_sha256
from common.missingness import classify_raw_value, clean_value
from common.patient_set import restrict_cases_to_label_patients
from .converters import convert_value, known_converters
from .landmark import (
    extract_from_objects,
    landmark_policy,
    parse_landmark_options,
    passing_family_objects,
    resolve_landmark,
)
from .field_bank_spec import SHARED_SPEC_PATH, fill_from_spec, load_shared_spec
from common.paths import (
    DEFAULT_CKPT,
    REPO_ROOT,
    dataset_field_bank_dir,
    dataset_field_bank_template_dir,
    dataset_kept_fields_path,
    dataset_stats_dir,
    landmark_tag_from_args,
    require_landmark_tag,
    resolve_cli_out_dir,
    shared_onehot_global_mapping_path,
    validate_encoding,
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
    landmark_tag: str | None = None,
) -> Path:
    out_dir = Path(out_dir or dataset_field_bank_template_dir(dataset_name, landmark_tag))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "FIELD_BANK.csv"
    map_path = out_dir / "FIELD_BANK_columns.json"
    fields = sorted(fields)
    preserved = _read_existing_templates(out_path)
    examples = examples or {}
    spec = load_shared_spec() if SHARED_SPEC_PATH.exists() else {}

    rows = []
    for field in fields:
        old = preserved.get(field, {})
        filled = fill_from_spec(
            field,
            old,
            spec,
            overwrite_convert_unit=False,
            overwrite_template=False,
        )
        rows.append(
            {
                "field": field,
                "example": examples.get(field) or old.get("example", ""),
                "convert": filled["convert"],
                "unit": filled["unit"],
                "template": filled["template"],
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


def load_kept_fields(dataset_name: str | None = None, path: Path | None = None, landmark_tag: str | None = None) -> dict:
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
    path = dataset_kept_fields_path(dataset_name, landmark_tag)
    if not path.exists():
        raise FileNotFoundError(
            f"未找到 {path}。请先运行 python projects/scripts/run_field_filter.py --dataset {dataset_name}"
        )
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return {dataset_name: _normalize_kept_payload(payload, dataset_name, path)}


def _fill_template(template: str, value: str) -> str:
    return str(template).replace("{}", str(value), 1)


def load_field_bank_template(
    dataset_name: str,
    *,
    require_templates: bool = True,
    landmark_tag: str | None = None,
) -> dict:
    template_dir = dataset_field_bank_template_dir(dataset_name, landmark_tag)
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
    if require_templates and empty_fields:
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



def _valid_raw_values(
    case: dict,
    field_path: str,
    objects: list | None,
    remainder: str,
    family: str | None = None,
) -> list:
    if objects is not None:
        raw_vals = extract_from_objects(objects, remainder)
    else:
        raw_vals = extract_path_values(case, field_path)
    if not raw_vals:
        return []

    use_primary = family == "diagnoses" or (
        family is None and field_path.startswith("diagnoses[]")
    )
    if use_primary:
        diagnoses = objects if objects is not None else case.get("diagnoses", [])
        diag_remainder = remainder if family == "diagnoses" else field_path[len("diagnoses[]"):].lstrip(".")
        leaf = field_path.split(".")[-1].replace("[]", "")
        if "." not in diag_remainder:
            primary = get_primary_diagnosis(diagnoses if isinstance(diagnoses, list) else [])
            if primary and leaf in primary:
                value = primary.get(leaf)
                return [value] if classify_raw_value(value) == "valid" else []
    return [value for value in raw_vals if classify_raw_value(value) == "valid"]


def extract_field_bank_raw_values(case: dict, field_path: str, landmark=True, landmark_time=None) -> list:
    """Return valid raw JSON values using the same Field Bank extract rules."""
    from .landmark import timed_family_for_field
    from .longitudinal import FOLLOW_UP_FAMILIES, extract_derived_raw_values, is_derived_field

    if is_derived_field(field_path):
        return extract_derived_raw_values(field_path, landmark=landmark)

    landmark_state = resolve_landmark(case, landmark, landmark_time=landmark_time)
    if isinstance(landmark_state, dict) and "current_follow_up" in landmark_state:
        family, remainder = timed_family_for_field(field_path)
        if family in FOLLOW_UP_FAMILIES:
            current = landmark_state.get("current_follow_up")
            if not isinstance(current, dict):
                return []
            if family == "follow_ups":
                objects = [current]
            elif family == "follow_ups_molecular_tests":
                objects = [item for item in (current.get("molecular_tests") or []) if isinstance(item, dict)]
            elif family == "follow_ups_other_clinical_attributes":
                objects = [item for item in (current.get("other_clinical_attributes") or []) if isinstance(item, dict)]
            else:
                objects = [current]
            return _valid_raw_values(case, field_path, objects, remainder, family=family)
    if landmark_state is not None and not (isinstance(landmark_state, dict) and landmark_state.get("no_mask")):
        family, remainder, objects = passing_family_objects(field_path, landmark_state)
        if family is not None:
            return _valid_raw_values(case, field_path, objects, remainder, family=family)
    return _valid_raw_values(case, field_path, None, "")


def extract_field_bank_value(case: dict, field_path: str, landmark=True, landmark_time=None) -> tuple[str, bool]:
    valid_vals = extract_field_bank_raw_values(
        case, field_path, landmark=landmark, landmark_time=landmark_time
    )
    if not valid_vals:
        return "not reported", False
    return unique_join(valid_vals, fallback="not reported"), True


def generate_field_bank_prompt_row(case: dict, cfg: dict, landmark=True, landmark_time=None) -> dict:
    row = {"patient_id": case["submitter_id"]}
    mask = {}
    converts = cfg.get("converts") or {}
    landmark_state = resolve_landmark(case, landmark, landmark_time=landmark_time)
    for out_col, field_path in zip(cfg["output_cols"], cfg["fields"]):
        value, valid = extract_field_bank_value(case, field_path, landmark=landmark_state)
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
    encoding = validate_encoding(getattr(args, "encoding", "prompt"))
    if encoding == "onehot" and getattr(args, "prompts_only", False):
        raise ValueError("--prompts_only is only valid with --encoding prompt")

    datasets = load_dataset_configs(args.datasets_config)
    names = resolve_dataset_names(args.dataset, datasets)
    if not names:
        raise ValueError("FIELD_BANK 需要 --dataset，例如 --dataset TCGA-READ 或 --dataset all")

    from .landmark import iter_landmark_args

    jobs = []
    for name in names:
        dataset_jobs = []
        for landmark_args in iter_landmark_args(
            args,
            scan_roots=dataset_stats_dir(name),
            context=f"field bank {name}",
        ):
            dataset_jobs.append((name, landmark_args))
        jobs.extend(dataset_jobs)
    args._multi_dataset = len(jobs) > 1
    if encoding == "onehot":
        _run_onehot_batch(args, jobs, datasets)
        return
    for name, landmark_args in jobs:
        landmark_args._multi_dataset = args._multi_dataset
        _run_field_bank_one(landmark_args, name, datasets, encoding)


def _resolve_bank_context(args, name, datasets, encoding) -> dict:
    """kept_fields/模板/病例加载(onehot 与 prompt 分支共用)。"""
    use_landmark, landmark_time = parse_landmark_options(args)
    tag = landmark_tag_from_args(args)
    args.landmark_tag = tag
    kept = load_kept_fields(
        dataset_name=name,
        path=Path(args.kept_fields) if args.kept_fields else None,
        landmark_tag=tag,
    )
    if name not in kept:
        raise ValueError(f"{name} 不在 {args.kept_fields or dataset_kept_fields_path(name, tag)} 中。请先跑 run_field_filter.py")
    cfg = load_field_bank_template(
        name,
        require_templates=(encoding != "onehot"),
        landmark_tag=tag,
    )
    expected = list(kept[name]["fields"])
    if cfg["fields"] != expected:
        print("  ⚠️  模板字段与 kept_fields.json 不完全一致，以模板当前行为准。")
    cases = load_clinical_cases(
        get_dataset_clinic_files(name, datasets),
        project_ids=get_dataset_project_ids(name, datasets),
    )
    # 患者级前置过滤(2026-10-09 用户拍板):字段级编码只在 label 患者集上做,
    # gt≤0 等不可靠患者在统计/筛选/编码之前即被剔除(不再靠评估期静默丢弃)。
    cases, _ = restrict_cases_to_label_patients(cases, name)
    return {
        "args": args,
        "name": name,
        "cfg": cfg,
        "cases": cases,
        "tag": tag,
        "use_landmark": use_landmark,
        "landmark_time": landmark_time,
    }


def _run_onehot_batch(args, jobs, datasets) -> None:
    """onehot 全局共享词表口径(2026-10-09 用户拍板)。

    按 tag 分组:同 tag 多数据集(如 --dataset all)时合并全部患者拟合一张
    全局名义词表并落盘;单数据集时消费已落盘的共享词表(缺失即报错)。
    与 baseline/HGCN 共享词表口径对标——index k 跨数据集语义一致。
    """
    from .onehot import (
        collect_patient_field_values,
        encode_onehot,
        fit_global_nominal_mappings,
        load_global_nominal_mapping,
        save_global_nominal_mapping,
    )

    rare_threshold = int(getattr(args, "rare_freq_threshold", 5))
    contexts = [_resolve_bank_context(landmark_args, name, datasets, "onehot") for name, landmark_args in jobs]
    by_tag: dict[str, list[dict]] = {}
    for ctx in contexts:
        by_tag.setdefault(ctx["tag"], []).append(ctx)

    for tag, group in by_tag.items():
        mapping_path = shared_onehot_global_mapping_path(tag)
        if len(group) == 1:
            if not mapping_path.exists():
                raise ValueError(
                    f"共享 onehot 词表不存在: {mapping_path}。"
                    f"请先跑 run_field_bank --encoding onehot --dataset all 重建全局词表(2026-10-09 口径)。"
                )
            global_mapping = load_global_nominal_mapping(mapping_path, fields=group[0]["cfg"]["fields"])
            try:
                payload = json.loads(mapping_path.read_text(encoding="utf-8"))
                built_scope = int((payload.get("n_datasets") or 0))
                tcga_total = sum(1 for key in datasets if str(key).startswith(("TCGA-", "TCGA_")))
                if built_scope < tcga_total:
                    print(f"  ⚠️  共享词表仅由 {built_scope} 个数据集拟合(全量应为 {tcga_total})，建议 --dataset all 重建后再消费")
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
            print(f"[onehot] {tag}: 消费共享词表 {mapping_path}")
        else:
            patients_by_ds = [
                collect_patient_field_values(
                    ctx["cases"],
                    ctx["cfg"]["fields"],
                    ctx["cfg"].get("converts") or {},
                    landmark=ctx["use_landmark"],
                    landmark_time=ctx["landmark_time"],
                )
                for ctx in group
            ]
            all_fields = sorted({field for ctx in group for field in ctx["cfg"]["fields"]})
            global_mapping = fit_global_nominal_mappings(patients_by_ds, all_fields, rare_threshold=rare_threshold)
            save_global_nominal_mapping(
                mapping_path,
                global_mapping,
                landmark_tag=tag,
                n_patients=sum(len(patients) for patients in patients_by_ds),
                n_datasets=len(group),
                rare_threshold=rare_threshold,
            )
            print(f"[onehot] {tag}: 拟合全局共享词表 {mapping_path} ({len(all_fields)} 字段, {len(group)} 数据集)")

        for ctx in group:
            encode_onehot(
                dataset_name=ctx["name"],
                cfg=ctx["cfg"],
                cases=ctx["cases"],
                out_dir=resolve_cli_out_dir(ctx["args"], dataset_field_bank_dir(ctx["name"], "onehot", tag), ctx["name"], tag),
                rare_threshold=rare_threshold,
                landmark=ctx["use_landmark"],
                landmark_time=ctx["landmark_time"],
                global_mapping=global_mapping,
            )


def _run_field_bank_one(args, name, datasets, encoding) -> None:
    ctx = _resolve_bank_context(args, name, datasets, encoding)
    cfg = ctx["cfg"]
    cases = ctx["cases"]
    tag = ctx["tag"]
    use_landmark = ctx["use_landmark"]
    landmark_time = ctx["landmark_time"]
    print(f"\n######## Dataset: {name}  {tag} ########")

    records = [
        generate_field_bank_prompt_row(
            case, cfg, landmark=use_landmark, landmark_time=landmark_time
        )
        for case in cases
        if "submitter_id" in case
    ]
    out_dir = resolve_cli_out_dir(args, dataset_field_bank_dir(name, encoding, tag), name, tag)
    # skip 守卫(2026-10-09 指纹化): 模板内容与字段表指纹一致才允许复用;
    # 模板/字段表改动 → 自动重建(不再仅凭 field_index.json 存在即跳过)。
    index_path = out_dir / "field_index.json"
    template_fp = file_sha256(cfg["template_file"])
    if index_path.exists() and not getattr(args, "overwrite", False):
        try:
            old_index = json.loads(index_path.read_text(encoding="utf-8"))
            if old_index.get("template_sha256") == template_fp and list(old_index.get("fields") or []) == cfg["fields"]:
                print(f"  [skip] bank 已存在且模板指纹一致: {out_dir}")
                return
            print(f"  [stale] bank 模板/字段表已变化,重建: {out_dir}")
        except (json.JSONDecodeError, OSError):
            pass
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
        return

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
        "landmark_policy": landmark_policy(use_landmark),
        "landmark_time": landmark_time,
        "template_sha256": template_fp,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_patients": len(patient_ids),
    }
    index_path = out_dir / "field_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"✅ field_index.json: {index_path}")
    print(f"✅ pt dir: {pt_dir}")
