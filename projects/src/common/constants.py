"""协议数值常量的唯一出处。

与权威文档 z_notes/time_axis/time_axis.md 保持一致:改协议时先改文档,再改这里。
"""

from __future__ import annotations

# 月→天反推与 landmark 平移月数(src/manual_pipeline/landmark_labels.py 使用)。
DAYS_PER_MONTH = 365.25 / 12.0

# PGC 外部标签生产除数(SurvPGC_github_init/dataset_deployment/scripts/pipeline.py
# 把天折算成 survival_months 用的 30.44)。本仓不参与该计算,只登记口径。
LABEL_MONTHS_TO_DAYS = 30.44

# 天→年换算(年龄/年份统计用;与 DAYS_PER_MONTH 同源,但属另一协议侧面)。
DAYS_PER_YEAR = 365.25

# landmark 取值集合(与 --landmark_time 的合法取值一致)。
LANDMARK_TIMES = (0, 365, 730)
