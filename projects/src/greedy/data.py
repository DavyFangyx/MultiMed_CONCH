"""Load candidate fields, patient IDs, and event labels for greedy search."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from common.paths import dataset_field_bank_dir, dataset_kept_fields_path


STUDY_BY_DISPLAY = {
    "TCGA-ACC": "tcga_acc",
    "TCGA-BLCA": "tcga_blca",
    "TCGA-BRCA": "tcga_brca",
    "TCGA-CESC": "tcga_cesc",
    "TCGA-CHOL": "tcga_chol",
    "TCGA-COAD": "tcga_coad",
    "TCGA-DLBC": "tcga_dlbc",
    "TCGA-ESCA": "tcga_esca",
    "TCGA-GBM": "tcga_gbm",
    "TCGA-HNSC": "tcga_hnsc",
    "TCGA-KICH": "tcga_kich",
    "TCGA-KIRC": "tcga_kirc",
    "TCGA-KIRP": "tcga_kirp",
    "TCGA-LAML": "tcga_laml",
    "TCGA-LGG": "tcga_lgg",
    "TCGA-LIHC": "tcga_lihc",
    "TCGA_LIHC": "tcga_lihc",
    "TCGA-LUAD": "tcga_luad",
    "TCGA-LUSC": "tcga_lusc",
    "TCGA-MESO": "tcga_meso",
    "TCGA-OV": "tcga_ov",
    "TCGA-PAAD": "tcga_paad",
    "TCGA-PCPG": "tcga_pcpg",
    "TCGA-PRAD": "tcga_prad",
    "TCGA-READ": "tcga_read",
    "TCGA-SARC": "tcga_sarc",
    "TCGA-SKCM": "tcga_skcm",
    "TCGA-STAD": "tcga_stad",
    "TCGA-TGCT": "tcga_tgct",
    "TCGA-THCA": "tcga_thca",
    "TCGA-THYM": "tcga_thym",
    "TCGA-UCEC": "tcga_ucec",
    "TCGA-UCS": "tcga_ucs",
    "TCGA-UVM": "tcga_uvm",
}

DEFAULT_SURVPGC_ROOT = Path("/data/fangyuxuan/projects/medical_dl/SurvPGC_github_init")
DEFAULT_ANALYZER_SPLIT_ROOT = Path(__file__).resolve().parents[2] / "Clinic_Analyzer" / "data" / "splits" / "5foldcv"
DEFAULT_ANALYZER_LABEL_ROOT = Path(__file__).resolve().parents[2] / "Clinic_Analyzer" / "data" / "datasets_csv" / "metadata"


def display_to_study(dataset: str) -> str:
    if dataset in STUDY_BY_DISPLAY:
        return STUDY_BY_DISPLAY[dataset]
    return str(dataset).strip().lower().replace("-", "_")


def default_analyzer_split_dir(dataset: str) -> Path:
    return DEFAULT_ANALYZER_SPLIT_ROOT / display_to_study(dataset)


def load_json(path: Path | str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_candidate_fields(dataset: str, kept_fields_path: Path | str | None = None, field_index_path: Path | str | None = None) -> list[str]:
    if field_index_path:
        payload = load_json(field_index_path)
        fields = payload.get("fields")
        if not fields:
            raise ValueError(f"field_index has no fields: {field_index_path}")
        return list(fields)

    bank_index = dataset_field_bank_dir(dataset) / "field_index.json"
    if bank_index.exists():
        return load_candidate_fields(dataset, field_index_path=bank_index)

    path = Path(kept_fields_path or dataset_kept_fields_path(dataset))
    payload = load_json(path)
    if isinstance(payload, dict) and "fields" in payload:
        return list(payload["fields"])
    if isinstance(payload, dict) and dataset in payload:
        return list(payload[dataset]["fields"])
    raise KeyError(f"{dataset} not in {path}")


def unique_ids(values) -> list[str]:
    seen = set()
    out = []
    for value in values:
        pid = str(value)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    return out


def load_patient_ids_from_field_bank(dataset: str, field_bank_dir: Path | str | None = None) -> list[str]:
    bank = Path(field_bank_dir) if field_bank_dir else dataset_field_bank_dir(dataset)
    prompt_path = bank / "prompts.csv"
    if prompt_path.exists():
        df = pd.read_csv(prompt_path)
        col = "patient_id" if "patient_id" in df.columns else df.columns[0]
        return unique_ids(df[col].tolist())
    pt_dir = bank / "embeddings" / "pt"
    if not pt_dir.is_dir():
        pt_dir = bank / "pt"
    if pt_dir.is_dir():
        return unique_ids(sorted(p.stem for p in pt_dir.glob("*.pt")))
    return []


def load_survival_table(dataset: str, label_file: Path | str | None = None, survpgc_root: Path | str | None = None) -> pd.DataFrame:
    if label_file:
        path = Path(label_file)
    else:
        study = display_to_study(dataset)
        local = DEFAULT_ANALYZER_LABEL_ROOT / f"{study}.csv"
        if local.exists():
            path = local
        else:
            root = Path(survpgc_root or DEFAULT_SURVPGC_ROOT)
            path = root / "datasets_csv" / "metadata" / f"{study}.csv"
    if not path.exists():
        raise FileNotFoundError(f"label file not found: {path}")
    df = pd.read_csv(path)
    if "case_id" not in df.columns:
        raise ValueError(f"{path} has no case_id column")
    return df


def load_events(dataset: str, patient_ids: list[str], label_file: Path | str | None = None) -> dict[str, int]:
    df = load_survival_table(dataset, label_file=label_file)
    if "censorship" not in df.columns:
        return {pid: 0 for pid in patient_ids}
    # SurvPGC: censorship=1 means censored, 0 means event.
    events = {}
    for _, row in df.iterrows():
        pid = str(row["case_id"])
        censored = int(row["censorship"])
        events[pid] = 0 if censored == 1 else 1
    return {pid: int(events.get(pid, 0)) for pid in patient_ids}


def resolve_patient_universe(dataset: str, field_bank_dir: Path | str | None = None, label_file: Path | str | None = None) -> tuple[list[str], dict[str, int]]:
    bank_ids = load_patient_ids_from_field_bank(dataset, field_bank_dir=field_bank_dir)
    try:
        labels = load_survival_table(dataset, label_file=label_file)
        label_ids = unique_ids(labels["case_id"].tolist())
    except FileNotFoundError:
        labels = None
        label_ids = []

    if bank_ids and label_ids:
        keep = unique_ids(pid for pid in bank_ids if pid in set(label_ids))
    elif bank_ids:
        keep = unique_ids(bank_ids)
    else:
        keep = unique_ids(label_ids)
    if not keep:
        raise ValueError(f"no patients found for {dataset}")

    if labels is None:
        events = {pid: 0 for pid in keep}
    else:
        events = load_events(dataset, keep, label_file=label_file)
    return keep, events
