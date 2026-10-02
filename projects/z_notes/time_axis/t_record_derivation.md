# t_record 区间确认规则（landmark 用）

> **地位**：本文是本目录 [`time_axis.md`](time_axis.md) §4 t_record 判据表的**推导与实例依据**；权威口径以 time_axis.md 为准。旧规格 `time_write_record_spec.md` 与 `t_record_localization_current_problems.md` 已删除（其 timepoint 置信度继承、负向勾选挂父诊断日均已作废）。
> **组织方式**：本文按 time_axis.md §4.2 判据表的行序组织——§1–§7 与判据表 7 行逐行对应，通用机制集中在 §0，跨实体机制在 §8，全表套用校验在 §9。每节开头标注该实体的落地状态。
> **落地状态总览**：已落地——§2 既往史定点、§3 t_lo 链、§4 P1/P2、§5 F-merge、§6/§7 molecular/OCA 规则、0.4 TH1/TH1b/TH2（`src/time_stats.py`，Δ 参数恒 0）；A2 已开启。未落地——§3 N1/N2 分类（现行 `treatment_or_therapy=no` 一律不建槽）、M1/M2/M3 合并、§8.1 `timepoint_category` 对照表（落地前须先做 §8.1 的方向检验）、biospecimen 实体连接（§8.1/§6 的 P2 型 Sample Procurement）、A1（默认关）。

依据实例归纳。`diagnoses[]` 一支：`TCGA-AD-6895`（COAD）、`TCGA-EA-A5O9`（CESC）、`TCGA-DS-A1OC`（CESC）。`follow_ups[]` 一支：`TCGA-AB-2810`（LAML）、`TCGA-2G-AAFY`（TGCT）、`TCGA-YU-A94M`（TGCT）。覆盖 `diagnoses[].treatments[]`、`diagnoses[].pathology_details[]`、`follow_ups[]`、`follow_ups[].molecular_tests[]`、`follow_ups[].other_clinical_attributes[]`。所有天数相对 `index_date`。

## 0. 通用机制（跨实体公理，只讲一次）

### 0.1 定义与门控

`t_record` 是区间 `(t_lo, t_hi]`，不是点。t 本身即**记录时间**——这条信息被写下的时刻；区间刻画的是这个时刻的不确定范围，**不是**记录所描述事件的时间跨度（如治疗记录的事件跨度是 [起始日, 结束日]，但其 `t_lo` 取结束日：疗程结束前无法结账）。

- `t_lo`：该记录时间的**起点**（下界）——该记录内容最早可能被写下的时刻。由记录内**最晚才可得的字段**决定。
- `t_hi`：该记录时间的**终点**（上界）——该记录最晚可能已被写下的时刻。只能来自外部证据，不能由对象自身的事件天数推出。
- landmark 门：记录在 L 时刻可用，当且仅当有限 `t_hi <= L` 且状态不是 `unlocated` / `non_informative`。

`created_datetime` / `updated_datetime` 是 GDC 入库时间（`t_write`），任何情况下不参与 `t_record`。

### 0.2 方向约束（核心）

事件天数给下界，不给上界。`days_to_treatment_start = 56` 只能推出记录不早于第 56 天，不能推出第 56 天记录已存在。把事件天数直接当 `t_hi`，等于默认 CRF 前瞻实时录入——这是假设 A1，默认关闭。

### 0.3 `t_lo` 通用原则：按最晚可得字段定

按以下顺序取第一条命中的：

| 条件 | `t_lo` |
| --- | --- |
| 含 `treatment_outcome` | `days_to_treatment_end + Δ_resp` |
| 含 `days_to_treatment_end`、累计 `treatment_dose`、`number_of_cycles`、`number_of_fractions` 中任一 | `days_to_treatment_end` |
| 仅含 `days_to_treatment_start` | `days_to_treatment_start` |
| `pathology_details` | 标本获取日（§4 判定） |
| 否定勾选 | 见 §3（N1/N2 分类） |
| 既往史类 | 见 §2（定点） |
| 以上皆无 | `unlocated` |

`Δ_resp` 为疗效评价延迟，默认 0（即以结束日为硬下界），作为敏感性参数。

### 0.4 `t_hi`：三个来源的 fallback 链

三者不是各自独立生成一个 `t_hi`，而是同一条 fallback 链：每个槽位按 **TH1 → TH1b → TH2** 依次尝试，第一个非空来源即为该槽唯一的 `t_hi`（代码 `src/time_stats.py::_t_hi_for_record` → `_t_hi_from_sources`），不会三个值并存。

**TH1 下游依赖事件**。存在一个天数已定位的事件 E，其发生必须以本记录为前提，则 `t_hi = t(E)`。唯一实例化形式：术后辅助治疗的适应证判断依赖术后病理报告，病理记录的 `t_hi = min(辅助治疗的 days_to_treatment_start)`（成立条件与实例见 §4.3）；新增 TH1 形式须逐条论证并登记，不得由类比扩展。

