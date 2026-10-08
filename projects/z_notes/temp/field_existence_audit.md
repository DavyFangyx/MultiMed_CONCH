# 论文字段存在性审计：字段在数据集中"根本不存在"问题

> 生成日期：2026-10-05。只读审计，未改任何代码/数据/实验。
> 问题来源：用户怀疑论文方案使用的字段在部分数据集中根本不存在（如"方案用了 field1，但 field1 在数据集 a 中没有"）。

## 1. 结论摘要

**是的，确认存在该问题。** 按实际方案×数据集绑定（spec §2.4：4 泛癌种方案 × 33 TCGA + 6 HGCN × 本癌种）枚举全部 **840 个 (数据集, 方案, 字段) 组合**：

| 档 | 判据 | 组合数 | 受影响数据集 |
|---|---|---|---|
| 档 1：根本不存在 | field_stats 无该字段行（原始 JSON 无键）或 coverage=0（有键全空） | **29** | DLBC、ESCA、**GBM★**、**LAML★**、**LGG★**、**OV★**（★=15 训练主集） |
| 档 2：近零 | 0 < coverage < 0.05 | **60** | ACC、CESC、OV、PCPG、PRAD、SARC、THYM、UCEC、UCS、LGG、KIRC 等 |

**最严重的 4 个主集**（字段全员常量占位符，见 §4 实证）：

- **TCGA-LAML**：AJCC stage/T/N/M 全部无键 → MULTISURV/SURVPGC/MMSURV/INTEGRATIVE_DNN 的 stage/TNM 特征全为 `"Stage X"`/`"TX"/"NX"/"MX"` 常量。
- **TCGA-GBM**：stage/T/N/M coverage=0.000 → 同上，全常量。
- **TCGA-LGG**：stage 无键、T 无键、N/M 近零（0.2%）→ stage/T 全常量。
- **TCGA-OV**：AJCC stage 无键，但 `figo_stage` 覆盖率 0.957，extract.py 的 FIGO fallback 生效 → **实际非常量**（有值，只是来源是 FIGO 而非 AJCC）。

## 2. 机制：占位符 fallback 掩盖字段不存在

论文方案通路对**全部数据集硬编码同一组 22 个字段**，提取时没有任何存在性检查，缺失静默替换为占位符：

`A_pipeline/src/extract.py:95-165`（`extract_values()`）：

| 占位符 | 触发字段 | 行号 |
|---|---|---|
| `"Stage X"` | `ajcc_pathologic_stage`（fallback 链：ajcc → figo_stage → "Stage X"） | extract.py:147 |
| `"TX"/"NX"/"MX"` | `ajcc_pathologic_t/n/m` | extract.py:144-146 |
| `"not reported"` | tumor_grade、prior_malignancy、bmi、alcohol 等 | extract.py:140-153 |
| `"unknown"` | pack_years_smoked、cigarettes_per_day 等 | extract.py:157,159 |

消费方无条件接收占位符：`json2prompt.py:31-33` 直接 `vals.get(field, "not reported")` 填入 prompt 模板；onehot/基线编码同理。因此"字段不存在"不报错、不留痕，只表现为**全数据集同一常量值**（常量特征对 c-index 无信息量，但论文字段表与 prompt 文本失实）。

## 3. 判据与数据来源

- **数据**：`rawdata_stats/{DS}/field_stats.csv`（原始 JSON 全量扫描口径；`field_path` + `coverage` 列）。无该 `field_path` 行 = 原始 GDC JSON 中该键不存在；coverage=0 = 有键但全空/全哨兵。
- **字段**：`A_pipeline/templates/{scheme}/fields.json`（10 方案）。注意 fields.json 内的 `datasets` 键是旧全绑定、已作废（S2b），本审计按 spec §2.4 实际绑定。
- **绑定**：MULTISURV/SURVPGC/MMSURV/INTEGRATIVE_DNN × 33 TCGA；HGCN_* × 本癌种（KIRC→KIRC、LIHC→LIHC、ESCA→ESCA、LUSC→LUSC、LUAD→LUAD、UCEC→UCEC）。
- **排除**：`derived.*`（pharmaceutical_therapy/radiation_therapy/years_smoked）与 `project.project_id` 为 extract.py 计算字段，不在原始扫描范围，不参与分档（其底层缺失已在 `A_pipeline/z_notes/paper_tcga_field_mapping.md` 记录）。
- 命名坑：`TCGA_LIHC` 为下划线注册名（datasets.json:77）。

