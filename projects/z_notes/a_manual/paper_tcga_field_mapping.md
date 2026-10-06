# 论文临床变量到 GDC 字段对照

对照对象是当前仓库里的 GDC Data Release 46.0（2026-08-10）clinical JSON 与字段表，不是论文当年下载的旧 XML / Biotab 原文。论文里写的是语义名（age、gender、stage），这里给出它们在现有 GDC 里最可能落到的字段；一对一时标成“首选”，一对多时把候选都列上。

依据：

- [field_tables/gdc_cases_mapping.csv](field_tables/gdc_cases_mapping.csv)：门户 clinical JSON 可查询路径
- [field_tables/gdc_clinical_dictionary.csv](field_tables/gdc_clinical_dictionary.csv)：实体、类型、枚举、定义
- [raw_json/](raw_json/)：33 个 TCGA project 的实际填充情况
- [biotab/](biotab/)：旧 BCR 列名，用来解释论文为什么会写成 gender、Age at index、Pharmaceutical Therapy

覆盖率按病例计，空值 / `not reported` / `unknown` 都算缺失。诊断字段取 `diagnosis_is_primary_disease=true` 的那条，没有则退回第一条 diagnosis。

## 怎么读这张表

GDC 现在是嵌套 JSON，不是论文常用的扁平表。常见路径：

- `demographic.*`：人口学
- `diagnoses.*`：诊断 / 分期 / 既往肿瘤
- `diagnoses.treatments.*`：治疗记录，一条 diagnosis 下多条 treatment
- `exposures.*`：吸烟饮酒
- `follow_ups.other_clinical_attributes.*`：BMI / 身高体重
- `project.project_id`：癌种队列名，如 `TCGA-KIRC`

旧 Biotab 的 `gender`、`radiation_treatment_adjuvant` 在当前 JSON 里已经改名或拆成多条记录。当前 mapping 里没有 `demographic.gender`，33 个 TCGA JSON 也全部是 `demographic.sex_at_birth`。

## 共用变量

