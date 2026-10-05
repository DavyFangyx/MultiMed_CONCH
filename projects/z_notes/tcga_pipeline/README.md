# TCGA 数据集处理 pipeline(当前状态)

状态日期:2026-10-05。**权威口径**以 `z_notes/Test_series_spec.md` 为准;时间/槽位口径以
`z_notes/time_axis/time_axis.md` 为准;执行历史见 `z_notes/Test_series_execution_log.md`。
本文只是一页地图,冲突时以上述文档为准。

## 一图流

```
ClinicDatasets/gdc_clinical/raw_json/{ds}.json        ← 33 个 TCGA 原始 GDC clinical JSON
  │ ① run_scan_fields.py(字段字典扫描)
  ▼
rawdata_stats/{ds}/scanned_fields.json                ← 字段路径字典
  │ ② run_field_stats.py [--landmark_time 0]         ← 统计口径在此分叉(见下)
  ├──────────────────────────────┬─────────────────────────────────────
  ▼ raw 统计(官方链)             ▼ landmark-first 统计(S7b 新链)
rawdata_stats/{ds}/field_stats.csv   rawdata_stats/{ds}/landmark_0/field_stats.csv
  │ ③ run_field_filter.py             │ (coverage/unique/mode_share 在 t_hi≤T 的 masked 值上算)
  │    R0-R6,R3≥0.30/R4≥2/0.95       │ ③ run_field_filter.py --stats_csv landmark_0 统计
  │                                   │    --out_suffix t0stats(同一套 R0-R6)
  ▼                                   ▼
landmark_0/kept_fields.json      landmark_0_t0stats/kept_fields.json
(官方:先 R3/R4、后 landmark)    (Test_1a 准入口径:先 landmark、后 R3/R4)
  └──────────────┬─────────────────┘
  │ ④ run_field_bank.py --landmark_time 0 --encoding prompt
  │    取值提取对 timed 槽位按 t_hi≤T mask;masked → "not reported" 占位符(不删列不删人)
  ▼
outputs/{ds}/field_bank/prompt/landmark_0/
  prompts.csv + embeddings/pt/{patient}.pt(含逐字段 mask bool)+ field_index.json
  │ ⑤ run_schemes.py / A_pipeline templates(schemes.json)   ← L2/L3/L5 + 10 个论文方案
  │ ⑥ label:results/Test_2b/arm_B/labels/{study}__landmark_0.csv
  │    派生 label = gt≤T 剔除 + 时间平移 gt−T;另有 gt≤0 全局剔除(所有臂,label 层)
  ▼
评估(5 折 CV seed 0,val c-index):run_univariate_cindex.py(逐字段)
  / Test_2b 两臂(off vs landmark_0,唯一差异 = mask)/ Test_3 贪婪三臂
  ▼
results/Test_*  →  results_display/scripts/*.py  →  results_display/Test_*/ 报表
```

## 各阶段速查

| # | 阶段 | 脚本 / 落点 | 输入 → 输出 | 说明 |
|---|---|---|---|---|
| ① | 字段扫描 | `scripts/run_scan_fields.py` | raw JSON → `scanned_fields.json` | 字段路径 + GDC 字典释义 |
| ② | 字段统计 | `scripts/run_field_stats.py`(stats 在 `src/discovery/stats.py`) | JSON + 字段字典 → `field_stats.csv`(coverage / unique_count / mode_share / 三态缺失等) | `--landmark_time 0` 时在 Field Bank 同款 mask 上统计,写 `landmark_0/field_stats.csv`;默认 none = 官方 raw 口径 |
| ③ | 字段筛选 | `scripts/run_field_filter.py`(`src/discovery/filter.py`) | stats CSV → `{tag}/kept_fields.json` + `fliter_log/{exclusion_log,field_registry}.csv` | R0 标签泄露、R1 行政字段、R3 coverage<0.30、R4 退化(n_unique<2 或 mode_share>0.95)、R5 可派生;`--out_suffix t0stats` 写 `landmark_0_t0stats/`(不动官方目录) |
| ④ | Field Bank | `scripts/run_field_bank.py`(`src/discovery/field_bank.py`) | kept_fields + 模板 → prompts.csv → CONCH 编码 → `embeddings/pt/*.pt` | 提取时逐患者逐字段记 mask bool;mask 判据 = 槽位 status 非 unlocated/non_informative 且有限 `t_hi ≤ T` |
| ⑤ | 方案组合 | `scripts/run_schemes.py` / `A_pipeline/templates/{scheme}/` | field bank → L2/L3/L5 与 10 个论文方案(MULTISURV/SURVPGC/MMSURV/INTEGRATIVE_DNN + HGCN×6 按癌种绑定) | 方案 × 数据集绑定见 spec §2.4 |
| ⑥ | 标签 | `A_pipeline/src/landmark_labels.py` + `Clinic_Analyzer/datasets/dataset_survival.py` | metadata → 派生 label CSV | landmark 三要件②③:风险集只留 gt>T、终点平移 gt−T;gt≤0 患者全局剔除(2026-10-05 拍板,所有臂含 off 臂) |
| ⑦ | 评估 | `run_univariate_cindex.py`、A_pipeline cindex、`run_greedy_search.py` | field bank + label + splits → `field_cindex.csv` / `cindex.csv` | 5 折 CV × seed 0,val c-index(`cv_c_mean`);不伪造独立测试集 |
| ⑧ | 报表 | `results_display/scripts/*.py` | results/Test_* → results_display/Test_*/ | 纯汇总,不新增训练;Main_/Appx_/Raw_/Meta_ 文件角色公约 |

