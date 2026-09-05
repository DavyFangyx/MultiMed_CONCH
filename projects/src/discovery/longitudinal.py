"""Longitudinal follow-up records, derived fields, and Field Bank encoding."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from common.missingness import classify_raw_value
from common.paths import (
    DEFAULT_GPU,
    LONGITUDINAL_EXPERIMENT,
    dataset_field_bank_dir,
    landmark_tag_from_args,
    validate_encoding,
)
from .converters import convert_value, parse_number
from .field_bank import (
    _fill_template,
    _lazy_import_conch,
    field_bank_output_col,
    generate_field_bank_prompt_row,
    load_kept_fields,
    load_field_bank_template,
)
from .landmark import (
    landmark_policy,
    parse_landmark_options,
    patient_landmark,
    slot_passes_landmark,
)
from .onehot import (
    build_feature_schema,
    encode_patient_matrix,
    fit_continuous_stats,
    fit_nominal_mapping,
    infer_field_types,
)
from time_stats import _is_follow_up_shell, _to_float, extract_patient_time_record


DAYS_SINCE_FIELD = "follow_ups[].days_since_last_follow_up"
ECOG_FIELD = "follow_ups[].ecog_performance_status"
KARNOFSKY_FIELD = "follow_ups[].karnofsky_performance_status"
BMI_FIELD = "follow_ups[].other_clinical_attributes[].bmi"
WEIGHT_FIELD = "follow_ups[].other_clinical_attributes[].weight"
ECOG_CHANGE_FIELD = "follow_ups[].ecog_change"
KARNOFSKY_CHANGE_FIELD = "follow_ups[].karnofsky_change"
BMI_CHANGE_FIELD = "follow_ups[].bmi_change"
WEIGHT_CHANGE_FIELD = "follow_ups[].weight_change"

DERIVED_FIELDS = (
    DAYS_SINCE_FIELD,
    ECOG_CHANGE_FIELD,
    KARNOFSKY_CHANGE_FIELD,
    BMI_CHANGE_FIELD,
    WEIGHT_CHANGE_FIELD,
)

DERIVED_FIELD_SPECS = {
    DAYS_SINCE_FIELD: {
        "convert": "int",
        "unit": "days",
        "template": "Days since last follow-up is {}.",
        "note": "longitudinal derived; empty on first dated follow-up",
    },
    ECOG_CHANGE_FIELD: {
        "convert": "",
        "unit": "",
        "template": "ECOG performance status change is {}.",
        "note": "longitudinal derived; current minus previous dated follow-up",
    },
    KARNOFSKY_CHANGE_FIELD: {
        "convert": "",
        "unit": "",
        "template": "Karnofsky performance status change is {}.",
        "note": "longitudinal derived; current minus previous dated follow-up",
    },
    BMI_CHANGE_FIELD: {
        "convert": "",
        "unit": "",
        "template": "Body mass index change is {}.",
        "note": "longitudinal derived; current minus previous dated follow-up",
    },
    WEIGHT_CHANGE_FIELD: {
        "convert": "",
        "unit": "kg",
        "template": "Patient weight change is {} kg.",
        "note": "longitudinal derived; current minus previous dated follow-up",
    },
}

SOURCE_FIELDS = {
    ECOG_CHANGE_FIELD: ECOG_FIELD,
    KARNOFSKY_CHANGE_FIELD: KARNOFSKY_FIELD,
    BMI_CHANGE_FIELD: BMI_FIELD,
    WEIGHT_CHANGE_FIELD: WEIGHT_FIELD,
}

FOLLOW_UP_FAMILIES = {
    "follow_ups",
    "follow_ups_molecular_tests",
    "follow_ups_other_clinical_attributes",
}


def is_derived_field(field_path: str) -> bool:
    return str(field_path or "") in DERIVED_FIELDS


def derived_field_specs() -> list[dict[str, str]]:
    rows = []
    for field in DERIVED_FIELDS:
        spec = dict(DERIVED_FIELD_SPECS[field])
        spec["field"] = field
        rows.append(spec)
    return rows


def add_derived_fields_to_cfg(cfg: dict) -> dict:
    fields = list(cfg.get("fields") or [])
    output_cols = list(cfg.get("output_cols") or [])
    templates = dict(cfg.get("templates") or {})
    converts = dict(cfg.get("converts") or {})
    seen = set(fields)
    for spec in derived_field_specs():
        field = spec["field"]
        if field in seen:
            continue
        seen.add(field)
        fields.append(field)
        output_cols.append(field_bank_output_col(field))
        templates[field] = spec["template"]
        converts[field] = spec["convert"]
    updated = dict(cfg)
    updated["fields"] = fields
    updated["output_cols"] = output_cols
    updated["templates"] = templates
    updated["converts"] = converts
    return updated


def _empty_derived() -> dict[str, float | int | None]:
    return {field: None for field in DERIVED_FIELDS}


def _follow_up_objects(case: dict) -> list[dict]:
    values = case.get("follow_ups") if isinstance(case, dict) else None
    if not isinstance(values, list):
        return []
    objs = []
    for item in values:
        if isinstance(item, dict) and not _is_follow_up_shell(item):
            objs.append(item)
    return objs


def _slot_for_follow_up(slots: dict, follow_up: dict) -> dict | None:
    for slot in slots.get("follow_ups") or []:
        if slot.get("obj") is follow_up:
            return slot
    return None


def _numeric_source_value(case: dict, follow_up: dict, field_path: str, landmark_state) -> float | None:
    from .field_bank import extract_field_bank_raw_values

    state = dict(landmark_state or {})
    state["current_follow_up"] = follow_up
    raw_vals = extract_field_bank_raw_values(case, field_path, landmark=state)
    numbers = []
    for value in raw_vals:
        number = parse_number(value)
        if number is not None:
            numbers.append(number)
    if not numbers:
        return None
    return float(numbers[-1])


def _record_extract_state(
    case: dict,
    record: dict,
    *,
    use_landmark: bool,
    landmark_time=None,
) -> dict:
    if use_landmark:
        state = dict(patient_landmark(case, landmark_time))
        state["no_mask"] = False
    else:
        time_record = extract_patient_time_record(case)
        state = {
            "last_time": None,
            "slots": time_record.get("_slots") or {},
            "record": time_record,
            "no_mask": True,
        }
    state["current_follow_up"] = record.get("follow_up")
    state["derived_values"] = dict(record.get("derived_values") or _empty_derived())
    return state


def build_follow_up_records(
    case: dict,
    *,
    landmark=True,
    landmark_time=None,
) -> list[dict]:
    """Build ordered follow-up records and derived values for one patient."""
    use_landmark = landmark not in (False, None)
    if use_landmark:
        landmark_state = patient_landmark(case, landmark_time)
    else:
        time_record = extract_patient_time_record(case)
        landmark_state = {
            "last_time": None,
            "slots": time_record.get("_slots") or {},
            "record": time_record,
            "no_mask": True,
        }

    slots = landmark_state.get("slots") or {}
    dated = []
    undated = []
    for follow_up in _follow_up_objects(case):
        slot = _slot_for_follow_up(slots, follow_up)
        if use_landmark:
            if slot is None or not slot_passes_landmark(slot, landmark_state):
                continue
            days = slot.get("record_days")
        else:
            days = slot.get("record_days") if slot is not None else _to_float(follow_up.get("days_to_follow_up"))
        item = {
            "follow_up": follow_up,
            "record_days": days,
            "derived_values": _empty_derived(),
        }
        if days is None:
            undated.append(item)
        else:
            dated.append(item)

    dated.sort(key=lambda item: (float(item["record_days"]),))
    for idx, item in enumerate(dated):
        if idx == 0:
            continue
        prev = dated[idx - 1]
        item["derived_values"][DAYS_SINCE_FIELD] = float(item["record_days"]) - float(prev["record_days"])
        extract_state = dict(landmark_state)
        for change_field, source_field in SOURCE_FIELDS.items():
            current_value = _numeric_source_value(case, item["follow_up"], source_field, extract_state)
            previous_value = _numeric_source_value(case, prev["follow_up"], source_field, extract_state)
            if current_value is None or previous_value is None:
                continue
            item["derived_values"][change_field] = current_value - previous_value

    records = dated + undated
    if not records:
        records = [
            {
                "follow_up": None,
                "record_days": None,
                "derived_values": _empty_derived(),
            }
        ]
    for idx, item in enumerate(records):
        item["index"] = idx
    return records


def extract_derived_raw_values(field_path: str, landmark=True) -> list:
    if not is_derived_field(field_path):
        return []
    if not isinstance(landmark, dict):
        return []
    value = (landmark.get("derived_values") or {}).get(field_path)
    if value is None or value == "":
        return []
    if classify_raw_value(value) != "valid":
        return []
    return [value]


def missing_prompt_row(cfg: dict) -> dict:
    row = {"patient_id": ""}
    mask = {}
    for out_col, field_path in zip(cfg["output_cols"], cfg["fields"]):
        row[out_col] = _fill_template(cfg["templates"][field_path], "not reported")
        mask[out_col] = False
    row["_mask"] = mask
    return row


def generate_record_prompt_row(
    case: dict,
    cfg: dict,
    record: dict,
    *,
    use_landmark: bool,
    landmark_time=None,
) -> dict:
    state = _record_extract_state(
        case, record, use_landmark=use_landmark, landmark_time=landmark_time
    )
    row = generate_field_bank_prompt_row(case, cfg, landmark=state)
    row["record_idx"] = record.get("index", 0)
    row["record_days"] = record.get("record_days")
    return row


def collect_record_field_values(
    case: dict,
    cfg: dict,
    record: dict,
    *,
    use_landmark: bool,
    landmark_time=None,
) -> dict[str, list[str]]:
    from .onehot import extract_converted_tokens

    state = _record_extract_state(
        case, record, use_landmark=use_landmark, landmark_time=landmark_time
    )
    converts = cfg.get("converts") or {}
    values = {}
    for field in cfg["fields"]:
        values[field] = extract_converted_tokens(
            case, field, converts.get(field, ""), landmark=state
        )
    return values


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _pad_record_rows(rows: list[dict], cfg: dict, max_records: int) -> list[dict]:
    padded = list(rows)
    filler = missing_prompt_row(cfg)
    while len(padded) < max_records:
        extra = dict(filler)
        extra["patient_id"] = rows[0]["patient_id"] if rows else ""
        extra["record_idx"] = len(padded)
        extra["record_days"] = None
        padded.append(extra)
    return padded[:max_records]


def _field_major_sentences(record_rows: list[dict], cfg: dict) -> list[str]:
    sentences = []
    for field_col in cfg["output_cols"]:
        for row in record_rows:
            sentences.append(row[field_col])
    return sentences


def _field_major_mask(record_rows: list[dict], cfg: dict) -> list[bool]:
    mask = []
    for field_col in cfg["output_cols"]:
        for row in record_rows:
            mask.append(bool((row.get("_mask") or {}).get(field_col)))
    return mask


def run_longitudinal_dataset(
    *,
    dataset_name: str,
    cfg: dict,
    cases: list[dict],
    args,
    encoding: str,
    use_landmark: bool,
    landmark_time,
    tag: str,
) -> dict:
    cfg = add_derived_fields_to_cfg(cfg)
    encoding = validate_encoding(encoding)
    out_dir = dataset_field_bank_dir(
        dataset_name, encoding, tag, experiment=LONGITUDINAL_EXPERIMENT
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    patient_records = []
    for case in cases:
        patient_id = str(case.get("submitter_id") or "").strip()
        if not patient_id:
            continue
        records = build_follow_up_records(
            case, landmark=use_landmark, landmark_time=landmark_time
        )
        patient_records.append({"case": case, "patient_id": patient_id, "records": records})

    max_records = max((len(item["records"]) for item in patient_records), default=1)
    max_records = max(int(max_records), 1)

    if encoding == "onehot":
        return _encode_longitudinal_onehot(
            dataset_name=dataset_name,
            cfg=cfg,
            patient_records=patient_records,
            out_dir=out_dir,
            args=args,
            use_landmark=use_landmark,
            landmark_time=landmark_time,
            max_records=max_records,
        )
    return _encode_longitudinal_prompt(
        dataset_name=dataset_name,
        cfg=cfg,
        patient_records=patient_records,
        out_dir=out_dir,
        args=args,
        use_landmark=use_landmark,
        landmark_time=landmark_time,
        max_records=max_records,
    )


def _encode_longitudinal_prompt(
    *,
    dataset_name: str,
    cfg: dict,
    patient_records: list[dict],
    out_dir: Path,
    args,
    use_landmark: bool,
    landmark_time,
    max_records: int,
) -> dict:
    prompt_rows = []
    encoded_rows = []
    for item in patient_records:
        case = item["case"]
        rec_rows = [
            generate_record_prompt_row(
                case,
                cfg,
                record,
                use_landmark=use_landmark,
                landmark_time=landmark_time,
            )
            for record in item["records"]
        ]
        for row in rec_rows:
            payload = {
                "patient_id": item["patient_id"],
                "record_idx": row.get("record_idx", 0),
                "record_days": row.get("record_days"),
            }
            payload.update({col: row[col] for col in cfg["output_cols"]})
            prompt_rows.append(payload)
        encoded_rows.append(
            {
                "patient_id": item["patient_id"],
                "rows": _pad_record_rows(rec_rows, cfg, max_records),
            }
        )

    prompt_path = out_dir / "prompts.csv"
    pd.DataFrame(prompt_rows).to_csv(prompt_path, index=False)
    print(f"✅ longitudinal prompts.csv: {prompt_path}  ({len(prompt_rows)} 行, max_records={max_records})")
    if getattr(args, "prompts_only", False):
        _write_json(
            out_dir / "field_index.json",
            {
                "dataset": dataset_name,
                "encoding": "prompt",
                "experiment": LONGITUDINAL_EXPERIMENT,
                "fields": cfg["fields"],
                "n_fields": len(cfg["fields"]),
                "n_records": max_records,
                "tokens_per_field": max_records,
                "layout": "field_major_records",
                "n_patients": len(encoded_rows),
                "landmark_policy": landmark_policy(use_landmark),
                "landmark_time": landmark_time if use_landmark else None,
                "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        return {"out_dir": out_dir, "n_patients": len(encoded_rows), "max_records": max_records}

    os.environ["CUDA_VISIBLE_DEVICES"] = DEFAULT_GPU
    torch, create_model_from_pretrained, get_tokenizer = _lazy_import_conch()
    from tqdm import tqdm

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, _ = create_model_from_pretrained(model_cfg="conch_ViT-B-16", checkpoint_path=args.ckpt)
    model = model.to(device).eval()
    tokenizer = get_tokenizer()

    patient_ids = [item["patient_id"] for item in encoded_rows]
    patient_sentences = [_field_major_sentences(item["rows"], cfg) for item in encoded_rows]
    flat_prompts = [sentence for sentences in patient_sentences for sentence in sentences]
    encoded = tokenizer(flat_prompts, padding=True, truncation=True, return_tensors="pt")
    all_tokens = encoded["input_ids"]
    all_embeddings = []
    with torch.inference_mode():
        for i in tqdm(range(0, len(flat_prompts), args.batch_size), desc=f"Encoding {dataset_name} longitudinal"):
            tokens = all_tokens[i : i + args.batch_size].to(device)
            feats = model.encode_text(tokens, embed_cls=False)
            feats = feats / feats.norm(dim=-1, keepdim=True)
            all_embeddings.append(feats.cpu().float().numpy())
    n_tokens = len(cfg["fields"]) * max_records
    embeddings = np.concatenate(all_embeddings, axis=0).reshape(len(patient_ids), n_tokens, -1)

    pt_dir = out_dir / "embeddings" / "pt"
    pt_dir.mkdir(parents=True, exist_ok=True)
    for item, emb in zip(encoded_rows, embeddings):
        mask = _field_major_mask(item["rows"], cfg)
        payload = {
            "matrix": torch.from_numpy(emb),
            "mask": torch.tensor(mask, dtype=torch.bool),
            "patient_id": item["patient_id"],
        }
        torch.save(payload, pt_dir / f"{item['patient_id']}.pt")

    index = {
        "dataset": dataset_name,
        "encoding": "prompt",
        "experiment": LONGITUDINAL_EXPERIMENT,
        "fields": cfg["fields"],
        "n_fields": len(cfg["fields"]),
        "n_records": max_records,
        "tokens_per_field": max_records,
        "layout": "field_major_records",
        "embed_dim": int(embeddings.shape[-1]),
        "encoder": "CONCH",
        "ckpt": str(args.ckpt),
        "missing_policy": "placeholder_sentence",
        "landmark_policy": landmark_policy(use_landmark),
        "landmark_time": landmark_time if use_landmark else None,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_patients": len(patient_ids),
    }
    _write_json(out_dir / "field_index.json", index)
    print(f"✅ longitudinal field_index.json: {out_dir / 'field_index.json'}")
    print(f"✅ longitudinal pt dir: {pt_dir}  shape=[{n_tokens}, {index['embed_dim']}]  max_records={max_records}")
    return {"out_dir": out_dir, "n_patients": len(patient_ids), "max_records": max_records}


def _encode_longitudinal_onehot(
    *,
    dataset_name: str,
    cfg: dict,
    patient_records: list[dict],
    out_dir: Path,
    args,
    use_landmark: bool,
    landmark_time,
    max_records: int,
) -> dict:
    torch = __import__("torch")
    fields = list(cfg["fields"])
    fit_patients = []
    encoded_patients = []
    for item in patient_records:
        record_values = []
        for record in item["records"]:
            values = collect_record_field_values(
                item["case"],
                cfg,
                record,
                use_landmark=use_landmark,
                landmark_time=landmark_time,
            )
            record_values.append(values)
            fit_patients.append({"patient_id": item["patient_id"], "values": values})
        encoded_patients.append(
            {"patient_id": item["patient_id"], "record_values": record_values}
        )

    field_types = infer_field_types(fields, fit_patients)
    rare_threshold = int(getattr(args, "rare_freq_threshold", 5))
    normalization_stats = {}
    category_mapping = {}
    field_widths = []
    for spec in field_types:
        field = spec["field"]
        if spec["final_type"] == "continuous":
            normalization_stats[field] = fit_continuous_stats(field, fit_patients)
            field_widths.append(1)
        else:
            mapping = fit_nominal_mapping(field, fit_patients, rare_threshold=rare_threshold)
            category_mapping[field] = mapping
            field_widths.append(len(mapping))
    max_width = int(max(field_widths)) if field_widths else 1
    empty_values = {field: [] for field in fields}

    pt_dir = out_dir / "embeddings" / "pt"
    metadata_dir = out_dir / "metadata"
    pt_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    for item in encoded_patients:
        record_matrices = []
        values_list = list(item["record_values"])
        while len(values_list) < max_records:
            values_list.append(empty_values)
        for values in values_list[:max_records]:
            record_matrices.append(
                encode_patient_matrix(
                    values,
                    field_types,
                    normalization_stats,
                    category_mapping,
                    max_width,
                )
            )
        stacked = np.stack(record_matrices, axis=1)  # [n_fields, n_records, width]
        matrix = stacked.reshape(len(fields) * max_records, max_width)
        torch.save(torch.from_numpy(matrix), pt_dir / f"{item['patient_id']}.pt")

    schema = build_feature_schema(field_types, category_mapping, max_width)
    field_index = {
        "dataset": dataset_name,
        "encoding": "onehot",
        "experiment": LONGITUDINAL_EXPERIMENT,
        "fields": fields,
        "n_fields": len(fields),
        "n_records": max_records,
        "tokens_per_field": max_records,
        "layout": "field_major_records",
        "feat_dim": max_width,
        "n_patients": len(encoded_patients),
        "rare_freq_threshold": rare_threshold,
        "landmark_policy": landmark_policy(use_landmark),
        "landmark_time": landmark_time if use_landmark else None,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _write_json(metadata_dir / "field_types.json", field_types)
    _write_json(metadata_dir / "normalization_stats.json", normalization_stats)
    _write_json(metadata_dir / "category_mapping.json", category_mapping)
    _write_json(metadata_dir / "feature_schema.json", schema)
    _write_json(out_dir / "field_index.json", field_index)
    print(
        f"✅ longitudinal onehot embeddings: {pt_dir}  "
        f"({len(encoded_patients)} 个 .pt, shape=[{len(fields) * max_records}, {max_width}], max_records={max_records})"
    )
    return {
        "out_dir": out_dir,
        "n_fields": len(fields),
        "max_width": max_width,
        "n_patients": len(encoded_patients),
        "max_records": max_records,
    }


def run_longitudinal_field_bank(args):
    from common.clinical_io import load_clinical_cases
    from common.datasets import get_dataset_clinic_files, get_dataset_project_ids, load_dataset_configs, resolve_dataset_names
    from common.paths import DEFAULT_DATASETS_CONFIG, dataset_kept_fields_path, dataset_stats_dir

    encoding = validate_encoding(getattr(args, "encoding", "prompt"))
    if encoding == "onehot" and getattr(args, "prompts_only", False):
        raise ValueError("--prompts_only is only valid with --encoding prompt")
    datasets = load_dataset_configs(getattr(args, "datasets_config", DEFAULT_DATASETS_CONFIG))
    names = resolve_dataset_names(args.dataset, datasets)
    if not names:
        raise ValueError("longitudinal Field Bank 需要 --dataset，例如 --dataset TCGA-READ 或 --dataset all")

    from .landmark import iter_landmark_args

    for name in names:
        for landmark_args in iter_landmark_args(
            args,
            scan_roots=dataset_stats_dir(name),
            context=f"longitudinal field bank {name}",
        ):
            use_landmark, landmark_time = parse_landmark_options(landmark_args)
            tag = landmark_tag_from_args(landmark_args)
            landmark_args.landmark_tag = tag
            landmark_args.experiment = LONGITUDINAL_EXPERIMENT
            print(f"\n######## Dataset: {name}  longitudinal {tag} ########")
            kept = load_kept_fields(
                dataset_name=name,
                path=Path(args.kept_fields) if getattr(args, "kept_fields", None) else None,
                landmark_tag=tag,
            )
            if name not in kept:
                raise ValueError(
                    f"{name} 不在 {getattr(args, 'kept_fields', None) or dataset_kept_fields_path(name, tag)} 中。请先跑 run_field_filter.py"
                )
            cfg = load_field_bank_template(
                name,
                require_templates=(encoding != "onehot"),
                landmark_tag=tag,
            )
            cases = load_clinical_cases(
                get_dataset_clinic_files(name, datasets),
                project_ids=get_dataset_project_ids(name, datasets),
            )
            run_longitudinal_dataset(
                dataset_name=name,
                cfg=cfg,
                cases=cases,
                args=landmark_args,
                encoding=encoding,
                use_landmark=use_landmark,
                landmark_time=landmark_time,
                tag=tag,
            )
