# H 系列执行日志

规格与口径唯一来源：`z_notes/H_series_spec.md`。本文件是**所有执行报告的统一归档**，追加写，不另开文件；追加前先重读文件末尾。

## 决策点状态表

| ID | 决策点 | 状态 | 结论 |
|---|---|---|---|
| D0 | S0 删除范围（results/results_display 的 E1/E2/旧 greedy/univariate/linear_probe；是否连 outputs/*/greedy、outputs/*/univariate、Clinic_Analyzer/results 中间产物） | 待确认 | — |
| D1 | H0 门槛与降级规则数值（照搬 event_impact_analysis 建议 vs 调整） | 待确认 | — |
| D2 | landmark 有效事件口径（mask vs 排除患者）+ MMRF 是否纳入 | 待确认 | — |
| D3 | S3 自检（臂 A 与旧 A_manual 数值一致）通过后放量 | 待确认 | — |
| D4 | H2 最优组合口径（sig_stop 推荐 vs 历史 best） | 待确认 | — |
| D5 | 回推：数据集中途降级/剔除 | 待确认 | — |

---

## S-1 准备：规格文档与执行日志

- 时间 / 执行者：2026-09-29 / Claude（主会话）
- 目标：建立 H 系列单步执行框架：规格文档、步骤注册表、决策点清单、执行日志模板与 Git 提交协议。
- 输入：用户实验清单（H1–H4）、`project_overview.md`、`z_notes/E2_Selection_Gain_Algorithm/E2_selection_algorithm_design.md`、`rawdata_stats/_shared/event_impact_analysis/`。
- 命令与参数：无（纯文档）。
- 产物：`z_notes/H_series_spec.md`、`z_notes/H_series_execution_log.md`（本文件）。
- 审计：规格中锁定口径（定量泄露、控制变量、三档、H0 规则、Git 协议）与用户三轮反馈一致。
- 偏差与原因：无。
- 决策点：无新增；D0–D5 注册待确认。
- 状态：完成。
