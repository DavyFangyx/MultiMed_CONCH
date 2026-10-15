#!/usr/bin/env python3
"""阶段 2.7:预生成搜索用的字段语义 CONCH 向量缓存(编码与实验解耦)。

搜索 runner(selection/runner.py)对 SEAS 系算法只 load 缓存、不再现场编码
(load_only=True);缓存 key = (tag, dataset),落
results/greedy_lm0/semantics/prompt/{tag}/{ds}/field_semantics.npy(+ .json 身份元数据)。

anchor 变体(--anchor_p)的缓存不在本脚本范围:anchor 依赖 univariate prior,
现行搜索网格(Test_3 / Test_6)不使用 anchor 变体;runner 缺缓存会报错并指向本脚本。

用法(阶段 2,conch 环境解释器由脚本内 DEFAULT_CONCH_PYTHON 指定;纯 CPU):
    python scripts/pregen_field_semantics.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts", ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common.paths import (  # noqa: E402
    DEFAULT_CKPT,
    DEFAULT_GDC_CLINICAL_DICTIONARY,
    dataset_field_bank_dir,
    dataset_field_bank_template_dir,
    test_results_dir,
)
from common.patient_set import main_datasets_by_label_events  # noqa: E402
from greedy.clinic_evaluator import DEFAULT_CONCH_PYTHON  # noqa: E402
from greedy.data import load_field_bank  # noqa: E402
from selection.search.seas import load_or_encode_field_semantics  # noqa: E402

TAGS = ["landmark_0"]  # Test_3 / Test_6 搜索统一 --landmark_time 0(tag 规范 = landmark_0,不是 "0")


def main() -> int:
    datasets = main_datasets_by_label_events(threshold=100)
    failed = 0
    for ds in datasets:
        for tag in TAGS:
            bank = load_field_bank(dataset_field_bank_dir(ds, "prompt", tag), encoding="prompt")
            fields = tuple(bank["fields"])
            cache = test_results_dir("greedy_lm0/semantics") / "prompt" / tag / ds / "field_semantics.npy"
            try:
                matrix = load_or_encode_field_semantics(
                    fields,
                    template_csv=dataset_field_bank_template_dir(ds, tag) / "FIELD_BANK.csv",
                    dictionary_csv=DEFAULT_GDC_CLINICAL_DICTIONARY,
                    checkpoint=DEFAULT_CKPT,
                    cache_path=cache,
                    python_executable=str(DEFAULT_CONCH_PYTHON),
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"[pregen] FAIL {ds} tag={tag}: {exc}", flush=True)
                continue
            print(f"[pregen] {ds} tag={tag} fields={len(fields)} "
                  f"cache={cache} shape={matrix.shape}", flush=True)
    print(f"[pregen] done: {len(datasets) * len(TAGS) - failed}/{len(datasets) * len(TAGS)} 成功", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