## 4. 档 1 完整清单：根本不存在（29 项）

### 4.1 按方案 × 数据集

| 方案 | 数据集 | 字段 | 实况 | 主集 |
|---|---|---|---|---|
| MULTISURV | TCGA-DLBC | ajcc_pathologic_stage | 无键 → 全 "Stage X" | |
| MULTISURV | TCGA-GBM | ajcc_pathologic_stage | coverage=0.000 → 全 "Stage X" | ★ |
| MULTISURV | TCGA-LAML | ajcc_pathologic_stage | 无键 → 全 "Stage X" | ★ |
| MULTISURV | TCGA-LGG | ajcc_pathologic_stage | 无键 → 全 "Stage X" | ★ |
| MULTISURV | TCGA-OV | ajcc_pathologic_stage | 无键，但 FIGO 0.957 救回 | ★ |
| SURVPGC | TCGA-DLBC | ajcc_pathologic_stage | 无键 → 全 "Stage X" | |
| SURVPGC | TCGA-GBM | ajcc_pathologic_stage / ajcc_staging_system_edition | 均 0.000 → 全占位 | ★ |
| SURVPGC | TCGA-LAML | ajcc_pathologic_stage / ajcc_staging_system_edition | 均无键 → 全占位 | ★ |
| SURVPGC | TCGA-LGG | ajcc_pathologic_stage / ajcc_staging_system_edition | 均无键 → 全占位 | ★ |
| SURVPGC | TCGA-OV | ajcc_pathologic_stage | 无键，但 FIGO 0.957 救回 | ★ |
| MMSURV | TCGA-DLBC | ajcc_pathologic_t/n/m | 均无键 → 全 "TX/NX/MX" | |
| MMSURV | TCGA-GBM | ajcc_pathologic_t/n/m | 均 0.000 → 全 "TX/NX/MX" | ★ |
| MMSURV | TCGA-LAML | ajcc_pathologic_t/n/m | 均无键 → 全 "TX/NX/MX" | ★ |
| MMSURV | TCGA-LGG | ajcc_pathologic_t | 无键 → 全 "TX" | ★ |
| INTEGRATIVE_DNN | TCGA-DLBC | ajcc_pathologic_stage | 无键 → 全 "Stage X" | |
| INTEGRATIVE_DNN | TCGA-GBM | ajcc_pathologic_stage | 0.000 → 全 "Stage X" | ★ |
| INTEGRATIVE_DNN | TCGA-LAML | ajcc_pathologic_stage | 无键 → 全 "Stage X" | ★ |
| INTEGRATIVE_DNN | TCGA-LGG | ajcc_pathologic_stage | 无键 → 全 "Stage X" | ★ |
| INTEGRATIVE_DNN | TCGA-OV | ajcc_pathologic_stage | 无键，但 FIGO 0.957 救回 | ★ |
| HGCN_ESCA | TCGA-ESCA | exposures[].cigarettes_per_day | coverage=0.000（185 条非空 0）→ 全 "unknown" | |

（MULTISURV 5 项 + SURVPGC 8 项 + MMSURV 10 项 + INTEGRATIVE_DNN 5 项 + HGCN_ESCA 1 项 = 29 项）

### 4.2 关键观察

