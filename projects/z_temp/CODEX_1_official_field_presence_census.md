# Codex 1：Task — 官方总表键出现情况统计

Audience: 另一个 Codex。只做第一步，不要改筛选、三态缺失、R0–R6、时间统计、Field Bank。
做完后把产物路径和自检数字写回，交给审计。

---

## 目标

对照 GDC 官方 clinical JSON 字段总表，统计 33 个 TCGA 数据集里：**总表里的键有没有在该数据集 JSON 中出现过**。

只看键是否出现，不看取值是否缺失、是否 sentinel、覆盖率多少。

三类状态：

| status | 含义 |
| --- | --- |
| `in_table_and_data` | 官方总表有这条路径，该数据集至少 1 例 JSON 扫到过这个键 |
| `in_table_not_data` | 官方总表有，该数据集所有病例都没出现过这个键 |
| `not_in_table` | 该数据集 JSON 扫到了这个键，但官方总表没有 |

本步不删字段，不改 `kept_fields.json`，不重跑 `run_field_filter.py` / `run_time_stats.py`。

---

## 官方总表（字段宇宙）

唯一宇宙：

```text
ClinicDatasets/gdc_clinical/field_tables/gdc_cases_mapping.csv
```

列：`field, entity, type, description, in_clinical_json`

- `field` 是 clinical JSON 可查询路径，例如 `demographic.race`、`diagnoses.age_at_diagnosis`、`diagnoses.treatments.treatment_type`。
- 当前 499 行，全部 `in_clinical_json=yes`。
- `type` / `description` **全空**，本步不要用这两列当元数据，也不要重跑 `gdc_field_tables.py`。

可选 join（只给审计表补 entity，不改变宇宙）：

```text
ClinicDatasets/gdc_clinical/field_tables/gdc_clinical_dictionary.csv
```

按 `(entity, leaf)` join。`leaf` = mapping `field` 的最后一段。dictionary 的 `entity` 是单数（`diagnosis`），mapping 路径里是复数（`diagnoses.`）。

dictionary 有 542 行，含实体内部关联容器（如 `diagnosis.cases`）。那些不是 JSON 叶子路径，**不要**拿 542 当宇宙。

元数据快照（只读）：`ClinicDatasets/gdc_clinical/field_tables/run_metadata.json`，Data Release 46.0。

---

## 数据范围

- 数据集名单：`datasets.json` 的 33 个 key（含历史名 `TCGA_LIHC`）。
- 病例读取必须走现有 `load_clinical_cases`：按 `clinic_files` 读 JSON，丢掉无 `submitter_id`，按 `project_ids` 切开，按 `submitter_id` 去重保留首次。
- 不要另写一套读 JSON 的逻辑。

可复用现有扫描：

- `src/discovery/scan.py` 的 `_collect_keys`
- 已有产物 `rawdata_stats/{dataset}/scanned_fields.json`

如果某数据集还没有 `scanned_fields.json`，先对该数据集跑现有：

```bash
python projects/scripts/run_scan_fields.py --dataset <name>
```

不要发明第二种扫描。优先复用已有 `scanned_fields.json`，不要无故重扫全部 33 个 JSON。

---

## 路径对齐（必须写死）

官方 mapping 不带 `[]`。现有扫描带 `[]`。join 前统一成 mapping 风格：

1. 从 `scanned_fields.json` 还原路径：`prefix + "." + key`，prefix 来自 `_section_prefixes`。
2. 去掉所有 `[]`。
   - `diagnoses[].age_at_diagnosis` -> `diagnoses.age_at_diagnosis`
   - `diagnoses[].treatments[].treatment_type` -> `diagnoses.treatments.treatment_type`
   - `follow_ups[].molecular_tests[].gene_symbol` -> `follow_ups.molecular_tests.gene_symbol`
3. 顶层别名只处理这两对，且只在和 mapping 对齐时使用：
   - JSON `case_id` <-> mapping `case_id`（dictionary 里是 `case.id`）
   - JSON `project.project_id` <-> mapping `project.project_id`（dictionary 里是 `case.project_id`）
4. **不要**把嵌套 `submitter_id` / `id` / `created_datetime` 折叠到 case 根字段。`diagnoses.submitter_id` 和 `submitter_id` 是两条键。

容器叶子本身（`demographic`、`diagnoses`、`follow_ups`、`project`、`diagnoses.pathology_details` 等）会出现在扫描并集里，但 mapping 没有这些容器键。它们必须记为 `not_in_table`，不要丢弃不报。

---

## 统计口径

“出现过”= 该数据集纳入病例的 JSON 并集里有这个 key。只要 1 例出现过就算 `in_table_and_data`。

不要用 `field_stats.csv` 的 `valid` / `coverage`。键在、值全是 null / Not Reported，本步仍算出现。

对每个数据集：

1. 取 mapping 499 条为左表。
2. 取该数据集扫描并集（去 `[]` 后）为右表。
3. 左交右 -> `in_table_and_data`
4. 左减右 -> `in_table_not_data`
5. 右减左 -> `not_in_table`

再做一份 33 数据集合计：某 mapping 字段在多少个数据集出现过。

