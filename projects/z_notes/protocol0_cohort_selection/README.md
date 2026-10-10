# 规则0:队列与患者筛选(权威)

**一句话**:先做患者级 gt≤0 全局剔除得到 **label 宇宙**,再在 label 宇宙上数有效事件做数据集分档。
本页是规则本体——**执行层文档(Test_series_spec / runbook / experiment_list)引用本页,本页不引用执行层口径**。

## 0.1 患者层:gt≤0 全局剔除(2026-10-05 拍板)

- **规则**:`ground_truth_time ≤ 0` 的患者(`days_to_death=0` 占位坑 + 负末次随访)从**所有实验的所有臂**
  (含 report/raw 对照臂)全局剔除;NaN 时间保留;split 文件不动。
- gt 的定义与占位坑依据:规则1 [`../1_landmark/time_axis.md`](../1_landmark/time_axis.md) §2.2 / §2.3。
- 实现落点:`Clinic_Analyzer/datasets/dataset_survival.py::_drop_nonpositive_time_labels`(读 label 后即过滤,
  运行时安全网;当前 label 本身已不含 gt≤0 行)。

## 0.2 患者宇宙 = label metadata(2026-10-09 拍板)

- **权威患者宇宙 = Clinic_Analyzer 的 label metadata**(评估宇宙 = label ∩ split ∩ embeddings)。
- **前置过滤**:gt≤0 等不可靠患者在**字段级统计/筛选/编码之前**即被剔除——字段链病例加载收敛到
  label 宇宙(`src/common/patient_universe.py`:统计分母、bank 患者集、词表拟合都只有可靠患者)。
- 审计工具(event_stats / time_stats / leak audit / presence / scan)**保持原始口径**——职责是数清杂质,
  不是实验口径。
- **split 对齐判据**:每数据集 **split 并集 == label 患者集**;split 是否按 label 宇宙重生成(seed 1)
  属于执行待拍板(见执行日志 T38 补),不影响本规则。

## 0.3 数据集层:协议 A 四档(2026-10-09 修订:计数口径 = label 宇宙有效事件)

- **计数**:`n_event_label` = label metadata 中 censorship==0 的行数(raw n_event 含从不进训练的病例,
  不再用于门槛;event_summary / manifest 的 `n_event_label` 列为审计对照)。
- **四档**:

  | n_event_label | 处理 | 数据集 |
  |---|---|---|
  | ≥ 100 | 主图,干净集(训练/搜索只在此档新增训练) | **13 主集**:BLCA / BRCA / GBM / HNSC / LAML / LGG / LUAD / LUSC / OV / PAAD / SKCM / STAD / LIHC(COAD 90、KIRC 86 出主集) |
  | 70–100 | 进主图,必须报告 CI,不参与严格排名 | CESC / MESO / ESCA / UCEC / SARC / COAD / KIRC |
  | 30–70 | 补充材料,bootstrap CI,不排名 | UVM / ACC / UCS / KIRP |
  | < 30 | 定量图不收录;单列"低事件组"定性讨论 | 9 个低事件集 |

- 名单**不硬编码**,派生自 `common.patient_universe::main_datasets_by_label_events(threshold=100)`。

## 0.4 作废口径(勿再引用)

- D1 暂定档(≥150/70/30、event_rate<0.1 降级、EPV 每折≥10×字段数、manifest `provisional` tier 列):
  已由协议 A(≥100 四档)取代;历史明细见执行日志 D4 / D5 / T39。
