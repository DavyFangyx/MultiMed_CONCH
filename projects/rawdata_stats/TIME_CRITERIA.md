# 时间统计判据

实现：`src/time_stats.py`。每个数据集写出并列的 `time_write/` 与 `time_record/`。
两套统计共用下面 6 个实体，不统计 `case`、`demographic`、`exposures[]`、`family_histories[]`。
槽位编号按 JSON DFS 遇到顺序，1-based，不按时间排序。
`follow_ups[]` 只给真实随访事件编号：有 `days_to_follow_up`、`submitter_id`，或任意非 nested 临床内容。
只有 `follow_up_id`、实质内容只是挂着的 `molecular_tests[]` / `other_clinical_attributes[]` 的壳对象排除出 `follow_ups` 分母和槽位；nested 数组仍按原规则统计。
`diagnoses[].treatments[]` 中 `treatment_or_therapy=no` 的对象同样排除出 treatments 分母、槽位和 landmark。

生存终点两套目录各放一份，规则不变：

- Dead：`demographic.days_to_death`
- 非死亡：先取 `diagnoses[].days_to_last_follow_up` 的最大值；没有再用 `follow_ups[].days_to_follow_up` 的最大值

完整任务说明见 `z_temp/time_write_record_spec.md`。

Field Bank 取值默认复用这套槽位做患者级 landmark mask：状态不是 `unlocated` / `non_informative`，且有限 `t_hi <= T`。`T` 是外部传入的全局 landmark 起点（天），不是生存终点。`t_write` / `updated_datetime` 不参与取值门控。无时间实体不 mask；缺 `T` 时直接报错，该槽缺有限 `t_hi` 时按缺失处理。字段表对所有患者保持同一套，被 mask 的值走现有 missing placeholder，不删列。

demographic、exposures[]、family_histories[] 不用统计

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

`t_record` 是区间 `(t_lo, t_hi)`。CSV 单元格写有限 `t_hi`；归一化仍是 `t_hi / last_time_days`。
landmark 收状态不是 `unlocated` / `non_informative` 且 `t_hi <= T` 的槽。事件天数只给下界，不单独当上界。
`diagnoses[].treatments[]` 中 `treatment_or_therapy=no` 的对象不编号、不进覆盖率、也不进 landmark。需要 biospecimen 的分子检测记 `unlocated`。覆盖率按 `point` / `bounded` / `lo_only` / `unlocated` / `non_informative` 拆分。

| 实体 | 主判据 | 备选判据 | 兜底 | 产物列名 |
| --- | --- | --- | --- | --- |
| `diagnoses[]` | 既往史定点 `(0,0]`；其余 `days_to_diagnosis` 作 `t_lo`，`t_hi` 走 H1b/H2 | — | 无天数则 `unlocated` | `diagnoses_record{i}` |
| `diagnoses[].treatments[]` | 结束日/结局作 `t_lo`，否则起始日；`t_hi` 走 H1b/H2 | 既往史定点 `(0,0]`；`Prior to Diagnosis` 且父 `prior_treatment=yes` 定点 | `treatment_or_therapy=no` 不编号；无天数、错标 Prior to Diagnosis 记 `unlocated` | `diagnoses_treatments_record{i}` |
| `diagnoses[].pathology_details[]` | P1/P2 用诊断日作 `t_lo`，`t_hi` 走 H1/H1b/H2 | — | P3 或无诊断日记 `unlocated`；不读 `days_to_pathology_detail` | `diagnoses_pathology_details_record{i}` |
| `follow_ups[]` | `days_to_follow_up` 作点 | — | 壳对象不编号；有内容无天数 `unlocated`；空行 `non_informative` | `follow_ups_record{i}` |
| `follow_ups[].molecular_tests[]` | 有 `days_to_test` 时作 `t_lo`，`t_hi` 走 H1b/H2 | P1 型 Initial Diagnosis / Preoperative 可给 `t_hi<=0` | Sample Procurement 与 P2 Preoperative 需 biospecimen，记 `unlocated` | `follow_ups_molecular_tests_record{i}` |
| `follow_ups[].other_clinical_attributes[]` | Initial / Prior to Diagnosis 定点 `(0,0]` | 正的 comorbidity/risk 天数作 `t_lo` | 天数不是记录时间；Not Reported 与生命阶段记 `unlocated` | `follow_ups_other_clinical_attributes_record{i}` |

---

## 覆盖率

各目录 `missing/{family}.csv` 与同名 png。按数组槽位：

- 分母：该槽位对象存在的患者数；`follow_ups[]` 不计壳对象
- 分子：该槽算出有限 `t_hi`，且状态不是 `unlocated` / `non_informative` 的人数
- 拆分：`point` / `bounded` / `lo_only` / `unlocated` / `non_informative`
- 排除：分母 − 分子
- 单元格：`24/25`
- 路径：`diagnoses[].pathology_details[1]`
