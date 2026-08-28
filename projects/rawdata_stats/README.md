# JSON 原始数据处理说明

本目录记录对 TCGA clinical JSON 做的测量和筛选，不进入 `outputs/`。
后面的人工 L0-L5 / Field Bank / greedy 都读这里的结果，不再回头扫原始 JSON 全字段。

输入由 [datasets.json](../datasets.json) 指定。当前 9 个数据集、去重后共 3904 例：

| 数据集 | 原始 JSON | 额外过滤 | 纳入病例 |
| --- | --- | --- | ---: |
| TCGA-BRCA | 5 份 clinical.cart（Bulk RNA / WSI / Mutation / Methylation / RPPA） | 无 | 1098 |
| TCGA_LIHC | 2 份 clinical.cart | 无 | 365 |
| TCGA-COAD | 1 份 clinical.cart | 无 | 458 |
| TCGA-PRAD | 2 份 clinical.cart | 无 | 499 |
| TCGA-READ | 2 份 clinical.cart | 无 | 171 |
| TCGA-STAD | 2 份 clinical.cart | 无 | 416 |
| TCGA-KICH | 肾癌共用 1 份 JSON | `project.project_id = TCGA-KICH` | 109 |
| TCGA-KIRC | 同上 | `project.project_id = TCGA-KIRC` | 513 |
| TCGA-KIRP | 同上 | `project.project_id = TCGA-KIRP` | 275 |

肾癌三套数据共用 `kindey_cancer_TCGA/clinical/clinical.cart.2026-03-17.json`，靠 `project_ids` 切开。

## 处理链路

```text
datasets.json + clinical JSON
        |
        |  读入 / 去重 / 按 project_id 切开
        v
scanned_fields.json          字段并集字典
        |
        |  按字段路径抽值，判三态缺失
        v
field_stats.csv              覆盖率 / 缺失 / 类型 / 信息量
        |
        |  R0-R6 筛选
        v
kept_fields.json             每个数据集留下的字段
_shared/kept_fields.json     --dataset all 时写出的跨数据集总表（n_patients + fields）
{dataset}/fliter_log/field_registry.csv
{dataset}/fliter_log/exclusion_log.csv
        |
        +-- time/            生存时间和字段更新早晚（并行，不依赖筛选）


这套文件是 JSON 临床字段的扫描 → 统计 → 筛选产物，还没进后面的 Field Bank /prompt。链路是：

scanned_fields.json → field_stats.csv → R0–R6 筛选 → kept_fields.json（以及
fliter_log/ 里的两份日志）

  各文件是什么：

  CONCH-main/projects/rawdata_stats/TCGA-BRCA/scanned_fields.json
  该数据集所有病例扫出来的字段并集字典，按分区组织（顶层、demographic对象、
  diagnoses数组_每个对象 等）。它记录“这个数据集里出现过哪些路径、中文释义是什么”，
  不是每个病人都有这些字段。BRCA 扫到 144 个路径。

  CONCH-main/projects/rawdata_stats/TCGA-BRCA/field_stats.csv
  对上面每个路径，按病人抽值后的全字段统计表（覆盖率、三态缺失、类型、信息量）。这
  是筛选的唯一输入。

  CONCH-main/projects/rawdata_stats/TCGA-BRCA/kept_fields.json
  R0–R6 之后留下的字段。BRCA 是 1098 例、39 个字段，以及每个字段的 coverage。

  fliter_log/ 是筛选过程日志，不是另一套结果：
  - /fliter_log/exclusion_log.csv：被删
    字段及触发规则。BRCA 105 行（R1 行政 48、R0 标签泄漏 26、R3 覆盖率 14、R4 退化
    12、R5 可派生 5）。

  - /fliter_log/field_registry.csv：该数
    据集全部 144 个字段的去留总表，比 kept_fields 更完整。

```

对应命令：

```bash
conda activate conch
cd CONCH-main

python projects/scripts/run_scan_fields.py --dataset all
python projects/scripts/run_field_stats.py --dataset all
python projects/scripts/run_field_filter.py --dataset all --write_templates
python projects/scripts/run_time_stats.py --dataset all
```

`run_scan_json_field_dict.py` 和 `run_scan_fields.py` 等价。

---

## 1. 读入原始 JSON

实现：`src/common/clinical_io.py`。

对每个数据集：

