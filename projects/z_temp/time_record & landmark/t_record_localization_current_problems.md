# t_record 定位：当前定义与未决问题

把 clinic 原始 JSON 里每一次 record 的记录时间钉死。本文只记录已对齐的定义、已锁规则、以及现在卡住的缺口；不继续展开字段级调研。

## 任务定义

`t_record` 是一次 record 相对 `index_date` 的记录时间，不是字段值是不是日期，也不是 `updated_datetime`（那是 `t_write`）。

输入：`ClinicDatasets/gdc_clinical/raw_json/*.json`，字段范围以 [`gdc_cases_mapping.csv`](../ClinicDatasets/gdc_clinical/field_tables/gdc_cases_mapping.csv) 为准。

对每一次需要统计的 record，给出相对 `index_date` 的记录时间。表示用区间 `(t_lo, t_hi, source)`。有精确 `days_to_*` 时两端相等。Landmark 用 `t_hi <= L`：问截至 L 这条记录是否已知。

这是语义任务。词典、GDC 实体、以及“这条信息临床上何时才可能被写下”都要进判断。不能把父对象天数无条件继承下去，也不能把 `timepoint_category` 折成一个假点。

## 一次 record

一次 record 不是一个字段名，也不是 `diagnoses` 这个数组名，而是父实体的一个 JSON 对象实例。该对象上的直属内容字段共用这只钟。`days_to_*` 是这条记录里的时间坐标字段，不是另一次 record。

| 父字段 | 计数 | 是否统计 t_record |
| --- | --- | --- |
| `demographic` | 每例 0/1 | 否，默认最早 |
| `exposures[]` | 每对象一次 | 否，默认最早 |
| `family_histories[]` | 每对象一次 | 否，默认最早 |
| `diagnoses[]` | 数组里几个对象几次 | 是 |
| `diagnoses[].treatments[]` | 每个治疗对象一次，不并进父诊断 | 是 |
| `diagnoses[].pathology_details[]` | 每个病理对象一次 | 是 |
| `follow_ups[]` | 每个随访对象一次 | 是 |
| `follow_ups[].molecular_tests[]` | 每次化验一次 | 是 |
| `follow_ups[].other_clinical_attributes[]` | 每条属性一次 | 是 |

嵌套对象不继承父对象的钟，除非后面单独锁了规则。

实例：[`TCGA-PCPG.json`](../ClinicDatasets/gdc_clinical/raw_json/TCGA-PCPG.json) 第 9 行 `diagnoses` 是 `TCGA-WB-A820`，数组里 2 个诊断对象，就是 2 次 diagnosis record（`days_to_diagnosis` 为 0 和 -289）。下面的 treatment / pathology 是额外 record。同文件 `TCGA-WB-A80K` 是 3 个诊断对象，3 次 diagnosis record。

注意：同一份 PCPG 里，有的诊断把治疗数组写成 `treatments`，有的写成 `c`。对象形态仍是 treatment，定位时按治疗对象数，不要只认键名 `treatments`。

## 已锁规则

1. 诊断对象上的内容字段（`primary_diagnosis`、分期、残存等）共用 `days_to_diagnosis`。`days_to_last_follow_up` 是同一条记录上的另一个时间字段，不是对象钟。
2. `days_to_treatment_start` 的词典定义是治疗开始日，不是这条 treatment 被写入病历的时间。有该字段时，它就是这条 treatment 记录钟的主判据。
3. 负向勾选：`treatment_or_therapy=no`，且没有 `days_to_treatment_start` / `days_to_treatment_end` / `timepoint_category` 时，`t_record` 用父诊断 `days_to_diagnosis`。父诊断也没有该天数则仍未定位。
   实例：PCPG 第 218 行 `TCGA-S7-A7WN`，同一诊断下两条 Adjuvant，`Radiation Therapy, NOS` / `Pharmaceutical Therapy, NOS`，都是 `or_therapy=no`，无任何时间字段。这是入组 CRF「未做放疗/药物」，挂诊断日 0。
4. 壳 follow-up（没有自己的随访内容、只装着 nested 化验/属性）不是一次真实 follow-up record；nested 对象仍各自一次 record，不能继承这个壳的天数。
5. 缺锚点不默认填 0。未定位就标未定位，交给调研。

旧规格 [`time_write_record_spec.md`](time_write_record_spec.md) 里 treatments/pathology 按 `timepoint_category` 置信度继承父诊断日、molecular/oca 继承父 follow-up 日，与当前定义冲突，不能当权威。

## 当前缺口

这些问题先停，不要继续猜规则。适合按实体交给其他 Codex 做字段/CRF 调研。

**已做治疗没有开始日。** `or_therapy=yes` 但 start/end/timepoint 全空，全库大约 9 千条。例如 ACC `TCGA-OR-A5KB`：辅助化疗 `yes`，outcome 已是 Progressive Disease，没有开始日。这不是负向勾选，不继承诊断日。对象钟目前空着。

**病理明细没有天数。** `days_to_pathology_detail` 全库 14366 条里 0 条有值。`TCGA-S7-A7WN` 的 pathology 同样没有时间。对象钟空着。能不能挂诊断日、手术日，还是未定位，未锁。

**壳 follow-up 下的化验只有类别。** 全库 20754 条 `molecular_tests` 都挂在壳 follow-up 下，父对象没有 `days_to_follow_up`。多数只有 `timepoint_category`（`Initial Diagnosis` / `Sample Procurement` / `Preoperative`），`days_to_test` 很少。CHOL `TCGA-4G-AAZG` 的术前 CA19-9/白蛋白等就是这种。`Preoperative` 在没有手术开始日时（全库手术 `or=yes` 且无 start 约 2984 条）给不出 `t_hi`。

**壳 follow-up 下的 other_clinical_attributes。** 8321 条同样几乎全在壳下。常见 `Prior to Diagnosis` / `Initial Diagnosis`，自身 `days_to_comorbidity` / `days_to_risk_factor` 基本为空。类别如何变成区间未锁。

**`timepoint_category` 对照表没写完。** 已锁的是区间门控，不是点估计。还没有「类别 → `(t_lo, t_hi)`、缺锚点怎么办」的表。旧的 high/medium/low 继承诊断日作废。

**同一 treatment 上的结束日/结局。** `days_to_treatment_end` 是这条记录里的另一个时间坐标，不是第二次 record。内容字段是否一律跟 start，`treatment_outcome` 要不要跟 end，未锁。先不要扩。

## 实现时不要做的事

- 不要把 `ajcc_pathologic_stage` / `residual_disease` 当成时间点。
- 不要把 `days_to_last_follow_up` 当成诊断对象钟。
- 不要把 `days_to_treatment_start` 与 `days_to_treatment_end` 理解成“无法定位”。它们是相对 index 的两个明确天数。
- 不要让 nested 化验继承壳 follow-up。
- 不要把 `or_therapy=yes` 缺日期和 `or_therapy=no` 负向勾选合成一条规则。

## 后续

代码已按本文已锁规则落地：`src/time_stats.py` 去掉 timepoint 继承和壳 follow-up 继承；负向勾选挂父诊断日只适用于「no + 无任何时间字段」。`or=yes` 缺日期、病理无天数、术前化验无手术锚点，一律保持未定位，直到调研给出规则。不改 Field Bank，不继续扫全库规则。
