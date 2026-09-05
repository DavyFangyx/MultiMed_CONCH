# t_record 区间确认规则（landmark 用）

依据实例归纳。`diagnoses[]` 一支：`TCGA-AD-6895`（COAD）、`TCGA-EA-A5O9`（CESC）、`TCGA-DS-A1OC`（CESC）。`follow_ups[]` 一支：`TCGA-AB-2810`（LAML）、`TCGA-2G-AAFY`（TGCT）、`TCGA-YU-A94M`（TGCT）。覆盖 `diagnoses[].treatments[]`、`diagnoses[].pathology_details[]`、`follow_ups[]`、`follow_ups[].molecular_tests[]`、`follow_ups[].other_clinical_attributes[]`。所有天数相对 `index_date`。

## 0. 定义与门控

`t_record` 是区间 `(t_lo, t_hi)`，不是点。

- `t_lo`：该记录的内容最早可能被写下的时刻。由记录内**最晚才可得的字段**决定。
- `t_hi`：该记录**必然已存在**的最早可证时刻。只能来自外部证据，不能由对象自身的事件天数推出。
- landmark 门：记录在 L 时刻可用，当且仅当 `t_hi <= L` 且状态不为 `unlocated`。

`created_datetime` / `updated_datetime` 是 GDC 入库时间（`t_write`），任何情况下不参与 `t_record`。

**方向约束（核心）**：事件天数给下界，不给上界。`days_to_treatment_start = 56` 只能推出记录不早于第 56 天，不能推出第 56 天记录已存在。把事件天数直接当 `t_hi`，等于默认 CRF 前瞻实时录入——这是假设 A1，默认关闭，见第 8 节。

## 1. 记录单元的合并（先于定位）

对象个数不等于 record 次数。合并在定位之前完成。

- **M1 同方案拆行**：同一 `diagnoses[]` 下的多个 treatment 对象，若 `days_to_treatment_start`、`days_to_treatment_end`、`number_of_cycles` 全部相同，仅 `therapeutic_agents` 与剂量不同，合并为一次 record。
  实例：`DS-A1OC` 的 `treatment2`（Gemcitabine）与 `treatment3`（Cisplatin），同为 252→332、4 周期，是一个含铂方案按药物拆行。
- **M2 属性补行**：同一诊断下的多个 `pathology_details`，若其中一个仅含属性字段而无独立内容主体与时间字段，并入主报告。
  实例：`DS-A1OC` 的 `pathology_detail2` 仅有 `lymph_node_involved_site`。
- **M3 重抄对**：同一诊断下治疗类型、`treatment_intent_type`、`treatment_outcome` 一致，一条带天数、一条仅有 `timepoint_category`，视为同一次治疗的新旧两次抄录，合并，天数取带天数的那条。
  实例：`EA-A5O9` 的 `treatment`（EBRT 56→81，CR）与 `treatment3`（Radiation NOS，Postoperative，CR）。M3 属可选合并，需在口径中声明；不合并时后者按 `unlocated` 处理。

合并后：`t_lo = max(各行 t_lo)`，`t_hi = min(各行可得 t_hi)`。

## 2. `t_lo`：按最晚可得字段定

按以下顺序取第一条命中的：

| 条件 | `t_lo` |
| --- | --- |
| 含 `treatment_outcome` | `days_to_treatment_end + Δ_resp` |
| 含 `days_to_treatment_end`、累计 `treatment_dose`、`number_of_cycles`、`number_of_fractions` 中任一 | `days_to_treatment_end` |
| 仅含 `days_to_treatment_start` | `days_to_treatment_start` |
| `pathology_details` | 标本获取日，见第 4 节 |
| 否定勾选 | 见第 5 节 |
| 既往史类 | 见第 6 节 |
| 以上皆无 | `unlocated` |

`Δ_resp` 为疗效评价延迟，默认 0（即以结束日为硬下界），作为敏感性参数。