| 论文用语 | 首选 GDC 字段 | 也需要考虑 | 说明 |
|---|---|---|---|
| age | `demographic.age_at_index` | `diagnoses.age_at_diagnosis`；`demographic.days_to_birth` | `age_at_index` 是年，索引日年龄，HGCN 原文就写这个名字。`age_at_diagnosis` 是出生后天数。`days_to_birth` 是负数天数，`abs(days_to_birth)/365.25` 可还原年龄。Biotab 常见 `age_at_initial_pathologic_diagnosis` / `age_at_diagnosis`（年）。 |
| gender / sex | `demographic.sex_at_birth` | 旧 API / Biotab `demographic.gender` / `gender` | 当前词典和 mapping 都只有 `sex_at_birth`（female / male / unknown）。本地 JSON 里 `gender` 键出现次数为 0。论文若写 gender，语义上就是这个字段的旧名。 |
| race | `demographic.race` | 无第二字段 | 枚举含 white / black or african american / asian 等。 |
| project_id / 癌种 | `project.project_id` | `disease_type`；`primary_site` | TCGA 癌种就是 project，如 `TCGA-LUAD`。`disease_type` 是 WHO 疾病大类（Adenomas and Adenocarcinomas），不是队列名。 |
| stage / tumor stage | `diagnoses.ajcc_pathologic_stage` | `diagnoses.ajcc_clinical_stage`；`diagnoses.figo_stage`（妇科）；少数癌种还有 Ann Arbor / ENST / Masaoka 等 | 实体癌首选 pathologic stage，覆盖率远高于 clinical。UCEC 几乎只有 FIGO，没有 AJCC pathologic stage。 |
| T / N / M | `diagnoses.ajcc_pathologic_t/n/m` | `diagnoses.ajcc_clinical_t/n/m` | 同样是 pathologic 更全。clinical T/N/M 在多数癌种接近空。 |
| stage edition | `diagnoses.ajcc_staging_system_edition` | `diagnoses.figo_staging_edition_year`；`diagnoses.uicc_staging_system_edition` | AJCC 取值如 6th / 7th。UCEC 用 FIGO 年份（1988/1995/2009）。 |
| prior malignancy | `diagnoses.prior_malignancy` | Biotab `history_other_malignancy` | yes/no/unknown。 |
| synchronous malignancy | `diagnoses.synchronous_malignancy` | 无第二字段 | 同时第二原发。 |
| prior treatment | `diagnoses.prior_treatment` | Biotab `history_neoadjuvant_treatment` | 标本采集前是否已治疗，不是 adjuvant 放疗/药疗本身。 |
| pharma / Pharmaceutical Therapy | `diagnoses.treatments.treatment_or_therapy`，且 `treatment_type` 为 `Pharmaceutical Therapy, NOS` | 同数组里的 Chemotherapy / Hormone Therapy / Targeted Molecular Therapy / Immunotherapy；Biotab `pharmaceutical_tx_adjuvant` | GDC 要求用 `treatment_type` 找到对应记录，再用 `treatment_or_therapy`（yes/no/unknown）当 0/1。只看 `treatment_type` 不能判断有没有做。 |
| radiation / Radiation Therapy | `diagnoses.treatments.treatment_or_therapy`，且 `treatment_type` 为 `Radiation Therapy, NOS` | Radiation, External Beam / Radiation, Internal / Brachytherapy, NOS 等；Biotab `radiation_treatment_adjuvant` | 同上。HGCN 论文列名就是这两种 NOS。 |
| subtype | 没有单一 GDC 字段 | `diagnoses.primary_diagnosis`；`diagnoses.morphology`；`disease_type`；组学分子分型（不在 clinical JSON） | 组织学亚型走 ICD-O 诊断/形态学；BRCA PAM50、CRC CMS 这类不在这套 clinical 表里。 |
| primary diagnosis | `diagnoses.primary_diagnosis` | 偶尔有人会拿 `disease_type` 顶替 | 例如 Clear cell adenocarcinoma, NOS。 |
| morphology | `diagnoses.morphology` | `diagnoses.fab_morphology_code`（白血病，这里基本用不到） | ICD-O-3 形态学编码，如 8310/3。 |
| site of resection / biopsy | `diagnoses.site_of_resection_or_biopsy` | `diagnoses.tissue_or_organ_of_origin`；`primary_site` | 切除/活检部位。ESCA 里 `site_of_resection_or_biopsy` 常是 Esophagus, NOS，更细的部位在 `tissue_or_organ_of_origin`（Lower third of esophagus）。 |
| BMI | `follow_ups.other_clinical_attributes.bmi` | 由同节点 `height`（cm）+ `weight`（kg）计算；Biotab `height_cm_at_diagnosis` / `weight_kg_at_diagnosis` | 不是 diagnosis 字段。LIHC / ESCA / UCEC 有值，KIRC / LUSC / LUAD 基本没有。 |
| alcohol history | `exposures.alcohol_history` | `exposures.alcohol_intensity` / `alcohol_drinks_per_day` / `alcohol_days_per_week`；Biotab `alcohol_history_documented` | 终身是否喝过至少 12 杯。ESCA 有值，KIRC / LUSC / LUAD / UCEC 基本空。 |
| pack years smoked | `exposures.pack_years_smoked` | Biotab `tobacco_smoking_pack_years_smoked` | 支/天 × 年 / 20。 |
| cigarettes per day | `exposures.cigarettes_per_day` | 由 pack years 反推；当前 TCGA JSON 里这个键经常在、值全是 null | 词典有定义，ESCA/LUSC/KIRC 的曝光记录里键存在但非空数为 0。 |
| years smoked | 当前 JSON 没有同名字段 | 由 `exposures.tobacco_smoking_onset_year` + `tobacco_smoking_quit_year`（或诊断年）推；`exposures.age_at_onset`；`exposures.exposure_duration_years`（词典有，这批 JSON 为空）；Biotab `tobacco_smoking_year_started` / `year_stopped`，LUSC 还有 `age_began_smoking_in_years` | HGCN 的 Years smoked 只能落到“推出来的吸烟年限”，不能落到单一现成列。 |

