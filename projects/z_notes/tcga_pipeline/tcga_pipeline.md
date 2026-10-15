# TCGA 数据集处理 pipeline(执行层地图)

**规则权威 = 协议层**(总纲 `z_notes/protocol_sum.md`):规则0 队列与患者筛选
`z_notes/protocol0_cohort_selection/cohort_rules.md`、规则1 landmark/时间轴 `z_notes/protocol1_landmark/time_axis.md`、
规则2 字段处理 `z_notes/protocol2_field_processing/field_filter.md`;实验口径以 `z_notes/Test_series_spec.md` 为准;
执行历史见 `z_notes/Test_series_execution_log.md`。本文只是执行层的一页地图,冲突时以协议层与 spec 为准。

## 规则引用(口径不再在本页重复)

- **规则0 队列与患者筛选**(gt≤0 全局剔除 → label 患者集 → 数据集分档协议四档 14 主集)→ [`../protocol0_cohort_selection/cohort_rules.md`](../protocol0_cohort_selection/cohort_rules.md)
- **规则1 landmark 三要件 / t_record 判据 / mask 语义** → [`../protocol1_landmark/time_axis.md`](../protocol1_landmark/time_axis.md)
- **规则2 字段处理(R0–R6 筛选 / 编码基座)** → [`../protocol2_field_processing/field_filter.md`](../protocol2_field_processing/field_filter.md)
- **评估口径**(5 折 `cv_c_mean`、seed 0、不伪造独立测试集)仍以 `z_notes/Test_series_spec.md` §2 为准(待迁入协议层,见总纲待办)。
- **验收惯例**:同输入重跑 diff=0;抽查手算一致;产物目录 `results_display/**`、`rawdata_stats/**` 被 gitignore 留磁盘。

## 各阶段速查

### ⓪ 前置:label 重建(患者级)

- **做什么**:从 t_write 另册 + 原始 JSON 重建生存结局表;**规则0 先删坏行**(`ground_truth_time ≤ 0` 全局剔除,与 ⓪ 同规则);只写 label/clinical CSV,不生成 split
- **输入**:`rawdata_stats/{ds}/time_write/patient_time_stats.csv` + `ClinicDatasets/gdc_clinical/raw_json/{ds}.json`
- **输出**:`Clinic_Analyzer/data/datasets_csv/metadata/{study}.csv`(+ clinical)
- **脚本 / 落点**:`Clinic_Analyzer/dataset_deployment/scripts/rebuild_labels.py`
- **注意**:多模态 5 集的 W∩C∩G∩RNA 完备过滤不属于本步,落在 split 生成(`generate_5fold_splits.py`,runbook 阶段1 ⓪b);NaN 时间行不写 label;t_write 有行但原始 JSON 缺该患者的行同样不写 label(重建时三个剔除:NaN、gt≤0、缺 JSON)

---

### ⓪ 先删坏行(患者级)

- **依据**:规则0(gt≤0 全局剔除,2026-10-09 拍板)
- **做什么**:从生存结局表筛出有效患者名单(label 患者集);之后 ② 统计、④ 编码、onehot/baseline/hgcn 词表拟合只在这份名单上做
- **输入**:生存结局表 `Clinic_Analyzer/data/datasets_csv/metadata/{study}.csv`(重建见 ⓪ 前置;每患者一行:死亡/失访 + 天数;有效患者名单的唯一来源)
- **输出**:有效患者名单
- **脚本 / 落点**:`src/common/patient_set.py`
- **注意**:事件统计出两份数(原始 n_event 审计 + label 患者集分档);其余审计统计(time_stats/leak/presence/scan)看原始数据不过滤

---

### ① 字段扫描(字段级)

- **做什么**:扫病历原文,列出所有字段路径 + GDC 字典释义
- **输入**:raw JSON(35 个,`ClinicDatasets/gdc_clinical/raw_json/{ds}.json`)
- **输出**:`rawdata_stats/{ds}/scanned_fields.json`
- **脚本 / 落点**:`scripts/run_scan_fields.py`