**TH1b 随访阶梯（TH1 假设 A2 成立情况下）**。真正随访记录自带 `days_to_follow_up`，在本病例上构成一串已定位时点。对任一 `t_lo` 已知的记录，取 `t_hi = min{days_to_follow_up : days_to_follow_up >= t_lo}`。依据是随访表按设计采集区间事件。无满足条件的随访日时退 TH2。

这条比 TH2 紧得多：`YU-A94M` 的术后血清标志物 `t_lo = 0`，TH2 给 564，TH1b 给 333。对治疗对象同样适用——若某方案结束于 332 天而本例有 360 天随访，`t_hi = 360` 而非全案末锚点。

**TH2 病例级末锚点（兜底）**。`t_hi = max(days_to_last_follow_up, days_to_last_known_disease_status, days_to_recurrence, 全部已定位事件天数)`。
实例：`AD-6895` → 763；`EA-A5O9` → 788。

**TH3 上界失守**。上述皆不可得时 `t_hi = +∞`，状态记 `lo_only`。
实例：`DS-A1OC` 的 `days_to_last_follow_up`、`days_to_recurrence`、`days_to_last_known_disease_status` 全空，最后的临床锚点是化疗结束日 332，之后无任何证据。该病例全部无日期对象上界失守。

### 0.5 合并先于定位

对象个数不等于 record 次数。合并在定位之前完成；合并后 `t_lo = max(各行 t_lo)`，`t_hi = min(各行可得 t_hi)`。各实体专属合并：

- **M1 同方案拆行、M3 重抄对**：treatments 对象按方案拆行或新旧抄录合并为一次 record（§3.4）
- **M2 属性补行**：pathology_details 的纯属性行并入主报告（§4.4）
- **F-merge**：末次访视的双抄行合并为一次 record（§5.3）

### 0.6 输出结构与病例分层

每条 record 输出 `(t_lo, t_hi, source_lo, source_hi, status)`。

`status ∈ {point, bounded, lo_only, unlocated, non_informative}`（定义与 landmark 可用性见 time_axis.md §4.1 状态表）。

病例分层：`days_to_last_follow_up` 与其余末锚点全空的病例（如 `DS-A1OC`）进入「无全局上界」层，其 `lo_only` 记录在主分析中不可用，不与有末锚点的病例共用同一分母。

---

## 1. `demographic`、`exposures[]`、`family_histories[]` — 无时间实体

**落地状态**：不建槽、不 mask（无专门代码分支）。

**字段统计**：词典里 `timepoint_category` 仅存在于 5 个实体（follow_up、molecular_test、other_clinical_attribute、treatment、pathology_detail），`diagnoses` 与这三支都没有。`demographic` 的天数字段只有 `days_to_birth`（年龄，为负）与 `days_to_death`（生存终点，属 gt 而非记录时间）；`exposures[]`、`family_histories[]` 无任何 `days_to_*`。三者的 `created_datetime` / `updated_datetime` 覆盖 100%，但那是 `t_write`。

**判据**：无时间实体，语义上认为是诊断初始信息——不建 `t_record` 槽、不定位、不 mask（值恒可用）。

---

## 2. `diagnoses[]`

**落地状态**：既往史定点已落地；`days_to_diagnosis` 作 `t_lo`、`t_hi` 走 TH1b/TH2 已落地。

### 2.1 字段统计

- `timepoint_category`：diagnoses 对象本身 0/18,839——该字段只出现在诊断下面的嵌套对象里（treatments 4,497、pathology_details 249，合计 4,746 次）。
- 既往史证据来自 `classification_of_tumor` 与 `diagnosis_is_primary_disease`，不是天数（既往诊断的 `age_at_diagnosis` 常为 null、无 `days_to_diagnosis`）。

### 2.2 `t_lo` 判据

- **既往史定点**：父诊断满足 `diagnosis_is_primary_disease = false` 或 `classification_of_tumor = "Prior primary"` 时，其下全部对象（含 treatments、pathology_details）一律 `t_record = (0, 0]`（论证见 2.4）。
- **其余**：`t_lo = days_to_diagnosis`。
- **无天数**：`unlocated`。

### 2.3 `t_hi` 判据

TH1b / TH2；既往史定点 `t_hi = 0`。

### 2.4 特殊情形：既往史定点 `(0, 0]`

- 事件时间不可定位（`age_at_diagnosis` 为 null、无 `days_to_diagnosis`），不试图恢复。
- 记录时间定点：`t_record = (0, 0]`，即基线病史采集。
- 成立条件：主诊断上存在 `prior_malignancy = "yes"`（有 `prior_treatment` 更佳）作同源佐证。

论证（Q1）：`diagnosis_is_primary_disease = false` 意味着这条诊断不是本次入组的主病，而是患者过去得过的另一种癌。这些既往癌的信息不是当年治疗时实时录入的，而是本次入组基线问诊时患者口述、再填入 CRF。所以定位的对象不是"那个癌什么时候发生"（该时间点往往不可知），而是"这条记录什么时候被写下"——答案就是基线问诊那一刻，即第 0 天。

这是全部类别中唯一可收敛为点的情形，其成立不依赖假设 A1，因为定位对象是问诊行为而非临床事件。

### 2.5 实例

