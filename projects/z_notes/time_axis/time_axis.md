# 时间轴协议（唯一权威）

时间口径的**唯一入口**。本文件回答三件事：一根怎样的时间轴（§2）、landmark 三要件如何定义与落地（§3）、支撑要件①的 `t_record` 判据（§4）。`t_write`（GDC 入库时间审计）按设计**不参与**泄露判定，已移出本协议，另册 [`t_write.md`](t_write.md)。代码常量必须与本文件一致。推导与审计明细见本目录附录：`t_record_derivation.md`、`index_date_anchor_audit.md`。旧规格与旧口径已作废并删除（§6）。

---

## 1. 协议解决什么问题

项目做 landmark 生存分析：在诊断后的时点 `T ∈ {0,365,730}`（天）预测患者生存。TCGA 数据集中**记录本身"何时才被写下"大多没有时间戳**，只能通过 TCGA 临床数据里每条记录带 `days_to_*` 事件天数，以及 `timepoint_category` 等字段的意思推断各个字段的真实记录时间。
若不管这一点，模型会用上 T 之后才已知的信息（如疗程结束才结账的 `treatment_outcome`），即**时间泄露**。

协议做两件事：

1. **唯一时间轴（§2）**：把每个患者的全部信息换算到 `t = 距 index date 的天数` 这一根轴上；生存终点 gt、协变量槽位、landmark 时点 `T` **同轴、同单位（天）**。
2. **`t_record` 区间（§4）**：给每条记录算出"这条信息临床上最早何时才可能被写下"的区间 `(t_lo, t_hi]`；landmark T 只放行 `t_hi ≤ T` 的值，这是三要件①的值级判据。

**"未来"的定义**：指临床上属于 `t > T` 的信息，**不是**"后来才写入数据库"。GDC 的 `updated_datetime` 晚不等于泄露——该口径（`t_write`）只用于入库审计，见 [`t_write.md`](t_write.md)。

轴上角色一览（下文各节的索引）：

| 角色 | 是什么 | 参与泄露判定吗 | 定义于 |
| --- | --- | --- | --- |
| 生存终点 gt | 预测目标：死亡用 `days_to_death`，否则末次随访 | 被预测对象 | §2.2 |
| landmark T | 外部传入的全局预测时点（天），`T ∈ {0,365,730}`，**不是**生存终点 | 判定的基准 | §3 |
| `t_record` | 一条记录临床上何时才可能被写下，区间 `(t_lo, t_hi]` | **是**（`t_hi <= T` 门控） | §4 |
| `t_write` | 该对象在 GDC 的入库/修订时间（`updated_datetime`） | **否**，按设计排除 | 另册 `t_write.md` |

时间轴协议的两块「推导依据」：

- `index_date_anchor_audit.md` — 回答「index_date —— 第 0 天是什么？」
- `t_record_derivation.md` — 回答「t_record —— 每条记录何时被写下？」

---

## 2. 唯一时间轴

TCGA GDC 临床数据只有**一根时间轴**：`t = 距 index date 的天数`。index date 是 case 级锚点（实践中即初始病理诊断日，见 §2.1）。

- 词典对每个 `days_to_*` 字段的定义都是同一锚点的差：`days_to_diagnosis` / `days_to_follow_up` / `days_to_treatment_start` / `days_to_treatment_end` / `days_to_death` / `days_to_last_follow_up` 均为 "index date → 事件日"；`days_to_birth` 为负。
- `t < 0` = 诊断前（既往史）；`t = 0` = 诊断时刻；`t > 0` = 诊断后（随访 / 治疗 / 死亡）。
- 轴上各点：`t_record` 槽位 = 每个实体按 §4 规则放上轴的区间 `(t_lo, t_hi]`；生存终点 gt 与 landmark 的 `T ∈ {0,365,730}` 都是这根轴上的点（T=0 即诊断时刻，T=365 即诊断后一年），单位同为**天**。

### 2.1 轴锚点（index_date）

结论来自 [`index_date_anchor_audit.md`](index_date_anchor_audit.md)（全库扫描）：33 份 TCGA JSON、11428 例中，有值的 `index_date` **全部是 Diagnosis**（11293 例，其余 6 个枚举 0 例）；135 例缺 `index_date` 键（127 例空壳、8 例有临床内容）。注意：