理由：累计剂量、周期数、分次数、结束日、结局，都不可能在疗程结束前结账。三例中：`EA-A5O9` 的 EBRT `t_lo = 81`（另含 outcome）；`DS-A1OC` 的 EBRT `t_lo = 155`、化疗 `t_lo = 332`，均非起始日。

## 3. `t_hi`：三个来源，按优先级取最小可得值

**H1 下游依赖事件（首选）**。存在一个天数已定位的事件 E，其发生必须以本记录为前提，则 `t_hi = t(E)`。

已确认的唯一实例化形式：术后辅助治疗的适应证判断依赖术后病理报告。
成立条件：(a) 本例确有切除标本证据（见第 4 节）；(b) 存在 `treatment_intent_type = "Adjuvant"` 或 `timepoint_category = "Postoperative"` 且带 `days_to_treatment_start` 的治疗。
则 `t_hi(pathology_details) = min(该类治疗的 days_to_treatment_start)`。
实例：`EA-A5O9` → 56；`DS-A1OC` → 117。

新增 H1 形式须逐条论证并登记，不得由类比扩展。

**H1b 随访阶梯（依赖假设 A2）**。真正随访记录（第 11 节）自带 `days_to_follow_up`，在本病例上构成一串已定位时点。对任一 `t_lo` 已知的记录，取 `t_hi = min{days_to_follow_up : days_to_follow_up >= t_lo}`。依据是随访表按设计采集区间事件。无满足条件的随访日时退 H2。

这条比 H2 紧得多：`YU-A94M` 的术后血清标志物 `t_lo = 0`，H2 给 564，H1b 给 333。对治疗对象同样适用——若某方案结束于 332 天而本例有 360 天随访，`t_hi = 360` 而非全案末锚点。

**H2 病例级末锚点（兜底）**。`t_hi = max(days_to_last_follow_up, days_to_last_known_disease_status, days_to_recurrence, 全部已定位事件天数)`。
实例：`AD-6895` → 763；`EA-A5O9` → 788。

**H3 上界失守**。上述皆不可得时 `t_hi = +∞`，状态记 `lo_only`。
实例：`DS-A1OC` 的 `days_to_last_follow_up`、`days_to_recurrence`、`days_to_last_known_disease_status` 全空，最后的临床锚点是化疗结束日 332，之后无任何证据。该病例全部无日期对象上界失守。

## 4. `pathology_details` 的锚点判定

标本获取日由 index 诊断的作出方式决定，与病理对象自身无关（`days_to_pathology_detail` 全库无值，不作判据）。

- **P1 切除标本即确诊标本**：无活检记载，同时具备 `residual_disease` 或 `ajcc_pathologic_*`，且 `site_of_resection_or_biopsy` 为实体器官。此时标本日等于诊断日，`t_lo = days_to_diagnosis`，`t_hi = days_to_diagnosis + Δ_path`（`Δ_path` 为报告出具周期，默认 0，作敏感性参数）；若 H1 可得且更紧，取 H1。
  实例：`AD-6895`，`residual_disease = R0`、pT3N1a、取材部位 Cecum，`t_record = (0, 0]`。
- **P2 活检确诊、另有切除**：`method_of_diagnosis = "Biopsy"`，且存在切除类治疗或病理分期/清扫淋巴结等切除标本所见。`t_lo = days_to_diagnosis`（保守取诊断日，实际严格大于），`t_hi` 取 H1。
  实例：`EA-A5O9` → `(0, 56]`；`DS-A1OC` → `(0, 117]`。
- **P3 二者皆不成立**：`unlocated`。

## 5. 否定勾选（`treatment_or_therapy = "no"` 且无任何天数）

不统一挂父诊断日。按该治疗方式对本病种的适用性分两类，判定需要外部维护的「病种 × 治疗方式」适用性表，不能从 JSON 推出。

- **N1 恒真否定**：该治疗方式对本病种本就不属可选项，字段值不携带时间信息。标 `non_informative`，不进入 landmark 特征集，也不赋 0。
  实例：`AD-6895` 结肠癌的 `Radiation Therapy, NOS = no`。