`AD-6895` 既往皮肤癌下 2 条（Pharmaceutical / Radiation `no`，头皮基底样鳞癌）→ `(0, 0]` point；`DS-A1OC` 既往乳腺癌下 2 条（Pharmaceutical / Radiation `no`，右乳癌）→ `(0, 0]` point。

---

## 3. `diagnoses[].treatments[]`

**落地状态**：`t_lo` 链已落地（Δ_resp 恒 0）；TH1b/TH2 已落地。未落地：N1/N2 分类（现行 `treatment_or_therapy=no` 一律不建槽）、M1/M3 合并、`timepoint_category` 对照表（须先做 §8.1 的方向检验）。

### 3.1 字段统计

全库 54,945 条（本文全库统计均限 33 份 TCGA JSON，不含 CPTAC-3 / MMRF-COMMPASS）。能表征记录/事件时间的主要字段：

| 字段 | 非空条数 | 覆盖率 |
| --- | --- | --- |
| `days_to_treatment_start` | 17,831 | 32.45% |
| `days_to_treatment_end` | 14,457 | 26.31% |
| 起止都有 | 14,059 | 25.59% |
| 只有 start | 3,772 | 6.86% |
| 只有 end | 398 | 0.72% |
| start / end 都没有 | 36,718 | 66.82% |

- `timepoint_category` 另有 4,497 条（8.2%），且在这批 TCGA 里与 start/end **互斥**：有天数的对象都没有类别，有类别的都没有天数。常见值：Prior to Procurement、Prior to Diagnosis、Preoperative。
- `treatment_duration`（49 条）与 `treatment_outcome_duration`（4 条）基本可忽略。
- `treatment_or_therapy`：`yes` 27,262 条 / `no` 25,122 条 / 缺失 2,561 条。
- 患者层：11,428 例中 10,557 例（92.38%）至少一条 treatment；其中有治疗的患者里，至少一条有 start 或 end 的 5,819（55.12%），一条都没有的 4,738（44.88%），同一患者混合有无的 5,459（51.71%）。

### 3.2 `t_lo` 判据

按 0.3 总表依次命中：
含 `treatment_outcome` → `days_to_treatment_end + Δ_resp`；
含结束日 / 累计剂量 / 周期数 / 分次数 → `days_to_treatment_end`；
仅起始日 → 起始日。理由：这些字段都不可能在疗程结束前结账。

实例：`EA-A5O9` 的 EBRT `t_lo = 81`（另含 outcome）；`DS-A1OC` 的 EBRT `t_lo = 155`、化疗 `t_lo = 332`，均非起始日。

### 3.3 `t_hi` 判据

TH1b / TH2。实例：`EA-A5O9` EBRT `[81, 788]`（TH2）；`DS-A1OC` EBRT `[155, +∞)`、化疗 `[332, +∞)`（TH3）。

### 3.4 特殊情形

**M1 同方案拆行**。同一 `diagnoses[]` 下的多个 treatment 对象，若 `days_to_treatment_start`、`days_to_treatment_end`、`number_of_cycles` 全部相同，仅 `therapeutic_agents` 与剂量不同，合并为一次 record。实例：`DS-A1OC` 的 Cisplatin 与 Gemcitabine 两行，同为 252→332、4 周期，是一个含铂方案按药物拆行。

**M3 重抄对**。同一诊断下治疗类型、`treatment_intent_type`、`treatment_outcome` 一致，一条带天数、一条仅有 `timepoint_category`，视为同一次治疗的新旧两次抄录，合并，天数取带天数的那条。实例：`EA-A5O9` 的 EBRT 行（56→81，CR）与 Radiation Therapy, NOS 行（Postoperative，CR）。M3 属可选合并，需在口径中声明；不合并时后者按 `unlocated` 处理。

**否定勾选 N1/N2**（`treatment_or_therapy = "no"` 且无任何天数）。不统一挂父诊断日。按该治疗方式对本病种的适用性分两类，判定需要外部维护的「病种 × 治疗方式」适用性表，不能从 JSON 推出。

- **N1 恒真否定**：该治疗方式对本病种本就不属可选项，字段值不携带时间信息。标 `non_informative`，不进入 landmark 特征集，也不赋 0。实例：`AD-6895` 结肠癌的 `Radiation Therapy, NOS = no`。
- **N2 有临床含义的否定**：该治疗方式属本病种本分期的标准选项，"未行"是实质结论，只有在相应治疗窗口关闭后才成立。`t_lo` = 窗口关闭时点，通常无法从本例推得，则 `t_lo` 记 `unlocated`；`t_hi` 取 TH2/TH3。实例：`AD-6895` ⅢB 期结肠癌的 `Pharmaceutical Therapy, NOS = no`；`EA-A5O9` 的两条 Pharmaceutical Therapy, NOS `no`。

N1 与 N2 形态完全相同，仅凭 JSON 不可分。此处是本规则集对外部知识的唯一硬依赖。

论证（Q2）：为什么不可选的治疗方式还要记录——这是 TCGA CRF 表单的设计方式：表单上预置了固定的几个治疗类别（手术、化疗、放疗），每个格子都必须填 yes 或 no，不管该方式对这个病种有没有临床意义。所以结肠癌患者的表单上也有"放疗"这一行，填了 no——这不是医生评估后决定不做放疗，而是表单强制填写产生的结构性噪声。

