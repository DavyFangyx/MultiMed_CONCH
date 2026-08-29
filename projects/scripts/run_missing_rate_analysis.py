import sys


if __name__ == "__main__":
    sys.exit(
        "run_missing_rate_analysis.py 已拆分。\n"
        "  JSON 全字段统计: python projects/scripts/run_field_stats.py --dataset all\n"
        "  R0-R6 筛选: python projects/scripts/run_field_filter.py --dataset all"
    )