- **SKCM 反例**：`index_date=Diagnosis` 不等于原发诊断日——SKCM 338 例的 day-0 是研究收录的转移/进展诊断，原发皮肤病灶反而在轴上前移。第 0 天对多数 SKCM 患者是"GDC 选作 index 的那次诊断"，不是初诊。
- **数据集级统计已落地（2026-09-30）**：`src/time_stats.py::build_index_date_stats` 随每套统计输出 7 枚举分布、缺键分流（空壳 / 有临床内容）、Diagnosis 病例的 primary day-0 一致性，产物 `rawdata_stats/{dataset}/index_date_stats.csv`（每数据集一行）+ `index_date_flagged.csv`（有临床内容仍缺键、或取值非 Diagnosis 的病例，非空才写）+ `_shared/index_date_stats_all.csv`（全数据集拼接）。flag 语义：`mixed_index_date`（同数据集多个非缺失取值）、`non_diagnosis_index_date`、`index_date_missing_clinical`、`day0_not_primary`（primary 对象 day-0 非零比例 ≥ 0.2）。换癌种或换 GDC 导出前须先看这张表。

### 2.2 生存终点 gt（两套目录各放一份，规则不变）

- Dead：`demographic.days_to_death`
- 非死亡：先取 `diagnoses[].days_to_last_follow_up` 的最大值；没有再用 `follow_ups[].days_to_follow_up` 的最大值

gt 与协变量槽位**同轴、同单位（天）**，这是 landmark 三要件自洽的前提。

### 2.3 已知数据质量坑

- **gt=0 占位**：全库 45 行 `gt=0 & event=1` 的 `days_to_death=0` 是 TCGA 源占位值（原始 JSON 为字面整数 0，非 null）。风险集 `gt > T` 会把它们从 T>0 的臂中剔除，而 T=0 臂保留——这是数据坑，不是口径错误。
- **月/天换算**：Clinic_Analyzer 标签月数除数为 30.44（SurvPGC `pipeline.py:349-361`）；A_pipeline `landmark_labels.py` 用 `365.25/12 = 30.4375` 反推 gt 天数。T∈{0,365,730} 整数天口径下风险集排除数一致，无实际影响；只用 `DAYS_PER_MONTH` 判断 `gt_days <= T` 的边界。
- **天数为负**：`days_to_*` 可为负（如术前化验 `days_to_test = -3`），负值不作异常处理，说明 index 不是本例最早事件。

---

## 3. landmark：经典三要件与代码落点（协议主体）

landmark 的 T 是**同一根轴上的点**（天），外部传入的全局 landmark 起点，**不是生存终点**。经典 landmark（Anderson 1983；van Houwelingen dynamic prediction）三要件必须同时做到：

| 要件 | 含义 | 实现位置 |
| --- | --- | --- |
| ① 协变量只用 T 前信息 | timed 家族槽位只保留状态不是 `unlocated`/`non_informative` 且有限 `t_hi <= T` 的取值；无时间实体（case/demographic/exposures/family_histories）不 mask；缺 T 直接报错，该槽缺有限 `t_hi` 按缺失处理；被 mask 的值走现有 missing placeholder，不删列 | `src/discovery/landmark.py`（Field Bank 侧）与 `A_pipeline/src/landmark.py`（A_pipeline 侧，`mask_case()`） |
| ② 风险集 = 只保留 `gt > T` 的患者 | 以**派生 label 文件**实现：被排除患者不在 label 文件中，`SurvivalDatasetFactory` 的 label ∩ split 交集自然把该患者从每折移除；split 文件不改动 | `A_pipeline/src/landmark_labels.py:110-111`（`excluded_mask = gt_days <= T`） |
| ③ 时间原点平移到 T（`gt − T`） | label 时间列减去 `shift_months = T/30.4375`；c-index 对平移不变，但仍实现并做一次不变性自检 | `A_pipeline/src/landmark_labels.py:114-116`（自检开关 `--landmark_shift off` 生成 `__noshift` 变体） |

要件①的值级判据是 `t_record`（§4）：T 时刻一条记录可用，当且仅当有限 `t_hi <= T` 且状态不是 `unlocated` / `non_informative`。