**`Prior to Diagnosis` 的机械核对**（§8.1 方向检验的一部分）。父诊断的 `prior_treatment` 字段与该类别构成可直接判定的一致性检验，不需要领域知识：

- 父诊断 `prior_treatment = "yes"`：属真实既往治疗史，采集自基线问诊，`t_record = (0, 0]`，机制同 2.4，与事件日是否可知无关。
- 父诊断 `prior_treatment = "No"`：**矛盾，类别标注不可用**，该对象记 `unlocated`，且应视为本次病程内的治疗而非既往治疗。
- `prior_treatment` 为空：不判定，记 `unlocated`。

`EA-A5O9` 与 `DS-A1OC` 均落在第二支：两例的 Hysterectomy NOS 标 `Prior to Diagnosis`，而父诊断 `prior_treatment = "No"`，同时 `margin_status = "Uninvolved"`、pT/pN 病理分期、10 枚与 19 枚清扫淋巴结、术后辅助放疗，均指向手术发生在 index 诊断之后。两例独立出现同一形态的错标，且同属 2025-01 重抄批次。

需要先跑一次 `timepoint_category × treatment_type` 交叉表：若 1,267 条 `Prior to Diagnosis` 中手术类占比很高，说明该批标注存在系统性偏差，第一支也需附加核对；若手术类只是少数，则按上述三分支处理即可。

### 3.5 实例

- `EA-A5O9` EBRT 56→81 CR → `[81, 788]` bounded（3.2 + TH2）
- `EA-A5O9` Hysterectomy `Prior to Diagnosis` → `unlocated`（3.4 机械核对）
- `EA-A5O9` 术后药物 `no` ×2 → `(?, 788]` lo_only（N2 + TH2）
- `DS-A1OC` EBRT 117→155 → `[155, +∞)` lo_only（3.2 + TH3）
- `DS-A1OC` 化疗（2 行合并）→ `[332, +∞)` lo_only（M1 + TH3）
- `AD-6895` 药物 Adjuvant `no` → `(?, 763]` lo_only（N2 + TH2）；放疗 Adjuvant `no` → `non_informative`（N1）

---

## 4. `diagnoses[].pathology_details[]`

**落地状态**：P1/P2 已落地；M2 合并未落地。

### 4.1 字段统计

- 全库 14,366 条。设计上的记录日 `days_to_pathology_detail`（词典：index 日到这次病理阅片日）实际 **0 条有值**，对象上也没有任何其它 `days_to_*`。因此标本获取日由 index 诊断的作出方式决定，与病理对象自身无关（`days_to_pathology_detail` 不作判据）。
- `timepoint_category` 只有 249 条（1.73%），而且全在 TGCT：Postoperative 218、Post Adjuvant Therapy 21、Prior to Adjuvant Therapy 10。
- 父诊断 `days_to_diagnosis` 有 13,867 条（96.53%），是最近的天数；缺的 499 条里 367 条在 SKCM。但这是父诊断的钟，当前规则不允许 nested 自动继承。

- 多对象分布：11,558 个有病理的诊断里，恰 1 条 9,824（85.00%）、2 条 795（6.88%）、3 条 861（7.45%）、4–6 条 78（0.67%）。多条几乎全挤在 HNSC、UCEC、SARC、TGCT、CESC、UCS、UVM、DLBC；ACC/BRCA/KIRC 只要该诊断有 pathology 就都是 1 条。
- 多条形态：多数是同一份病理被拆字段（一条记淋巴结计数，其余各记一个 `lymph_node_involved_site`；SARC 的放射学/病理学尺寸、切缘被拆开）。
**反例在 TGCT**：同一诊断下 `timepoint_category` 是混的（`2G-AAFY` 一条原发灶脉管侵犯无类别、另一条腹膜后淋巴结标 Postoperative；`2G-AAGC` 第二条是 Prior to Adjuvant Therapy 的淋巴结清扫）——这类不能当成同一个记录时间。典型空钟对象：ACC `TCGA-OR-A5KB` 的 pathology 只有淋巴结数字和 `consistent_pathology_review`。

### 4.2 `t_lo` 判据：P1/P2 用诊断日

- **P1 切除标本即确诊标本**：无活检记载，同时具备 `residual_disease` 或 `ajcc_pathologic_*`，且 `site_of_resection_or_biopsy` 为实体器官。此时标本日等于诊断日，`t_lo = days_to_diagnosis`，`t_hi = days_to_diagnosis + Δ_path`（`Δ_path` 为报告出具周期，默认 0，作敏感性参数）；若 TH1 可得且更紧，取 TH1。
  实例：`AD-6895`，`residual_disease = R0`、pT3N1a、取材部位 Cecum，`t_record = (0, 0]`。
- **P2 活检确诊、另有切除**：`method_of_diagnosis = "Biopsy"`，且存在切除类治疗或病理分期/清扫淋巴结等切除标本所见。`t_lo = days_to_diagnosis`（保守取诊断日，实际严格大于），`t_hi` 取 TH1。
  实例：`EA-A5O9` → `(0, 56]`；`DS-A1OC` → `(0, 117]`。