- **N2 有临床含义的否定**：该治疗方式属本病种本分期的标准选项，"未行"是实质结论，只有在相应治疗窗口关闭后才成立。`t_lo` = 窗口关闭时点，通常无法从本例推得，则 `t_lo` 记 `unlocated`；`t_hi` 取 H2/H3。
  实例：`AD-6895` ⅢB 期结肠癌的 `Pharmaceutical Therapy, NOS = no`；`EA-A5O9` 的 `treatment2` / `treatment4`。

N1 与 N2 形态完全相同，仅凭 JSON 不可分。此处是本规则集对外部知识的唯一硬依赖。

## 6. 既往史类

父诊断满足 `diagnosis_is_primary_disease = false` 或 `classification_of_tumor = "Prior primary"` 时，其下全部对象适用。

- 事件时间不可定位（`age_at_diagnosis` 为 null、无 `days_to_diagnosis`），不试图恢复。
- 记录时间定点：`t_record = (0, 0]`，即基线病史采集。
- 成立条件：主诊断上存在 `prior_malignancy = "yes"`（有 `prior_treatment` 更佳）作同源佐证。
- 实例：`AD-6895` 的 `treatment3` / `treatment4`（头皮基底样鳞癌）、`DS-A1OC` 的 `treatment4` / `treatment5`（右乳癌）。

这是全部类别中唯一可收敛为点的情形，其成立不依赖假设 A1，因为定位对象是问诊行为而非临床事件。

## 7. `timepoint_category` 的使用限制

全库覆盖：`treatments[]` 4497/54945（8.2%），`pathology_details[]` 249/14366（1.7%，全部集中在 TGCT），`diagnoses[]` 本身 0/18839。因此该字段在任何情况下都不能作为定位主干，只能作为局部补充。

### 7.1 它给的是区间的一侧，不是区间

`timepoint_category` 不含天数，单独使用不产生任何时间值。它的作用是**指明本记录挂靠哪一个临床路标、挂在哪一侧**，天数仍须由同案的已定位字段提供。"Prior to X" 给上界，"Post X" 给下界。

| 类别 | 计数 | 需要的同案锚点 | 落在哪一侧 |
| --- | --- | --- | --- |
| Prior to Procurement | 1480 | 生物标本实体的取材日（`samples[].days_to_collection`），**不在 clinic JSON 内** | `t_hi` |
| Prior to Diagnosis | 1267 | 不用事件锚，见 7.3 | — |
| Preoperative | 973 | 手术类 treatment 的 `days_to_treatment_start` | `t_hi` |
| Postoperative | 484 | 同上 | `t_lo` |
| First Treatment | 264 | 全案最早的 `days_to_treatment_start` | `t_lo` |
| Recurrence | 21 | `days_to_recurrence` | `t_lo` |
| Progression | 8 | `days_to_last_known_disease_status` | `t_lo` |

`pathology_details[]`（249，全 TGCT）：Postoperative 218 挂手术日给 `t_lo`；Prior to Adjuvant Therapy 10 挂辅助治疗最早 start 给 `t_hi`；Post Adjuvant Therapy 21 挂辅助治疗最晚 end 给 `t_lo`。后两类的锚点在同一诊断对象内即可取到，是本字段中唯一能自足闭合的部分，但合计仅 31 条。

由此，旧规格所设想的「类别 → `(t_lo, t_hi)` 对照表」在结构上不成立：类别永远只填一格，另一格仍走第 2、3 节。

### 7.2 语义未定：事件位置还是记录位置

该字段既可读作"所描述事件发生在哪个时点"，也可读作"该条数据在哪个时点被采集"。两种读法给出的方向相反，7.1 的表按记录位置读法编制。