1. 按 `datasets.json` 的 `clinic_files` 依次读入全部病例。
2. 丢掉没有 `submitter_id` 的记录。
3. 若配置了 `project_ids`（肾癌三套），只保留 `case["project"]["project_id"]` 匹配的病例。
4. 按 `submitter_id` 去重，重复时保留第一次出现的记录。同一患者出现在 Bulk RNA / WSI 等多份 cart 里时，只留一份。

主键始终是 `submitter_id`，不是 `case_id`。

---

## 2. 扫描字段字典

实现：`src/discovery/scan.py`。产物：`{dataset}/scanned_fields.json`。

对纳入病例做深度遍历，把所有出现过的 key 做成并集。嵌套对象写成 `project.xxx`，数组写成 `diagnoses[]`、`diagnoses[].treatments[]` 这类路径。不同病人字段不完全一致，所以这里是并集，不是每个病人都有的字段。

中文释义优先从 `templates/field_labels.json` 对齐；对不上的标成“扫描发现的字段（待标注）”，`*_id` 默认标成 UUID。

`scanned_fields.json` 按分区组织，例如：

- 顶层字段：`submitter_id`、`primary_site`、`lost_to_followup`
- `demographic`
- `diagnoses[]`
- `diagnoses[].pathology_details[]`
- `diagnoses[].treatments[]`
- `follow_ups[]` / `follow_ups[].molecular_tests[]` / `follow_ups[].other_clinical_attributes[]`
- 部分数据集还有 `exposures[]`、`family_histories[]`

当前各数据集扫描到的字段数：BRCA 144，COAD 147，KICH 120，KIRC 127，KIRP 139，PRAD 132，READ 146，STAD 128，LIHC 144。

---

## 3. 三态缺失与全字段统计

实现：`src/discovery/stats.py`、`src/common/missingness.py`、`src/common/fields.py`。产物：`{dataset}/field_stats.csv`，并合并为 `_shared/field_stats.csv`。

每个字段对每个患者抽路径值，只分成三种状态：

| 状态 | 含义 |
| --- | --- |
| `null` | 路径抽不到，或值为 `None` / 空字符串 / 空 list / 空 dict |
| `sentinel` | 有值，但是占位词：`not reported`、`unknown`、`not applicable`、`not available`、`na`、`n/a`、`none`、`--` 等 |
| `valid` | 其余真实值 |

约定：

- `missing = null + sentinel`
- `coverage = valid / n_patients`
- 数组字段只要该患者有一条 valid，就算覆盖
- 同一患者多条 valid：数值取均值，类别去重后用 ` | ` 拼接

统计表还会写：

- `value_kind`：numeric / categorical / empty
- `inferred_type`：numeric / ordinal_stage / ordinal_class / text
- `unique_count`、`mode_value`、`mode_share`
- 数值方差或类别归一化熵
- `multi_record` / `multi_record_rate`
- 是否属于人工 L0-L5 字段（`used_in_l0_l5`）

这张表是筛选的唯一输入。

---

## 4. R0-R6 字段筛选

实现：`src/discovery/filter.py`。默认覆盖率阈值 `min_coverage = 0.30`。

规则按文档顺序执行。R2 / R6 只打标，不删字段。

| 规则 | 作用 | 当前触发规模 |
| --- | --- | --- |
| R0 标签泄漏 | 丢掉 `vital_status`、`days_to_death`、`days_to_last_follow_up`、复发/进展/治疗结局，以及其它 `days_to_*`（`days_to_birth` 除外） | 212 行 |
| R1 行政字段 | 丢掉 `submitter_id`、`*_id`、时间戳、`project_id`、`primary_site`，以及容器叶子（`diagnoses`、`follow_ups` 等） | 414 行 |
| R2 时间位置 | 路径落在 `follow_ups` / `other_clinical_attributes` 标 `follow_up`，其余 `baseline` | 只打标 |
| R3 覆盖率 | `coverage < 0.30` | 171 行 |
| R4 退化 | 有效取值 `n_unique < 2`，或众数占比 `> 0.95` | 104 行 |
| R5 可派生 | 丢掉 `age_at_index`、`days_to_birth`（保留 `age_at_diagnosis`）、`ajcc_pathologic_stage`（保留 T/N/M）、`ajcc_staging_system_edition`、`year_of_diagnosis` | 43 行 |
| R6 可移植性 | 按该字段在多少个数据集上被保留，标 `universal` / `common` / `local` | 只打标 |