- **P3 二者皆不成立**：`unlocated`。

### 4.3 `t_hi` 判据：TH1 的唯一实例化形式

术后辅助治疗的适应证判断依赖术后病理报告。成立条件：
(a) 本例确有切除标本证据（P1/P2 判定）；
(b) 存在 `treatment_intent_type = "Adjuvant"` 或 `timepoint_category = "Postoperative"` 且带 `days_to_treatment_start` 的治疗。
则 `t_hi(pathology_details) = min(该类治疗的 days_to_treatment_start)`。
实例：`EA-A5O9` → 56；`DS-A1OC` → 117。

新增 TH1 形式须逐条论证并登记，不得由类比扩展。

### 4.4 特殊情形：M2 属性补行

同一诊断下的多个 `pathology_details`，若其中一个仅含属性字段而无独立内容主体与时间字段，并入主报告。实例：`DS-A1OC` 的 `pathology_detail2` 仅有 `lymph_node_involved_site`。

但 TGCT 反例给出边界（见 4.1）：同一诊断下多条 pathology **带不同 `timepoint_category`** 时不是拆字段，是不同临床动作，不得合并。

### 4.5 实例

- `AD-6895` 主诊断 pathology_details → `(0, 0]` point（P1）
- `EA-A5O9` pathology_details → `(0, 56]` bounded（P2 + TH1）
- `DS-A1OC` pathology_details（2 行合并）→ `(0, 117]` bounded（M2 + P2 + TH1）

---

## 5. `follow_ups[]`

**落地状态**：F-merge 已落地；TH1b 随访阶梯（A2）已开启。

### 5.1 字段统计：三个平行集合，不是真嵌套

GDC 模型上 `molecular_test` / `other_clinical_attribute` 必须挂在 follow_up 下面，所以 JSON 看起来像父子。但这 72,435 条 follow_ups 里，一条 follow_up 永远只装一类有效数据，三个集合互斥、无例外：

| 这条 follow_up 实际是什么 | 条数 | 父级 | 子级 |
| --- | --- | --- | --- |
| 真正随访 | 43,360 | 有 `days_to_follow_up`、`timepoint_category`、`disease_response` 等 | 无 |
| 分子检测的空壳包装 | 20,754 | 只有 `follow_up_id` | 恰好 1 条 molecular_tests |
| 其他临床属性的空壳包装 | 8,321 | 只有 `follow_up_id` | 恰好 1 条 other_clinical_attributes |

- 真正随访从不挂 molecular_tests / other_clinical_attributes；同一条 follow_up 从不同时挂 mol 和 oca；一个空壳最多只包 1 个子对象；空壳自己没有 `submitter_id`、`created_datetime`、`days_to_follow_up`。7,458 例同时有两类。
- 真正随访的 `timepoint_category` 覆盖 43,187 条（59.6%）：Follow-up 20,117、Last Contact 11,223、Post Initial Treatment 5,191、Preoperative 1,950、Not Reported 1,192、Initial Diagnosis 1,043、Within 3 Months of Surgery 575、Post Adjuvant Therapy 468、Prior to Adjuvant Therapy 445、Other 377、Unknown 234、Prior to Diagnosis 218，其余均 <50。其中 37,837 条同时有 `days_to_follow_up`。

所以从病例视角应看成三个平行集合：`follow_ups`（真正随访事件）、`molecular_tests`（分子检测）、`other_clinical_attributes`（基线属性）。空壳一律不参与定位，也不作为父钟向下传递。

### 5.2 `t_lo` / `t_hi` 判据：访视日作点

视为时点，`t_lo = t_hi = days_to_follow_up`。该次访视的内容字段（`disease_response`、`last_known_disease_status` 等）就是这次访视的产出，无延后字段。

本集合同时是 TH1b 随访阶梯的唯一来源，须在其余记录定位之前先行构建。

### 5.3 特殊情形

- **F-merge**：`timepoint_category = "Last Contact"` 的行，若其 `days_to_follow_up` 与同案某条 `Follow-up` 相同，两者是同一次访视的两次抄录，合并为一次 record。`AB-2810` 两行同为 31、`YU-A94M` 两行同为 564，两例均如此。不合并会重复计数末次访视，并污染随访次数类特征。
- **空行剔除**：`days_to_follow_up` 为 null 且无任何内容字段者记 `non_informative`（`YU-A94M_follow_up6`）；天数为 null 但有 `disease_response` 者记 `unlocated`。

### 5.4 实例

- `AB-2810` 随访 ×2（均 31 天，Follow-up + Last Contact）→ `[31, 31]` point（F-merge 合并为一次）
- `YU-A94M` 随访 333／431／493／564 → 各自 point
- `YU-A94M` `follow_up6`（天数 null、无内容字段）→ `non_informative`

---

## 6. `follow_ups[].molecular_tests[]`

**落地状态**：规则已落地（Δ_lab 恒 0）。未落地：biospecimen 实体连接（Sample Procurement 与 P2 型 Preoperative）。

### 6.1 字段统计

