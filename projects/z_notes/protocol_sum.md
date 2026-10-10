# 数据规则总纲(protocol/)

**规则协议层**:三条规则的**本体与唯一权威**。执行层文档(`Test_series_spec.md` 规格、
`Test_series_execution_log.md` 执行日志、`experiment_list/` 清单与 runbook/usage)
**引用本目录**;冲突时以本目录为准(除非执行日志登记了更新的用户拍板)。

| 编号 | 规则 | 主页 |
|---|---|---|
| **规则0** | 队列与患者筛选:gt≤0 全局剔除 → label 宇宙 → n_event 四档(13 主集) | [`0_cohort_selection/README.md`](0_cohort_selection/README.md) |
| **规则1** | landmark 三要件(时间轴协议) | [`1_landmark/time_axis.md`](1_landmark/time_axis.md) §3/§4 |
| **规则2** | 字段处理(筛选 R0–R6 + 编码基座 + 方案装配) | [`2_field_processing/README.md`](2_field_processing/README.md) |

- 字段规则 **R0–R6 是规则2 内部的实现编号**(代码与历史产物沿用),R0(标签泄露硬排除)**≠ 规则0**。
- 规则1 目录 = 原 `z_notes/time_axis/` 整体迁入(2026-10-10,**内容未动**);规则2 的 `field_filter.md` /
  `frozen_schemes_contract.md` 分别自 `tcga_pipeline/`、`time_axis/` 迁入,内容未动(2026-10-10 起随协议层修订)。
- 评估口径(5 折 `cv_c_mean`、seed 0、max_epochs 12、不伪造独立测试集)暂留在 spec §2,
  **尚未迁入本目录**——迁入前该条仍以 spec §2 为权威(登记为待办,勿误以为协议层已覆盖)。

## 目录结构

```text
protocol/
  README.md                     ← 本页(总纲)
  0_cohort_selection/README.md  ← 规则0 权威(gt≤0 → label 宇宙 → 四档)
  1_landmark/                   ← 原 z_notes/time_axis/
    time_axis.md                  = 规则1 权威协议(landmark 三要件 + t_record 判据)
    t_record_derivation.md        = t_record 推导附录
    index_date_anchor_audit.md    = 轴锚点审计附录
    t_write.md                    = 入库时间审计(另册,不参与泄露判定)
  2_field_processing/
    README.md                     = 规则2 权威(索引)
    field_filter.md               = R0–R6 筛选规则权威(原 z_notes/tcga_pipeline/)
    frozen_schemes_contract.md    = PGC 线冻结契约(原 z_notes/time_axis/)
    probe_*_20261008.md           = R4 豁免 / R5 别名的决策依据探查(原 z_notes/tcga_pipeline/)
```
