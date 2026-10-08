"""Test_3 两臂编排(全走同一条编码/模型/划分/seed;spec §7.2,bank-only 口径 2026-10-07)。

  臂 B  = 论文完整组合 × landmark_0(Test_2b 产物,历史口径;只读不跑,保留为交叉参考)
  臂 B = 论文组合 ∩ bank 字段 × landmark_0 —— 自定义方案 Test_3_{work}_{dataset}(去泄露值)
  臂 C  = 贪婪最优子集 × landmark_0 —— 自定义方案 Test_3_greedy_{dataset}(可达值;
          recommended_subset = gain-only δ=0.005 参考点;--arm best 用历史 best_subset)

链路:generate(fields.json ∩ bank 登记)→ encode(bank 切片,零 CONCH 重编码)
      → enqueue(manual pipeline cindex conf)→ drain(Clinic_Analyzer/run.sh)
      → summarize(写 arm_B 表,按行键合并)。臂 C 的 c-index 与搜索 best_cv_c_mean 同口径,
      可直接引用搜索 result.json,无需重新训练。

用法(projects/ 根目录):
  python3 scripts/Test_3_arms.py generate --arm b
  python3 scripts/Test_3_arms.py encode   --arm b --parallel 3
  python3 scripts/Test_3_arms.py enqueue  --arm b
  python3 scripts/Test_3_arms.py drain    --gpu 1 --workers 2
  python3 scripts/Test_3_arms.py summarize
  python3 scripts/Test_3_arms.py status   --arm b
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import Test_3_common as C  # noqa: E402

from common.paths import config_family_dir, test_results_dir  # noqa: E402

LOG_ROOT = C.OUT_ROOT / "logs"
ARMS = ("b", "ksig", "best")
C_KIND = {"ksig": "ksig", "best": "best"}
# 命名公约过渡（见 common/paths.py）：新名优先、旧名回退，迁移前后都能跑。
QUEUE_ROOT = config_family_dir("Test_3_arms")      # cindex conf 队列根（迁移前回退 configs/A_manual）
ARM_B_RESULTS = test_results_dir("Test_2b/arm_B")  # 臂 B 汇总表根（迁移前回退 results/A_manual_landmark）


def conch_python() -> Path:
    from greedy.clinic_evaluator import DEFAULT_CONCH_PYTHON

    return Path(DEFAULT_CONCH_PYTHON)


def scheme_pairs(arm: str, datasets: list[str]) -> list[tuple[str, str, str | None]]:
    """[(dataset, scheme, work|None)]；b 按 §2.4 绑定展开。"""
    pairs: list[tuple[str, str, str | None]] = []
    for dataset in datasets:
        if arm == "b":
            for _, work in [(d, w) for d, w in C.work_pairs([dataset])]:
                pairs.append((dataset, C.b_scheme_name(work, dataset), work))
        else:
            name = C.c_scheme_name(dataset, kind=C_KIND[arm])
            if not C.search_result_json(dataset).exists():
                raise SystemExit(f"[test_3][arms] 缺搜索 result.json: {C.search_result_json(dataset)}")
            pairs.append((dataset, name, None))
    return pairs


def cmd_generate(arm: str, datasets: list[str]) -> None:
    from Test_3_custom_scheme import build_scheme, load_bank_field_list, load_greedy_fields, load_scheme

    bank_cache: dict[str, list[str]] = {}
    for dataset, name, work in scheme_pairs(arm, datasets):
        bank_fields = bank_cache.setdefault(dataset, load_bank_field_list(dataset))
        if work:
            fields = load_scheme(work)
            note = f"work={work} bank切片(landmark_{C.LANDMARK_TIME})"
        else:
            fields, algo = load_greedy_fields(C.search_result_json(dataset))
            note = f"greedy={C.search_result_json(dataset).name} algo={algo} bank切片(landmark_{C.LANDMARK_TIME})"
        build_scheme(name, dataset, fields, bank_fields, note)


def embeddings_dir(dataset: str, scheme: str) -> Path:
    return ROOT / "outputs" / dataset / "A_manual" / scheme / f"landmark_{C.LANDMARK_TIME}" / "embeddings" / "pt"


def _encode_one(dataset: str, scheme: str, gpu: str) -> str:
    """bank-only 口径:按方案 fields.json(∩ bank)切片 bank 嵌入矩阵,零 CONCH 重编码。"""
    from Test_3_custom_scheme import load_scheme, materialize_bank_subset

    clinic = embeddings_dir(dataset, scheme)
    if clinic.is_dir() and any(clinic.glob("*")):
        return f"skip {dataset}/{scheme} (embeddings exist)"
    fields = load_scheme(scheme)  # fields.json 已只含 bank 内字段
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log = LOG_ROOT / f"encode_{dataset}__{scheme}.log"
    try:
        payload = materialize_bank_subset(dataset, fields, clinic, overwrite=True)
    except Exception as exc:  # noqa: BLE001
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"\n===== slice {time.strftime('%F %T')} FAILED: {exc}\n")
        raise
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"\n===== slice {time.strftime('%F %T')} {scheme}: {payload}\n")
    return f"ok   {dataset}/{scheme} (bank 切片 {len(fields)} 字段)"


def cmd_encode(arm: str, datasets: list[str], gpu: str, parallel: int) -> None:
    pairs = scheme_pairs(arm, datasets)
    print(f"[test_3][arms] encode(bank 切片) {len(pairs)} 个 (dataset, scheme), parallel={parallel}", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        for message in pool.map(lambda item: _encode_one(item[0], item[1], gpu), pairs):
            print(f"[test_3][arms] {message}", flush=True)


def _cindex_jobs(dataset: str, scheme: str) -> list[dict]:
    from common.datasets import load_dataset_configs
    from manual_pipeline.cindex import iter_cindex_jobs

    return iter_cindex_jobs(
        dataset_name=dataset,
        schemes=[scheme],
        datasets=load_dataset_configs(ROOT / "datasets.json"),
        baseline_out=str(ROOT / "outputs"),
        encoding="text",
        modalities=[C.ANALYZER],
        results_root=ROOT / "results",
        seed=C.SEED,
        landmark_tag=f"landmark_{C.LANDMARK_TIME}",
        landmark_time=int(C.LANDMARK_TIME),
    )


def cmd_enqueue(arm: str, datasets: list[str]) -> None:
    from manual_pipeline.cindex import enqueue_cindex_jobs

    created = existing = missing = 0
    for dataset, scheme, _work in scheme_pairs(arm, datasets):
        jobs = _cindex_jobs(dataset, scheme)
        if not jobs:
            missing += 1
            print(f"[test_3][arms] 无 job（缺 embeddings?）: {dataset}/{scheme} -> {embeddings_dir(dataset, scheme)}")
            continue
        queued = enqueue_cindex_jobs(jobs, queue_root=QUEUE_ROOT)
        created += len(queued["created"])
        existing += len(queued["existing"])
    print(f"[test_3][arms] enqueue created={created} existing={existing} missing={missing}")


def cmd_drain(gpu: str, workers: int, poll: float) -> None:
    from manual_pipeline.cindex import drain_queue

    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    print(f"[test_3][arms] drain queue={QUEUE_ROOT} gpu={gpu} workers={workers}", flush=True)
    drain_queue(Path(QUEUE_ROOT), reuse=True, poll_seconds=poll, workers=workers)


def cmd_summarize(datasets: list[str], arm: str) -> None:
    from manual_pipeline.cindex import summarize_dataset

    for dataset, scheme, _work in scheme_pairs(arm, datasets):
        jobs = _cindex_jobs(dataset, scheme)
        # 表目录沿用 S4/Test_2b 约定 "{dataset}[gdc]"（s4_enqueue.table_key），
        # 否则会另建一张无后缀表、与臂 B 的行分家。
        rows = summarize_dataset(dataset_name=f"{dataset}[gdc]", jobs=jobs, results_root=ROOT / "results",
                                 encoding="text", modality=C.ANALYZER,
                                 landmark_tag=f"landmark_{C.LANDMARK_TIME}")
        print(f"[test_3][arms] summarize {dataset}: {len(rows)} 行（表内累计）", flush=True)


def cmd_status(arm: str, datasets: list[str]) -> None:
    from manual_pipeline.cindex import conf_filename
    from greedy.data import display_to_study

    root = Path(QUEUE_ROOT)
    for dataset, scheme, work in scheme_pairs(arm, datasets):
        study = display_to_study(dataset)
        name = conf_filename(study, scheme, C.ANALYZER, f"landmark_{C.LANDMARK_TIME}")
        bucket = next((b for b in ("queue", "running", "done", "failed") if (root / b / name).exists()), "-")
        encoded = "emb" if (embeddings_dir(dataset, scheme).is_dir()) else "   "
        table = ARM_B_RESULTS / f"{dataset}[gdc]" / "cindex.csv"
        c = ""
        if table.exists():
            with table.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("scheme") == f"{scheme}__landmark_{C.LANDMARK_TIME}" and \
                            row.get("modality") == C.ANALYZER:
                        c = f" c={row.get('val_c_index_mean')}"
        print(f"[test_3][arms] {dataset:12s} {scheme:44s} {encoded} {bucket:8s}{c}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Test_3 两臂编排器")
    parser.add_argument("command", choices=["generate", "encode", "enqueue", "drain", "summarize", "status"])
    parser.add_argument("--arm", default="b", choices=ARMS)
    parser.add_argument("--gpu", default="1")
    parser.add_argument("--parallel", type=int, default=3, help="encode 并发进程数")
    parser.add_argument("--workers", type=int, default=2, help="drain 并发 worker 数")
    parser.add_argument("--poll", type=float, default=15.0)
    parser.add_argument("--datasets", default=None, help="可选：覆盖数据集名单（冒烟/调试用）")
    return parser


def main(argv=None) -> int:
    args = parse_args(argv).parse_args(argv)
    datasets = ([x.strip() for x in args.datasets.split(",") if x.strip()]
                if args.datasets else C.main_datasets())
    if args.command == "generate":
        cmd_generate(args.arm, datasets)
    elif args.command == "encode":
        cmd_encode(args.arm, datasets, args.gpu, args.parallel)
    elif args.command == "enqueue":
        cmd_enqueue(args.arm, datasets)
    elif args.command == "drain":
        cmd_drain(args.gpu, args.workers, args.poll)
    elif args.command == "summarize":
        cmd_summarize(datasets, args.arm)
    elif args.command == "status":
        cmd_status(args.arm, datasets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