- **GBM/LAML/LGG 无任何救回路径**：`figo_stage` 在 GBM coverage=0.000、LAML/LGG/DLBC 无键 → 全部患者拿常量 `"Stage X"`。
- **OV/CESC/UCEC/UCS 有 FIGO 救回**：figo_stage 覆盖率 OV 0.957 / CESC 0.951 / UCEC 0.979 / UCS 1.000 → 档 1 的 stage 实际非常量，但取值来源是 FIGO 而非 fields.json 声称的 AJCC。
- DLBC 属低事件组（n_event<30 定性档），影响较小但仍全常量。

## 5. 档 2 完整清单：近零（60 项，0 < coverage < 0.05）

| 方案 | 数据集 | 字段 | coverage | 主集 |
|---|---|---|---|---|
| MULTISURV | ACC / CESC / PCPG / PRAD / SARC / THYM / UCEC / UCS | ajcc_pathologic_stage | 0.008–0.023 | |
| MULTISURV | TCGA-OV | prior_malignancy / synchronous_malignancy | 0.020 | ★ |
| SURVPGC | ACC / CESC / PCPG / PRAD / SARC / THYM / UCEC / UCS | ajcc_pathologic_stage + ajcc_staging_system_edition | 0.008–0.035 | |
| SURVPGC | TCGA-OV | ajcc_staging_system_edition | 0.002 | ★ |
| MMSURV | ACC / PCPG / SARC / THYM / UCEC / UCS | ajcc_pathologic_t/n/m | 0.017–0.035 | |
| MMSURV | TCGA-LGG | ajcc_pathologic_n/m | 0.002 | ★ |
| MMSURV | TCGA-OV | ajcc_pathologic_t/n/m | 0.005 | ★ |
| MMSURV | TCGA-PRAD | ajcc_pathologic_m | 0.014 | |
| INTEGRATIVE_DNN | ACC / CESC / PCPG / PRAD / SARC / THYM / UCEC / UCS | ajcc_pathologic_stage | 0.008–0.023 | |
| HGCN_KIRC | TCGA-KIRC | exposures[].pack_years_smoked | 0.039（21/537） | ★ |

说明：妇科癌种（CESC/OV/UCEC/UCS）的 stage 虽 AJCC 近零，但 FIGO fallback 救回（§4.2）；KIRC pack_years 96% 患者为 `"unknown"`，此点 `paper_tcga_field_mapping.md:140` 已有记录。

## 6. 常量特征实证（prompts.csv）

| 文件 | 实际内容 |
|---|---|
| `outputs/TCGA-LAML/A_manual/MMSURV/prompts.csv` 行 2 | `Pathologic T stage is TX., Pathologic N stage is NX., Pathologic M stage is MX.` |
| `outputs/TCGA-GBM/A_manual/MULTISURV/prompts.csv` 行 2 | `Pathologic overall stage is Stage X.` |
| `outputs/TCGA-LGG/A_manual/SURVPGC/prompts.csv` 行 2 | `Pathologic overall stage is Stage X.` |
| `outputs/TCGA-GBM/A_manual/MMSURV/prompts.csv` 行 2 | `Pathologic T stage is TX., Pathologic N stage is NX., Pathologic M stage is MX.` |

## 7. Test_2a 审计交叉验证

Test_2a 审计 JSON（`results/Test_2a_leak_audit/{DS}/{scheme}.json`）的 `fields[].n_valid=0` + `placeholder` + `not_in_bank=True` 与本报告档 1 一致（抽查全部受影响组合）：

| 数据集/方案 | 零有效字段（n_valid=0） | n_not_in_bank |
|---|---|---|
| LAML/MMSURV | T、N、M（placeholder "TX/NX/MX"） | 4/5 |
| LAML/MULTISURV | ajcc_pathologic_stage（"Stage X"） | 5/10 |
| GBM/SURVPGC | ajcc_pathologic_stage + edition（0 有效） | 4/6 |
| GBM/MMSURV | T、N、M | 4/5 |
| LGG/INTEGRATIVE_DNN | ajcc_pathologic_stage | 2/3 |
| DLBC/MMSURV | T、N、M | 4/5 |
| ESCA/HGCN_ESCA | cigarettes_per_day | 5/11 |

