# 序列提交时间按类型拆表：实现方案

Audience: 实现或复现 `rawdata_stats/{dataset}/time` 的代码。
不要改提交时间的抽取规则，只把现有宽表按序列类型拆成多张表。

---

## 1. 现状

入口：`src/time_stats.py`，脚本：`python projects/scripts/run_time_stats.py --dataset TCGA_LIHC`

当前每个数据集只写两张宽表：

- `rawdata_stats/{dataset}/time/patient_time_stats.csv`：原始 `updated_datetime`
- `rawdata_stats/{dataset}/time/normalized_update_time.csv`：相对该患者首次提交、再除以 `last_time_days` 的归一化值

序列字段已经在宽表里，只是混在同一行。LIHC 例子：

- `diagnoses_updated1` ... `diagnoses_updated5`
- `diagnoses_treatments_updated1` ... `diagnoses_treatments_updated29`
- `follow_ups_updated1` ... `follow_ups_updated9`
- 以及 `family_histories`、`diagnoses_pathology_details`、`follow_ups_molecular_tests`、`follow_ups_other_clinical_attributes`

目标：每种序列性数据单独一张表。`diagnoses_updated1/2/3` 进入 diagnoses 表，其余同理。

---

## 2. 不要改的抽取规则

拆表前，继续沿用现有逻辑。

1. 病例读取：`load_clinical_cases`，按 `submitter_id` 去重，保留首次。
2. DFS 遍历 case JSON。对象则递归；值为“dict 列表”则逐项递归，并记为 array。
3. 只收集 `updated_datetime`，忽略 `created_datetime`。
4. 列族名 = 路径用 `_` 连接。`diagnoses[].treatments[].updated_datetime` -> `diagnoses_treatments`。
5. 编号按 JSON 遍历顺序，**不按时间排序**。`updated1` 是遇到的第 1 条，不一定更早。
6. 列数按数据集最大条数对齐。患者不足的格子留空。
7. 标量对象（`demographic`）列名是 `{key}_updated`，没有数字后缀。
8. case 根节点是 `updated_datetime`。

归一化也保持不变：

- `t_start` = 该患者所有提交时间的最小值
- `last_time_days`：Dead 用 `days_to_death`，否则用 `days_to_last_follow_up`
- 单元格 = `(dt - t_start) / last_time_days`，可以大于 1

---

## 3. 序列族怎么切

复用已有 `_field_family(col)`：

| family | 列模式 | 是否拆表 |
|---|---|---|
| `diagnoses` | `diagnoses_updated{i}` | 是 |
| `diagnoses_treatments` | `diagnoses_treatments_updated{i}` | 是 |
| `diagnoses_pathology_details` | `diagnoses_pathology_details_updated{i}` | 是 |
| `follow_ups` | `follow_ups_updated{i}` | 是 |
| `follow_ups_molecular_tests` | `follow_ups_molecular_tests_updated{i}` | 是 |
| `follow_ups_other_clinical_attributes` | `follow_ups_other_clinical_attributes_updated{i}` | 是 |
| `family_histories` | `family_histories_updated{i}` | 是 |
| `exposures` | `exposures_updated{i}` | 有才写 |
| `case` | `updated_datetime` | 可选，不是数组 |
| `demographic` | `demographic_updated` | 可选，不是数组 |

默认只拆带数字后缀的数组族。`case` / `demographic` 不要放进 diagnoses 表。

文件名用 family 原名，不要改成 `diagnose.csv`：

```text
diagnoses.csv
diagnoses_treatments.csv
follow_ups.csv
```

---

## 4. 每张表的 schema

保持宽表，不改成长表。一行一个患者，列为 `updated1..N`。

### 原始时间表

路径：`rawdata_stats/{dataset}/time/sequences/{family}.csv`

```text
dataset,submitter_id,case_id,{family}_updated1,{family}_updated2,...,{family}_updatedN
```

