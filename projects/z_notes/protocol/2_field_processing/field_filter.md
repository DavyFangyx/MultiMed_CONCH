# 字段筛选(field filter)—— pipeline 字段线第③步[字段级]

主文件:见 [`../tcga_pipeline/README.md`](../tcga_pipeline/README.md)。本文展开第③步的口径与实现;规则冲突时以
`z_notes/Test_series_spec.md` 为准,时间/槽位口径见 `z_notes/protocol/1_landmark/time_axis.md`。

## 一句话

在字段统计(第②步)之上,用 **R0-R6 规则**决定每个数据集"哪些字段准入"。
统计口径 = **landmark-first(已扶正 2026-10-05)**:coverage / n_unique / mode_share
在 `t_hi ≤ T` 的 masked 值上计算,**R3/R4 作用在 t0 口径上——landmark 先于 R3/R4**。

## 输入 → 输出

- 输入:`rawdata_stats/{ds}/landmark_0/field_stats.csv`(第②步 landmark-first 统计,
  Field Bank 同款 mask 提取)+ `templates/field_filter_rules.json`(R0/R1/R5 名单)
- 输出(现行目录):
  - `rawdata_stats/{ds}/landmark_0/kept_fields.json` → `{"n_patients": N, "fields": [...], "coverage": {field: cov}}`;
  - `rawdata_stats/{ds}/landmark_0/fliter_log/exclusion_log.csv`(每条排除:dataset / field / rule /
    trigger / coverage / n_unique / mode_share);
  - `rawdata_stats/{ds}/landmark_0/fliter_log/field_registry.csv`(逐字段 keep 判定 + 汇总列);
  - 共享合并:`rawdata_stats/_shared/landmark_0/kept_fields.json`。

## R0-R6 规则速查

| 规则 | 语义 | 落点 |
|---|---|---|
| R0 | 标签泄露**硬排除**(leaves / substrings / path_suffixes / leaf_startswith 名单;`except_leaves` 白名单)。**不因 landmark 开关删除 timed 层**(2026-10-08 口径对齐:原"无 landmark 时整层删除 diagnoses / follow_ups"条款已移除;no_mask = 全字段不裁剪,与 landmark_0 同字段集;取值裁剪只在 Field Bank 提取期 mask) | `templates/field_filter_rules.json` → R0_label_leak |
| R1 | 行政 / 标识字段(leaves 名单 + leaf_endswith 后缀;container_leaves) | R1_admin |
| R2 | ~~timepoint 结构标记(follow_up/baseline)~~ **已移除 2026-10-05**:无下游消费者,且"按字段所在层判时点"与 time_axis 的槽位 t_hi 语义不一致;该语义由 landmark-first R3(t0 coverage)承载。编号保留不复用,以免与历史产物规则名冲突 | — |
| R3 | **coverage < 0.30 删除**。landmark-first 下 coverage = t0 口径(masked 值上的有效占比) | `--R3_coverage`,默认 0.30 |
| R4 | **退化删除**:n_unique < 2 或 mode_share > 0.95。同样作用在 t0 值上 | `--R4_n_unique` 2 / `--R4_mode_share` 0.95 |
| R5 | 可派生字段策略:drop 组删除,keep 组保留(组内 drop 名单按 leaf) | R5_derivable |
| R6 | **仅标记不删**:portability = universal / common / local(按字段在多少数据集被保留:≥0.8 / ≥0.5)。用途:量化"通吃字段 vs 局部字段"(癌种特有字段合法),供方案组合参考 | `filter.py::_portability` |

## 口径顺序(核心)

| | ~~旧链(raw-first,已废弃)~~ | **现行链(landmark-first,已扶正 2026-10-05)** |
|---|---|---|
| 顺序 | ② raw 统计 → ③ R3/R4 筛 raw coverage → ④ Field Bank 取值时才 mask | ② masked 值统计(`--landmark_time 0`)→ ③ R3/R4 筛 t0 口径 |
| 缺陷 | t0 覆盖崩塌的字段仍准入 → Test_1a 旧头条(+0.034)被"字段整个消失"的伪效应驱动 | — |
| 影响面 | — | 15 主集 468 对中 **172 对被排除** = R3_coverage 124 + R4_degenerate 48;准入 296 |

- 扶正实现:`run_field_filter` 在 landmark 开启且 `rawdata_stats/_shared/{tag}/field_stats.csv`
  存在时**默认消费 landmark-first 统计**(`filter.py::resolve_filter_stats_path`);
  显式 `--stats_csv` 仍可覆盖 raw 口径(旧机制保留为显式能力)。
- 旧 raw-first 产物已移走 `z_notes/backup/landmark_first_promotion_20261005/`;
  清理登记见 `z_notes/Test_series_execution_log.md` D13 行。
- **未决**:365/730 的 landmark 统计尚未生成,当前跑 `--landmark_time 365` 会回退 raw
  统计(静默 raw-first);建议改为"统计缺失直接报错"——待用户拍板。


## 代码落点

- 规则与主循环:`src/discovery/filter.py`(`apply_rules` / `run_field_filter` /
  `_run_field_filter_one` / `resolve_filter_stats_path`)
- 统计口径:`src/discovery/stats.py`(`--landmark_time`,经 `extract_field_bank_raw_values`
  与 Field Bank 同源;none 行为不变)
- 路径:`src/common/paths.py`(`dataset_kept_fields_path` / `dataset_filter_log_dir` /
  `_tag_with_suffix` 后缀命名空间)
- CLI:`src/discovery/cli.py`(`build_filter_parser`:`--R3_coverage` / `--R4_n_unique` /
  `--R4_mode_share` / `--out_suffix`;`--stats_csv` 默认 None = 自动选择)