### 3.1 Test_ 系列实验口径（详见 `z_notes/Test_series_spec.md` §2.1/§2.5）

- **Test_1b 两臂**：臂 A = 取值 mask off（`landmark_time none`，报告值对照）；臂 B = `landmark_0` 三要件全开（去泄露值）。两臂字段集、模板、编码、模型、划分完全一致，唯一差异 = mask。产物：`results/A_manual_landmark/`。
- **leak_rate（新口径，2026-09-30 纠错）**：`#{患者: 实际进入模型的值来自 t_hi > 0 的槽位} / #{管线产出有效值的患者}`，直接跑论文管线（A_pipeline，不做泄露处理）并追溯每个值的来源槽位。旧口径 `1 − n_valid_t0/n_valid_none` 已作废。
- **有效事件数**（如需 landmark 门槛重套，当前协议 A 不执行）：`#{event==1 且 gt > T}`。
- 默认 landmark = `landmark_0`；365/730 作敏感性。原 `landmark_none`（关 mask + R0 整层删 diagnoses/follow_ups）更名 **static_only**，移出主图仅进补充材料——注意与"取值 mask 状态 off"不是一回事。
- Field Bank 变体：`landmark_0/365/730` + `static_only`；Test_2 搜索池 = `landmark_0`。

### 3.2  对象级"不建槽"
────────────────────────────────────────
规则: treatment_or_therapy=no → 不编号
代码: _is_negative_therapy :281，:728 跳过
理由: 否定勾选不是事件（上轮已查证）
────────────────────────────────────────
规则: follow_ups[] 壳对象 → 不编号（排除出 follow_ups 分母和槽位）
代码: _is_follow_up_shell :285，:477/:737
理由: 壳只有 follow_up_id + 挂着的 molecular/OCA，无
days_to_follow_up/submitter_id/临床内容——是容器不是随访事件。nested 数组仍照常统计
────────────────────────────────────────
规则: follow_ups 空行 → non_informative
代码: _interval_follow_up :632-634
理由: 无天数且无任何内容字段，不携带信息

---

## 4. t_record：要件①的值级判据

### 4.1 定义与方向约束

`t_record` 是区间 `(t_lo, t_hi]`，不是点。
- `t_lo`：该记录**时间的起点**，该记录内容**最早可能被写下**的时刻，由记录内**最晚才可得的字段**决定。
- `t_hi`：该记录**时间的终点**，该记录最晚被写下的时刻，**必然存在**的最早可证时刻，只能来自外部证据（§4.3），不能由对象自身的事件天数推出。

- **方向约束**：事件天数给下界，不给上界。`days_to_treatment_start = 56` 只能推出记录不早于第 56 天，不能推出第 56 天记录已存在。把事件天数直接当 `t_hi`，等于默认 CRF 前瞻实时录入——这是假设 A1，默认关闭（`t_record_derivation.md` §8.2）。

- **状态枚举**：在`方向约束`的基础上表示 `t_record` 区间本身的"定位质量"：我们对"这条记录何时被写下"这条信息，在时间轴上能钉得多准。

| 状态 | 形态 | landmark 可用性 |
| --- | --- | --- |
| `point` | `t_lo = t_hi` 均有限，区间坍缩成点（访视日、基线问诊等直接钉死） | ✅ `T >= t_hi` 放行 |
| `bounded` | 两端均有限（`t_lo < t_hi`） | ✅ `T >= t_hi` 放行 |
| `lo_only` | 仅 `t_lo` 有限，`t_hi = +∞`（上界失守，无法证明"T 时已存在"） | ❌ 任何有限 T 都不放行 |
| `unlocated` | `t_lo` 不可得，无法定位（无天数、字段矛盾等） | ❌ 排除 |
| `non_informative` | 对象不携带时间信息（空行、恒真否定），不建槽 | ❌ 排除 |

CSV 单元格写有限 `t_hi`（无有限值则留空）；归一化仍是 `t_hi / last_time_days`（不再减日历 t0）。覆盖率按状态拆分。

### 4.2 判据表