判别性检验在 `molecular_tests` 一侧已由实例给出答案：`2G-AAFY` 术前 LDH `days_to_test = -3`、术后 AFP `days_to_test = +11`，`YU-A94M` 三项术前标志物 `days_to_test = 0`。类别与天数方向完全一致，且指向"所测量/所观察的时点"，锚点是手术／取材日。第 12 节据此编制。

`treatments` 一侧仍未验证，不能照搬。检验办法不变：取同时具备 `timepoint_category` 与 `days_to_treatment_start` 的 treatment 对象，将天数与类别所指路标对比。若 `Preoperative` 的起始日晚于同案手术日，7.1 的方向须整体翻转。一次全库扫描即可，应在实现 7.1 之前完成。

### 7.3 `Prior to Diagnosis` 的机械核对

父诊断的 `prior_treatment` 字段与该类别构成可直接判定的一致性检验，不需要领域知识：

- 父诊断 `prior_treatment = "yes"`：属真实既往治疗史，采集自基线问诊，`t_record = (0, 0]`，机制同第 6 节，与事件日是否可知无关。
- 父诊断 `prior_treatment = "No"`：**矛盾，类别标注不可用**，该对象记 `unlocated`，且应视为本次病程内的治疗而非既往治疗。
- `prior_treatment` 为空：不判定，记 `unlocated`。

`EA-A5O9` 与 `DS-A1OC` 均落在第二支：两例的 Hysterectomy NOS 标 `Prior to Diagnosis`，而父诊断 `prior_treatment = "No"`，同时 `margin_status = "Uninvolved"`、pT/pN 病理分期、10 枚与 19 枚清扫淋巴结、术后辅助放疗，均指向手术发生在 index 诊断之后。两例独立出现同一形态的错标，且同属 2025-01 重抄批次。

需要先跑一次 `timepoint_category × treatment_type` 交叉表：若 1267 条 `Prior to Diagnosis` 中手术类占比很高，说明该批标注存在系统性偏差，第一支也需附加核对；若手术类只是少数，则按上述三分支处理即可。

### 7.4 与内容字段冲突时

以内容字段为准，并将该对象的类别标注整体记为不可用，不做部分采信。

### 7.5 优先级

即便 7.1 全部落地，可新增定位的对象上限是 4497 条（占 treatments 的 8.2%）；其中依赖外部锚点的 Procurement、Preoperative、Postoperative 三类合计 2937 条（65%），而手术类 `treatment_or_therapy = "yes"` 却无 `days_to_treatment_start` 的病例约 2984 例，两者高度重叠，实际可闭合的比例远低于 8.2%。因此本节的实现优先级应低于第 4 节（病理锚点，覆盖 14366 条）、第 5 节（否定勾选分类）与第 6 节（既往史定点）。

## 8. 假设开关与敏感性参数

| 名称 | 含义 | 默认 |
| --- | --- | --- |
| A1 | CRF 前瞻近实时录入，令带天数对象 `t_hi = t_lo` | 关闭 |
| M3 | 新旧抄录对合并 | 关闭 |
| A2 | 随访表捕获区间事件，据此启用 H1b 随访阶梯 | 开启 |
| `Δ_resp` | 疗效评价延迟（天） | 0 |
| `Δ_path` | 病理报告出具周期（天） | 0 |
| `Δ_lab` | 实验室／分子检测周转期（天） | 0 |

A1 关闭时，仅 H1 与第 6 节能给出有限上界，landmark 可用记录数会显著低于按事件日定点的做法；这是口径差异，不是数据缺失。建议主分析关闭 A1，敏感性分析开启并报告两组结果之差。

## 9. 输出结构与病例分层

每条 record 输出 `(t_lo, t_hi, source_lo, source_hi, status)`。

`status ∈ {point, bounded, lo_only, unlocated, non_informative}`。

病例分层：`days_to_last_follow_up` 与其余末锚点全空的病例（如 `DS-A1OC`）进入「无全局上界」层，其 `lo_only` 记录在主分析中不可用，不与有末锚点的病例共用同一分母。