治疗记录的完整路径是 `diagnoses[].treatments[]`。mapping 写成：

- `diagnoses.treatments.treatment_type`
- `diagnoses.treatments.treatment_or_therapy`

## 1. MultiSurv

论文字段：age、gender、race、project_id（癌种）、stage、prior malignancy、synchronous malignancy、prior treatment、pharma、radiation。

| 论文字段 | 首选 | 候选 / 备注 |
|---|---|---|
| age | `demographic.age_at_index` | `diagnoses.age_at_diagnosis`（天） |
| gender | `demographic.sex_at_birth` | 旧 `demographic.gender` |
| race | `demographic.race` | |
| project_id | `project.project_id` | 不要用 `disease_type` 当癌种 |
| stage | `diagnoses.ajcc_pathologic_stage` | 妇科 `figo_stage`；血液/特殊癌种各自的 staging 字段 |
| prior malignancy | `diagnoses.prior_malignancy` | |
| synchronous malignancy | `diagnoses.synchronous_malignancy` | |
| prior treatment | `diagnoses.prior_treatment` | 不是 radiation/pharma 那两条 |
| pharma | `diagnoses.treatments.treatment_or_therapy` + `treatment_type=Pharmaceutical Therapy, NOS` | 也可能把 Chemotherapy 等并进去 |
| radiation | `diagnoses.treatments.treatment_or_therapy` + `treatment_type=Radiation Therapy, NOS` | 也可能并入更细的放射类型 |

这组字段在当前 GDC 里都能直接对上，没有“只能猜测”的项。唯一会漂的是 gender 旧名，以及跨癌种时 stage 体系不统一。

## 2. SurvPGC

论文字段：subtype、age、sex、tumor stage、stage edition、race。

| 论文字段 | 首选 | 候选 / 备注 |
|---|---|---|
| subtype | 不确定，优先 `diagnoses.primary_diagnosis` | `diagnoses.morphology`；`disease_type`；若论文用的是 PAM50 / 分子亚型，则不在 clinical JSON。本仓库 L 组抽取把 subtype 写成 `primary_diagnosis`，缺省再退 `disease_type`。 |
| age | `demographic.age_at_index` | `diagnoses.age_at_diagnosis` |
| sex | `demographic.sex_at_birth` | 旧 `gender` |
| tumor stage | `diagnoses.ajcc_pathologic_stage` | `figo_stage`（UCEC/CESC/OV）；clinical stage 覆盖差 |
| stage edition | `diagnoses.ajcc_staging_system_edition` | 妇科 `figo_staging_edition_year` |
| race | `demographic.race` | |

这里最含糊的是 subtype。clinical 侧没有名为 subtype 的列。

## 3. MMSurv

论文字段：T、N、M、age、gender。

| 论文字段 | 首选 | 候选 / 备注 |
|---|---|---|
| T | `diagnoses.ajcc_pathologic_t` | `diagnoses.ajcc_clinical_t`（多数癌种很稀） |
| N | `diagnoses.ajcc_pathologic_n` | `diagnoses.ajcc_clinical_n` |
| M | `diagnoses.ajcc_pathologic_m` | `diagnoses.ajcc_clinical_m` |
| age | `demographic.age_at_index` | `diagnoses.age_at_diagnosis` |
| gender | `demographic.sex_at_birth` | 旧 `gender` |

取值例：T1a / N0 / M0。`NX` / `MX` 在 JSON 里是有值的，分析时通常当缺失。UCEC 这套 AJCC T/N/M 基本为空，要用 FIGO。

## 4. Integrative DNN

论文字段：age、gender、stage。

| 论文字段 | 首选 | 候选 / 备注 |
|---|---|---|
| age | `demographic.age_at_index` | `diagnoses.age_at_diagnosis` |
| gender | `demographic.sex_at_birth` | 旧 `gender` |
| stage | `diagnoses.ajcc_pathologic_stage` | `figo_stage`；不太像是 T/N/M 三个字段，论文写的是 stage |