---

### ② 字段统计(字段级)

- **做什么**:统计每个字段的 coverage / unique_count / mode_share / 三态缺失等
- **输入**:raw JSON + ① 的字段字典
- **输出**:`rawdata_stats/{ds}/field_stats.csv`;`--landmark_time 0` 时按 Field Bank 同款 mask 统计,写 `landmark_0/field_stats.csv`(现行链);默认 none = raw 口径
- **脚本 / 落点**:`scripts/run_field_stats.py`(stats 在 `src/discovery/stats.py`)

---

### ③ 字段筛选(字段级)

- **依据**:规则2 R0–R6 准入(R2 编号保留不复用)
- **做什么**:按统计结果砍掉坏字段(标签泄露 / 覆盖低 / 有效取值少 / 众数占比过高)
- **输入**:② 的统计 CSV
- **输出**:`rawdata_stats/{ds}/{tag}/kept_fields.json` + `fliter_log/{exclusion_log,field_registry}.csv`
- **脚本 / 落点**:`scripts/run_field_filter.py`(`src/discovery/filter.py`)
- **口径**:landmark 开启且对应 landmark 统计存在时默认消费 landmark-first 统计(显式 `--stats_csv` 可覆盖);权威口径见 [`../protocol2_field_processing/field_filter.md`](../protocol2_field_processing/field_filter.md)

---

### ④ Field Bank 编码(字段级)

- **依据**:规则1 要件①(mask 判据:有限 `t_hi ≤ T` 且槽位非 unlocated/non_informative,见 time_axis §3/§4)
- **做什么**:把留下的字段写成句子(prompt),CONCH 编码成向量;逐患者逐字段记 mask bool,被 mask 的值写 "not reported" 占位符(不删列不删人)
- **输入**:③ 的 kept_fields + 字段模板
- **输出**:`outputs/{ds}/field_bank/prompt/{tag}/` 的 prompts.csv → CONCH 编码 → `embeddings/pt/{patient}.pt` + `field_index.json`
- **脚本 / 落点**:`scripts/run_field_bank.py`(`src/discovery/field_bank.py`)
- **地位**:主线唯一的 CONCH 编码基座;下游(逐字段评估、贪婪搜索、论文方案臂)一律从这份 bank 按字段位号取列,不再触发重编码

---

### ⑤ 论文方案组合(字段级;2026-10-13 训练时索引)

- **做什么**:论文方案只提供**字段组合名单**(`templates/manual_schemes/{scheme}/fields.json`),
  不触发重编码——cindex conf 记录(bank 根 + 字段名单来源 + bank 指纹),analyzer **训练时现场解析**
  "方案字段 ∩ bank 字段 → 列位号 → 取列",不物化切片文件;解析结果写 run 的 `field_resolution.json`
- **输入**:field bank
- **输出**:无中间文件(臂方案名 = F×T 口径 `work_raw_{work}_{ds}` / `work_lm0_{work}_{ds}` / `greedy_lm0_{ds}`)
- **脚本 / 落点**:解析在 `Clinic_Analyzer/evaluate.py`(镜像实现 `src/manual_pipeline/arm_names.py`);
  阶段检查 `scripts/check_arm_fields.py`(主线外,只读);方案 × 数据集绑定见 spec §2.4

---

### ⑥ 按预测时点生成结局表(患者级)

- **依据**:规则1 要件②③(排除 gt≤T 的患者、时间减 T;T=0 臂与 gt≤0 等价,仅 365/730 臂多出)
- **做什么**:每个臂(如 landmark_365)生成自己的结局表;只读结局表,不碰字段数据;评估时与字段、split 按患者交集对起来
- **输入**:生存结局表 + 臂 T
- **输出**:该臂的结局 CSV(cindex 臂评估时自动生成;univariate 臂不自动——前置 `scripts/derive_landmark_labels.py` 预生成,见 runbook 阶段 2 步骤 2.5;none 臂无派生文件,直接用原始 label)
- **脚本 / 落点**:`src/manual_pipeline/landmark_labels.py` + `Clinic_Analyzer/datasets/dataset_survival.py`(读结局表时再删一次 gt≤0,全臂双保险——与 ⓪ 同规则、两个落点)

