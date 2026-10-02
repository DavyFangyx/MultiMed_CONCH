"""Test_3 三臂用 A_pipeline 单次入口：以 in-memory 补丁调用 A_pipeline CLI。

为什么需要它（两处 A_pipeline 缺口，**不改 A_pipeline 源文件**——其工作树有他人未提交修改）：
  1) 方案白名单：`A_pipeline/src/cindex.py: expand_cindex_jobs` 只认静态
     PAPER_SCHEMES/DEFAULT_*；Test_3 自定义方案（登记在 templates/schemes.json `_schemes`）
     会被判「未知 cindex 方案」。本入口在运行期把这些名字追加进程内 PAPER_SCHEMES 列表
     （config 与 cindex 共享同一 list 对象，append 即对两处生效），磁盘文件不动。
  2) 编码 GPU：`A_pipeline/src/encode.py: run_encode` 硬设 CUDA_VISIBLE_DEVICES=DEFAULT_GPU
     （paths.py 里 = "7"，现被 S5b Test_1a 批跑占用）。本入口把 paths/encode 两个模块的
     DEFAULT_GPU 改为 --gpu 指定值（默认 1，任务要求避开 GPU 7）。

用法（projects/ 根目录）：
  # 编码（json2prompt + encode，需 conch 环境 python）
  /data/fangyuxuan/miniconda3/envs/conch/bin/python scripts/Test_3_pipeline_one.py \
      --gpu 1 pipeline --dataset TCGA-LAML --scheme Test_3_MULTISURV_TCGA-LAML \
      --landmark_time 0 --encoding text
  # cindex（enqueue + drain，base python 即可；训练由 Clinic_Analyzer/run.sh 内部起 SurvPGC）
  python3 scripts/Test_3_pipeline_one.py --gpu 1 cindex --dataset TCGA-LAML \
      --scheme Test_3_MULTISURV_TCGA-LAML --landmark_time 0 --encoding text \
      --analyzer mlp_clinic_flatten --workers 1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 顺序关键：A_pipeline 必须排在 projects/src 之前，`src` 才是 A_pipeline 的包
# （projects/src 也是 `src`；两者同名，靠 sys.path 先后区分）。
for _p in (ROOT / "src", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
for _p in (ROOT / "A_pipeline",):
    if str(_p) in sys.path:
        sys.path.remove(str(_p))
    sys.path.insert(0, str(_p))

SCHEMES_JSON = ROOT / "A_pipeline" / "templates" / "schemes.json"


def registered_test3_schemes(schemes_json: Path = SCHEMES_JSON) -> list[str]:
    payload = json.loads(schemes_json.read_text(encoding="utf-8"))
    return [name for name in payload.get("_schemes", []) if str(name).startswith("Test_3")]


def apply_patches(gpu: str, schemes: list[str] | None = None) -> dict:
    """返回补丁摘要（便于日志审计）。"""
    from src import config as aconfig
    from src import encode as aencode
    from src import paths as apaths

    schemes = registered_test3_schemes() if schemes is None else schemes
    added = [name for name in schemes if name not in aconfig.PAPER_SCHEMES]
    aconfig.PAPER_SCHEMES.extend(added)          # cindex.PAPER_SCHEMES 是同一 list 对象
    aconfig.ALL_TEXT_SCHEMES.extend(added)
    apaths.DEFAULT_GPU = str(gpu)
    aencode.DEFAULT_GPU = str(gpu)
    return {"gpu": str(gpu), "added_schemes": added}


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--gpu", default="1")
    parser.add_argument("--print-patches", action="store_true")
    known, rest = parser.parse_known_args(argv)
    if known.print_patches:
        print(json.dumps(apply_patches(known.gpu), ensure_ascii=False))
        return
    summary = apply_patches(known.gpu)
    print(f"[test_3][pipeline_one] patches={json.dumps(summary, ensure_ascii=False)}", flush=True)
    sys.argv = [sys.argv[0], *rest]
    from src.cli import main as ap_main

    ap_main()


if __name__ == "__main__":
    main()
