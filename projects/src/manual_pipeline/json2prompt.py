"""Scheme prompt 生成 —— 已退役(2026-10-07,决策:编码统一 bank-only)。

句式模板(template.csv)是历史遗留的第二编码源,已全部删除;任何字段组合
(论文方案 / 贪婪最优)的编码一律走 field bank 切片路径,见
``scripts/Test_3_custom_scheme.materialize_bank_subset``。

本模块保留为快速失败桩:任何仍调用 json2prompt 的旧链路会立即报错,
而不是静默产出与 bank 口径不一致的 prompts。
"""

from __future__ import annotations

import sys


def run_json2prompt(*args, **kwargs):
    raise SystemExit(
        "[json2prompt] 已退役:句式模板(template.csv)已删除,编码统一走 field bank 切片。"
        "请改用 scripts/Test_3_custom_scheme.materialize_bank_subset(按字段索引切片 bank 嵌入矩阵)。"
    )


def main(argv=None) -> int:
    return run_json2prompt()


if __name__ == "__main__":
    sys.exit(main())
