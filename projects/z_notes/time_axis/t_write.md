# t_write：GDC 入库时间审计（另册）

> **地位**：本文**不属于** [`time_axis.md`](time_axis.md) 的判据协议。`t_write` 按设计**不参与** landmark 取值 mask 与泄露判定（`src/discovery/landmark.py` 头部）。本文只回答：GDC 何时把数据写进库、如何归一化展示、有什么审计价值。

## 1. 是什么

`t_write` = 该对象在 GDC 的**入库/修订时间**（`updated_datetime`，忽略 `created_datetime`）。

- 与 `t_record` 的区别：`t_record` 问"这条信息**临床上**何时才可能被写下"（参与泄露判定，见 `time_axis.md` §4）；`t_write` 问"GDC 数据库何时才写入它"——纯粹的数据管线事实，与临床可得性无关。
- **"未来"的定义**（`time_axis.md` §1）：泄露指临床上属于 `t > T` 的信息，**不是**"后来才写入"。因此 `updated_datetime` 晚**不等于**泄露。t_write 统计的价值在审计，不在判据。

## 2. 归一化与 t0

- 归一化：`(updated − t0) / last_time_days`。
- `t0` = 该患者 6 个实体中**最早一次** `updated_datetime`（只在这 6 个实体里取）。
- 注意：这个 `t0` 是**入库时间轴**上的绘图锚点，与**临床轴锚点 index date 无关**（后者是 `days_to_*` 的零点，见 `time_axis.md` §2.1）。
- 覆盖率排除：该槽对象存在，但没有可解析的 `updated_datetime`。`follow_ups[]` 的壳对象不进入分母。

## 3. 实现表

判据一律是该对象自己的 `updated_datetime`（忽略 `created_datetime`）。缺或无法解析则该槽排除。

| 实体 | 主判据 | 备选判据 | 兜底 | 产物列名 |
| --- | --- | --- | --- | --- |
| `diagnoses[]` | `updated_datetime` | — | 缺失则排除 | `diagnoses_updated{i}` |
| `diagnoses[].treatments[]` | `updated_datetime` | — | 缺失则排除 | `diagnoses_treatments_updated{i}` |
| `diagnoses[].pathology_details[]` | `updated_datetime` | — | 缺失则排除 | `diagnoses_pathology_details_updated{i}` |
| `follow_ups[]` | `updated_datetime` | — | 壳对象不编号；其余缺失则排除 | `follow_ups_updated{i}` |
| `follow_ups[].molecular_tests[]` | `updated_datetime` | — | 缺失则排除 | `follow_ups_molecular_tests_updated{i}` |
| `follow_ups[].other_clinical_attributes[]` | `updated_datetime` | — | 缺失则排除 | `follow_ups_other_clinical_attributes_updated{i}` |

## 4. 产物目录

由 `python projects/scripts/run_time_stats.py --dataset all` 与 `time_record/` 一并产出（实现 `src/time_stats.py`）。

```text
rawdata_stats/{dataset}/time_write/
  patient_time_stats.csv / .png
  normalized_update_time.csv / .png / _boxplot.png
  sequences/{family}.csv / .png        # 6 个 family
  missing/{family}.csv / .png
```

生存终点 gt 同 `time_record/`，各放一份（规则见 `time_axis.md` §2.2）。

## 5. 审计价值

- **入库批次形态**：`sequences/` 图按患者排出 6 个实体的入库顺序与批次聚团，可用于发现集中重抄 / 回填。
- **已知发现**：两例 Hysterectomy 被错标 `Prior to Diagnosis`、且同属 2025-01 重抄批次（矛盾判定见 [`t_record_derivation.md`](t_record_derivation.md) §7.3）——批次归属即由 t_write 统计给出，是定位系统性错标批次的依据。
