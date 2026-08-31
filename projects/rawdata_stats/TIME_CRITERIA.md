# 时间统计判据

实现：`src/time_stats.py`。每个数据集写出并列的 `time_write/` 与 `time_record/`。
两套统计共用下面 6 个实体，不统计 `case`、`demographic`、`exposures[]`、`family_histories[]`。
槽位编号按 JSON DFS 遇到顺序，1-based，不按时间排序。

生存终点两套目录各放一份，规则不变：

- Dead：`demographic.days_to_death`
- 非死亡：先取 `diagnoses[].days_to_last_follow_up` 的最大值；没有再用 `follow_ups[].days_to_follow_up` 的最大值

完整任务说明见 `z_temp/time_write_record_spec.md`。

demographic、exposures[]、family_histories[] 不用统计

---

## t_write 实现表

判据一律是该对象自己的 `updated_datetime`（忽略 `created_datetime`）。缺或无法解析则该槽排除。
归一化：`(updated - t0) / last_time_days`。`t0` 只取这 6 个实体里该患者最早一次 `updated_datetime`。
覆盖率排除：该槽对象存在，但没有可解析的 `updated_datetime`。

| 实体 | 主判据 | 备选判据 | 兜底 | 产物列名 |
| --- | --- | --- | --- | --- |
| `diagnoses[]` | `updated_datetime` | — | 缺失则排除 | `diagnoses_updated{i}` |
| `diagnoses[].treatments[]` | `updated_datetime` | — | 缺失则排除 | `diagnoses_treatments_updated{i}` |
| `diagnoses[].pathology_details[]` | `updated_datetime` | — | 缺失则排除 | `diagnoses_pathology_details_updated{i}` |
| `follow_ups[]` | `updated_datetime` | — | 缺失则排除 | `follow_ups_updated{i}` |
| `follow_ups[].molecular_tests[]` | `updated_datetime` | — | 缺失则排除 | `follow_ups_molecular_tests_updated{i}` |
| `follow_ups[].other_clinical_attributes[]` | `updated_datetime` | — | 缺失则排除 | `follow_ups_other_clinical_attributes_updated{i}` |

---

## t_record 实现表

单元格是相对 index 的天数。归一化：`days / last_time_days`，不再减日历 `t0`。
主判据优先；备选只在主判据缺失时使用。父级继承只指向直接父对象，不用患者级 max。
`follow_ups[].other_clinical_attributes[]` 两个 days 都有时用 `days_to_comorbidity`。
覆盖率排除：该槽对象存在，但主判据和备选都拿不到天数。

| 实体 | 主判据 | 备选判据 | 兜底 | 产物列名 |
| --- | --- | --- | --- | --- |
| `diagnoses[]` | `days_to_diagnosis` | — | 缺失则排除 | `diagnoses_record{i}` |
| `diagnoses[].treatments[]` | `days_to_treatment_start` | `timepoint_category` 命中 treatments 窄表则继承父诊断 `days_to_diagnosis` | 两者均缺则排除 | `diagnoses_treatments_record{i}` |
| `diagnoses[].pathology_details[]` | `days_to_pathology_detail` | `timepoint_category` 命中 pathology 窄表则继承父诊断 `days_to_diagnosis` | 两者均缺则排除 | `diagnoses_pathology_details_record{i}` |
| `follow_ups[]` | `days_to_follow_up` | — | 缺失则排除 | `follow_ups_record{i}` |
| `follow_ups[].molecular_tests[]` | `days_to_test` | 继承父 follow-up `days_to_follow_up` | 两者均缺则排除 | `follow_ups_molecular_tests_record{i}` |
| `follow_ups[].other_clinical_attributes[]` | `days_to_comorbidity`，否则 `days_to_risk_factor` | 继承父 follow-up `days_to_follow_up` | 两者均缺则排除 | `follow_ups_other_clinical_attributes_record{i}` |

窄表（strip 后大小写不敏感、整串相等）：

- treatments：`Prior to Diagnosis`、`Preoperative`、`Prior to Procurement`、`Pretreatment`、`Pre-treatment`
- pathology：`Initial Diagnosis`、`Prior to Diagnosis`

不算基线：`Postoperative`、`Recurrence`、`Progression`、`First Treatment`、`Prior to Adjuvant Therapy`。

---

## 覆盖率

各目录 `missing/{family}.csv` 与同名 png。按数组槽位：

- 分母：该槽位对象存在的患者数
- 分子：该槽算出时间的人数
- 排除：分母 − 分子
- 单元格：`24/25`
- 路径：`diagnoses[].pathology_details[1]`
