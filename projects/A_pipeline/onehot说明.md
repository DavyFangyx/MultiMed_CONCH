# D 组混合编码说明

D0-D5 现在按 GDC dictionary 的字段类型编码，不再用人工划分的 continuous / ordinal / nominal。

- `enum` / `boolean` → onehot
- `integer` / `number` → ordinary（标量 min-max）
- 人工方案字段现在用 greedy 同款字段名。ordinary 只有 `demographic.age_at_index`、`diagnoses[].year_of_diagnosis`、`diagnoses[].age_at_diagnosis`、`diagnoses[].pathology_details[].lymph_nodes_tested`、`diagnoses[].pathology_details[].lymph_nodes_positive`、`follow_ups[].other_clinical_attributes[].bmi`，以及论文方案里的 `exposures[].pack_years_smoked`、`derived.years_smoked`、`exposures[].cigarettes_per_day`
- 其余字段全部 onehot，包括原来按 ordinal 处理的 `diagnoses[].tumor_grade`、AJCC T/N/M/stage、`follow_ups[].ecog_performance_status`

类别规则不变：

- `MISSING` 单独保留
- 出现次数 `>= threshold` 的类别保留
- 出现次数 `< threshold` 的类别合并到 `OTHER`
- 默认 `--baseline_nominal_min_count 5`

多数据集跑 `baseline` 时，仍会先合并所选患者，生成一份共享的 `category_mapping.json` 和 `feature_schema.json`。

共享 mapping 目录：

- `A_pipeline/baseline_onehot_mapping_tables/category_mapping.json`
- `A_pipeline/baseline_onehot_mapping_tables/feature_schema.json`

每个数据集本地 metadata 仍只保留：

- `normalization_stats.json`
- `global_metadata_ref.json`

HGCN clinic 不走这套 dictionary 分类：

- 入口仍是 `python projects/A_pipeline/run.py hgcn_clinic ...`
- 字段类型仍是原来的 continuous / ordinal / nominal
- ordinal 仍用整数编码器，nominal 仍用 `fit_nominal_mappings`

建议使用方式：

- 单数据集：`python projects/A_pipeline/run.py baseline --dataset TCGA-READ --scheme all --baseline_nominal_min_count 5`
- 多数据集共享全局 metadata：`python projects/A_pipeline/run.py baseline --dataset all --scheme all --baseline_nominal_min_count 5`