---

## 产物（只写这些）

目录：`rawdata_stats/`，不要写进 `outputs/`。

### 1. 每数据集明细

```text
rawdata_stats/{dataset}/field_presence.csv
```

一行一个键。必须包含：

| 列 | 内容 |
| --- | --- |
| `dataset` | 如 `TCGA-BRCA` / `TCGA_LIHC` |
| `mapping_field` | 对齐后的路径；`not_in_table` 也用去 `[]` 后的扫描路径 |
| `scan_field_path` | 原始扫描路径（带 `[]`）；只在 mapping 里、扫描没有时留空 |
| `entity` | mapping.entity；`not_in_table` 可空 |
| `status` | 三态之一 |
| `n_cases` | 该数据集纳入病例数，与 `scanned_fields.json` 的 `_meta.n_cases` 一致 |

建议按 `status, mapping_field` 排序。

### 2. 每数据集计数

```text
rawdata_stats/{dataset}/field_presence_summary.json
```

示例：

```json
{
  "dataset": "TCGA-BRCA",
  "n_cases": 1098,
  "n_mapping_fields": 499,
  "n_scanned_fields": 152,
  "in_table_and_data": 143,
  "in_table_not_data": 356,
  "not_in_table": 9,
  "source_scanned_fields": "rawdata_stats/TCGA-BRCA/scanned_fields.json"
}
```

`n_scanned_fields` = 扫描并集键数（含容器叶子）。必须满足：

- `in_table_and_data + in_table_not_data = 499`
- `in_table_and_data + not_in_table = n_scanned_fields`

### 3. 跨数据集总表

```text
rawdata_stats/_shared/field_presence.csv
rawdata_stats/_shared/field_presence_summary.csv
rawdata_stats/_shared/field_presence_mapping_census.csv
```

- `_shared/field_presence.csv`：33 个数据集明细纵向拼接。
- `_shared/field_presence_summary.csv`：每数据集一行，列与 summary JSON 对齐。
- `_shared/field_presence_mapping_census.csv`：mapping 499 行，列至少包括：
  - `mapping_field`
  - `entity`
  - `n_datasets_present`：在多少个数据集是 `in_table_and_data`
  - `n_datasets_total`：33
  - `present_datasets`：出现过的数据集名，逗号分隔，按 `datasets.json` 顺序

不要改现有 `field_stats.csv` / `kept_fields.json` / `fliter_log/` / `time/`。

---

## 实现约束

1. 代码放在现有 discovery 链里，例如 `src/discovery/presence.py` + `scripts/run_field_presence.py`，CLI 风格对齐 `run_scan_fields.py`：`--dataset all` 或单个/逗号列表。
2. 不要把普查塞进 `run_field_filter.py`。
3. 不要改 `src/common/missingness.py`、`src/discovery/filter.py`、`src/time_stats.py`。
4. 不要重写 `gdc_field_tables.py`，不要下载新数据。
5. README 最多在 `rawdata_stats/README.md` 加一小段产物说明；不要趁机改 R0–R6 文档口径。
6. 工作目录：`CONCH-main`，命令形如：

```bash
python projects/scripts/run_field_presence.py --dataset all
```

---

## 自检（必须跑，写进最终回复）

对 `TCGA-BRCA`（已有 `scanned_fields.json`）核对：

- `n_mapping_fields = 499`
- `n_scanned_fields` 约 152（以该文件实际键数为准）
- `in_table_and_data` 约 143
- `in_table_not_data` 约 356
- `not_in_table` 约 9，应基本是容器叶子：`demographic`、`diagnoses`、`diagnoses.pathology_details`、`diagnoses.treatments`、`exposures`、`follow_ups`、`follow_ups.molecular_tests`、`follow_ups.other_clinical_attributes`、`project`

跨 33 数据集并集（去 `[]` 后）此前探查约：

- `in_table_and_data` 并集 377
- mapping 从未出现 122
- 扫描多余键 10（9 个容器叶子 + `family_histories`）

数字可以因扫描文件更新差几个，但三类关系必须成立，容器叶子必须落在 `not_in_table`。

加最小测试：路径去 `[]`、`case_id` / `project.project_id` 对齐、容器叶子标记为 `not_in_table`。可放进 `tests/test_common_and_filter.py` 或新测试文件，不要改现有 R0/R1 断言。

---

## 明确不要做

- 不要改 R0 / R1 / sentinel 词表。后续步骤会用官方表重做，本步不做。
- 不要用 dictionary `category=administrative` 删字段。
- 不要统计取值、覆盖率、三态缺失。
- 不要生成 Field Bank 模板。
- 不要改 `outputs/`。

---

## 完成后怎么交审计

最终回复只需要：

1. 改了哪些文件
2. 怎么跑：`python projects/scripts/run_field_presence.py --dataset all`
3. `TCGA-BRCA` 三类计数
4. `_shared/field_presence_summary.csv` 的 33 行计数表
5. mapping 499 里有多少字段 `n_datasets_present=0` / `=33`
6. 测试命令和结果

不要在回复里贴整张 499 行表。
