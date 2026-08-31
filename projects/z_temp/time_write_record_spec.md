# Dual Time Stats: t_write / t_record

Audience: 后续改 `src/time_stats.py` 或复核产物。规则已锁死，不要再发明判据或目录。
权威表：`rawdata_stats/TIME_CRITERIA.md`。代码常量必须与该文档一致。

入口：`python projects/scripts/run_time_stats.py --dataset all`
一次跑出 `time_write/` 与 `time_record/`。旧 `rawdata_stats/{dataset}/time/` 删除。

---

## 目录

每个数据集：

```text
rawdata_stats/{dataset}/time_write/
  patient_time_stats.csv
  patient_time_stats.png
  normalized_update_time.csv
  normalized_update_time.png
  normalized_update_time_boxplot.png
  sequences/{family}.csv
  sequences/{family}.png
  missing/{family}.csv
  missing/{family}.png
rawdata_stats/{dataset}/time_record/
  同上（列名用 *_record{i}，归一化文件名仍用 normalized_update_time.*）
```

`_shared/patient_time_stats_all.png` 仍只出一份。生存终点两套目录各放一份。

6 个 family：`diagnoses`、`diagnoses_treatments`、`diagnoses_pathology_details`、`follow_ups`、`follow_ups_molecular_tests`、`follow_ups_other_clinical_attributes`。
不统计 `case` / `demographic` / `exposures[]` / `family_histories[]`。
槽位 1-based，按 JSON DFS 遇到顺序，不按时间排序。
`follow_ups[]` 只给真实随访事件编号；只有 `follow_up_id`、实质内容只是 nested `molecular_tests[]` / `other_clinical_attributes[]` 的壳对象不编号、不进分母。nested 数组仍统计。

生存终点不变：Dead=`demographic.days_to_death`；非死亡先 max `diagnoses[].days_to_last_follow_up`，否则 max `follow_ups[].days_to_follow_up`。
本轮不改 Field Bank、flatten 或 R0 筛选。

覆盖率按槽位：分母=该槽对象存在的患者数（`follow_ups[]` 不计壳对象），分子=算出时间的人数，单元格 `24/25`，路径 `diagnoses[].pathology_details[1]`。

---

## t_write 实现表

判据一律是该对象自己的 `updated_datetime`（忽略 `created_datetime`）。缺或无法解析则该槽排除。
归一化：`(updated - t0) / last_time_days`。`t0` 只取这 6 个实体里该患者最早一次 `updated_datetime`。
覆盖率排除：该槽对象存在，但没有可解析的 `updated_datetime`。`follow_ups[]` 的壳对象不进入分母。

| 实体 | 主判据 | 备选判据 | 兜底 | 产物列名 |
| --- | --- | --- | --- | --- |
| `diagnoses[]` | `updated_datetime` | — | 缺失则排除 | `diagnoses_updated{i}` |
| `diagnoses[].treatments[]` | `updated_datetime` | — | 缺失则排除 | `diagnoses_treatments_updated{i}` |
| `diagnoses[].pathology_details[]` | `updated_datetime` | — | 缺失则排除 | `diagnoses_pathology_details_updated{i}` |
| `follow_ups[]` | `updated_datetime` | — | 壳对象不编号；其余缺失则排除 | `follow_ups_updated{i}` |
| `follow_ups[].molecular_tests[]` | `updated_datetime` | — | 缺失则排除 | `follow_ups_molecular_tests_updated{i}` |
| `follow_ups[].other_clinical_attributes[]` | `updated_datetime` | — | 缺失则排除 | `follow_ups_other_clinical_attributes_updated{i}` |

---

## t_record 实现表

单元格是相对 index 的天数。归一化：`days / last_time_days`，不再减日历 `t0`。
主判据优先；备选只在主判据缺失时使用。父级继承只指向直接父对象，不用患者级 max。
`follow_ups[].other_clinical_attributes[]` 两个 days 都有时用 `days_to_comorbidity`。
覆盖率排除：该槽对象存在，但主判据和备选都拿不到天数。`follow_ups[]` 的壳对象不进入分母。

| 实体 | 主判据 | 备选判据 | 兜底 | 产物列名 |
| --- | --- | --- | --- | --- |
| `diagnoses[]` | `days_to_diagnosis` | — | 缺失则排除 | `diagnoses_record{i}` |
| `diagnoses[].treatments[]` | `days_to_treatment_start` | `timepoint_category` 命中 treatments 窄表则继承父诊断 `days_to_diagnosis` | 两者均缺则排除 | `diagnoses_treatments_record{i}` |
| `diagnoses[].pathology_details[]` | `days_to_pathology_detail` | `timepoint_category` 命中 pathology 窄表则继承父诊断 `days_to_diagnosis` | 两者均缺则排除 | `diagnoses_pathology_details_record{i}` |
| `follow_ups[]` | `days_to_follow_up` | — | 壳对象不编号；其余缺失则排除 | `follow_ups_record{i}` |
| `follow_ups[].molecular_tests[]` | `days_to_test` | 继承父 follow-up `days_to_follow_up` | 两者均缺则排除 | `follow_ups_molecular_tests_record{i}` |
| `follow_ups[].other_clinical_attributes[]` | `days_to_comorbidity`，否则 `days_to_risk_factor` | 继承父 follow-up `days_to_follow_up` | 两者均缺则排除 | `follow_ups_other_clinical_attributes_record{i}` |

窄表（strip 后大小写不敏感、整串相等）：

- treatments：`Prior to Diagnosis`、`Preoperative`、`Prior to Procurement`、`Pretreatment`、`Pre-treatment`
- pathology：`Initial Diagnosis`、`Prior to Diagnosis`

不算基线：`Postoperative`、`Recurrence`、`Progression`、`First Treatment`、`Prior to Adjuvant Therapy`。

---

## 验收

```bash
python projects/scripts/run_time_stats.py --self_test
python -m pytest tests/test_time_stats.py -q
```

合成病例必须覆盖：主判据命中；treatments/pathology 窄表继承父 `days_to_diagnosis`；Postoperative 且无主判据则排除；follow-up 缺天数排除；壳 follow-up 不编号且不进分母，nested 仍统计；molecular/other 继承父 follow-up；comorbidity 优先于 risk_factor；输出不含 case/demographic/exposures/family_histories；旧 `time/` 被删；missing 槽位分母只计该槽存在的人。
