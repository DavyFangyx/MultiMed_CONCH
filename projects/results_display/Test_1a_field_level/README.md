# Test_1a 单字段泄露对照(时间轴链动机)

**问题**:时间口径 t0 在**单字段**层面改变了什么?

**准入口径**(2026-10-05,规格 §5bis.1):先 landmark 再筛选——字段统计在 t0 mask 上重算,
按 R3_coverage=0.30 / R4_n_unique=2 / R4_mode_share=0.95 过 R0-R6;t0 口径下覆盖率崩塌或
值退化的字段(其 t0 臂基本是全占位符常数特征,c≈0.5)不计入头条统计,单列
`Appx_excluded_fields.csv`。产物:`rawdata_stats/{dataset}/landmark_0/field_stats.csv` +
`landmark_0_t0stats/`(脚本 `scripts/run_landmark_first_filter.py`,验收
`scripts/validate_t0stats_vs_masks.py`,35 数据集与 t0 臂 .pt mask 比对 max_abs_diff ≤ 5e-7)。

**结论**(15 主集 468 对;准入集 296 对,排除 172 对 = R3_coverage 124 + R4_degenerate 48,
数字见 `Meta_metrics.json`):
- 准入集 Δc 均值 **−0.0010**、中位 0、极值 −0.098~+0.035;取值被 mask 改动的字段
  (114 行)Δc 均值 **−0.0045**、中位 −0.0016,取值未改动(182 行)= 编码噪声本底
  (均值 +0.0013、p90 |Δc| 0.014)。
- **口径修正后,此前"效应集中在 mask 改动字段(+0.034)"的结论不再成立**——旧头条数字
  主要由 t0 覆盖率崩塌的字段(治疗后槽位、follow_up 等)驱动,其 t0 臂是常数占位符,
  Δc ≈ c(off) − 0.5,属于"字段整个消失"的伪效应。在被排除字段内
  (leak_rate≈1.0,见 `Appx_excluded_fields.csv`),Δc 依然可达 +0.15~+0.25——
  这部分是"字段只有泄露值可用"的真实效应,但按 t0 口径它们不应进入单字段评估。
- 准入集内 143 正 / 134 负 / 19 零;|Δc| ≥ 0.01 的 73/296(24.7%);influential 清单
  (leak_rate > 0.05 且 |Δc| ≥ 0.01)由 97 行降为 **8** 行。

**文件角色**:`Main_` = 头条(回答命题)、`Appx_` = 附录(明细/主表补充)、`Raw_` = 原始矩阵、`Meta_` = 元数据与审计。

| 文件 | 角色 | 它想表达的含义 |
|---|---|---|
| `Main_mask_group_density.png` | 头条图(新版) | 同一结论的密度直方图版:共享分箱,灰山=取值未改动(噪声本底)、红/蓝=被 mask 改动(按箱符号分色,红=off 臂更高=泄露方向);本底 5–95% 走廊 + 最大值虚线;右上关键数字、标题带 KS D/p |
| `Main_mask_group_delta.png` | 头条图(旧版,保留) | Δc 分组点图:被 mask 改动的字段 vs 未改动的字段(噪声本底)——脚本仍生成,作对照留存 |
| `Main_field_ranking.csv` | 头条表 | 条件化字段汇总(只统计准入集内取值确实被 mask 改动的行):`n_datasets_total` / `n_datasets_affected` / `median_delta_among_affected` / `frac_abs_delta_ge_0p05`(一致性) / `max_abs_delta`;按 affected 中位 Δc 降序,无 affected 数据集的字段排表尾——**哪些字段的泄露值得关注**(大小 × 涉及面 × 一致性) |
| `Appx_off_vs_t0.png` | 附录图 | 每字段 c(off) vs c(t0) 散点;偏离对角线 = 时间口径造成的差异 |
| `Appx_delta_by_dataset.png` | 附录图 | 逐数据集 Δc 箱线(按 n_event 排序)——效应在哪些数据集更明显 |
| `Appx_delta_distribution.png` | 附录图 | Δc 分布形态(全体 + 逐数据集条带) |
| `Appx_field_delta.csv` | 附录表 | 逐 (dataset, field) 完整明细(全部 468 行):c_t0 / c_off / Δc / leak_rate / coverage_off / coverage_t0 / t0_filter_status / t0_filter_rule / t0_filter_trigger |
| `Appx_dataset_summary.csv` | 附录表 | 逐数据集 Δc 汇总(均值/中位/极值、非平凡占比、Top ± 字段) |
| `Appx_influential_fields.csv` | 附录表 | "能动组合结论的字段清单"(leak_rate 高且 \|Δc\| 大;准入集内) |
| `Appx_excluded_fields.csv` | 附录表 | landmark-first 被排除字段(172 行):rule / trigger / coverage_t0 / coverage_off / c_t0 / c_off / Δc / leak_rate |
| `Appx_leak_vs_delta.png` | 附录图 | x=leak_rate, y=Δc_field(准入集) |
| `Raw_delta_matrix.csv` | 原始矩阵 | dataset × field Δc 对齐矩阵(准入集) |
| `Meta_metrics.json` | 元数据 | 头条量化数字 + 准入口径键(n_excluded_fields / excluded_by_rule / excluded_by_dataset / coverage_join) |
| `Meta_audit.json` | 元数据 | `--audit` 抽查记录(数字可信度) |

生成脚本:`results_display/scripts/Test_1a_field_level.py`(可复跑,diff=0)。

条件产物 `Appx_leak_vs_delta.png`(leak_rate × Δc 散点):Test_2a 逐字段审计
(`results/Test_2a_leak_audit/{dataset}/G1_*.json`)出数后由脚本自动生成(审计已出数,
当前目录内有此文件)。
