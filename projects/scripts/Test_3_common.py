"""Test_3（字段轴链主体）共享常量、主集读取与两臂路径工具。

口径来源（唯一来源 = `z_notes/Test_series_spec.md`）：
  §7     Test_3 规格（搜索池 / A2_greedy / gain-only 早停（D4 修订 2026-10-04）/ 两臂 B, C / 遗漏字段清单）
  §2.4   方案 × 数据集绑定（泛癌种 4 方案 × 全部 TCGA；HGCN_* 仅本癌种）
  §12 U1 数据集分档协议+ R13 训练范围（label 患者集有效事件 >= 100 的 14 个主集）

纪律：
  * 数据集名单一律从数据读（Test_0 manifest / event_summary.csv），**不硬编码**；
  * 本模块只做只读读取与路径拼接，不写入任何 results/ 目录（除显式 mkdir）。
"""
from __future__ import annotations

import csv
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]

for _p in (ROOT, ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common.paths import test_results_dir

# --- 数据集分档协议/ R13 -----------------------------------------------------------
# 2026-10-09 用户拍板: 主集门槛计数口径 = label 患者集有效事件(患者级前置过滤
# 同口径;raw n_event 含 gt≤0 等从不进训练的病例)。阈值 100 不变,
# 主集 = 14 个(2026-10-12 label 全表口径重建后 KIRC 175 回归;COAD 95 出主集)。
MAIN_N_EVENT_MIN = 100  # 数据集分档协议主集阈值(R13): label 患者集有效事件 >= 100

MANIFEST_CSV = ROOT / "results" / "Test_0_dataset_availability" / "manifest.csv"
EVENT_SUMMARY_CSV = ROOT / "rawdata_stats" / "_shared" / "event_summary.csv"

# --- Test_3 产物路径 --------------------------------------------------------
OUT_ROOT = ROOT / "results" / "Test_3_greedy_vs_works"
SEARCH_ROOT = OUT_ROOT / "search"           # 搜索 run 落盘（evaluations.jsonl / result.json）
SEARCH_CACHE = test_results_dir("Test_3_search") / "cache.sqlite"
COMPARE_ROOT = OUT_ROOT                     # Test_3_compare.py 的两臂 json/csv

ANALYZER = "mlp_clinic_flatten"             # E2 唯一搜索目标模型（spec §7.1）
ALGO = "A2_greedy"
STOP_MODE = "gain_only"                     # D4 修订(2026-10-04):gain-only δ=0.005;原 sig_stop 经 --stop-mode sig 保留
SEED = 0
LANDMARK_TIME = "0"
ENCODING = "prompt"

# --- 方案 × 数据集绑定（spec §2.4） ----------------------------------------
PAN_CANCER_WORKS = ("MULTISURV", "SURVPGC", "MMSURV", "INTEGRATIVE_DNN")
HGCN_BINDING = {
    "TCGA-KIRC": "HGCN_KIRC",
    "TCGA_LIHC": "HGCN_LIHC",
    "TCGA-ESCA": "HGCN_ESCA",
    "TCGA-LUSC": "HGCN_LUSC",
    "TCGA-LUAD": "HGCN_LUAD",
    "TCGA-UCEC": "HGCN_UCEC",
}


def tcga_prefix(name: str) -> bool:
    return name.upper().startswith("TCGA")


def load_n_event(manifest_csv: Path | str = MANIFEST_CSV,
                 event_summary_csv: Path | str = EVENT_SUMMARY_CSV,
                 *, strict: bool = True) -> dict[str, int]:
    """dataset -> label 患者集有效事件(2026-10-09 口径)。

    计数直接读 label metadata(censorship==0 行数),不依赖 raw 统计;
    若 event_summary 已有 n_event_label 列则交叉核对(不一致即报错)。
    """
    from common.patient_set import tcga_label_event_table

    label_events = tcga_label_event_table()

    summary: dict[str, int] = {}
    summary_path = Path(event_summary_csv)
    if summary_path.exists():
        with summary_path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("dataset") or row.get("study") or row.get("name") or "").strip()
                if not name or not tcga_prefix(name):
                    continue
                value = row.get("n_event_label")
                if value in (None, ""):
                    continue
                summary[name] = int(float(value))
    if strict and label_events and summary:
        diff = {name: (label_events[name], summary.get(name)) for name in label_events
                if summary.get(name) is not None and label_events[name] != summary[name]}
        if diff:
            raise ValueError(f"n_event_label 与 label metadata 不一致: {diff}")
    if not label_events:
        raise SystemExit("[test_3] 读不到 label 患者集有效事件(Clinic_Analyzer/data/datasets_csv/metadata)")
    return label_events


def main_datasets(n_event: dict[str, int] | None = None, *, threshold: int = MAIN_N_EVENT_MIN) -> list[str]:
    """数据集分档协议主集：TCGA 中 label 患者集有效事件 >= threshold，字典序（不硬编码名单）。"""
    from common.patient_set import main_datasets_by_label_events

    if n_event is not None:
        names = sorted(name for name, value in n_event.items() if tcga_prefix(name) and value >= threshold)
        if not names:
            raise SystemExit(f"[test_3] 主集为空（label 患者集有效事件 >= {threshold}）")
        return names
    return main_datasets_by_label_events(threshold=threshold)


def work_pairs(datasets: list[str]) -> list[tuple[str, str]]:
    """spec §2.4：泛癌种 4 方案 × 全部数据集 + HGCN_* 仅本癌种。"""
    pairs: list[tuple[str, str]] = []
    for dataset in datasets:
        for work in PAN_CANCER_WORKS:
            pairs.append((dataset, work))
        bound = HGCN_BINDING.get(dataset)
        if bound:
            pairs.append((dataset, bound))
    return pairs


def search_dir(dataset: str) -> Path:
    """runner --out 落点；runner 内部再追加 /{modality}/seed_{seed}/。"""
    return SEARCH_ROOT / dataset


def search_seed_dir(dataset: str, *, analyzer: str = ANALYZER, seed: int = SEED) -> Path:
    return search_dir(dataset) / analyzer / f"seed_{seed}"


def search_result_json(dataset: str, *, analyzer: str = ANALYZER, seed: int = SEED) -> Path:
    return search_seed_dir(dataset, analyzer=analyzer, seed=seed) / "result.json"


def search_evaluations_jsonl(dataset: str, *, analyzer: str = ANALYZER, seed: int = SEED) -> Path:
    return search_seed_dir(dataset, analyzer=analyzer, seed=seed) / "evaluations.jsonl"


def b_scheme_name(work: str, dataset: str) -> str:
    return f"Test_3_{work}_{dataset}"


def c_scheme_name(dataset: str, *, kind: str = "ksig") -> str:
    return f"Test_3_greedy_{dataset}" if kind == "ksig" else f"Test_3_greedybest_{dataset}"


if __name__ == "__main__":  # 自检：python3 scripts/Test_3_common.py
    table = load_n_event()
    main = main_datasets(table)
    print(f"[test_3] n_event 表 {len(table)} 个 TCGA；主集 {len(main)} 个（阈值 {MAIN_N_EVENT_MIN}）:")
    print("         " + ", ".join(f"{name}({table[name]})" for name in main))
    pairs = work_pairs(main)
    print(f"[test_3] 工作组合数 {len(pairs)}（泛癌种 4 × {len(main)} + HGCN 绑定 "
          f"{sum(1 for d in main if d in HGCN_BINDING)}）")
    print(f"[test_3] 搜索产物根目录 {SEARCH_ROOT}")