跨 9 个数据集一共扫到 211 个唯一字段路径，筛后保留 84 个。其中 13 个在全部或几乎全部数据集都留下（`universal`），10 个比较常见（`common`），其余 61 个是癌种局部字段。

9 个数据集都留下的字段：

- `demographic.race`
- `diagnoses[].age_at_diagnosis`
- `diagnoses[].ajcc_pathologic_t/n/m`
- `diagnoses[].diagnosis_is_primary_disease`
- `diagnoses[].morphology`
- `diagnoses[].primary_diagnosis`
- `diagnoses[].prior_treatment`
- `diagnoses[].tissue_or_organ_of_origin`
- `diagnoses[].treatments[].treatment_type`
- `follow_ups[].disease_response`
- `follow_ups[].timepoint_category`

筛后各数据集保留字段数：LIHC 40，BRCA 39，READ 36，COAD 35，KIRP 32，PRAD 28，KICH 26，STAD 25，KIRC 22。

加 `--write_templates` 时，还会按保留字段生成 `templates/B_scan/{dataset}/FIELD_BANK.csv` 长表骨架（`field,example,convert,unit,template`）。`example` 只给人看原始取值和单位，不进 prompt。

---

## 5. 生存时间与字段更新早晚

实现：`src/time_stats.py`。和字段筛选并行，读的是同一批去重后的 JSON。

每个患者的 ground-truth 时间：

- Dead：`demographic.days_to_death`
- 非死亡：优先 `diagnoses[].days_to_last_follow_up`，没有再用 `follow_ups[].days_to_follow_up`
- `event`：Dead=1，Alive=0，其它 vital_status 记空

同时抽出每条 nested 记录的 `updated_datetime`（忽略 `created_datetime`）。同一数组的多次提交保留为独立列，例如 `diagnoses_updated1`、`diagnoses_treatments_updated2`。

归一化：先找该患者最早一次 `updated_datetime` 作为 `t0`，再把每个字段提交时刻换成

```text
(updated - t0) / last_time_days
```

`1` 表示临床终点。字段在终点之后才更新时，值可以大于 1。

当前各数据集生存概况：

| 数据集 | n | Alive | Dead | 其它 | 缺时间 | 中位时间（天） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| TCGA-BRCA | 1098 | 945 | 152 | 1 | 2 | 823.5 |
| TCGA-COAD | 458 | 354 | 102 | 2 | 3 | 652 |
| TCGA-KICH | 109 | 97 | 12 | 0 | 1 | 1513 |
| TCGA-KIRC | 513 | 342 | 171 | 0 | 0 | 1165 |
| TCGA-KIRP | 275 | 233 | 42 | 0 | 1 | 761 |
| TCGA-PRAD | 499 | 489 | 10 | 0 | 0 | 930 |
| TCGA-READ | 171 | 142 | 28 | 1 | 2 | 609 |
| TCGA-STAD | 416 | 247 | 169 | 0 | 7 | 431 |
| TCGA_LIHC | 365 | 237 | 128 | 0 | 1 | 595 |

---

## 最终产物

### 每个数据集 `rawdata_stats/{dataset}/`

```text
scanned_fields.json     该数据集 JSON 字段并集字典
field_stats.csv         全字段三态缺失 / 覆盖率 / 类型
kept_fields.json        R0-R6 后留下的字段、覆盖率和 n_patients
fliter_log/
  exclusion_log.csv     该数据集被删字段及触发规则
  field_registry.csv    该数据集字段路径的去留、可移植性、覆盖率
time/
  patient_time_stats.csv
  patient_time_stats.png
  normalized_update_time.csv
  normalized_update_time.png
  normalized_update_time_boxplot.png
  sequences/
    {family}.csv              该序列类型每次提交的 updated_datetime
    {family}.png              每个 updated{i} 一个子图，横轴样本，纵轴归一化提交时间
```

### 跨数据集 `rawdata_stats/_shared/`

```text
field_stats.csv              9 个数据集 field_stats 纵向合并，1227 行
kept_fields.json             --dataset all 时写出：数据集名 -> {n_patients, fields}
patient_time_stats_all.png   9 个数据集 ground-truth 时间叠图
```

这些文件就是 JSON 预处理的终点。之后：

- 人工方案继续走 `outputs/{dataset}/A_manual/`
- Field Bank 读 `{dataset}/kept_fields.json` 和 `templates/B_scan/{dataset}/FIELD_BANK.csv`，写出 `outputs/{dataset}/B_scan/`
