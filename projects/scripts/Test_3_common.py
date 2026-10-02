"""Test_3（字段轴链主体）共享常量、主集读取与三臂路径工具。

口径来源（唯一来源 = `z_notes/Test_series_spec.md`）：
  §7     Test_3 规格（搜索池 / A2_greedy / sig_stop / 三臂 B, B', C / 遗漏字段清单）
  §2.4   方案 × 数据集绑定（泛癌种 4 方案 × 全部 TCGA；HGCN_* 仅本癌种）
  §12 U1 数据协议 A + R13 训练范围（n_event >= 100 的 15 个主集）

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

# --- 协议 A / R13 -----------------------------------------------------------
MAIN_N_EVENT_MIN = 100  # 协议 A 主集阈值（R13：训练类实验只在 n_event >= 100 上训练）

MANIFEST_CSV = ROOT / "results" / "Test_0_dataset_availability" / "manifest.csv"
EVENT_SUMMARY_CSV = ROOT / "rawdata_stats" / "_shared" / "event_summary.csv"

# --- Test_3 产物路径 --------------------------------------------------------
OUT_ROOT = ROOT / "results" / "Test_3_greedy_vs_works"
SEARCH_ROOT = OUT_ROOT / "search"           # 搜索 run 落盘（evaluations.jsonl / result.json）
SEARCH_CACHE = test_results_dir("Test_3_search") / "cache.sqlite"
COMPARE_ROOT = OUT_ROOT                     # Test_3_compare.py 的三臂 json/csv

ANALYZER = "mlp_clinic_flatten"             # E2 唯一搜索目标模型（spec §7.1）
ALGO = "A2_greedy"
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
    """dataset -> n_event。两个来源交叉核对（S5c 已验证一致），不一致即报错。"""
    manifest: dict[str, int] = {}
    manifest_path = Path(manifest_csv)
    if manifest_path.exists():
        with manifest_path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("dataset") or "").strip()
                if not name or not tcga_prefix(name):
                    continue
                manifest[name] = int(float(row.get("n_event") or 0))
    summary: dict[str, int] = {}
    summary_path = Path(event_summary_csv)
    if summary_path.exists():
        with summary_path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("dataset") or row.get("study") or row.get("name") or "").strip()
                if not name or not tcga_prefix(name):
                    continue
                value = row.get("n_event")
                if value in (None, ""):
                    continue
                summary[name] = int(float(value))
    if strict and manifest and summary:
        diff = {name: (manifest[name], summary.get(name)) for name in manifest
                if summary.get(name) is not None and summary[name] != manifest[name]}
        if diff:
            raise ValueError(f"n_event 两来源不一致: {diff}")
    merged = dict(summary)
    merged.update(manifest)  # manifest 优先
    if not merged:
        raise SystemExit(f"[test_3] 读不到 n_event（{manifest_path} / {summary_path}）")
    return merged


def main_datasets(n_event: dict[str, int] | None = None, *, threshold: int = MAIN_N_EVENT_MIN) -> list[str]:
    """协议 A 主集：TCGA 中 n_event >= threshold，字典序（不硬编码名单）。"""
    table = load_n_event() if n_event is None else n_event
    names = sorted(name for name, value in table.items() if tcga_prefix(name) and value >= threshold)
    if not names:
        raise SystemExit(f"[test_3] 主集为空（n_event >= {threshold}）")
    return names


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


def bp_scheme_name(work: str, dataset: str) -> str:
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
