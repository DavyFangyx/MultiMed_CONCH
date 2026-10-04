#!/usr/bin/env python3
"""Test_5 汇总：把各子检查的 run dir 结果收成表 results/Test_5_invariance/{sub}/{dataset}/cindex.csv。

复用 cindex.summarize_dataset 的既有表口径（行键 = scheme×encoding×modality，行内
val/test c-index ± std、per_fold），只把表落点用 exp_group_override(tables=True) 覆写为
Test_5_invariance 子树（不写 Test_2b/Test_3 的表目录）。

幂等：表已存在的行保序不重复（_merge_cindex_rows），重跑只补新行；run 缺失的 job 打印
skip 不中断（汇总可在 drain 进行中反复跑，逐步补齐）。

完成性门（默认开）：只汇总"真完成"的 run —— conf 在 done/ 且 run dir 有 .done
（run.sh 成功才 touch，line 376；ended_at 失败时也会写，不能用）。原因：read_cindex 会把
run dir 里当前已有的 val_result_fold*.csv 直接聚成行，而 _merge_cindex_rows 只追加不更新
（已存在的行键不会被覆盖），若对进行中的 run 汇总，半截行（比如只有 fold0-2）会永久留在
表里。需要看半截状态时用 --allow-partial（调试用，会污染表，慎用）。

用法（projects/ 根目录，base python3）：
  python3 scripts/Test_5_summarize.py --sub all
  python3 scripts/Test_5_summarize.py --sub 5E_2b --datasets TCGA-LAML,TCGA-GBM
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


def job_finished(sub: str, job: dict) -> bool:
    """该 job 是否真完成：conf 在 done/ 且 run dir 有 .done（run.sh 成功才 touch）。"""
    root = C.queue_root(sub)
    if not (root / "done" / job["conf_name"]).exists():
        return False
    return (Path(job["out_dir"]) / ".done").exists()


def summarize_sub(sub: str, datasets: list[str], allow_partial: bool = False) -> dict[str, int]:
    from src.cindex import existing_result_dir, summarize_dataset

    # out_dir 由 job 携带（build_jobs 在 runs 覆写下算好），故先建 job 再切表覆写。
    jobs = C.build_jobs(sub, datasets)
    n_jobs = len(jobs)
    if not allow_partial:
        jobs = [job for job in jobs if job_finished(sub, job)]
        print(f"[test_5][{sub}] 完成性门: {len(jobs)}/{n_jobs} 个 conf 真完成（done/ + .done），"
              f"其余不汇总（--allow-partial 可关）")
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for job in jobs:
        groups.setdefault((job["dataset"], job["encoding"], job["modality"]), []).append(job)
    ready = sum(1 for job in jobs
                if existing_result_dir(Path(job["out_dir"])) is not None)

    rows_total = 0
    with C.exp_group_override(sub, tables=True):
        for (dataset, encoding, modality), gjobs in sorted(groups.items()):
            if not any(existing_result_dir(Path(job["out_dir"])) is not None for job in gjobs):
                print(f"[test_5][{sub}] skip {dataset} {encoding} {modality}: no run dirs yet")
                continue
            merged = summarize_dataset(
                dataset_name=dataset,
                jobs=gjobs,
                results_root=C.RESULTS_ROOT,
                encoding=encoding,
                modality=modality,
                landmark_tag=gjobs[0]["landmark_tag"],
            )
            rows_total += len(merged)
    return {"jobs": n_jobs, "finished": len(jobs), "ready": ready, "groups": len(groups),
            "rows": rows_total}


def cmd(sub: str, datasets: list[str], allow_partial: bool = False) -> None:
    info = summarize_sub(sub, datasets, allow_partial=allow_partial)
    table_root = C.INVARIANCE_ROOT / sub
    print(f"[test_5][{sub}] confs={info['jobs']} finished={info['finished']} "
          f"run_dirs_done={info['ready']} groups={info['groups']} table_rows={info['rows']} "
          f"tables -> {table_root}/<dataset>/cindex.csv")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sub", default="all", choices=(*C.SUBS, "all"))
    parser.add_argument("--datasets", default=None, help="逗号分隔数据集过滤（调试用）")
    parser.add_argument("--allow-partial", action="store_true",
                        help="调试用：不要求完成性门（会对进行中的 run 写半截行且不可覆盖）")
    args = parser.parse_args(argv)

    C.load_all_schemes()
    C.apply_test3_patches()
    subs = list(C.SUBS) if args.sub == "all" else [args.sub]
    datasets = ([x.strip() for x in args.datasets.split(",") if x.strip()]
                if args.datasets else C.main_datasets())
    for sub in subs:
        cmd(sub, datasets, allow_partial=args.allow_partial)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
