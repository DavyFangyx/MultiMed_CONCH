"""Ridge linear probe for CONCH prompt embeddings vs continuous Field Bank values."""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from sklearn.preprocessing import StandardScaler

from common.clinical_io import load_clinical_cases
from common.datasets import (
    get_dataset_clinic_files,
    get_dataset_project_ids,
    load_dataset_configs,
    resolve_dataset_names,
)
from common.paths import (
    DEFAULT_DATASETS_CONFIG,
    dataset_field_bank_dir,
    dataset_linear_probe_dir,
    landmark_tag_from_args,
    validate_encoding,
)
from greedy.data import load_field_bank
from greedy.embeddings import _as_matrix

from .field_bank import load_field_bank_template
from .landmark import add_landmark_cli_args, iter_landmark_args, parse_landmark_options
from .onehot import aggregate_continuous, collect_patient_field_values, extract_converted_tokens, gdc_lookup_key, parse_gdc_types


CSV_COLUMNS = [
    "field",
    "field_idx",
    "n_valid",
    "r2",
    "status",
    "error",
]
PREDICTION_COLUMNS = [
    "field",
    "field_idx",
    "patient_id",
    "y_true",
    "y_pred",
]


def _json_dump(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=_json_default)
        f.write("\n")


def _json_default(obj):
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"not json serializable: {type(obj)}")


