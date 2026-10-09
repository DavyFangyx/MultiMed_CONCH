#!/usr/bin/env python3
"""S12b reach 臂的 baseline 编码（Test_3_greedy_{dataset} × onehot_ordinary）。

背景：S12a 按规格跳过了 reach 臂的 baseline 编码（当时模板仅 2/15）。5E_3/5M_3 的 reach 臂
本轮要跑，E 轴的 baseline 档需要 outputs/{ds}/A_manual/baseline/Test_3_greedy_{ds}/。

口径（与 S12a phase 3 完全相同，只换方案名单）：
  * 方案白名单已在源头放开（manual_pipeline.baseline 注册 templates/manual_schemes 下全部
    已登记方案；原 A_pipeline 时代靠 Test_3_pipeline_one 进程内补 PAPER_SCHEMES）；
    仅对"字段全部可由 GDC 字典定型的 greedy 方案"生效——含未定型字段
    （diagnoses[].calgb_risk_group 等）的方案 build_baseline_feature_schema 会抛错，
    这类 conf 按任务约定跳过并报告；
  * --landmark_time 0 --baseline_stats_dir outputs/{ds}/A_manual/baseline/metadata（S12a 已
    落盘），--baseline_out outputs；baseline 编码纯 CPU，不占 GPU；
  * 幂等：目标目录已有 .pt 即跳过（绝不覆盖）。

用法（repo 根目录，conch 环境 python；baseline 不读 CUDA，--gpu 仅为满足入口参数）：
  /data/fangyuxuan/miniconda3/envs/conch/bin/python scripts/Test_5_baseline_c.py --all
  ... scripts/Test_5_baseline_c.py --datasets TCGA-GBM,TCGA-OV
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SCHEMES_JSON = ROOT / "templates" / "manual_schemes" / "schemes.json"
OUTPUTS = ROOT / "outputs"


def greedy_templates() -> dict[str, tuple[str, list[str]]]:
    """scheme -> (dataset, fields)（schemes.json 注册的 Test_3_greedy_*，数据驱动）。"""
    payload = json.loads(SCHEMES_JSON.read_text(encoding="utf-8"))
    out: dict[str, tuple[str, list[str]]] = {}
    for name in payload.get("_schemes", []):
        if not str(name).startswith("Test_3_greedy_"):
            continue
        fields_file = SCHEMES_JSON.parent / name / "fields.json"
        cfg = json.loads(fields_file.read_text(encoding="utf-8"))
        datasets = cfg.get("datasets") or []
        if len(datasets) != 1:
            raise SystemExit(f"[test_5][baseline_c] {name} 的 datasets 绑定不唯一: {datasets}")
        out[name] = (datasets[0], list(cfg.get("fields") or []))
    return out


def baseline_encodable() -> tuple[dict[str, str], list[tuple[str, list[str]]]]:
    """返回 (encodable scheme -> dataset, [(skipped scheme, fields), ...])。"""
    from common.fields import HUMAN_SCHEME_FIELDS  # noqa: E402

    human = set(HUMAN_SCHEME_FIELDS)
    ok: dict[str, str] = {}
    skipped: list[tuple[str, list[str]]] = []
    for name, (dataset, fields) in sorted(greedy_templates().items()):
        bad = [f for f in fields if f not in human]
        if bad:
            skipped.append((name, bad))
        else:
            ok[name] = dataset
    return ok, skipped


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="全部可定型 greedy 模板")
    parser.add_argument("--datasets", default=None, help="逗号分隔数据集过滤（TCGA-GBM,...）")
    parser.add_argument("--gpu", default="1", help="占位（baseline 不读 CUDA），默认 1 避开 GPU 7")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    ok, skipped = baseline_encodable()
    want = None
    if args.datasets:
        want = {x.strip() for x in args.datasets.split(",") if x.strip()}
    plans = [(name, ds) for name, ds in sorted(ok.items()) if want is None or ds in want]
    print(f"[test_5][baseline_c] 可定型 greedy 方案 {len(ok)}: {sorted(ok)}")
    for name, bad in skipped:
        print(f"[test_5][baseline_c] SKIP 不可定型: {name} 的字段 {bad}（build_baseline_feature_schema 无类型）")
    if not args.all and not args.datasets:
        print("[test_5][baseline_c] 未给 --all/--datasets，仅列清单（dry）")
        return 0

    fail = 0
    todo = []
    for name, dataset in plans:
        target = OUTPUTS / dataset / "A_manual" / "baseline" / name / "landmark_0" / "embeddings" / "pt"
        if target.is_dir() and any(target.glob("*.pt")):
            print(f"[test_5][baseline_c] skip existing: {dataset}/{name}")
            continue
        stats_dir = OUTPUTS / dataset / "A_manual" / "baseline" / "metadata"
        if not (stats_dir / "normalization_stats.json").is_file():
            print(f"[test_5][baseline_c] SKIP {dataset}/{name}: 缺 {stats_dir}/normalization_stats.json")
            fail += 1
            continue
        todo.append((name, dataset, stats_dir, target))

    if todo and not args.dry_run:
        from manual_pipeline.cli import main as ap_main  # noqa: E402

    for name, dataset, stats_dir, target in todo:
        if args.dry_run:
            print(f"[test_5][baseline_c] DRY {dataset}/{name}")
            continue
        sys.argv = [sys.argv[0], "baseline", "--dataset", dataset, "--scheme", name,
                    "--landmark_time", "0", "--baseline_stats_dir", str(stats_dir),
                    "--baseline_out", str(OUTPUTS)]
        try:
            ap_main()
        except SystemExit as exc:  # argparse/CLI 退出码
            if exc.code not in (0, None):
                fail += 1
                print(f"[test_5][baseline_c] FAIL {dataset}/{name} exit={exc.code}")
                continue
        if target.is_dir() and any(target.glob("*.pt")):
            print(f"[test_5][baseline_c] OK {dataset}/{name} -> {target}")
        else:
            fail += 1
            print(f"[test_5][baseline_c] FAIL {dataset}/{name}: 未见产物 {target}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
