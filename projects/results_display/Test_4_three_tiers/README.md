# Test_4 三档汇总表（报告值 / 去泄露值 / 可达值）

**问题**：论文报告值 → 去泄露值 → 可达值，三档之间差多少？每 (dataset, work) 一行：

- 档 1 **报告值** = `results/Test_2b/arm_A/{dataset}[gdc]/cindex.csv` 的 `{work}` 行（论文报告原值）
- 档 2 **去泄露值** = `results/Test_2b/arm_B/{dataset}[gdc]/cindex.csv` 的 `{work}__landmark_0` 行（S6 已修复口径）
- 档 3 **可达值** = `results/Test_3_greedy_vs_works/two_arm.csv` 的 `C_c`（Test_3 臂 C：贪婪最优 × bank 模板）
- 档间 Δ：**Δ1 = 报告 − 去泄露**（泄露高估幅度）、**Δ2 = 去泄露 − 可达**（同协议下工作字段 vs 贪婪最优的差距）

主口径 analyzer = `mlp_clinic_flatten`；`clinic_cox` 作交叉列。**缺臂哲学**与 `Test_3_compare.py` 一致：
缺可达值的行**整行保留**、C 相关列记 `pending`（不中断）；arm_A 无该行时报告列记 `n/a`（该工作未报告该数据集）。

**结论（局部预览，可达值 25/64 行）**：

- Δ1（42 个有报告值的行）：mean **−0.0032**、median **+0.0001** —— 与 Test_2b 主结论一致，**无数据集级系统性高估**。
- Δ2（25 个有可达值的行）：mean **+0.0272**、median **+0.0425** —— 去泄露后工作组合平均仍比 greedy 可达值高约 0.03；
  仅 5/25 行可达值反超（PAAD 3 行、KIRC 2 行）。Δ2 与 Test_3 **交叉核对口径** Δc=C−B 互为镜像
  （two_arm.csv `delta_C_minus_B`；bank-only 口径 T31，scheme 交叉对照已退役）。
- 可达值 pending 的 9 个数据集：BLCA、BRCA、COAD、HNSC、LUAD、LUSC、SKCM、STAD、TCGA_LIHC（各 4 组合，+ HGCN_LUAD/LUSC/LIHC）。

| 文件 | 角色 | 含义 |
|---|---|---|
| `Main_three_tiers.csv` | 头条表 | 64 行 = 15 主集 × 工作组合；三档值 + Δ1/Δ2 + cox 交叉列 + 状态（`ok` / `pending_C`） |
| `Main_three_tiers.png` | 头条图 | 逐数据集三档均值柱状图(橙=报告/蓝=去泄露/绿=可达;仅含可达值就绪的 6 个数据集,柱上标 n works) |
| `Appx_three_tiers_by_work.png` | 附录图 | 逐工作三档均值柱状图(跨可达值就绪数据集聚合,柱上标 n datasets) |
| `Main_tier_summary.csv` | 头条表 | 按协议 A 四档聚合（行数 / pending 数 / 无报告值数 / Δ1、Δ2 均值中位） |

**列字典**（`Main_three_tiers.csv`）：`dataset, work, tier, n_event, n_fields_work`（工作组合字段数，读模板）;
`report_c/std`（档 1）; `deleak_c/std`（档 2）; `delta_report_minus_deleak`（Δ1）;
`reach_c/std`（档 3 = Test_3 臂 C）、`reach_b_c/std`（bank 模板工作组合臂 B）;
`delta_deleak_minus_reach`（Δ2）、`delta_C_minus_B`（Test_3 头条口径，直接引用 two_arm.csv）;
`n_fields_greedy, n_missed`（Test_3 搜索口径）; `report_cox_c, deleak_cox_c, delta_report_minus_deleak_cox`（cox 交叉列）;
`status`（`ok` = 有可达值；`pending_C` = 无）。

**分层**：协议 A 四档由 `n_event` 决定（`main` ≥100 / `main_ci` 70–100 / `supp` 30–70 / `low` <30），
n_event 从 Test_0 manifest 与 `rawdata_stats/_shared/event_summary.csv` 交叉核对读取（不硬编码）。
当前范围 = R13 主集（n_event ≥100），故 64 行全为 `main` 档；四档机制为后续扩大范围预留。

**数据源与复跑**：`results/Test_2b/arm_A`（报告值）、`results/Test_2b/arm_B`（去泄露值）、
`results/Test_3_greedy_vs_works/two_arm.csv`（可达值）；脚本 `results_display/scripts/Test_4_three_tiers.py`，
`python3 results_display/scripts/Test_4_three_tiers.py [--audit]`（`--audit` = 前 2 个可达值行三档逐位抽查：
源表重读 + 折文件重算 + Δ 手算 + cox 列同源核对）。

**状态（预览版）**：

- 可达值 25/64 行（6/15 数据集：GBM、KIRC、LAML、LGG、OV、PAAD），39 行 `pending_C`；15 集齐后重出完整版。
- 可达值产自 Test_3 **旧 sig 停点**（δ=0.005 + Wilcoxon 门控）；D4 修订（2026-10-04，`stop_mode=gain_only`）
  后如需重出，对应数据集 C 值会变，本表随 two_arm.csv 一起更新。
