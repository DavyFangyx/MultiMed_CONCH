# Test_2b 去泄露对照(时间轴链主体)

**问题**:论文方案的**组合**报告值有没有被泄露抬高(高估)?Δc = 报告值 − 去泄露值。

**结论**:无数据集级系统性高估;方向一致率最高为 MULTISURV × clinic_cox **10/15**(mean +0.0063,CI 跨 0);幅度均落在折间 std 之内。

**文件角色**:`Main_` = 头条(回答命题)、`Appx_` = 附录(明细)、`Raw_` = 原始矩阵、`Meta_` = 元数据。

| 文件 | 角色 | 它想表达的含义 |
|---|---|---|
| `Main_overview_clinic_cox.png` | 头条图 | 跨方案均值 Δc 条形 + bootstrap CI + 方向一致率直标(Cox)——整体有没有系统性高估 |
| `Main_overview_mlp_clinic_flatten.png` | 头条图 | 同上(MLP) |
| `Main_delta_summary.csv` | 头条表 | 方案 × 分析器 × 档组汇总(效应量、方向一致率、bootstrap CI;wilcoxon 仅数值参考) |
| `Appx_forest_{方案}_{分析器}.png` ×20 | 附录图 | 每方案一张森林图:行 = 数据集,误差棒 = 折内配对 95% CI;Δc>0 = 该数据集上被泄露抬高 |
| `Appx_delta_main.csv` | 附录表 | 主图档(≥100 的 15 + 70–100 的 5)逐 (dataset, scheme, analyzer) Δc 行 |
| `Appx_delta_supp.csv` | 附录表 | 补充档(30–70,4 个数据集) |
| `Appx_delta_low.csv` | 附录表 | 低事件档(<30,9 个,仅定性讨论) |

数据源:`results/Test_2b/arm_A`(报告值)与 `results/Test_2b/arm_B`(去泄露值);生成脚本 `results_display/scripts/Test_2b_delta_report.py`(可复跑,diff=0)。
