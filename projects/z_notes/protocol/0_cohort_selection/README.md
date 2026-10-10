# 规则0:队列与患者筛选(索引页)

**一句话**:先做患者级 gt≤0 全局剔除得到 **label 宇宙**,再在 label 宇宙上数有效事件做数据集分档——**label 宇宙有效事件 = gt≤0 全局剔除后的结果**,两件事同口径(T38/T39)。权威口径在下列出处,本页不重写。

## 患者层:gt≤0 全局剔除

- 权威口径:[`../1_landmark/time_axis.md`](../1_landmark/time_axis.md) §2.3(2026-10-05 拍板)与 `z_notes/Test_series_spec.md` §2.5「患者资格」条。
- `days_to_death=0` 占位坑 + 负末次随访;NaN 保留;split 文件不动;落点 `Clinic_Analyzer/datasets/dataset_survival.py::_drop_nonpositive_time_labels`。

## 数据集层:协议 A 四档(label 宇宙有效事件)

- 权威口径:`z_notes/Test_series_spec.md` §4(Test_0 规格)与 §12 U1(**2026-10-09 修订:门槛计数口径 = label 宇宙有效事件**,主集收敛为 13 个)。
- ≥100 主图 13 主集 / 70–100 带 CI 不排名 / 30–70 补充 / <30 定性(训练实验不跑,仅 Test_2a 审计)。
- 训练范围:只在 13 主集新增训练(T12,2026-10-09 修订);名单只读 `results/Test_0_dataset_availability/manifest.csv`,不硬编码。
- 执行口径(训练 vs 报告)速查:`z_notes/experiment_list/experiment_list.md` 核心口径。

## 患者宇宙前置过滤与 split

- 患者级前置过滤在字段级统计/筛选/编码**之前**(T38):字段链统计分母 = label 宇宙(见 `runbook.md` 阶段 1 ②)。
- split 判据:每数据集 **split 并集 == label 患者集**(`runbook.md` 阶段 1 ⓪);split 是否按 label 宇宙重生成 = 待拍板(执行日志 T38 补)。
