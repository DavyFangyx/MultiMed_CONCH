"""Patient-level front filter: authoritative patient set = label metadata.

患者级前置过滤(2026-10-09 用户拍板):gt≤0 等已明确不可靠的患者,应在**字段级
预处理(统计/筛选/编码)之前**就从病例集中剔除——而不是等到评估期才被
label ∩ split 静默丢弃。

权威患者集 = Clinic_Analyzer 的 label metadata(评估实际使用 label ∩ split;
label 已不含 gt≤0 患者,D7 口径)。字段链的病例加载一律收敛到本患者集:
stats / filter / field bank(含 raw 变体)/ baseline / hgcn 的拟合与编码
都只看见可靠患者;审计阶段(time_stats / leak audit / presence / scan)
不经过本过滤——保持原始口径;event_stats 另出 n_event_label 列
(label 患者集有效事件)供数据集分档协议分档。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]

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
    "CPTAC": "cptac",
    "MMRF": "mmrf",
}

DEFAULT_ANALYZER_LABEL_ROOT = PROJECT_ROOT / "Clinic_Analyzer" / "data" / "datasets_csv" / "metadata"


def display_to_study(dataset: str) -> str:
    if dataset in STUDY_BY_DISPLAY:
        return STUDY_BY_DISPLAY[dataset]
    return str(dataset).strip().lower().replace("-", "_")


def label_metadata_path(study: str, *, analyzer_dir: Path | str | None = None) -> Path:
    """metadata CSV 路径;analyzer_dir = Clinic_Analyzer 根目录(默认本仓库的)。"""
    if analyzer_dir is None:
        return DEFAULT_ANALYZER_LABEL_ROOT / f"{study}.csv"
    return Path(analyzer_dir) / "data" / "datasets_csv" / "metadata" / f"{study}.csv"


def label_patient_ids(dataset: str, *, analyzer_dir: Path | str | None = None) -> set[str]:
    path = label_metadata_path(display_to_study(dataset), analyzer_dir=analyzer_dir)
    if not path.exists():
        raise FileNotFoundError(f"label metadata 不存在: {path}(患者级前置过滤需要)")
    df = pd.read_csv(path)
    if "case_id" not in df.columns:
        raise ValueError(f"{path} has no case_id column")
    return {str(x) for x in df["case_id"].tolist()}


def label_event_count(dataset: str, *, analyzer_dir: Path | str | None = None) -> dict:
    """label 患者集的 (n_patients, n_event, n_censored)。

    数据集分档协议主集门槛(2026-10-09 用户拍板)的计数口径 = label 患者集有效事件
    (censorship==0,SurvPGC 约定 1=删失):患者在字段级预处理之前即已收敛到
    label 患者集,门槛须与之同口径(raw n_event 含 gt≤0 等从不进训练的病例)。
    """
    path = label_metadata_path(display_to_study(dataset), analyzer_dir=analyzer_dir)
    if not path.exists():
        raise FileNotFoundError(f"label metadata 不存在: {path}")
    df = pd.read_csv(path)
    censor_cols = [c for c in df.columns if c.lower() == "censorship"]
    if not censor_cols:
        raise ValueError(f"{path} has no censorship column")
    series = pd.to_numeric(df[censor_cols[0]], errors="coerce")
    n_event = int((series == 0).sum())
    n_censored = int((series == 1).sum())
    return {
        "n_patients": len(df),
        "n_event": n_event,
        "n_censored": n_censored,
    }


def tcga_label_event_table() -> dict[str, int]:
    """显示名 -> label 患者集有效事件(仅 TCGA,下划线变体优先,字典序可迭代)。"""
    display_by_study: dict[str, str] = {}
    for display in sorted(STUDY_BY_DISPLAY):
        study = STUDY_BY_DISPLAY[display]
        if study in display_by_study and "_" not in display_by_study[study]:
            display_by_study[study] = display
        elif study not in display_by_study:
            display_by_study[study] = display
    table: dict[str, int] = {}
    for study, display in sorted(display_by_study.items()):
        if not display.upper().startswith("TCGA"):
            continue
        try:
            table[display] = label_event_count(display)["n_event"]
        except FileNotFoundError:
            continue
    return table


def main_datasets_by_label_events(threshold: int = 100) -> list[str]:
    """数据集分档协议主集(2026-10-09 用户拍板):TCGA 中 label 患者集有效事件 >= threshold。

    主集 = 14 个(2026-10-12 label 全表口径重建后 KIRC 175 回归;COAD 95 仍出主集)。
    """
    names = sorted(name for name, value in tcga_label_event_table().items() if value >= threshold)
    if not names:
        raise RuntimeError(f"主集为空(label 患者集有效事件 >= {threshold})")
    return names


def restrict_cases_to_label_patients(
    cases: list[dict],
    dataset: str,
    *,
    analyzer_dir: Path | str | None = None,
    quiet: bool = False,
) -> tuple[list[dict], dict]:
    """按 label 患者集过滤病例;返回 (kept, stats)。患者级前置口径(2026-10-09)。"""
    patients = label_patient_ids(dataset, analyzer_dir=analyzer_dir)
    kept: list[dict] = []
    dropped: list[str] = []
    for case in cases:
        pid = str(case.get("submitter_id", "")).strip()
        if pid in patients:
            kept.append(case)
        else:
            dropped.append(pid)
    stats = {
        "dataset": dataset,
        "n_cases_loaded": len(cases),
        "n_label_patients": len(patients),
        "n_kept": len(kept),
        "n_dropped": len(dropped),
        "dropped_ids": sorted(dropped),
    }
    if not quiet:
        print(
            f"  [patient filter] {dataset}: {len(cases)} 病例 → {len(kept)} 保留 / "
            f"{len(dropped)} 剔除(label 患者集 = {len(patients)})"
        )
    return kept, stats