- 全库 20,754 条。设计字段是 `days_to_test`（index 日到化验日），实际只有 1,638 条（7.89%），而且只在 TGCT 1,199 + PRAD 439。有天数的 1,638 条同时都有 `timepoint_category`（Preoperative / Postoperative）。
- 更常见的是类别，不是天数：`timepoint_category` 14,643 条（70.56%）。分布：Initial Diagnosis 6,655、Sample Procurement 3,781、Preoperative 3,583、Postoperative 564、Prior to Treatment 60。
- 仍有 6,111 条（29.4%）天数和类别都没有，主要是 BRCA 的 ERBB2/ESR1/PGR IHC。
- 父 follow-up 全部是壳：父对象只有 `follow_up_id` + molecular_tests，`days_to_follow_up` 为 0。CHOL `TCGA-4G-AAZG` 那种术前 CA19-9/白蛋白就是这种，自身只有 `timepoint_category = Preoperative`。
- **语义方向已验证（判别性检验见 §8.1，molecular 侧）**：`2G-AAFY` 术前 LDH `days_to_test = -3`、术后 AFP `days_to_test = +11`，`YU-A94M` 三项术前标志物 `days_to_test = 0`。类别与天数方向完全一致，且指向"所测量/所观察的时点"，锚点是手术／取材日。本节的锚点表据此编制。

### 6.2 `t_lo` / `t_hi` 判据

- **有天数**：`t_lo = days_to_test + Δ_lab`，`t_hi` 走 TH1b／TH2。天数可为负（`2G-AAFY` 术前 LDH `-3`），说明 index 不是本例最早事件，负值不作异常处理。
- **无天数、有类别**：按下表取锚点。锚点的具体天数取决于本例的 P1／P2 判定（§4.2），两支共用同一判别。

| 类别 | 计数 | P1 型（index 诊断作于切除／取材标本） | P2 型（活检确诊、手术在后） |
| --- | --- | --- | --- |
| Initial Diagnosis | 6,655 | `t_hi = 0 + Δ_lab` | 同左（锚点是诊断日，与手术无关） |
| Sample Procurement | 3,781 | `t_hi = 0` | `t_hi` = 取材日，须连接 biospecimen 实体 |
| Preoperative | 3,583 | `t_hi = 0` | `t_hi` = 手术日；无手术天数则 `unlocated` |
| Prior to Treatment | 60 | `t_hi` = 全案最早 `days_to_treatment_start` | 同左 |
| Postoperative | 564 | `t_lo = 0`，`t_hi` 走 TH1b／TH2 | `t_lo` = 手术日 |

**收益**：P1 型病例中前四类合计 14,079 条，占有类别对象的 96%，全部落在 `t_hi <= 0`，对任何 `L >= 0` 的 landmark 无条件通过门控。这是全规则集中收益最高的一条，其可靠性完全系于 P1／P2 判定，因此 §4.2 的判别质量必须先保证。

### 6.3 特殊情形：Δ_lab 的适用场合

`Initial Diagnosis` 下的 IHC 与突变检测（`AB-2810` 的 MPO、CD33、HLA-DR、IDH1、NPM1、FLT3）有实验室周转期，结果严格晚于第 0 天。`L >= 30` 时可忽略；做 `L = 0` 或极短 landmark 时须开启该参数。

### 6.4 实例

- `AB-2810` Sample Procurement 血象／骨髓象 ×15 → `(-∞, 0]` bounded（LAML 属 P1）
- `AB-2810` Initial Diagnosis IHC／突变 ×8 → `(-∞, 0+Δ_lab]` bounded
- `2G-AAFY` 术前 LDH（`days_to_test = -3`）→ `[-3, TH1b]` bounded
- `2G-AAFY` 术后 AFP（`days_to_test = 11`）→ `[11, TH1b]` bounded
- `YU-A94M` 术前 AFP／LDH／hCG（`days_to_test = 0`）→ `[0, 0]` point
- `YU-A94M` 术后 AFP／LDH／hCG（无天数）→ `[0, 333]` bounded（TH1b）

---

## 7. `follow_ups[].other_clinical_attributes[]`

**落地状态**：规则已落地。

### 7.1 字段统计

- 全库 8,321 条，内容为 BMI、月经史、合并症、危险因素、生育史等基线病史与查体项（`YU-A94M` 的 `fertility_history`、`undescended_testis_history`）。
- `timepoint_category` 覆盖 8,229 条（98.89%）：Initial Diagnosis 4,245、Prior to Diagnosis 3,497、Not Reported 436、Adulthood 27、Childhood 16、Adolescence 8。
- 精确天数几乎没有：`days_to_comorbidity` 和 `days_to_risk_factor` 各 24 条（0.29%），而且是同一 24 条 PAAD 记录、两值始终相等。
- 缺类别的 92 条全在 UVM（80 条只有 `eye_color`）。
- 父 follow-up 同样全是壳（5.1）。

### 7.2 `t_lo` / `t_hi` 判据