这三个都是高覆盖、歧义小的字段。

## 5. HGCN（按癌种）

HGCN supplementary 的列名已经很接近 GDC/Biotab 原名，所以对照比前面几篇更死。下面覆盖率来自本地 `raw_json`。

### 共同项

| 论文字段 | 首选 GDC 字段 | 覆盖率摘要 |
|---|---|---|
| Race | `demographic.race` | KIRC 99%；LIHC 97%；ESCA 89%；LUSC 78%；LUAD 78%；UCEC 92% |
| Age at index | `demographic.age_at_index` | 几乎就是这个字段。KIRC 100%；LIHC 100%；ESCA 100%；LUSC 98%；LUAD 86%；UCEC 97% |
| Gender | `demographic.sex_at_birth`（当前） / 旧 `gender` | 除 LUAD 89%、UCEC 98% 外，其余约 100%。UCEC 论文没列 Gender。 |
| Radiation Therapy | treatments：`treatment_type=Radiation Therapy, NOS` 的 `treatment_or_therapy` | 有 yes/no 记录的比例：KIRC 35%，LIHC 高（大量 no），ESCA 82%，LUSC 68%，LUAD 58%，UCEC 53%。很多病例是明确的 no，不是字段缺失。 |
| Pharmaceutical Therapy | treatments：`treatment_type=Pharmaceutical Therapy, NOS` 的 `treatment_or_therapy` | KIRC 31%；ESCA 78%；LUSC 54%；LUAD 47%；UCEC 84%。JSON 里还会并列 Chemotherapy 等更细类型。 |

### KIRC

| 论文字段 | 首选 | 其他可能 | 本地观察 |
|---|---|---|---|
| Race | `demographic.race` | | 530/537 |
| Age at index | `demographic.age_at_index` | | 537/537，单位年 |
| Gender | `demographic.sex_at_birth` | 旧 gender | 537/537 |
| Prior malignancy | `diagnoses.prior_malignancy` | Biotab `history_other_malignancy` | 531/537 |
| Pack years smoked | `exposures.pack_years_smoked` | Biotab `tobacco_smoking_pack_years_smoked` | 仅 21/537，很稀 |
| Years smoked | 无现成列 | `tobacco_smoking_onset_year` + `tobacco_smoking_quit_year`；Biotab `tobacco_smoking_year_started/stopped` | onset 12、quit 13；`exposure_duration_years` / `years_smoked` 均为空 |
| Radiation / Pharma | 见上 | Biotab adjuvant 两列 | JSON 里 Radiation/Pharma NOS 都在 |

### LIHC

| 论文字段 | 首选 | 其他可能 | 本地观察 |
|---|---|---|---|
| Race / Age at index / Gender | 同上 | | 高覆盖 |
| BMI | `follow_ups.other_clinical_attributes.bmi` | `height` + `weight`；Biotab 身高体重 | BMI 341/377，height 345，weight 350。LIHC JSON 几乎没有 exposures。 |
| Radiation / Pharma | 见上 | | 治疗数组很全，大量 `Radiation Therapy, NOS = no` |

### ESCA

| 论文字段 | 首选 | 其他可能 | 本地观察 |
|---|---|---|---|
| Race / Age at index / Gender | 同上 | | 高覆盖 |
| Alcohol history | `exposures.alcohol_history` | intensity / drinks per day；Biotab `alcohol_history_documented` | 116/185（62.7%），取值 Yes/No |
| Primary diagnosis | `diagnoses.primary_diagnosis` | | 185/185，Adenocarcinoma vs Squamous |
| Site of resection or biopsy | `diagnoses.site_of_resection_or_biopsy` | `tissue_or_organ_of_origin` 更细 | 切除部位常是 Esophagus, NOS |
| Morphology | `diagnoses.morphology` | | 185/185，如 8140/3、8070/3 |
| BMI | `follow_ups.other_clinical_attributes.bmi` | height/weight | 175/185 |
| Cigarettes per day | `exposures.cigarettes_per_day` | 实际全空，可退 `pack_years_smoked` | 键在 185 条 Tobacco exposure 里，非空 0；pack years 98/185 |
| Radiation / Pharma | 见上 | | 覆盖较好 |

