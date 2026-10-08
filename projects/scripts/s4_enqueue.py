"""S4 Test_2b: enqueue-only / summarize / status dispatcher for the A_manual cindex queue.

Reuses the exact CLI code path (expand_source_jobs -> iter_cindex_jobs ->
enqueue_cindex_jobs / summarize_dataset, same functions as `scripts/run_a_manual.py
cindex`) but skips drain_queue, so grid slices can be staged by priority
(数据协议 A: >=100 与 70-100 先跑 -> 30-70 -> <30) without spawning extra
claim workers. 实际训练由独立的 drainer 进程按 conf+run.sh claim 机制执行。

R13（2026-10-05 复核）：训练切片只收 n_event >= 100 的 15 个 TCGA 主集；
70-100 / 30-70 / <30 档不新增训练（wave 2/3 切片投出 0 conf）。Tier 划分仍
按协议 A 阈值保留在 load_waves 里供报告分层。方案 x 数据集绑定按 spec §2.4
（HGCN_* 仅本癌种；ESCA/UCEC 不在主集 → 其绑定切片不再训练）。

用法（统一 python 3.13.12，硬条件 D3-1）:
  python3 scripts/s4_enqueue.py --list                       # 打印网格
  python3 scripts/s4_enqueue.py --slice A1                   # enqueue 波1 臂A 泛癌种
  python3 scripts/s4_enqueue.py --slice B1H --summarize      # 汇总已完成 run 的行
  python3 scripts/s4_enqueue.py --emit-encodes               # 输出缺失的编码任务清单
  python3 scripts/s4_enqueue.py --status                     # 队列桶计数
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT / "src"))
from common.paths import config_family_dir, test_results_dir  # noqa: E402

# A_manual 内核已吸收进主项目（src/manual_pipeline），不再需要 A_pipeline 的
# 同名 `src` 包遮蔽技巧：import 一律走 manual_pipeline.*。
from manual_pipeline.baseline import load_baseline_scheme_fields  # noqa: E402
from manual_pipeline.cli import _add_common_args  # noqa: E402
from manual_pipeline.config import (  # noqa: E402
    SCHEME_FIELDS,
    load_custom_schemes,
    resolve_scheme_names,
)
from manual_pipeline.hgcn_clinic import load_hgcn_scheme_fields  # noqa: E402
from manual_pipeline.cindex import (  # noqa: E402
    enqueue_cindex_jobs,
    iter_cindex_jobs,
    summarize_dataset,
)
from manual_pipeline.datasets import expand_source_jobs, load_source_dataset_configs  # noqa: E402
from manual_pipeline.landmark import parse_landmark_setting  # noqa: E402
from manual_pipeline.paths import (  # noqa: E402
    DEFAULT_BASELINE_OUT_ROOT,
    DEFAULT_GDC_DATASETS_CONFIG,
    DEFAULT_OUT_DIR,
    DEFAULT_PROMPT_DIR,
    DEFAULT_TEMPLATE_DIR,
)

MANIFEST = PROJECT_ROOT / "results" / "Test_0_dataset_availability" / "manifest.csv"
OUTPUTS = PROJECT_ROOT / "outputs"

PAN_CANCER_SCHEMES = ["MULTISURV", "SURVPGC", "MMSURV", "INTEGRATIVE_DNN"]
HGCN_BINDING = {
    "TCGA-KIRC": "HGCN_KIRC",
    "TCGA_LIHC": "HGCN_LIHC",
    "TCGA-ESCA": "HGCN_ESCA",
    "TCGA-LUSC": "HGCN_LUSC",
    "TCGA-LUAD": "HGCN_LUAD",
    "TCGA-UCEC": "HGCN_UCEC",
}
ANALYZERS = ["clinic_cox", "mlp_clinic_flatten"]
ENCODING = "text"
ARMS = {"A": "none", "B": "0"}


MAIN_N_EVENT_MIN = 100  # R13：训练范围 = n_event >= 100 的 TCGA 主集


def load_waves() -> tuple[dict[str, list[str]], set[str]]:
    """(wave name -> dataset list, R13 主集) from Test_0 manifest n_event。

    wave 划分按协议 A 阈值(>=70 / >=30 / <30)供报告分层;
    mains = n_event >= 100,训练切片只从 mains 取(R13)。
    """
    waves: dict[str, list[str]] = {"1": [], "2": [], "3": []}
    mains: set[str] = set()
    with MANIFEST.open(newline="") as f:
        for row in csv.DictReader(f):
            name = row["dataset"]
            if not name.startswith("TCGA"):
                continue
            n_event = float(row["n_event"] or 0)
            if n_event >= MAIN_N_EVENT_MIN:
                mains.add(name)
            wave = "1" if n_event >= 70 else ("2" if n_event >= 30 else "3")
            waves[wave].append(name)
    for wave in waves:
        waves[wave].sort()
    return waves, mains


def slice_spec(slice_name: str, waves: dict[str, list[str]], mains: set[str]) -> tuple[str, str, list[tuple[str, str]]]:
    """Return (arm, wave, [(dataset, scheme), ...]) for a slice name like A1/A1H/B2。

    R13：训练组合只收主集(n_event >= 100);wave 2/3 无主集 → 空组合。
    """
    arm = slice_name[0].upper()
    if arm not in ARMS:
        raise SystemExit(f"未知 slice: {slice_name}（形如 A1 / A1H / B2 / B3H）")
    hgcn = slice_name.endswith("H")
    wave = slice_name[1:2]
    if wave not in ("1", "2", "3"):
        raise SystemExit(f"未知 slice: {slice_name}")
    combos = []
    if hgcn:
        for dataset, scheme in sorted(HGCN_BINDING.items()):
            if dataset in waves[wave] and dataset in mains:
                combos.append((dataset, scheme))
    else:
        for dataset in waves[wave]:
            if dataset in mains:
                for scheme in PAN_CANCER_SCHEMES:
                    combos.append((dataset, scheme))
    return arm, wave, combos


def grid_combo_count(waves: dict[str, list[str]], mains: set[str]) -> int:
    total = 0
    for wave in ("1", "2", "3"):
        total += len(slice_spec(f"A{wave}", waves, mains)[2]) + len(slice_spec(f"A{wave}H", waves, mains)[2])
    return total


def _jobs_for_combos(combos: list[tuple[str, str]], arm: str, results_root: Path) -> list[dict]:
    schemes = sorted({scheme for _, scheme in combos})
    datasets_by_scheme: dict[str, list[str]] = {}
    for dataset, scheme in combos:
        datasets_by_scheme.setdefault(scheme, []).append(dataset)

    all_jobs: list[dict] = []
    for scheme in schemes:
        dataset_arg = ",".join(datasets_by_scheme[scheme])
        jobs = expand_source_jobs(
            dataset_arg,
            [scheme],
            load_source_dataset_configs(
                gdc_config=DEFAULT_GDC_DATASETS_CONFIG,
            ),
            json_path=None,
            prompt_dir=DEFAULT_PROMPT_DIR,
            out_dir=DEFAULT_OUT_DIR,
            baseline_out=DEFAULT_BASELINE_OUT_ROOT,
        )
        landmark = parse_landmark_setting(ARMS[arm])
        for job in jobs:
            if not job.get("name"):
                continue
            all_jobs.extend(
                iter_cindex_jobs(
                    dataset_name=job["name"],
                    schemes=list(job.get("schemes") or []),
                    datasets=job.get("datasets") or {},
                    baseline_out=DEFAULT_BASELINE_OUT_ROOT,
                    encoding=ENCODING,
                    modalities=ANALYZERS,
                    results_root=results_root,
                    landmark_tag=landmark.arm_tag,
                    landmark_time=landmark.landmark_time,
                )
            )
    return all_jobs


def cmd_enqueue(slice_name: str, results_root: Path) -> None:
    waves, mains = load_waves()
    arm, wave, combos = slice_spec(slice_name, waves, mains)
    print(f"[S4] slice={slice_name} arm=landmark_{ARMS[arm]} wave={wave} "
          f"combos={len(combos)} confs_expected={len(combos) * len(ANALYZERS)}")
    jobs = _jobs_for_combos(combos, arm, results_root)
    queued = enqueue_cindex_jobs(jobs, queue_root=str(config_family_dir("Test_2b_arms")))
    print(f"[S4] queue={queued['root']} created={len(queued['created'])} "
          f"existing={len(queued['existing'])} retried={len(queued.get('retried', []))}")
    print(f"[S4] 下一步: 由 drainer 进程 claim 并训练（见 scripts/s4_Test_2b_queue.sh）")


def cmd_summarize(slice_name: str, results_root: Path) -> None:
    waves, mains = load_waves()
    arm, wave, combos = slice_spec(slice_name, waves, mains)
    landmark = parse_landmark_setting(ARMS[arm])
    jobs = _jobs_for_combos(combos, arm, results_root)
    by_dataset: dict[str, list[dict]] = {}
    for job in jobs:
        # run_cindex_queue 用 f"{name}[{source}]" 作表目录键（旧 A_manual 同款），保持一致。
        table_key = f"{job['dataset']}[gdc]"
        by_dataset.setdefault(table_key, []).append(job)
    for dataset, dataset_jobs in sorted(by_dataset.items()):
        print(f"[S4] summarize {dataset}")
        summarize_dataset(
            dataset_name=dataset,
            jobs=dataset_jobs,
            results_root=results_root,
            encoding=ENCODING,
            modality=",".join(ANALYZERS),
            landmark_tag=landmark.arm_tag,
        )


def _encodes_exist(dataset: str, scheme: str, arm: str) -> bool:
    subdir = "" if arm == "A" else "landmark_0"
    base = OUTPUTS / dataset / "A_manual" / scheme
    if subdir:
        base = base / subdir
    emb = base / "embeddings" / "pt"
    return (base / "prompts.csv").is_file() and emb.is_dir() and any(emb.glob("*.pt"))


def cmd_emit_encodes() -> None:
    waves, mains = load_waves()
    print("wave|dataset|scheme|arm|landmark_arg")
    for wave in ("1", "2", "3"):
        for arm in ("A", "B"):
            for prefix in ("", "H"):
                _, _, combos = slice_spec(f"{arm}{wave}{prefix}", waves, mains)
                for dataset, scheme in combos:
                    if not _encodes_exist(dataset, scheme, arm):
                        print(f"{wave}|{dataset}|{scheme}|{arm}|{ARMS[arm]}")


def cmd_list() -> None:
    waves, mains = load_waves()
    total = 0
    for wave in ("1", "2", "3"):
        print(f"wave {wave}: {len(waves[wave])} datasets {waves[wave]}")
    print("--- grid ---")
    for wave in ("1", "2", "3"):
        for arm in ("A", "B"):
            for prefix in ("", "H"):
                name = f"{arm}{wave}{prefix}"
                _, _, combos = slice_spec(name, waves, mains)
                missing = [
                    (d, s) for d, s in combos if not _encodes_exist(d, s, arm)
                ]
                total += len(combos)
                print(f"  slice {name}: {len(combos)} combos, "
                      f"encodes missing {len(missing)}")
    print(f"total combos: {total} (R13 训练范围 = {len(mains)} 主集, 含 A/B 两臂; "
          f"confs = {total} x {len(ANALYZERS)} analyzers = {total * len(ANALYZERS)})")
    print("--- old tables coverage ---")
    missing_old = 0
    for wave in ("1", "2", "3"):
        for prefix in ("", "H"):
            _, _, combos = slice_spec(f"A{wave}{prefix}", waves, mains)
            for dataset, scheme in combos:
                table = test_results_dir("Test_2b/arm_A") / f"{dataset}[gdc]" / "cindex.csv"
                if not table.exists():
                    missing_old += 1
                    continue
                with table.open(newline="") as f:
                    rows = {(r["scheme"], r["modality"]) for r in csv.DictReader(f)}
                if (scheme, "clinic_cox") not in rows:
                    missing_old += 1
    print(f"combos without old-table clinic_cox row (no diff check possible): {missing_old}")


def cmd_status() -> None:
    for bucket in ("queue", "running", "done", "failed"):
        root = config_family_dir("Test_2b_arms") / bucket
        count = len(list(root.glob("*.conf"))) if root.is_dir() else 0
        print(f"{bucket}: {count}")
    done_new = len(list((config_family_dir("Test_2b_arms") / "done").glob("*__landmark_*.conf"))) \
        if (config_family_dir("Test_2b_arms") / "done").is_dir() else 0
    print(f"done (landmark confs): {done_new}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slice", default=None, help="A1/A1H/B1/B1H/A2/A2H/B2/B2H/A3/A3H/B3/B3H")
    parser.add_argument("--summarize", action="store_true", help="只汇总已完成的 run 行（不训练）")
    parser.add_argument("--emit-encodes", action="store_true", help="输出缺失编码任务清单")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)

    load_custom_schemes(DEFAULT_TEMPLATE_DIR)
    load_baseline_scheme_fields(SCHEME_FIELDS)
    load_hgcn_scheme_fields(SCHEME_FIELDS)

    if args.list:
        cmd_list()
    elif args.status:
        cmd_status()
    elif args.emit_encodes:
        cmd_emit_encodes()
    elif args.slice:
        if args.summarize:
            cmd_summarize(args.slice, None)
        else:
            cmd_enqueue(args.slice, None)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