- **Initial Diagnosis（4,245）与 Prior to Diagnosis（3,497）**：合计 7,742 条一律 `t_record = (0, 0]`。机制同既往史定点（§2.4）——类别描述的是该状况**存在的时期**，不是它**被记录的时点**，两者都在基线问诊中一次采集。
- **Not Reported（436）与生命阶段尾巴（Adulthood 27／Childhood 16／Adolescence 8，共 51）**：合并按 Not Reported 处理，记 `unlocated`，不再细分。生命阶段是年龄区间而非相对诊断的时点，51 条不值得为其引入 `age_at_diagnosis` 换算。

### 7.3 特殊情形：陷阱——天数是发生时间，不是记录时间

24 条带 `days_to_comorbidity` / `days_to_risk_factor` 的对象，其天数是该状况的**发生时间**，不是记录时间，不得直接充当 `t_record`。天数为负则仍取 `(0, 0]`；天数为正说明该状况在 index 之后出现，取 `t_lo` = 该天数、`t_hi` 走 TH1b。

### 7.4 实例

`YU-A94M` `fertility_history`（Prior to Diagnosis）→ `(0, 0]` point。

---

## 8. 共享机制

### 8.1 `timepoint_category`：只作局部补充，不能作定位主干

**全库覆盖**（6 个实体，按父项目）：

| 父项目 | 对象总数 | 有该字段 | 覆盖率 |
| --- | --- | --- | --- |
| `follow_ups[]` | 72,435 | 43,187 | 59.6% |
| `follow_ups[].molecular_tests[]` | 20,754 | 14,643 | 70.6% |
| `follow_ups[].other_clinical_attributes[]` | 8,321 | 8,229 | 98.9% |
| `diagnoses[].treatments[]` | 54,945 | 4,497 | 8.2% |
| `diagnoses[].pathology_details[]` | 14,366 | 249 | 1.7% |
| `diagnoses[]` | 18,839 | 0 | 0% |

词典里 5 个实体共用同一套 enum（36 个值，非必填），diagnoses 上没有这个字段。11 个 enum 在这批 TCGA 里一次都没出现：After Chemotherapy、After Study Registration、End of Consolidation Therapy、End of Treatment Course、End of Treatment Course 1、End of Treatment Course 2、First Complete Response、Post Hormone Therapy、Post Secondary Therapy、Prior to Chemotherapy、Prior to Study Registration。

因此该字段在任何情况下都不能作为定位主干，只能作为局部补充。

**它给的是区间的一侧，不是区间**。`timepoint_category` 不含天数，单独使用不产生任何时间值。它的作用是**指明本记录挂靠哪一个临床路标、挂在哪一侧**，天数仍须由同案的已定位字段提供。"Prior to X" 给上界，"Post X" 给下界。

| 类别 | 计数 | 需要的同案锚点 | 落在哪一侧 |
| --- | --- | --- | --- |
| Prior to Procurement | 1,480 | 生物标本实体的取材日（`samples[].days_to_collection`），**不在 clinic JSON 内** | `t_hi` |
| Prior to Diagnosis | 1,267 | 不用事件锚，见 §3.4 | — |
| Preoperative | 973 | 手术类 treatment 的 `days_to_treatment_start` | `t_hi` |
| Postoperative | 484 | 同上 | `t_lo` |
| First Treatment | 264 | 全案最早的 `days_to_treatment_start` | `t_lo` |
| Recurrence | 21 | `days_to_recurrence` | `t_lo` |
| Progression | 8 | `days_to_last_known_disease_status` | `t_lo` |

`pathology_details[]`（249，全 TGCT）：Postoperative 218 挂手术日给 `t_lo`；Prior to Adjuvant Therapy 10 挂辅助治疗最早 start 给 `t_hi`；Post Adjuvant Therapy 21 挂辅助治疗最晚 end 给 `t_lo`。后两类的锚点在同一诊断对象内即可取到，是本字段中唯一能自足闭合的部分，但合计仅 31 条。

由此，旧规格所设想的「类别 → `(t_lo, t_hi)` 对照表」在结构上不成立：类别永远只填一格，另一格仍走通用 t_lo / t_hi 链（0.3/0.4）。

**语义未定：事件位置还是记录位置**。该字段既可读作"所描述事件发生在哪个时点"，也可读作"该条数据在哪个时点被采集"。两种读法给出的方向相反，上表按记录位置读法编制。

判别性检验在 `molecular_tests` 一侧已由实例给出答案（§6.1），`treatments` 一侧仍未验证，不能照搬。检验办法不变：取同时具备 `timepoint_category` 与 `days_to_treatment_start` 的 treatment 对象，将天数与类别所指路标对比。若 `Preoperative` 的起始日晚于同案手术日，上表的方向须整体翻转。一次全库扫描即可，应在实现本节的对照表之前完成。

**与内容字段冲突时**。以内容字段为准，并将该对象的类别标注整体记为不可用，不做部分采信。

**优先级**。即便对照表全部落地，可新增定位的对象上限是 4,497 条（占 treatments 的 8.2%）；其中依赖外部锚点的 Procurement、Preoperative、Postoperative 三类合计 2,937 条（65%），而手术类 `treatment_or_therapy = "yes"` 却无 `days_to_treatment_start` 的病例约 2,984 例，两者高度重叠，实际可闭合的比例远低于 8.2%。因此本节的实现优先级应低于病理锚点（§4，覆盖 14,366 条）、否定勾选分类（§3）与既往史定点（§2）。