def _short_error(exc: BaseException, limit: int = 240) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _is_finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def require_prompt_encoding(encoding: str) -> str:
    value = str(encoding or "").strip().lower()
    if value == "onehot":
        raise ValueError(
            "numeric linear probe only accepts --encoding prompt; "
            "onehot continuous columns are already numeric"
        )
    if value != "prompt":
        raise ValueError(f"unsupported encoding {encoding!r}; expected prompt")
    return validate_encoding(value)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ridge linear probe: recover continuous Field Bank values from CONCH prompt embeddings."
    )
    parser.add_argument("--dataset", required=True, help="数据集名；支持 all 或逗号分隔列表")
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument("--encoding", default="prompt")
    parser.add_argument("--field_bank_dir", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--min_valid", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    add_landmark_cli_args(parser, extraction=True)
    return parser


def resolve_probe_landmark(args, field_index: dict | None = None) -> tuple[bool, float | None, str]:
    use_landmark, landmark_time = parse_landmark_options(args)
    return use_landmark, landmark_time, ("t_hi_le_landmark_time" if use_landmark else "off")


def _require_field_bank(field_bank_dir: Path, encoding: str) -> dict:
    if not field_bank_dir.exists():
        raise FileNotFoundError(f"field bank not found: {field_bank_dir}")
    loaded = load_field_bank(field_bank_dir, encoding=encoding)
    index_path = loaded["dir"] / "field_index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"field_index.json not found: {index_path}")
    pt_dir = loaded["pt_dir"]
    pt_files = list(pt_dir.glob("*.pt")) if pt_dir.is_dir() else []
    if not pt_files:
        raise FileNotFoundError(f"no Field Bank .pt files under {pt_dir}")
    return loaded


def _load_patient_row(path: Path, field_idx: int, tokens_per_field: int = 1) -> np.ndarray:
    import torch

    matrix = _as_matrix(torch.load(path, map_location="cpu"))
    n_rows = int(matrix.shape[0])
    width = max(int(tokens_per_field), 1)
    start = int(field_idx) * width
    stop = start + width
    if start < 0 or stop > n_rows:
        raise IndexError(
            f"field_idx {field_idx} out of range for {path} with {n_rows} rows and tokens_per_field={width}"
        )
    row = matrix[start:stop].reshape(-1).detach().cpu().numpy().astype(np.float64, copy=False)
    if row.ndim != 1:
        raise ValueError(f"expected 1-d field embedding, got {row.shape} from {path}")
    return row


def _patient_last_time_landmark(case: dict) -> dict:
    from time_stats import extract_patient_time_record

    record = extract_patient_time_record(case)
    return {
        "last_time": record.get("ground_truth_time"),
        "slots": record.get("_slots") or {},
        "record": record,
    }


def _merge_derived_tokens(
    cases: list[dict],
    fields: list[str],
    converts: dict[str, str],
    patients: list[dict],
    *,
    landmark=True,
    landmark_time=None,
) -> list[dict]:
    from .longitudinal import DERIVED_FIELDS, build_follow_up_records, collect_record_field_values

    needed = [field for field in fields if field in DERIVED_FIELDS]
    if not needed:
        return patients
    by_id = {item["patient_id"]: item for item in patients}
    cfg = {"fields": needed, "converts": converts}
    use_landmark = bool(landmark)
    for case in cases:
        patient_id = str(case.get("submitter_id") or "").strip()
        if not patient_id or patient_id not in by_id:
            continue
        values = dict(by_id[patient_id].get("values") or {})
        for record in build_follow_up_records(case, landmark=use_landmark, landmark_time=landmark_time):
            record_values = collect_record_field_values(
                case,
                cfg,
                record,
                use_landmark=use_landmark,
                landmark_time=landmark_time,
            )
            for field in needed:
                values.setdefault(field, [])
                values[field].extend(record_values.get(field) or [])
        by_id[patient_id]["values"] = values
    return patients


def collect_patient_values(
    cases: list[dict],
    fields: list[str],
    converts: dict[str, str] | None = None,
    landmark=True,
    landmark_time=None,
    landmark_policy: str = "t_hi_le_landmark_time",
) -> list[dict]:
    converts = converts or {}
    if not landmark or landmark_policy == "off":
        patients = collect_patient_field_values(cases, fields, converts, landmark=False)
        return _merge_derived_tokens(
            cases, fields, converts, patients, landmark=False, landmark_time=None
        )
    if landmark_policy != "t_record_le_last_time":
        patients = collect_patient_field_values(
            cases, fields, converts, landmark=True, landmark_time=landmark_time
        )
        return _merge_derived_tokens(
            cases, fields, converts, patients, landmark=True, landmark_time=landmark_time
        )

    patients = []
    for case in cases:
        patient_id = str(case.get("submitter_id") or "").strip()
        if not patient_id:
            continue
        landmark_state = _patient_last_time_landmark(case)
        values = {
            field: extract_converted_tokens(
                case, field, converts.get(field, ""), landmark=landmark_state
            )
            for field in fields
        }
        patients.append({"patient_id": patient_id, "values": values})
    return _merge_derived_tokens(
        cases, fields, converts, patients, landmark=True, landmark_time=None
    )


NUMERIC_GDC_TYPES = {"number", "integer"}


def is_numeric_gdc_type(gdc_type: str) -> bool:
    tokens = parse_gdc_types(gdc_type)
    return bool(tokens) and all(token in NUMERIC_GDC_TYPES for token in tokens)


def collect_continuous_targets(
    cases: list[dict],
    fields: list[str],
    converts: dict[str, str] | None = None,
    landmark=True,
    landmark_time=None,
    landmark_policy: str = "t_hi_le_landmark_time",
    dictionary: dict[tuple[str, str], str] | None = None,
) -> tuple[list[dict], dict[str, dict[str, float]]]:
    if dictionary is None:
        from .onehot import _load_gdc_dictionary

        dictionary = _load_gdc_dictionary()
    patients = collect_patient_values(
        cases,
        fields,
        converts,
        landmark=landmark,
        landmark_time=landmark_time,
        landmark_policy=landmark_policy,
    )
    field_types = []
    targets: dict[str, dict[str, float]] = {}
    for field in fields:
        entity, leaf = gdc_lookup_key(field)
        gdc_type = dictionary.get((entity, leaf), "")
        numeric = is_numeric_gdc_type(gdc_type)
        spec = {
            "field": field,
            "gdc_entity": entity,
            "gdc_type": gdc_type,
            "final_type": "continuous" if numeric else "nominal",
            "source": "gdc_dictionary",
        }
        field_types.append(spec)
        if not numeric:
            continue
        values = {}
        for patient in patients:
            value = aggregate_continuous(patient["values"].get(field, []), field)
            if value is None or not _is_finite(value):
                continue
            values[patient["patient_id"]] = float(value)
        if values:
            targets[field] = values
    return field_types, targets


def _empty_metrics_row(field: str, field_idx: int, n_valid: int, status: str, error: str = "") -> dict:
    return {
        "field": field,
        "field_idx": int(field_idx),
        "n_valid": int(n_valid),
        "r2": "",
        "status": status,
        "error": error,
    }


def probe_one_field(
    field: str,
    field_idx: int,
    y_by_patient: dict[str, float],
    pt_dir: Path,
    *,
    alpha: float = 1.0,
    min_valid: int = 10,
    tokens_per_field: int = 1,
) -> tuple[dict, list[dict]]:
    valid_ids = [pid for pid, value in y_by_patient.items() if _is_finite(value)]
    n_valid = len(valid_ids)
    if n_valid < int(min_valid):
        return _empty_metrics_row(field, field_idx, n_valid, "skipped"), []

    features = {}
    try:
        for pid in valid_ids:
            path = pt_dir / f"{pid}.pt"
            if not path.exists():
                continue
            features[pid] = _load_patient_row(path, field_idx, tokens_per_field=tokens_per_field)
    except Exception as exc:
        return _empty_metrics_row(field, field_idx, n_valid, "error", _short_error(exc)), []

    usable = [pid for pid in valid_ids if pid in features]
    n_valid = len(usable)
    if n_valid < int(min_valid):
        return _empty_metrics_row(field, field_idx, n_valid, "skipped"), []

    x = np.stack([features[pid] for pid in usable], axis=0)
    y = np.asarray([y_by_patient[pid] for pid in usable], dtype=np.float64)
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x)
    try:
        model = Ridge(alpha=float(alpha), fit_intercept=True)
        model.fit(x_scaled, y)
        y_hat = model.predict(x_scaled)
        score = float(r2_score(y, y_hat))
    except Exception as exc:
        return _empty_metrics_row(field, field_idx, n_valid, "error", _short_error(exc)), []

    predictions = [
        {
            "field": field,
            "field_idx": int(field_idx),
            "patient_id": pid,
            "y_true": float(y_true),
            "y_pred": float(y_pred),
        }
        for pid, y_true, y_pred in zip(usable, y, y_hat)
    ]
    return (
        {
            "field": field,
            "field_idx": int(field_idx),
            "n_valid": int(n_valid),
            "r2": score,
            "status": "ok",
            "error": "",
        },
        predictions,
    )