### LUSC

| 论文字段 | 首选 | 其他可能 | 本地观察 |
|---|---|---|---|
| Race / Age at index / Gender | 同上 | | race 稍差（78%） |
| Prior malignancy | `diagnoses.prior_malignancy` | | 503/504 |
| Site of resection | `diagnoses.site_of_resection_or_biopsy` | `tissue_or_organ_of_origin` | 多为 Lung, NOS |
| Pack years smoked | `exposures.pack_years_smoked` | | 427/504（84.7%） |
| Years smoked | 无现成列 | onset/quit year；Biotab `tobacco_smoking_year_started/stopped`、`age_began_smoking_in_years` | onset 321、quit 309 |
| Radiation / Pharma | 见上 | | |

### LUAD

| 论文字段 | 首选 | 其他可能 | 本地观察 |
|---|---|---|---|
| Race / Age at index / Gender | 同上 | | LUAD 缺 demographic 的病例比别的多（sex 89%） |
| Morphology | `diagnoses.morphology` | | 522/585 |
| Prior malignancy | `diagnoses.prior_malignancy` | | 522/585 |
| Site of resection or biopsy | `diagnoses.site_of_resection_or_biopsy` | | 522/585，多为 Lung, NOS |
| Radiation / Pharma | 见上 | | |

### UCEC

论文没写 Gender。妇科分期不要去找 AJCC TNM。

| 论文字段 | 首选 | 其他可能 | 本地观察 |
|---|---|---|---|
| Race | `demographic.race` | | 516/560 |
| Age at index | `demographic.age_at_index` | | 545/560 |
| Primary diagnosis | `diagnoses.primary_diagnosis` | | 548/560，Endometrioid / Serous 等 |
| Morphology | `diagnoses.morphology` | | 548/560 |
| Radiation / Pharma | 见上 | | pharma 覆盖明显高于 radiation |
| （未写但容易误用）stage | 若补分期，用 `diagnoses.figo_stage` | AJCC pathologic stage 在 UCEC 为 0 | FIGO 548/560；edition year 有 2009/1988/1995 |

## 当前 JSON 里对不上或会踩坑的名字

1. `gender`：词典、mapping、本地 JSON 都没有。用 `sex_at_birth`。
2. `years_smoked`：词典没有这个字段名。不要指望 `exposures.years_smoked`。
3. `exposures.cigarettes_per_day`：schema 有，TCGA 这批基本全空。ESCA 论文写了它，落地时大概率得改用 pack years 或承认缺失。
4. `exposures.exposure_duration_years`：词典有“暴露持续年”，本地 33 个 project 几乎全空，不能当 Years smoked 的现成列。
5. 治疗不是病例根字段。必须按 `treatment_type` 过滤后再读 `treatment_or_therapy`。
6. BMI 不在 diagnosis / demographic 下，在 `follow_ups.other_clinical_attributes`。
7. age 的单位：`age_at_index` 是年，`age_at_diagnosis` 是天。KIRC 样例里 53 岁对应 19620 天。

## 建议落地优先级

复现这五篇时，若只从当前 `raw_json` 抽：

1. 人口学：`age_at_index`、`sex_at_birth`、`race`、`project.project_id`
2. 分期：先 pathologic AJCC，妇科改 FIGO
3. 既往史：`prior_malignancy`、`synchronous_malignancy`、`prior_treatment`
4. 治疗：按 NOS 类型取 yes/no
5. 诊断细节：`primary_diagnosis`、`morphology`、`site_of_resection_or_biopsy`
6. 暴露：pack years、alcohol_history；cigarettes/day 和 years smoked 按缺失或派生处理
7. BMI：从 other_clinical_attributes 取，不要在 diagnosis 里找

