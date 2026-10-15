"""Test_3 两臂编排(结果侧工具;F×T 口径 2026-10-13)。

臂语义唯一来源 = z_notes/experiment_list/arm_registry.md:
  deleak    = work × lm0 —— 方案 work_lm0_{work}_{ds}(与 Test_2b 臂 B 同一产物)
  reach     = greedy × lm0 —— 方案 greedy_lm0_{ds}(字段 = 搜索 result.json recommended_subset)
  reach_raw = greedy × raw —— 方案 greedy_raw_{ds}(同字段名单,raw bank;Test_4 档 4)

链路:enqueue(exp_queue,训练时索引,无切片步骤)→ run → 汇总(results_display/scripts/Test_3_arms_summarize.py)。
字段名单训练时解析(scripts/check_arm_fields.py 可做阶段检查,不进主 pipeline)。

用法(projects/ 根目录):
  python3 scripts/Test_3_arms.py summarize --arm deleak
  python3 scripts/Test_3_arms.py status   --arm deleak
  # enqueue / run 走统一入口:
  bash scripts/exp_queue.sh enqueue --arm test_3_arms --variant deleak
  bash scripts/exp_queue.sh run
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import Test_3_common as C  # noqa: E402

from manual_pipeline.arm_names import greedy_scheme_name  # noqa: E402

from common.paths import config_family_dir, test_results_dir  # noqa: E402

ARMS = ("deleak", "reach", "reach_raw", "reach_best")
ARM_ALIASES = {"b": "deleak", "ksig": "reach", "raw": "reach_raw", "best": "reach_best"}
QUEUE_ROOT = config_family_dir("Test_3_arms")
ARM_B_RESULTS = ROOT / "results" / "paper_lm0"  # deleak/reach 臂汇总表根(与 2b 臂 B 同表)


def conch_python() -> Path:
    from greedy.clinic_evaluator import DEFAULT_CONCH_PYTHON

    return Path(DEFAULT_CONCH_PYTHON)


def scheme_pairs(arm: str, datasets: list[str]) -> list[tuple[str, str, str | None]]:
    """[(dataset, scheme, work|None)]；deleak 按 §2.4 绑定展开;reach 需搜索 result.json。"""
    arm = ARM_ALIASES.get(arm, arm)
    pairs: list[tuple[str, str, str | None]] = []
    for dataset in datasets:
        if arm == "deleak":
            for _, work in C.work_pairs([dataset]):
                pairs.append((dataset, C.b_scheme_name(work, dataset), work))
        else:
            name = C.c_scheme_name(dataset, kind="best" if arm == "reach_best" else "ksig")
            if not C.search_result_json(dataset).exists():
                raise SystemExit(f"[test_3][arms] 缺搜索 result.json: {C.search_result_json(dataset)}")
            if arm == "reach_raw":
                name = greedy_scheme_name(dataset, t="raw")
            pairs.append((dataset, name, None))
    return pairs


def arm_landmark(arm: str) -> tuple[str, int | None]:
    """臂的时间口径 → (landmark_tag, landmark_time);raw 臂 = 原始口径(与 paper×raw 同)。"""
    if arm == "reach_raw":
        return "", None
    return f"landmark_{C.LANDMARK_TIME}", int(C.LANDMARK_TIME)


def _cindex_jobs(dataset: str, scheme: str, arm: str = "deleak") -> list[dict]:
    from common.datasets import load_dataset_configs
    from manual_pipeline.cindex import iter_cindex_jobs

    tag, time = arm_landmark(arm)
    return iter_cindex_jobs(
        dataset_name=dataset,
        schemes=[scheme],
        datasets=load_dataset_configs(ROOT / "datasets.json"),
        baseline_out=str(ROOT / "outputs"),
        encoding="text",
        modalities=[C.ANALYZER],
        results_root=ROOT / "results",
        seed=C.SEED,
        landmark_tag=tag,
        landmark_time=time,
    )


def cmd_enqueue(arm: str, datasets: list[str]) -> None:
    """已收敛：实现在 `scripts/exp_queue.py` 的 cindex backend（--arm test_3_arms）。"""
    raise SystemExit(
        "[test_3][arms] enqueue 已收敛到统一入口:\n"
        f"  bash scripts/exp_queue.sh enqueue --arm test_3_arms --variant {arm}"
        + (f" --datasets {','.join(datasets)}" if datasets else "")
    )


def cmd_drain(workers: int, poll: float) -> None:
    """已收敛:执行 = 统一 run。GPU 由调用方 CUDA_VISIBLE_DEVICES 控制。"""
    raise SystemExit(
        "[test_3][arms] 执行已收敛到统一入口:\n"
        f"  bash scripts/exp_queue.sh run --workers {workers}"
    )


def cmd_summarize(datasets: list[str], arm: str) -> None:
    """已归位:汇总 = results_display/scripts 的职责(2026-10-13)。"""
    raise SystemExit(
        "[test_3][arms] summarize 已归位 results_display/scripts/Test_3_arms_summarize.py:\n"
        f"  python3 results_display/scripts/Test_3_arms_summarize.py --arm {arm}"
        + (f" --datasets {','.join(datasets)}" if datasets else "")
    )


def cmd_status(arm: str, datasets: list[str]) -> None:
    from manual_pipeline.arm_names import bank_dir, bank_embeddings, parse_arm_scheme
    from manual_pipeline.cindex import conf_filename
    from greedy.data import display_to_study

    root = Path(QUEUE_ROOT)
    tag, _time = arm_landmark(arm)
    table_root = ROOT / "results" / "paper_raw" if arm == "reach_raw" else ARM_B_RESULTS
    for dataset, scheme, work in scheme_pairs(arm, datasets):
        study = display_to_study(dataset)
        name = conf_filename(study, scheme, C.ANALYZER, tag)
        bucket = next((b for b in ("queue", "running", "done", "failed") if (root / b / name).exists()), "-")
        parsed = parse_arm_scheme(scheme)
        bank = "bank" if parsed and bank_embeddings(bank_dir(dataset, parsed["t"])).is_dir() else "    "
        table = table_root / f"{dataset}[gdc]" / "cindex.csv"
        c = ""
        if table.exists():
            with table.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("scheme") == scheme and row.get("modality") == C.ANALYZER:
                        c = f" c={row.get('val_c_index_mean')}"
        print(f"[test_3][arms] {dataset:12s} {scheme:44s} {bank} {bucket:8s}{c}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Test_3 两臂编排器(结果侧)")
    parser.add_argument("command", choices=["generate", "enqueue", "drain", "summarize", "status"])
    parser.add_argument("--arm", default="deleak", choices=ARMS)
    parser.add_argument("--workers", type=int, default=2, help="drain 并发 worker 数(占位)")
    parser.add_argument("--poll", type=float, default=15.0)
    parser.add_argument("--datasets", default=None, help="可选：覆盖数据集名单（冒烟/调试用）")
    return parser


def main(argv=None) -> int:
    args = parse_args(argv).parse_args(argv)
    datasets = ([x.strip() for x in args.datasets.split(",") if x.strip()]
                if args.datasets else C.main_datasets())
    if args.command == "generate":
        # 训练时索引(2026-10-13 拍板):无切片生成步骤;阶段检查见 scripts/check_arm_fields.py。
        raise SystemExit(
            "[test_3][arms] 无 generate 步骤:字段名单训练时解析(bank 模式)。\n"
            "  阶段检查: python3 scripts/check_arm_fields.py --arm deleak --datasets TCGA-BLCA"
        )
    elif args.command == "enqueue":
        cmd_enqueue(args.arm, datasets)
    elif args.command == "drain":
        cmd_drain(args.workers, args.poll)
    elif args.command == "summarize":
        cmd_summarize(datasets, args.arm)
    elif args.command == "status":
        cmd_status(args.arm, datasets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