**对象**：`t_record` 面向的对象是 JSON 中每个可独立计数的对象——`demographic`、`diagnoses[]`/`follow_ups[]` 的数组元素，及其下嵌套的 `treatments[]`/`pathology_details[]`/`molecular_tests[]`/`other_clinical_attributes[]` 元素。
**记录**：对象与记录不是一一对应：对象先过 §3.2 建槽前置（negative / 壳 / 空行不编号），再过合并规则（M1/M2/M3，`t_record_derivation.md` §0.5），合并后每个「记录」得一条 `(t_lo, t_hi]` 与一个产物列。

| 实体 | 主判据 | 备选判据 | 兜底 | 产物列名 |
| --- | --- | --- | --- | --- |
| `demographic`、`exposures[]`、`family_histories[]` | 无时间实体，语义上认为是诊断初始信息：不建 `t_record` 槽、不定位、不 mask（值恒可用） | — | — | — |
| `diagnoses[]` | 既往史定点 `(0,0]`；其余 `days_to_diagnosis` 作 `t_lo`，`t_hi` 走 TH1b/TH2 | — | 无天数则 `unlocated` | `diagnoses_record{i}` |
| `diagnoses[].treatments[]` | 结束日/结局作 `t_lo`，否则起始日；`t_hi` 走 TH1b/TH2 | 既往史定点 `(0,0]`；`Prior to Diagnosis` 且父 `prior_treatment=yes` 定点 | `treatment_or_therapy=no` 不编号；无天数、错标 Prior to Diagnosis 记 `unlocated` | `diagnoses_treatments_record{i}` |
| `diagnoses[].pathology_details[]` | P1/P2 用诊断日作 `t_lo`，`t_hi` 走 TH1/TH1b/TH2 | — | P3 或无诊断日记 `unlocated`；不读 `days_to_pathology_detail` | `diagnoses_pathology_details_record{i}` |
| `follow_ups[]` | `days_to_follow_up` 作点 | — | 壳对象不编号；有内容无天数 `unlocated`；空行 `non_informative` | `follow_ups_record{i}` |
| `follow_ups[].molecular_tests[]` | 有 `days_to_test` 时作 `t_lo`，`t_hi` 走 TH1b/TH2 | P1 型 Initial Diagnosis / Preoperative 可给 `t_hi<=0` | Sample Procurement 与 P2 Preoperative 需 biospecimen，记 `unlocated` | `follow_ups_molecular_tests_record{i}` |
| `follow_ups[].other_clinical_attributes[]` | Initial / Prior to Diagnosis 定点 `(0,0]` | 正的 comorbidity/risk 天数作 `t_lo` | 天数不是记录时间；Not Reported 与生命阶段记 `unlocated` | `follow_ups_other_clinical_attributes_record{i}` |

注：
关于 {i} 编号：在TCGA json源文件中，一个患者一个实体往往有多个记录， {i} 编号为按 JSON DFS 遇到顺序、1-based、不按时间排序。

### 4.3 t_hi 的三个来源

三者不是各自独立生成一个 `t_hi`，而是同一条 fallback 链：每个槽位按 **TH1 → TH1b → TH2** 依次尝试，第一个非空来源即为该槽唯一的 `t_hi`（代码 `src/time_stats.py::_t_hi_for_record` → `_t_hi_from_sources`），不会三个值并存。推导与实例见 [`t_record_derivation.md`](t_record_derivation.md) §0.3/§0.4：

- **TH1 下游依赖**：存在天数已定位、且以本记录为前提的事件 E，则 `t_hi = t(E)`（唯一实例化形式：术后病理 `t_hi = min(辅助治疗的 days_to_treatment_start)`）。
- **TH1b 随访阶梯**：`t_hi = min{ days_to_follow_up : >= t_lo }`（随访表按设计采集区间事件）。
- **TH2 病例级末锚点**：`t_hi = max(days_to_last_follow_up, days_to_last_known_disease_status, days_to_recurrence, 全部已定位事件天数)`；四项都是病例级字段，每患者只算一次（`_case_context`），该患者所有落到 TH2 的槽位共享同一个值；全空则 `t_hi = +∞`，状态 `lo_only`。

---

## 5. 实现与入口