## 10. 三例套用结果（回归校验基线）

| 病例 | 记录 | `t_record` | status | 依据 |
| --- | --- | --- | --- | --- |
| AD-6895 | 主诊断 pathology_details | `(0, 0]` | point | P1 |
| AD-6895 | 药物 Adjuvant `no` | `(?, 763]` | lo_only | N2 + H2 |
| AD-6895 | 放疗 Adjuvant `no` | — | non_informative | N1 |
| AD-6895 | 既往皮肤癌下 2 条 | `(0, 0]` | point | 第 6 节 |
| EA-A5O9 | EBRT 56→81 CR | `[81, 788]` | bounded | 第 2 节 + H2 |
| EA-A5O9 | pathology_details | `(0, 56]` | bounded | P2 + H1 |
| EA-A5O9 | Hysterectomy `Prior to Diagnosis` | — | unlocated | 第 7 节 |
| EA-A5O9 | 术后药物 `no` ×2 | `(?, 788]` | lo_only | N2 + H2 |
| DS-A1OC | EBRT 117→155 | `[155, +∞)` | lo_only | 第 2 节 + H3 |
| DS-A1OC | 化疗（2 行合并） | `[332, +∞)` | lo_only | M1 + H3 |
| DS-A1OC | pathology_details（2 行合并） | `(0, 117]` | bounded | M2 + P2 + H1 |
| DS-A1OC | Hysterectomy `Prior to Diagnosis` | — | unlocated | 第 7 节 |
| DS-A1OC | 既往乳腺癌下 2 条 | `(0, 0]` | point | 第 6 节 |
| AB-2810 | 随访 ×2（均 31 天，Follow-up + Last Contact） | `[31, 31]` | point | 第 11 节，F-merge 合并为一次 |
| AB-2810 | Sample Procurement 血象／骨髓象 ×15 | `(-∞, 0]` | bounded | 第 12 节，LAML 属 P1 |
| AB-2810 | Initial Diagnosis IHC／突变 ×8 | `(-∞, 0+Δ_lab]` | bounded | 第 12 节 |
| 2G-AAFY | 术前 LDH（`days_to_test = -3`） | `[-3, H1b]` | bounded | 第 12 节 |
| 2G-AAFY | 术后 AFP（`days_to_test = 11`） | `[11, H1b]` | bounded | 第 12 节 |
| YU-A94M | 随访 333／431／493／564 | 各自 point | point | 第 11 节 |
| YU-A94M | `follow_up6`（天数 null、无内容字段） | — | non_informative | 第 11 节 |
| YU-A94M | 术前 AFP／LDH／hCG（`days_to_test = 0`） | `[0, 0]` | point | 第 12 节 |
| YU-A94M | 术后 AFP／LDH／hCG（无天数） | `[0, 333]` | bounded | 第 12 节 + H1b |
| YU-A94M | `fertility_history`（Prior to Diagnosis） | `(0, 0]` | point | 第 13 节 |

## 11. 真正随访 `follow_ups[]`（43,360）

前提：`follow_ups` 在这批 JSON 里是三个互斥集合，真正随访从不挂子对象，空壳只装恰好一个子对象 molecular_tests , other_clinical_attributes 且自身无 `submitter_id`、`created_datetime`、`days_to_follow_up`。空壳一律不参与定位，也不作为父钟向下传递。

- **定位**：视为时点，`t_lo = t_hi = days_to_follow_up`。该次访视的内容字段（`disease_response`、`last_known_disease_status` 等）就是这次访视的产出，无延后字段。
- **F-merge**：`timepoint_category = "Last Contact"` 的行，若其 `days_to_follow_up` 与同案某条 `Follow-up` 相同，两者是同一次访视的两次抄录，合并为一次 record。`AB-2810` 两行同为 31、`YU-A94M` 两行同为 564，两例均如此。不合并会重复计数末次访视，并污染随访次数类特征。
- **空行剔除**：`days_to_follow_up` 为 null 且无任何内容字段者记 `non_informative`（`YU-A94M_follow_up6`）；天数为 null 但有 `disease_response` 者记 `unlocated`。
- 本集合同时是 H1b 随访阶梯的唯一来源，须在其余记录定位之前先行构建。