### 8.2 假设开关与敏感性参数

对于当前机制中一些 t_record 判据里有几处必须选边的地方，无法通过 JSON 文件与词典直接裁决，因此就变成了用户决定的假设开关与敏感性参数：
- 「随访表会采集区间事件吗？」——选了"是"，TH1b 才成立
- 「治疗记录是事件当天就写下的吗？」——选了"是"，每个带天数对象都变成点；选了"否"，大多数只有下界
- 「疗效评价要等多久？病理报告几天出？」

| 名称 | 含义 | 默认 |
| --- | --- | --- |
| A1 | CRF 前瞻近实时录入，令带天数对象 `t_hi = t_lo` | 关闭 |
| A2 | 随访表捕获区间事件，据此启用 TH1b 随访阶梯 | 开启 |
| M1 | 同方案拆行合并（§3.4） | 关闭 |
| M2 | 属性补行合并（§4.4） | 关闭 |
| M3 | 新旧抄录对合并（§3.4） | 关闭 |
| `Δ_resp` | 疗效评价延迟（天） | 0 |
| `Δ_path` | 病理报告出具周期（天） | 0 |
| `Δ_lab` | 实验室／分子检测周转期（天） | 0 |

A1 开了就回到"事件日定点"的老口径，可用记录暴涨，但等于默认写入 = 事件，乐观且无法验证，泄露风险；A1 关闭时，仅 TH1 与 §2 能给出有限上界，landmark 可用记录数会显著低于按事件日定点的做法；这是口径差异，不是数据缺失。建议主分析关闭 A1，敏感性分析开启并报告两组结果之差。

A2 是 TH1b 存在的开关，关闭之后原 TH1b 退 TH2。

---

## 9. 三例套用结果（回归校验基线）

| 病例 | 记录 | `t_record` | status | 依据 |
| --- | --- | --- | --- | --- |
| AD-6895 | 主诊断 pathology_details | `(0, 0]` | point | §4 P1 |
| AD-6895 | 药物 Adjuvant `no` | `(?, 763]` | lo_only | §3 N2 + TH2 |
| AD-6895 | 放疗 Adjuvant `no` | — | non_informative | §3 N1 |
| AD-6895 | 既往皮肤癌下 2 条 | `(0, 0]` | point | §2 |
| EA-A5O9 | EBRT 56→81 CR | `[81, 788]` | bounded | §3 t_lo 链 + TH2 |
| EA-A5O9 | pathology_details | `(0, 56]` | bounded | §4 P2 + TH1 |
| EA-A5O9 | Hysterectomy `Prior to Diagnosis` | — | unlocated | §3.4 |
| EA-A5O9 | 术后药物 `no` ×2 | `(?, 788]` | lo_only | §3 N2 + TH2 |
| DS-A1OC | EBRT 117→155 | `[155, +∞)` | lo_only | §3 t_lo 链 + TH3 |
| DS-A1OC | 化疗（2 行合并） | `[332, +∞)` | lo_only | §3 M1 + TH3 |
| DS-A1OC | pathology_details（2 行合并） | `(0, 117]` | bounded | §4 M2 + P2 + TH1 |
| DS-A1OC | Hysterectomy `Prior to Diagnosis` | — | unlocated | §3.4 |
| DS-A1OC | 既往乳腺癌下 2 条 | `(0, 0]` | point | §2 |
| AB-2810 | 随访 ×2（均 31 天，Follow-up + Last Contact） | `[31, 31]` | point | §5 F-merge |
| AB-2810 | Sample Procurement 血象／骨髓象 ×15 | `(-∞, 0]` | bounded | §6，LAML 属 P1 |
| AB-2810 | Initial Diagnosis IHC／突变 ×8 | `(-∞, 0+Δ_lab]` | bounded | §6 |
| 2G-AAFY | 术前 LDH（`days_to_test = -3`） | `[-3, TH1b]` | bounded | §6 |
| 2G-AAFY | 术后 AFP（`days_to_test = 11`） | `[11, TH1b]` | bounded | §6 |
| YU-A94M | 随访 333／431／493／564 | 各自 point | point | §5 |
| YU-A94M | `follow_up6`（天数 null、无内容字段） | — | non_informative | §5 |
| YU-A94M | 术前 AFP／LDH／hCG（`days_to_test = 0`） | `[0, 0]` | point | §6 |
| YU-A94M | 术后 AFP／LDH／hCG（无天数） | `[0, 333]` | bounded | §6 + TH1b |
| YU-A94M | `fertility_history`（Prior to Diagnosis） | `(0, 0]` | point | §7 |

## 10. 未覆盖范围

- `demographic`、`exposures[]`、`family_histories[]` 三支不在本规则集内（§1，无时间实体不定位）。
- biospecimen 实体连接（Prior to Procurement 1,480 条、P2 型 Sample Procurement 所需）尚未实现。
- `treatments` 上 `timepoint_category` 的语义方向（§8.1）尚未检验。
