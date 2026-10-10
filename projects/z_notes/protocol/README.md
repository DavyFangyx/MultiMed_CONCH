# 数据规则总纲(protocol/)

规则分层索引。实验口径唯一来源不变:`z_notes/Test_series_spec.md`(规格)与 `z_notes/Test_series_execution_log.md`(执行日志);本目录只做规则的编号与归位,不改写任何现有口径。

| 编号 | 规则 | 主页 |
|---|---|---|
| **规则0** | 队列与患者筛选:gt≤0 全局剔除 → label 宇宙 → n_event 四档 | [`0_cohort_selection/README.md`](0_cohort_selection/README.md) |
| **规则1** | landmark 三要件(时间轴协议) | [`1_landmark/time_axis.md`](1_landmark/time_axis.md) §3/§4 |
| **规则2** | 字段处理(筛选 R0–R6 + 编码基座 + 方案装配) | [`2_field_processing/README.md`](2_field_processing/README.md) |

- 字段规则 **R0–R6 是规则2 内部的实现编号**(代码与历史产物沿用),R0(标签泄露硬排除)**≠ 规则0**。
- 规则1 目录 = 原 `z_notes/time_axis/` 整体迁入(2026-10-10,**内容未动**);规则2 的 `field_filter.md` / `frozen_schemes_contract.md` 分别自 `tcga_pipeline/`、`time_axis/` 迁入,**内容未动**。
- 评估协议(5 折 `cv_c_mean`、seed 0、max_epochs 12、不伪造独立测试集)等实验口径仍以 spec §2 为准,不迁入本目录。

## 目录结构

```text
protocol/
  README.md                     ← 本页
  0_cohort_selection/README.md  ← 规则0 主页(索引页;权威口径在 spec 与 1_landmark/time_axis.md)
  1_landmark/                   ← 原 z_notes/time_axis/
    time_axis.md                  = 规则1 权威协议(landmark 三要件 + t_record 判据)
    t_record_derivation.md        = t_record 推导附录
    index_date_anchor_audit.md    = 轴锚点审计附录
    t_write.md                    = 入库时间审计(另册,不参与泄露判定)
  2_field_processing/
    README.md                     = 规则2 主页(索引页)
    field_filter.md               = R0–R6 筛选规则权威(原 z_notes/tcga_pipeline/)
    frozen_schemes_contract.md    = PGC 线冻结契约(原 z_notes/time_axis/)
```