---

### ⑦ 评估(字段×患者×split 汇合)

- **依据**:评估口径 = 5 折 CV × seed 0,val c-index(`cv_c_mean`);不伪造独立测试集
- **做什么**:字段向量、结局表、5 折分组三份文件按患者交集对起来进训练
- **输入**:field bank + ⑥ 的臂结局表 + splits(`Clinic_Analyzer/data/splits/5foldcv/{study}/splits_*.csv`)
- **输出**:`field_cindex.csv` / `cindex.csv`
- **脚本 / 落点**:`run_univariate_cindex.py`(逐字段)/ `run_a_manual.py`(manual_pipeline cindex)/ `run_greedy_search.py`(贪婪)

---

### ⑧ 报表汇总(不新增训练)

- **输入**:`results/Test_*`
- **输出**:`results_display/Test_*/`
- **脚本 / 落点**:`results_display/scripts/*.py`;Main_/Appx_/Raw_/Meta_ 文件角色公约

## 注意事项

### 编码方式(prompt 与 onehot)

Field Bank 有两种编码变体(同一个 `scripts/run_field_bank.py`,不同 `--encoding`),共用 kept_fields / 模板 / mask 口径:

- **prompt(主线)**:把每个字段的值写成句子,CONCH 编码成向量。主线实验只用这一种(见 ④)。
- **onehot**:名义字段按**全局共享词表**编码——全部数据集患者合并后逐字段拟合,同一类别在所有数据集占同一个 index,稀有类别(min_count 以下)统一进 `__OTHER__`;连续字段 min/max/median 仍逐数据集拟合(与 baseline 线同口径)。产物 `outputs/{ds}/field_bank/onehot/{tag}/`,词表落盘 `rawdata_stats/_shared/{tag}/onehot_global_mapping.json`。

**为什么 onehot 用全局词表**(T37,2026-10-09 拍板):Test_5 不变性 E 轴要把三个编码(prompt / baseline / hgcn)互相对标,而 baseline 和 HGCN 的共享词表本来就是全局拟合的;onehot 若逐数据集拟合,同一类别在不同数据集里占不同位置(如 "female" 在 BRCA 第 3 位、在 LGG 第 7 位),跨数据集语义对不上、对标失效。全局词表让三条编码线的词表口径一致。

### 两条筛选链(landmark 与 R3/R4 的先后)

管线里有两道跟字段有关的过滤:
1. **R3/R4 筛选**(第③步):决定一个字段留不留。比如 R3:覆盖率(coverage)< 0.30 字段删掉。
2. **landmark mask**(第④步编码时,规则1 要件①):决定一个字段的某个值能不能用。预测时点 T=0,一个值的记录时间 t_hi 必须 ≤ 0 才可用,否则打上 "not reported"。

矛盾点在于:R3/R4 用的统计(覆盖率、取值数、众数占比)应该在 landmark 之前，还是之后的字段上去计算?（如果要是在原始值上计算，则大量通过 R3/R4 的字段在 landmark 之后几乎全是 "not reported"——统计说能用,实际不能用。

因此目前以规则2 权威 [`../protocol2_field_processing/field_filter.md`](../protocol2_field_processing/field_filter.md) 为准。先进行 landmark 之后进行 R3/R4。

## 相关脚本速查

- `scripts/run_field_stats.py --landmark_time 0` + `scripts/run_field_filter.py --landmark_time 0` — 现行链两步:重算 t0 mask 统计 → 自动消费 landmark 统计过 R0–R6(写现行 `landmark_0/` 目录;R3/R4 阈值可命令行改)
- `scripts/build_raw_field_bank.py` — Test_1a off 臂 raw bank(`outputs/_raw/.../no_mask/`)+ `raw_value_diff.json`
- `scripts/Test_1a_audit_arms.py` — Test_1a 两臂患者集一致性审计