def sort_metric_rows(rows: list[dict]) -> list[dict]:
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    other_rows = [row for row in rows if row.get("status") != "ok"]
    ok_rows.sort(key=lambda row: (-float(row["r2"]), int(row["field_idx"])))
    other_rows.sort(key=lambda row: int(row["field_idx"]))
    return ok_rows + other_rows


def write_numeric_r2_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            payload = {}
            for key in CSV_COLUMNS:
                value = row.get(key, "")
                payload[key] = "" if value is None else value
            writer.writerow(payload)


def write_predictions_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PREDICTION_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in PREDICTION_COLUMNS})


def write_outputs(
    out_dir: Path,
    metric_rows: list[dict],
    prediction_rows: list[dict],
    *,
    dataset: str,
    encoding: str,
    alpha: float,
    min_valid: int,
    seed: int,
    landmark: bool,
    landmark_time,
    landmark_policy: str,
    field_bank_dir: Path | str,
    extra: dict | None = None,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_numeric_r2_csv(out_dir / "numeric_r2.csv", metric_rows)
    write_predictions_csv(out_dir / "predictions.csv", prediction_rows)
    config = {
        "dataset": dataset,
        "encoding": encoding,
        "alpha": float(alpha),
        "min_valid": int(min_valid),
        "n_continuous_fields": len(metric_rows),
        "n_ok": sum(1 for row in metric_rows if row.get("status") == "ok"),
        "n_skipped": sum(1 for row in metric_rows if row.get("status") == "skipped"),
        "n_error": sum(1 for row in metric_rows if row.get("status") == "error"),
        "landmark": bool(landmark),
        "landmark_time": landmark_time,
        "landmark_policy": landmark_policy,
        "target": "onehot_aggregate_continuous_unscaled",
        "model": "ridge",
        "fit": "all_patients",
        "standardize_x": True,
        "seed": int(seed),
        "field_bank_dir": str(field_bank_dir),
        "out_dir": str(out_dir),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if extra:
        config.update(extra)
    _json_dump(out_dir / "run_config.json", config)
    return config


def run_one(
    args,
    dataset: str,
    *,
    cases: list[dict] | None = None,
    dictionary: dict[tuple[str, str], str] | None = None,
    converts: dict[str, str] | None = None,
    field_types: list[dict] | None = None,
    targets: dict[str, dict[str, float]] | None = None,
) -> Path:
    encoding = require_prompt_encoding(getattr(args, "encoding", "prompt"))
    args.encoding = encoding
    tag = landmark_tag_from_args(args)
    args.landmark_tag = tag
    if args.out:
        out_dir = Path(args.out)
        if getattr(args, "_multi_dataset", False):
            out_dir = out_dir / dataset / tag
    else:
        out_dir = dataset_linear_probe_dir(dataset, encoding, tag)
    out_dir.mkdir(parents=True, exist_ok=True)

    field_bank_dir = Path(args.field_bank_dir) if args.field_bank_dir else dataset_field_bank_dir(dataset, encoding, tag)
    loaded = _require_field_bank(field_bank_dir, encoding)
    fields = list(loaded["fields"])
    if not fields:
        raise ValueError(f"field_index has no fields: {loaded['dir'] / 'field_index.json'}")

    use_landmark, landmark_time, landmark_policy = resolve_probe_landmark(args, loaded.get("index") or {})

    if field_types is None or targets is None:
        if converts is None:
            if cases is None:
                cfg = load_field_bank_template(dataset, require_templates=False, landmark_tag=tag)
                converts = cfg.get("converts") or {}
            else:
                converts = {}
        if cases is None:
            datasets = load_dataset_configs(args.datasets_config)
            cases = load_clinical_cases(
                get_dataset_clinic_files(dataset, datasets),
                project_ids=get_dataset_project_ids(dataset, datasets),
            )
        field_types, targets = collect_continuous_targets(
            cases,
            fields,
            converts,
            landmark=use_landmark,
            landmark_time=landmark_time,
            landmark_policy=landmark_policy,
            dictionary=dictionary,
        )

    metric_rows = []
    prediction_rows = []
    type_by_field = {spec["field"]: spec for spec in field_types}
    for field_idx, field in enumerate(fields):
        spec = type_by_field.get(field)
        if not spec or spec.get("final_type") != "continuous":
            continue
        y_by_patient = targets.get(field) or {}
        if not y_by_patient:
            continue
        row, preds = probe_one_field(
            field,
            field_idx,
            y_by_patient,
            loaded["pt_dir"],
            alpha=args.alpha,
            min_valid=args.min_valid,
            tokens_per_field=int((loaded.get("index") or {}).get("tokens_per_field") or 1),
        )
        metric_rows.append(row)
        if row.get("status") == "ok":
            prediction_rows.extend(preds)

    metric_rows = sort_metric_rows(metric_rows)
    config = write_outputs(
        out_dir,
        metric_rows,
        prediction_rows,
        dataset=dataset,
        encoding=encoding,
        alpha=args.alpha,
        min_valid=args.min_valid,
        seed=args.seed,
        landmark=use_landmark,
        landmark_time=landmark_time,
        landmark_policy=landmark_policy,
        field_bank_dir=loaded["dir"],
        extra={
            "n_patients": len(list(loaded["pt_dir"].glob("*.pt"))),
            "landmark_tag": tag,
        },
    )
    print()
    print(f"######## Dataset: {dataset}  numeric linear probe {encoding} ########")
    print(
        f"  continuous={config['n_continuous_fields']} ok={config['n_ok']} "
        f"skipped={config['n_skipped']} error={config['n_error']}"
    )
    print(f"  wrote {out_dir / 'numeric_r2.csv'}")
    print(f"  wrote {out_dir / 'predictions.csv'}")
    print(f"  wrote {out_dir / 'run_config.json'}")
    return out_dir


def main(argv=None):
    parser = make_parser()
    args = parser.parse_args(argv)
    args.encoding = require_prompt_encoding(args.encoding)
    datasets = load_dataset_configs(args.datasets_config)
    names = resolve_dataset_names(args.dataset, datasets)
    if not names:
        names = [args.dataset]
    landmark_jobs = []
    for name in names:
        for landmark_args in iter_landmark_args(
            args,
            scan_roots=dataset_field_bank_dir(name, args.encoding, "landmark_none").parent,
            context=f"linear probe {name}",
        ):
            landmark_jobs.append((name, landmark_args))
    args._multi_dataset = len(landmark_jobs) > 1
    failures = []
    for name, landmark_args in landmark_jobs:
        landmark_args._multi_dataset = args._multi_dataset
        try:
            run_one(landmark_args, name)
        except Exception as exc:
            tag = getattr(landmark_args, "landmark_tag", landmark_args.landmark_time)
            failures.append((f"{name}/{tag}", _short_error(exc)))
            print(f"[linear_probe] {name} {tag} failed: {failures[-1][1]}")
            if not args._multi_dataset:
                raise
    if failures:
        detail = "; ".join(f"{name}: {err}" for name, err in failures)
        raise SystemExit(f"numeric linear probe failed for {len(failures)} dataset(s): {detail}")


if __name__ == "__main__":
    main()
