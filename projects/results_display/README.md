# results_display

把各数据集 `results/` 里的评测表抽到这里做展示，不改 `outputs/`。

```bash
python results_display/scripts/collect_greedy_cindex.py --dataset all --landmark_time 730
python results_display/scripts/collect_greedy_cindex.py --dataset TCGA-STAD,TCGA-BRCA --landmark_time none
python results_display/scripts/collect_univariate_cindex.py --dataset all --landmark_time none
python results_display/scripts/collect_linear_probe_r2.py --dataset all --landmark_time 730
python results_display/scripts/FigA_Other_Paper_Works.py --dataset all --landmark_time 730
```

产物写到 `results_display/{experiment}/{encoding}/{landmark_tag}/`：

- greedy：`cindex_by_n_fields.png/.csv`，以及 `field_gain_matrix.png/.csv`
- univariate：`field_cindex.csv`
- linear_probe：`numeric_r2.csv`
- FigA other paper works：`results_display/FigA_Other_Paper_Works/{encoding}/{landmark_tag}/`
  - 分数据集 PNG：`per_dataset/{dataset}.png`
  - 33 宫格：`cindex_by_n_fields.png`
  - 论文参考线表：`paper_reference_cindex.csv`

FigA 只画 TCGA。蓝色实线是 greedy 增长曲线；论文字段组合按绑定癌种画彩色水平参考线。缺 c-index 的绑定方案会写进 CSV，但不画线。默认 modality 是 `mlp_clinic_flatten`。

`--dataset` 默认 `all`；`--landmark_time` 必填，和 CLI 一样写成天数或 `none`。纵向实验加 `--experiment longitudinal`。

## Test 系列（spec: `z_notes/Test_series_spec.md`，用法见各脚本 docstring）

### 结果目录索引（先看这个）

| 目录 | 问题 | 结论(一句话) | 入口文件 |
|---|---|---|---|
| `Test_1a_field_level/` | 时间口径 t0 在**单字段**层面改变了什么? | mask 改动的字段 Δc +0.061,未改动 ≈0(噪声本底) | `Main_mask_group_delta.png` + `Main_field_ranking.csv` |
| `Test_1b_dataset_cindex/` | 每个数据集是不是有**各自的最优字段组合**? | top-1 落在 18 个不同字段,k=5 时 47% 数据集对零共享 | `Main_per_dataset_profile.png` + `Main_topk_overlap.png` |
| `Test_2b_delta/` | 论文**组合**报告值有没有被泄露抬高? | 无数据集级系统性高估(MULTISURV×Cox 一致率 10/15) | `Main_overview_*.png` + `Main_delta_summary.csv` |

每个目录内文件角色前缀:`Main_` = 头条(回答命题)、`Appx_` = 附录(明细/主表补充)、`Raw_` = 原始矩阵、`Meta_` = 元数据与审计。目录内 README.md 有逐文件含义。

```bash
python3 results_display/scripts/Test_1a_field_level.py            # Test_1a 单字段泄露对照（mask off vs t0）
python3 results_display/scripts/Test_1a_field_level.py --audit    # 追加 3 组 (dataset, field) 抽查
```

- Test_1a（§5bis，范围 = R13 主集 n_event ≥ 100 的 15 个 TCGA）：两臂同患者集，唯一差异 = 取值 mask 状态
  （off 臂 `results/Test_1a/arm_off/univariate/prompt/landmark_none/`，t0 臂 `results/Test_1a/arm_t0/prompt/landmark_0/`），
  输出 Δc_field = c(off) − c(t0) 交叉表（`results_display/Test_1a_field_level/`）。
  `leak_rate` 列来自 Test_2a 逐字段审计（`results/Test_2a_leak_audit/{dataset}/G1_*.json`）；审计未出数时该列留空标
  `pending_test_2a`，出数后重跑本脚本即自动填列（含 leak×Δc 散点与「能动字段清单」）。
