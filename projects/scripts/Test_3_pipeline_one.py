"""Test_3 三臂用 manual pipeline 单次入口（原 A_pipeline 进程内补丁已退休）。

历史背景：A_pipeline 独立子项目时代有两处缺口，本入口曾用**进程内补丁**绕过
（不动其源文件，因其工作树有他人未提交修改）：
  1) 方案白名单：``cindex.expand_cindex_jobs`` 只认静态 ``PAPER_SCHEMES``，Test_3_*
     自定义方案（登记在 templates 的 schemes.json `_schemes`）会被判「未知 cindex 方案」；
  2) 编码 GPU：``encode.run_encode`` 无条件写 ``CUDA_VISIBLE_DEVICES=DEFAULT_GPU``（=7）。

吸收进主项目时两处都已在**源头**修好：
  1) ``manual_pipeline.cindex.expand_cindex_jobs`` 接受 config 里已注册的任意方案
     （templates/manual_schemes/{scheme}，无需进程内 append）；
  2) encode 的可见 GPU 走 ``--gpu`` > 环境变量 ``A_PIPELINE_GPU`` > 7。
因此本入口退化为 thin wrapper：只把 ``--gpu`` 透传给 ``manual_pipeline.cli.main``。

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
for _p in (ROOT, ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SCHEMES_JSON = ROOT / "templates" / "manual_schemes" / "schemes.json"


def registered_test3_schemes(schemes_json: Path = SCHEMES_JSON) -> list[str]:
    """templates/manual_schemes/schemes.json 里登记的 Test_3_* 方案（诊断用）。"""
    payload = json.loads(Path(schemes_json).read_text(encoding="utf-8"))
    return [name for name in payload.get("_schemes", []) if str(name).startswith("Test_3")]


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--gpu", default=None, help="encode 可见 GPU，透传给 CLI 的 --gpu")
    parser.add_argument(
        "--print-schemes",
        action="store_true",
        help="打印 templates/manual_schemes/schemes.json 登记的 Test_3_* 方案后退出",
    )
    known, rest = parser.parse_known_args(argv)
    if known.print_schemes:
        print(json.dumps(registered_test3_schemes(), ensure_ascii=False))
        return
    if known.gpu not in (None, ""):
        print(
            f"[test_3][pipeline_one] gpu={known.gpu}"
            "（白名单 / GPU 已在 manual_pipeline 源头修好，无需进程内补丁）",
            flush=True,
        )
        rest = ["--gpu", str(known.gpu), *rest]
    from manual_pipeline.cli import main as ap_main

    ap_main(rest)


if __name__ == "__main__":
    main()