## 12. `molecular_tests[]`（20,754）

`days_to_test` 覆盖 1,638 条（7.9%），`timepoint_category` 覆盖 14,643 条（70.5%）。

- **有天数**：`t_lo = days_to_test + Δ_lab`，`t_hi` 走 H1b／H2。天数可为负（`2G-AAFY` 术前 LDH `-3`），说明 index 不是本例最早事件，负值不作异常处理。
- **无天数、有类别**：按下表取锚点。锚点的具体天数取决于本例在第 4 节中的 P1／P2 判定，两支共用同一判别。

| 类别 | 计数 | P1 型（index 诊断作于切除／取材标本） | P2 型（活检确诊、手术在后） |
| --- | --- | --- | --- |
| Initial Diagnosis | 6655 | `t_hi = 0 + Δ_lab` | 同左（锚点是诊断日，与手术无关） |
| Sample Procurement | 3781 | `t_hi = 0` | `t_hi` = 取材日，须连接 biospecimen 实体 |
| Preoperative | 3583 | `t_hi = 0` | `t_hi` = 手术日；无手术天数则 `unlocated` |
| Prior to Treatment | 60 | `t_hi` = 全案最早 `days_to_treatment_start` | 同左 |
| Postoperative | 564 | `t_lo = 0`，`t_hi` 走 H1b／H2 | `t_lo` = 手术日 |

**收益**：P1 型病例中前四类合计 14,079 条，占有类别对象的 96%，全部落在 `t_hi <= 0`，对任何 `L >= 0` 的 landmark 无条件通过门控。这是全规则集中收益最高的一条，其可靠性完全系于 P1／P2 判定，因此第 4 节的判别质量必须先保证。

`Δ_lab` 的适用场合：`Initial Diagnosis` 下的 IHC 与突变检测（`AB-2810` 的 MPO、CD33、HLA-DR、IDH1、NPM1、FLT3）有实验室周转期，结果严格晚于第 0 天。`L >= 30` 时可忽略；做 `L = 0` 或极短 landmark 时须开启该参数。

## 13. `other_clinical_attributes[]`（8,321）

内容为 BMI、月经史、合并症、危险因素、生育史等基线病史与查体项（`YU-A94M` 的 `fertility_history`、`undescended_testis_history`）。`timepoint_category` 覆盖 8,229 条。

- **Initial Diagnosis（4245）与 Prior to Diagnosis（3497）**：合计 7,742 条一律 `t_record = (0, 0]`。机制同第 6 节——类别描述的是该状况**存在的时期**，不是它**被记录的时点**，两者都在基线问诊中一次采集。
- **Not Reported（436）与生命阶段尾巴（Adulthood 27／Childhood 16／Adolescence 8，共 51）**：合并按 Not Reported 处理，记 `unlocated`，不再细分。生命阶段是年龄区间而非相对诊断的时点，51 条不值得为其引入 `age_at_diagnosis` 换算。
- **陷阱**：24 条带 `days_to_comorbidity` / `days_to_risk_factor` 的对象，其天数是该状况的**发生时间**，不是记录时间，不得直接充当 `t_record`。天数为负则仍取 `(0, 0]`；天数为正说明该状况在 index 之后出现，取 `t_lo` = 该天数、`t_hi` 走 H1b。

## 14. 未覆盖范围

`demographic`、`exposures[]`、`family_histories[]` 三支不在本规则集内，沿用既有的"默认最早"口径。biospecimen 实体连接（第 7.1 节 Prior to Procurement 1480 条、第 12 节 P2 型 Sample Procurement 所需）尚未实现。`treatments` 上 `timepoint_category` 的语义方向（第 7.2 节）尚未检验。