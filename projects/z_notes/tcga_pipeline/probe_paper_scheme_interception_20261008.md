# 探查记录:论文方案字段被筛选链(R0–R5)拦截明细(2026-10-08,只读)

用途:R4 豁免、R5 映射、derived 字段处理的决策依据。口径:4 泛癌种方案 × 15 主集 + 6 HGCN × 绑定数据集 = 66 组合、408 个"方案字段-数据集"对。数据源:`rawdata_stats/{ds}/fliter_log/{exclusion_log,field_registry}.csv`(root 口径)+ `landmark_0/` 变体 + raw_json 验证。

## 总量

| 结局 | 次数 |
|---|---|
| kept | 186 |
| R5_derivable | 99 |
| R4_degenerate | 30 |
| R3_coverage | 19(含 8 次 coverage=0.0 = 数据无值) |
| R1_admin | 15(全是 MULTISURV 的 project.project_id,数据集内恒定,删得对) |
| 数据无值(未入日志,raw 0 值) | 15 |
| derived.*(不在筛选链/field bank) | 44 |
| R0_label_leak | **0** |

## R5 拦截(99 次,映射可解)

- `demographic.age_at_index` ×4 方案 ×15 主集 = 60 次(trigger `keep age_at_diagnosis`);
- `diagnoses[].ajcc_pathologic_stage` ×3 方案(INTEGRATIVE_DNN/MULTISURV/SURVPGC)×11 有值主集 = 33 次(trigger `keep t,n,m`);另 GBM R3 无值、LAML/LGG/OV raw 0 值。

## R4 拦截全部案例(30 次;root 口径)

| field | dataset | trigger | coverage / n_unique / mode_share |
|---|---|---|---|
| sex_at_birth | BRCA | mode_share | 0.999089 / 2 / 0.989061(female 1085 / male 12) |
| sex_at_birth | OV | n_unique=1 | 0.965461 / 1 / 1.0(全 female) |
| race | SKCM | mode_share | 0.978723 / 3 / 0.971739 |
| prior_malignancy | BRCA/HNSC/LGG/SKCM/STAD | mode_share | 各 0.960–0.971 |
| synchronous_malignancy | BRCA/HNSC/KIRC/LGG/LIHC/LUAD/LUSC/SKCM/STAD | mode_share | 各 0.969–0.998 |
| synchronous_malignancy | PAAD | n_unique=1 | 全 "No" |
| primary_diagnosis | GBM/OV | mode_share | GBM 0.998331(胶母 1124 vs 腺癌 1) |
| prior_treatment | landmark_0 下 13 主集(BLCA/BRCA/COAD/GBM/HNSC/KIRC/LGG/LIHC/LUAD/LUSC/OV/PAAD/STAD) | mode_share | 0.956–0.998(root 全 kept) |
| site_of_resection_or_biopsy | ESCA/LUSC/LUAD | n_unique=1 | "Esophagus, NOS"/"Lung, NOS" 单值 |
| primary_diagnosis | KIRC/LIHC(landmark_0 变体) | mode_share | 0.974 / 0.955 |

分类:mode_share 触发(有真信号、少数类存在)vs n_unique=1 真常数(数据集内零信息)。R4 豁免决策(2026-10-08)见协议 `field_filter_rules.json` 的 `R4_exempt`。

## R3 与数据无值(数据事实,不可挽回)

- R3 低覆盖有真值:OV 的 t/n/m(3/608)、LGG 的 n/m(1/516)、KIRC pack_years_smoked(21/537)、ESCA cigarettes_per_day(0 值)等。
- 真无值(23 对):GBM 全部 stage 字段(0/617)、LAML/LGG/OV 的 ajcc_pathologic_stage 等。
- 注意:OV/LGG 属"极少数真实值"的低覆盖,与无值不同。

## derived.* 字段(44 对,不在筛选链)

- `pharmaceutical_therapy` / `radiation_therapy`:提取自 `treatments[].treatment_type + treatment_or_therapy`;15 主集 landmark_0 bank **全部无 treatments 层字段**(landmark_0 过滤 t0 后治疗记录)→ 无重合 → 记 missing。
- `years_smoked`:提取自 `exposure_duration_years`(raw 0 值)/ onset-quit year / age_at_onset;仅 **LUSC** bank 含 onset/quit year + pack_years_smoked → 明确重合 → 纳入 bank 派生列(决策 2026-10-08);KIRC bank 无吸烟字段 → missing。
- 受影响的方案:MULTISURV(pharma+rad ×15)、HGCN 6 方案各 2–3 字段。

## landmark_0(= 实际 field bank)与 root 的差异

landmark_0 下新增 R4 两处(其余相同):MULTISURV prior_treatment 13 主集、SURVPGC primary_diagnosis KIRC/LIHC。实际 bank 字段表 = `outputs/{ds}/field_bank/prompt/landmark_0/field_index.json`(BRCA 17、BLCA 32、KIRC 13、LUAD 19 等)。

## 关键文件

- `rawdata_stats/{ds}/fliter_log/exclusion_log.csv`(列:dataset,field,rule,trigger,coverage,n_unique,mode_share,timepoint)
- `rawdata_stats/{ds}/fliter_log/field_registry.csv`
- `templates/manual_schemes/{scheme}/fields.json`(方案字段源)
- `src/manual_pipeline/extract.py`(`_therapy_flag` / `_years_smoked` 提取逻辑)