注意：`not_in_bank` 还包含**存在有效值但与 field bank 路径不同**的字段（如 `demographic.age_at_index` n_valid=200 但 not_in_bank——bank 用 `diagnoses[].age_at_diagnosis`；`project.project_id`、`derived.*` 为计算字段），这些**不是**"字段不存在"，与本报告档 1 需区分开。

## 8. 次要问题（同类机制，非本报告主体）

1. **Clinic_Analyzer 临床 CSV 的 stage 列**：`Clinic_Analyzer/dataset_deployment/scripts/generate_5fold_splits.py:37` 对 35 个 study 硬编码 `["case_id","stage","subtype","grade"]` 列；实测 `tcga_laml/gbm/ov/sarc/lgg` 的 stage 列**全员空值**、laml/sarc 的 grade 列全员空值（下游 `dataset_survival.py:955-968` 用 try/except 静默容忍）。
2. **L2-L5 通路的 `tumor_grade`**：33 TCGA 中 **21 个** coverage=0（含 lizhe 9 队中的 BRCA/COAD/PRAD/READ/KICH/KIRP 6 个）→ 全 `"not reported"`。
3. 文档已记录、无需重复审计的同类问题（`A_pipeline/z_notes/paper_tcga_field_mapping.md`）：`gender` 键全库不存在（用 sex_at_birth，:25,32）；`years_smoked` 无现成列（:51）；`cigarettes_per_day` 值全 null（:50）；BMI 仅 LIHC/ESCA/UCEC 有值（:47）；KIRC pack_years 21/537（:140）。

## 9. 现有防护 vs 缺口

| 通路 | 防护 |
|---|---|
| Field Bank（Test_1a/1b/3） | **有**：R3 覆盖率≥0.30 + R4 去退化逐数据集筛选（`rawdata_stats/{DS}/landmark_0/kept_fields.json`），不会带常量字段 |
| Test_2a 审计 | **半有**：`not_in_bank`/`n_valid=0` 标记进审计报告，但不阻断、不修正臂 A 训练 |
| 论文方案通路（extract.py / json2prompt.py / encode.py / generate_5fold_splits.py） | **无**：字段缺失静默占位符化，直接进 prompt/编码/训练 |

即：Test_1a/1b/3（field bank 口径）安全；**Test_2b 臂 A（论文报告值）、Test_3 臂 B、Test_5 中使用方案 fields.json 的部分**受影响——占位常量特征已进入这些实验的 prompt 与编码。

## 10. 待议事项（本报告只列问题，不改）

1. **是否修正方案×数据集绑定**：4 泛癌种方案在 LAML/GBM/LGG/DLBC 上无任何可用的 AJCC 分期信息（U2 未决）；是否对这些数据集剔除 stage/TNM 字段或换用各自癌种的 staging 体系（如 LGG 的 WHO grade）。
2. **是否加存在性拦截**：extract.py 对 coverage=0/无键字段显式标记或剔除（参考 Test_2a 的 not_in_bank 机制），而不是静默占位。
3. **是否重跑受影响实验**：Test_2b/Test_3/Test_5 中 LAML/GBM/LGG/DLBC 的结果目前携带常量占位特征（对 c-index 数值无信息量影响，但报告口径失实）；若修正字段则需评估重跑范围。
4. KIRC pack_years（3.9%）、OV prior/synchronous_malignancy（2.0%）等档 2 字段是否也按"实质缺失"处理。

## 附录：审计脚本口径

一次性只读枚举脚本（未落盘）：读 `A_pipeline/templates/{scheme}/fields.json` × spec §2.4 绑定 → 对照 `rawdata_stats/{DS}/field_stats.csv`（field_path + coverage）分档：无行或 coverage=0 → 档 1；0<coverage<0.05 → 档 2。组合总数 840 = (10+6+5+3)×33 + (8+6+11+9+8+6)×1。
