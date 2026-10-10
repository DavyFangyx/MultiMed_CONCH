# Projects：TCGA 临床生存预测实验（Test_ 系列）

对 33 个 TCGA 队列做生存预测（OS，c-index），临床字段经 CONCH 编码。两条论证链：**时间轴链**（论文工作未做时间处理 → 高估，Test_2）与**字段轴链**（论文工作未做字段选择 → 低估，Test_3）；Test_1 为动机层，Test_4 三档表收口，Test_5 不变性。

## 文档导航

| 文档 | 内容 |
|---|---|
| `z_notes/experiment_list/experiment_list.md` | 实验清单与协议速查 |
| `z_notes/Test_series_spec.md` | Test_ 系列唯一口径来源与步骤注册表 |
| `z_notes/Test_series_execution_log.md` | 执行日志与单步登记（2026-10-05 起新格式，见文件末尾） |
| `z_notes/protocol/1_landmark/time_axis.md` | 时间轴协议（landmark 三要件、t_record 判据） |
| `z_notes/experiment_list/naming_convention.md` | configs/results/results_display 目录命名公约 |
| `z_notes/protocol/README.md` | 数据规则总纲(规则0/1/2 索引) |
| `z_notes/search_algorithm/Test_6_search_algorithms.md` | 搜索算法速查(实现以 `src/selection/` 代码为准) |
| `scripts/run_a_manual.py`（`--help`）+ `src/manual_pipeline/` 包 docstring | 特征提取与 landmark 编码管线（原 `A_pipeline/`，已吸收进主项目） |
| `Clinic_Analyzer/README.md` | 训练/评估器 |
| `rawdata_stats/README.md` | rawdata_stats 统计阶段 |
| `results/README.md`、`results_display/README.md` | 结果目录布局 |

## Git 约定

只有**明确的决策点**才提交（见 `z_notes/Test_series_spec.md` §9）；脚本小改、改名、决策点的单步实现不单独提交。每次改动在 `z_notes/Test_series_execution_log.md` 的"改动登记"表追加一行：改动名称 | git 提交 | 时间 | 简单描述。
