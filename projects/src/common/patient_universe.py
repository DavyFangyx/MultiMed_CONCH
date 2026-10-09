"""Patient-level front filter: authoritative patient universe = label metadata.

患者级前置过滤(2026-10-09 用户拍板):gt≤0 等已明确不可靠的患者,应在**字段级
预处理(统计/筛选/编码)之前**就从病例宇宙中剔除——而不是等到评估期才被
label ∩ split 静默丢弃。

权威宇宙 = Clinic_Analyzer 的 label metadata(评估实际使用 label ∩ split;
label 已不含 gt≤0 患者,D7 口径)。字段链的病例加载一律收敛到本宇宙:
stats / filter / field bank(含 raw 变体)/ baseline / hgcn 的拟合与编码
都只看见可靠患者;审计阶段(event_stats / time_stats / leak audit /
presence / scan)保持原始口径,不经过本过滤。
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


def label_universe_ids(dataset: str, *, analyzer_dir: Path | str | None = None) -> set[str]:
    path = label_metadata_path(display_to_study(dataset), analyzer_dir=analyzer_dir)
    if not path.exists():
        raise FileNotFoundError(f"label metadata 不存在: {path}(患者级前置过滤需要)")
    df = pd.read_csv(path)
    if "case_id" not in df.columns:
        raise ValueError(f"{path} has no case_id column")
    return {str(x) for x in df["case_id"].tolist()}


def restrict_cases_to_label_universe(
    cases: list[dict],
    dataset: str,
    *,
    analyzer_dir: Path | str | None = None,
    quiet: bool = False,
) -> tuple[list[dict], dict]:
    """按 label 宇宙过滤病例;返回 (kept, stats)。患者级前置口径(2026-10-09)。"""
    universe = label_universe_ids(dataset, analyzer_dir=analyzer_dir)
    kept: list[dict] = []
    dropped: list[str] = []
    for case in cases:
        pid = str(case.get("submitter_id", "")).strip()
        if pid in universe:
            kept.append(case)
        else:
            dropped.append(pid)
    stats = {
        "dataset": dataset,
        "n_cases_loaded": len(cases),
        "n_label_universe": len(universe),
        "n_kept": len(kept),
        "n_dropped": len(dropped),
        "dropped_ids": sorted(dropped),
    }
    if not quiet:
        print(
            f"  [patient filter] {dataset}: {len(cases)} 病例 → {len(kept)} 保留 / "
            f"{len(dropped)} 剔除(label 宇宙 = {len(universe)})"
        )
    return kept, stats
