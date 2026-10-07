# 探查记录:R5 字段组互斥性 + days_to_birth 单位(2026-10-08,只读)

用途:R5_derivable 从"删除"改为"别名映射"前的依据探查。结论:两组字段均非互斥,而是同源等价 → **不需要"按覆盖率选代表"逻辑,纯别名映射即可**。

## 组 sex

- `demographic.gender` 在 raw_json 中**不存在**(33 文件递归扫描 0 次),字典与 cases_mapping 也无;它是 legacy biotab 源的同义列。
- 跨源一致性(biotab `gender` join raw_json `sex_at_birth`,按 barcode):join 11167 例,非空 11163/11163 **100% 一致**;4 处不一致均为 `[Not Available]`/`[Unknown]` vs `unknown`(两侧同为缺失)。
- → 别名映射只需统一大小写与缺失占位符,无覆盖率择优需求。

## 组 age:高度共现 + 严格包含链

- 三字段为同一信息的三次表达,33 数据集共现率 91.6%–100%(31 个 ≥95%,其中 16 个 = 100%),**0 个互斥**。
- 严格包含链 `age_at_index ⊇ days_to_birth ⊇ age_at_diagnosis`(有 ad 必有 db、有 db 必有 ai 的患者数 = 0)。
- 非三字段齐备的患者仅两类共 124 例(1.1%):`ai only` 68 例;`ai & db only` 56 例(KIRP 14 / LUSC 10 / PRAD 31 / STAD 1)。
- 覆盖总数:age_at_index 11223 > days_to_birth 11155 > age_at_diagnosis 11099(总 N=11428;127 例整个 demographic dict 缺失)。
- 值一致性抽样(ACC 3 例):age_at_index=74 ↔ days_to_birth=-27179 ↔ age_at_diagnosis=[27179],语义完全一致,差异仅为"年取整"。

## 单位

| 字段 | 单位 | 换算 |
|---|---|---|
| `demographic.age_at_index` | 岁(整数,已 floor) | `= floor(-days_to_birth / 365.25)`,全库 99.96% 精确命中,除数是 **365.25 不是 365** |
| `demographic.days_to_birth` | 天(**负数**),范围 -32872~0 | 与 age_at_diagnosis 同量纲、互为镜像(差一个负号) |
| `diagnoses[].age_at_diagnosis` | 天(正) | 同 days_to_birth |

- legacy biotab 的 `birth_days_to` 是 days_to_birth 的前身(同为负天)。

## 决策含义(当时记录)

1. 组 age 无需覆盖率择优;canonical 选择是精度/覆盖取舍 → 最终选 `age_at_index`(覆盖最高,方案字段同名命中)。
2. 原 R5 note "age can be derived from diagnoses.age_at_diagnosis" **不严谨**:3646 例多条 diagnosis 年龄各异,14 例(含 KIRP 12)无法还原;正确派生需 `diagnosis_is_primary_disease` 先选主诊断。
3. days_to_birth 单独保留为自有字段,模板 convert 需处理负号(见协议修订)。
4. 127 例 demographic dict 整体缺失(DLBC 10 / LUAD 63 / OV 21 / GBM 17 / UCEC 12 等),纯 demographic 派生的年龄/性别列对这些患者整块缺失。

## 关键文件

- `templates/field_filter_rules.json`(R5 定义)
- `ClinicDatasets/gdc_clinical/raw_json/TCGA-*.json`(33 个,连字符命名)
- `ClinicDatasets/gdc_clinical/field_tables/gdc_clinical_dictionary.csv`
- `ClinicDatasets/gdc_clinical/biotab/TCGA-*/…_clinical_patient_*.txt`(gender / birth_days_to 来源)