## 核心概念:两条筛选链(landmark 与 R3/R4 的先后)

| | 官方链(现状) | landmark-first 链(S7b,2026-10-05) |
|---|---|---|
| 统计口径 | raw 值(未 mask) | t_hi≤T 的 masked 值(Field Bank 同款提取) |
| R3/R4 作用对象 | raw coverage / raw 值分布 | t0 coverage / t0 值分布 |
| 产物 | `rawdata_stats/{ds}/landmark_0/kept_fields.json` | `rawdata_stats/{ds}/landmark_0_t0stats/` |
| 后果 | t0 覆盖崩塌的字段仍准入 → Test_1a 旧头条被伪效应驱动 | 15 主集 172/468 被排除(124 R3 + 48 R4),Test_1a 头条按准入集重算 |
| 消费方 | field bank / Test_2b 臂 B / Test_3 bank(已完成) | Test_1a 报表准入列 + `Appx_excluded_fields.csv` |

取值时的 mask 本身**历来在 Field Bank 提取期生效**(阶段④);两条链的区别只在
"筛选统计用不用 mask 过的值"。官方 kept_fields 是否切换为新口径(选项 C)待用户拍板。

## 关键口径(一句话版)

- **landmark 三要件**:① 协变量只取 `t_hi ≤ T` 槽位;② 风险集只留 `gt > T`;③ 终点平移到 `gt − T`。默认 `landmark_0`(t0 = 诊断日)。
- **mask 语义**:被 mask 的值走 `"not reported"` 占位符(编码后进模型),**不删列、不删患者**——t0 覆盖崩塌的字段在 t0 臂变成常数特征(c≈0.5)。
- **患者资格**:`gt ≤ 0`(days_to_death=0 占位坑 + 负末次随访)从所有臂全局剔除。
- **数据集范围**:本阶段 33 TCGA(CPTAC/MMRF 只留描述性记录);训练限 15 主集(n_event ≥ 100);名单一律读 `results/Test_0_dataset_availability/manifest.csv`,不硬编码。
- **验收惯例**:同输入重跑 diff=0;抽查手算一致;产物目录 `results_display/**`、`rawdata_stats/**` 被 gitignore 留磁盘。

## 相关脚本速查

| 脚本 | 作用 |
|---|---|
| `scripts/run_landmark_first_filter.py` | 一条命令跑完 landmark-first 链(②`--landmark_time 0` → ③`--out_suffix t0stats`) |
| `scripts/validate_t0stats_vs_masks.py` | 验收:t0 stats coverage vs t0 臂 .pt mask 逐字段比对(tol 1e-5;35 数据集 max_abs_diff ≤ 5e-7) |
| `scripts/s5b_build_raw_field_bank.py` | Test_1a off 臂 raw bank(`outputs/_raw/.../landmark_none/`)+ `raw_value_diff.json` |
| `scripts/s5b_audit_arms.py` | Test_1a 两臂患者集一致性审计 |
