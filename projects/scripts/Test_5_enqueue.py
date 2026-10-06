"""S12b Test_5 不变性 conf 投放（只入队，不训练；幂等可重跑）。

枚举口径与子检查定义见 scripts/Test_5_common.py（spec §8bis）；本脚本只做：
  1) 按子检查枚举 conf（缺失编码目录的 (dataset, scheme, arm) 被跳过并列名）；
  2) 写入 Clinic_Analyzer/configs/Test_5_{sub}/queue/（已存在 = existing，不重复写）；
  3) 不做任何训练/汇总（drain 由 scripts/Test_5_drain.py / Test_5_scheduler.py 负责）。

EXP_GROUP 映射：runs -> results/Test_5_invariance/{sub}/runs（cindex.ANALYZER_EXP_GROUP /
LANDMARK_ANALYZER_EXP_GROUP 进程内覆写，见 Test_5_common.exp_group_override），汇总表 ->
results/Test_5_invariance/{sub}/{dataset}/cindex.csv（由 Test_5_summarize.py 写）。

多模态（5M_2b 的 survgc_f/survpgc_f，72 conf）默认撤到
`Clinic_Analyzer/configs/Test_5_5M_2b/parked/`（= 不投放，drainer 不读；同 s5b 的
parked 惯例）。原因（2026-10-04 实测）：这两个模型走 WSI，SurvPGC_Workspace/{study}/P/
uni_v1/*.pt 是 slide 级命名，而 label metadata 需为 slide 级
（SurvPGC_github_init/datasets_csv/metadata/{study}.csv）；当前 Clinic_Analyzer 的
case 级 metadata 会让 WSI filter kept 0 -> run.sh 失败。换上游 metadata 后同一 run
可通过（验证记录见 Test_5_common.park_reason），label 源 + landmark_0 派生口径待 S13
决定；决定后用 --include-multimodal 正常投放（或把 parked/*.conf 手工 mv 回 queue/）。

用法（projects/ 根目录，base python3）：
  python3 scripts/Test_5_enqueue.py --sub all                 # 投放 4 个子检查（幂等）
  python3 scripts/Test_5_enqueue.py --sub 5E_2b --dry-run     # 只列 conf，不写盘
  python3 scripts/Test_5_enqueue.py --status                  # 队列桶 + 期望数 + 缺件
  python3 scripts/Test_5_enqueue.py --list                    # 逐 conf 打 conf_name / clinic_dir
  python3 scripts/Test_5_enqueue.py --sub 5M_3 --only TCGA-LAML --only Test_3_greedy_TCGA-LAML
                                                              # (dataset|scheme|conf_name 子串过滤)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import Test_5_common as C  # noqa: E402


def missing_encodings(sub: str, datasets: list[str]) -> list[tuple[str, str, str, str, str]]:
    """缺编码的 (dataset, arm, scheme, encoding, path)——iter_cindex_jobs 会静默跳过这些。"""
    out = []
    for dataset in datasets:
        for plan in C.arm_plans(sub, dataset):
            for scheme in plan.schemes:
                path = C.encoding_paths(dataset, scheme, plan.encoding, plan.landmark_tag)
                if not (path.is_dir() and any(path.glob("*.pt"))):
                    out.append((dataset, plan.arm, scheme, plan.encoding, str(path)))
    return out


def cmd_enqueue(subs: list[str], datasets: list[str], only: tuple[str, ...],
                dry_run: bool, include_multimodal: bool) -> int:
    from manual_pipeline.cindex import enqueue_cindex_jobs

    rc = 0
    for sub in subs:
        missing = missing_encodings(sub, datasets)
        jobs = C.build_jobs(sub, datasets, conf_filters=only)
        expect = C.expected_counts(datasets)[sub]["total"]
        parked_jobs: list[dict] = []
        if sub == "5M_2b" and not include_multimodal:
            parked_jobs = [j for j in jobs if j["modality"] in C.PARK_MODALITIES]
            jobs = [j for j in jobs if j["modality"] not in C.PARK_MODALITIES]
        tag = "DRY " if dry_run else "QUEUE"
        print(f"[test_5][{sub}] expected={expect} jobs={len(jobs)} "
              f"parked={len(parked_jobs)} missing_encodings={len(missing)}"
              + ("  (dry-run)" if dry_run else ""))
        if parked_jobs:
            print(f"[test_5][{sub}] PARK {sorted({j['modality'] for j in parked_jobs})}: "
                  f"{C.park_reason(C.PARK_MODALITIES[0])}")
        for row in missing:
            print(f"[test_5][{sub}]   SKIP missing encoding: {row[0]} {row[1]} {row[2]} "
                  f"({row[3]}) -> {row[4]}")
        if dry_run:
            for job in jobs:
                print(f"[test_5][{sub}]   {job['conf_name']}")
            continue
        queued = enqueue_cindex_jobs(jobs, queue_root=str(C.queue_root(sub)))
        print(f"[test_5][{sub}] {tag} root={queued['root']} created={len(queued['created'])} "
              f"existing={len(queued['existing'])} retried={len(queued.get('retried', []))}")
        if parked_jobs:
            parked = C.park_jobs(parked_jobs, sub)
            print(f"[test_5][{sub}] PARKED root={parked['root']} "
                  f"created={len(parked['created'])} existing={len(parked['existing'])} "
                  f"(drainer 不读 parked/)")
        if missing:
            rc = 1  # 有缺件（C 臂 baseline 编码未产/模板缺失），不影响其余投放
    return rc


def cmd_status(subs: list[str], datasets: list[str]) -> None:
    C.print_status(datasets)
    for sub in subs:
        missing = missing_encodings(sub, datasets)
        if missing:
            print(f"[test_5][{sub}] 缺编码 {len(missing)}:")
            for row in missing:
                print(f"[test_5][{sub}]   {row[0]} {row[1]} {row[2]} ({row[3]}) -> {row[4]}")


def cmd_list(subs: list[str], datasets: list[str], only: tuple[str, ...]) -> None:
    for sub in subs:
        for job in C.build_jobs(sub, datasets, conf_filters=only):
            print(f"{sub}\t{job['conf_name']}\t{job['clinic_dir']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sub", default="all", choices=(*C.SUBS, "all"))
    parser.add_argument("--datasets", default=None, help="逗号分隔覆盖数据集名单（调试用）")
    parser.add_argument("--only", action="append", default=[],
                        help="conf 过滤子串（dataset|scheme|conf_name），可重复")
    parser.add_argument("--include-multimodal", action="store_true",
                        help="5M_2b 的 survgc_f/survpgc_f 也按常规投放"
                             "（默认撤到 parked/，见 Test_5_common.park_reason）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)

    C.load_all_schemes()
    subs = list(C.SUBS) if args.sub == "all" else [args.sub]
    datasets = ([x.strip() for x in args.datasets.split(",") if x.strip()]
                if args.datasets else C.main_datasets())
    only = tuple(args.only)

    if args.status:
        cmd_status(subs, datasets)
        return 0
    if args.list:
        cmd_list(subs, datasets, only)
        return 0
    return cmd_enqueue(subs, datasets, only, args.dry_run, args.include_multimodal)


if __name__ == "__main__":
    raise SystemExit(main())