`N` = 该数据集该 family 的最大条数，与当前宽表一致。

LIHC diagnoses 表示例：

```text
dataset,submitter_id,case_id,diagnoses_updated1,diagnoses_updated2,diagnoses_updated3,diagnoses_updated4,diagnoses_updated5
TCGA_LIHC,TCGA-DD-AAVP,<case_id>,2025-10-24T...,2025-01-08T...,2025-01-08T...,2025-01-08T...,
```

### 归一化时间表

路径：`rawdata_stats/{dataset}/time/sequences_normalized/{family}.csv`

```text
dataset,submitter_id,case_id,vital_status,last_time_days,last_time_source,{family}_updated1,...,{family}_updatedN
```

归一化值仍按**该患者全部提交时间**的 `t_start` 计算，不是按这个 family 自己的最早时间。否则跨表不可比。

---

## 5. 代码改动

只改 `src/time_stats.py`，在 `analyze_dataset_times()` 写完两张宽表之后拆表。不要重爬 JSON。

```python
SEQUENCE_ID_COLS = ["dataset", "submitter_id", "case_id"]
NORMALIZED_ID_COLS = [
    "dataset", "submitter_id", "case_id",
    "vital_status", "last_time_days", "last_time_source",
]

def _sequence_families(df) -> dict[str, list[str]]:
    families = OrderedDict()
    for col in _ordered_update_columns(df):
        family = _field_family(col)
        if family in {"case", "demographic"}:
            continue
        families.setdefault(family, []).append(col)
    return families

def write_sequence_tables(df, output_dir: Path, id_cols: list[str]) -> list[Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    keep_ids = [c for c in id_cols if c in df.columns]
    for family, cols in _sequence_families(df).items():
        sub = df.loc[:, keep_ids + cols].copy()
        path = out_dir / f"{family}.csv"
        sub.to_csv(path, index=False)
        written.append(path)
    return written
```

在 `analyze_dataset_times()` 末尾：

```python
write_sequence_tables(df, output_dir / "sequences", SEQUENCE_ID_COLS)
if not wide.empty:
    write_sequence_tables(wide, output_dir / "sequences_normalized", NORMALIZED_ID_COLS)
```

宽表和现有 png 继续写，作为兼容层。

---

## 6. 输出布局

```text
rawdata_stats/TCGA_LIHC/time/
  patient_time_stats.csv
  normalized_update_time.csv
  sequences/
    diagnoses.csv
    diagnoses_treatments.csv
    diagnoses_pathology_details.csv
    follow_ups.csv
    follow_ups_molecular_tests.csv
    follow_ups_other_clinical_attributes.csv
    family_histories.csv
  sequences_normalized/
    diagnoses.csv
    ...
```

某个数据集没有 `exposures` 就不要写空表。

---

## 7. 测试

扩展 `run_self_test()`：

1. 合成样本已有 1 条 diagnosis、2 条 treatments、2 条 follow_ups。
2. `sequences/diagnoses.csv` 含 `diagnoses_updated1`，没有 `follow_ups_updated1`。
3. `sequences/diagnoses_treatments.csv` 含 `updated1` 和 `updated2`；第二条患者的 `updated2` 为空。
4. 归一化表的 diagnoses 值与宽表同列相同。
5. 列顺序按 `updated1, updated2, ...`，不要按时间重排。

回归命令：

```bash
python projects/scripts/run_time_stats.py --self_test
python projects/scripts/run_time_stats.py --dataset TCGA_LIHC
```

---

## 8. 明确不做

- 不按 `updated_datetime` 重排序列。
- 不改成长表 `(submitter_id, seq_index, updated_datetime)`。若以后要长表，另开函数，不要替换宽表。
- 不把所有 diagnosis 压成一条。时间统计保留每次提交。
- 不用 `get_primary_diagnosis` / `unique_join`。那是 prompt 展平规则，和这里无关。
- 不改 ground-truth 生存时间。