- 实现：`src/time_stats.py`；脚本：`python projects/scripts/run_time_stats.py --dataset all`（一次跑出 `time_write/` 与 `time_record/` 两套目录；`time_write/` 的口径与布局见 [`t_write.md`](t_write.md)）。
- 两套统计共用 6 个实体，不统计 `case`、`demographic`、`exposures[]`、`family_histories[]`。
- 槽位编号按 JSON DFS 遇到顺序，1-based，不按时间排序。
- `follow_ups[]` 只给真实随访事件编号：有 `days_to_follow_up`、`submitter_id`，或任意非 nested 临床内容。只有 `follow_up_id`、实质内容只是挂着的 `molecular_tests[]` / `other_clinical_attributes[]` 的壳对象排除出 `follow_ups` 分母和槽位；nested 数组仍按原规则统计。
- `diagnoses[].treatments[]` 中 `treatment_or_therapy=no` 的对象同样排除出 treatments 分母、槽位和 landmark。

目录布局（每个数据集）：

```text
rawdata_stats/{dataset}/time_record/
  patient_time_stats.csv / .png
  normalized_update_time.csv / .png / _boxplot.png
  sequences/{family}.csv / .png        # 6 个 family
  missing/{family}.csv / .png
rawdata_stats/{dataset}/index_date_stats.csv      # 轴锚点分布（§2.1）
rawdata_stats/{dataset}/index_date_flagged.csv    # 需关注的病例（非空才写）
```

`time_write/` 目录结构同 `time_record/`（列名用 `*_updated{i}`），归一化口径与布局见 [`t_write.md`](t_write.md)。生存终点两套目录各放一份（§2.2）。`_shared/patient_time_stats_all.png` 仍只出一份，另加 `_shared/index_date_stats_all.csv`（全数据集锚点分布拼接）。

验收：

```bash
python projects/scripts/run_time_stats.py --self_test
python -m pytest tests/test_time_stats.py -q
```

---

## 6. 已作废口径（勿再引用）

| 旧口径 | 现行口径 | 出处 |
| --- | --- | --- |
| treatments/pathology 按 `timepoint_category` 置信度（high/medium/low）继承父诊断日；molecular/oca 继承父 follow-up 日 | 见 §4 t_record 表（无置信度继承；`timepoint_category` 只作局部补充，见 `t_record_derivation.md` §8.1） | 旧 `time_write_record_spec.md`（已删） |
| 负向勾选 `treatment_or_therapy=no` 挂父诊断日 | `treatment_or_therapy=no` 一律不建槽、不进 landmark | 旧 `t_record_localization_current_problems.md`（已删） |
| `leak_rate = 1 − n_valid_t0/n_valid_none`（t0 完全缺失比例） | 见 §3.1 新口径 | `z_notes/Test_series_spec.md` §2.1（R9 纠错） |
| 拆表方案 `time_sequence_tables_plan.md`（旧 `rawdata_stats/{dataset}/time/` 布局） | 已由 `time_write/` + `time_record/` 布局取代 | 执行完成，已删 |

---

## 7. 附录（本目录）

- [`t_record_derivation.md`](t_record_derivation.md) — t_record 区间判据的逐条推导与实例（P1/P2 病理锚点、N1/N2 否定勾选、既往史定点、molecular/OCA 规则）。§4 判据表是该文档的落地版。**未落地部分**：§8.1 `timepoint_category` 对照表（须先做 §8.1 的方向检验）、biospecimen 实体连接、合并开关 M1/M2/M3 与假设开关 A1（默认关；Δ 参数恒 0），A2 随访阶梯已开启。
- [`index_date_anchor_audit.md`](index_date_anchor_audit.md) — index_date 轴锚点全库审计（含 SKCM 反例）。枚举分布、缺键打标、day-0 一致性三项已落地为 `index_date_stats.csv`（2026-09-30）；原发诊断平移与换数据前的重跑提示仍未落地。
- [`t_write.md`](t_write.md) — GDC 入库时间（`updated_datetime`）审计，**另册**；不参与 landmark / 泄露判定。
- [`错误.md`](错误.md) — 旧口径的批判与设计动因（三条硬伤 → 区间判据的动机），历史文档，非现行判据。
- 相关口径：`z_notes/Test_series_spec.md`（Test_ 系列实验规格，§2.1 泄露定义、§2.5 landmark 三要件）；`z_notes/Test_series_execution_log.md`（历史决策与执行记录）。
