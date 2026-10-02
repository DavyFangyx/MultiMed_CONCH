# Test_1a 单字段泄露对照(时间轴链动机)

**问题**:时间口径 t0 在**单字段**层面改变了什么?

**结论**(全量 15 主集最终数字,见 `Meta_metrics.json`):取值被 mask 改动的字段(267 字段行)Δc 均值 **+0.034**、中位 +0.005、极值 −0.098~+0.247;取值未改动的字段(201 行)= 编码噪声本底(均值 **+0.0011**、中位 ~0、p90 |Δc| 0.014)→ 时间处理确实改变单字段评估值,且效应集中在被 mask 改动的字段上(本底比效应小一个数量级)。

**文件角色**:`Main_` = 头条(回答命题)、`Appx_` = 附录(明细/主表补充)、`Raw_` = 原始矩阵、`Meta_` = 元数据与审计。

| 文件 | 角色 | 它想表达的含义 |
|---|---|---|
| `Main_mask_group_delta.png` | 头条图 | Δc 分组对比:被 mask 改动的字段 vs 未改动的字段(噪声本底)——**全实验唯一主结论** |
| `Main_field_ranking.csv` | 头条表 | 条件化字段汇总(只统计取值确实被 mask 改动的行):`n_datasets_total` / `n_datasets_affected` / `median_delta_among_affected` / `frac_abs_delta_ge_0p05`(一致性) / `max_abs_delta`;按 affected 中位 Δc 降序,无 affected 数据集的字段排表尾——**哪些字段的泄露值得关注**(大小 × 涉及面 × 一致性) |
| `Appx_off_vs_t0.png` | 附录图 | 每字段 c(off) vs c(t0) 散点;偏离对角线 = 时间口径造成的差异 |
| `Appx_delta_by_dataset.png` | 附录图 | 逐数据集 Δc 箱线(按 n_event 排序)——效应在哪些数据集更明显 |
| `Appx_delta_distribution.png` | 附录图 | Δc 分布形态(全体 + 逐数据集条带) |
| `Appx_field_delta.csv` | 附录表 | 逐 (dataset, field) 完整明细:c_t0 / c_off / Δc / leak_rate(待 Test_2a) |
| `Appx_dataset_summary.csv` | 附录表 | 逐数据集 Δc 汇总(均值/中位/极值、非平凡占比、Top ± 字段) |
| `Appx_influential_fields.csv` | 附录表 | "能动组合结论的字段清单"(leak_rate 高且 \|Δc\| 大;审计出数前为空表) |
| `Raw_delta_matrix.csv` | 原始矩阵 | dataset × field Δc 对齐矩阵(底层数据) |
| `Meta_metrics.json` | 元数据 | 头条量化数字 + 覆盖度 |
| `Meta_audit.json` | 元数据 | `--audit` 抽查记录(数字可信度) |

生成脚本:`results_display/scripts/Test_1a_field_level.py`(可复跑,diff=0)。

条件产物 `Appx_leak_vs_delta.png`(leak_rate × Δc 散点):仅当 Test_2a 逐字段审计
(`results/Test_2a_leak_audit/{dataset}/G1_*.json`)出数后重跑脚本才生成;当前审计未出数,目录内无此文件。
