# H 系列实验规格（H1–H4 泄露与低估）

本文档是 H 系列实验的**唯一口径来源与步骤注册表**。所有执行 agent 必须先读本文档，再读 `z_notes/H_series_execution_log.md`（执行日志）。若本文档与仓库现状冲突，以本文档明确写出的规则为准，并在执行日志记录冲突与处理方式。

相关文档：项目口径见 `project_overview.md`；可复用机制见 `z_notes/E2_Selection_Gain_Algorithm/E2_selection_algorithm_design.md`（E2 的评估器/缓存/搜索规格仍有效，但 E2 的算法竞赛目标作废）。

---

## 1. 目标

现有使用临床数据的生存预测工作，在选取临床字段时存在两个缺陷：

- **无依据** → 有效字段被遗漏、临床模态被低估；
- **无时点约束** → 预测时点之后才产生的信息被纳入、临床模态被高估。

H 系列实验按逻辑链展开：

- **H1** 证明高估存在：1a 审计（定量泄露占比）+ 1b 去泄露对照（控制变量，唯一差异 = landmark mask）。
- **H2** 在去泄露字段池上证明低估存在：贪婪搜索最优组合 vs 各工作去泄露后的组合。
- **H3** 合并两种偏差：三档对照（报告值 / 去泄露值 / 可达值）+ 单字段排序在有无 landmark 下的对照。
- **H4** 不变性（编码 / 模型 / 数据轴）——**后期**，H1–H3 完成后另出规格。

本阶段只执行 H0、H1、H2、H3；H4 只占位。

## 2. 锁定口径

### 2.1 泄露是定量指标

字段 f 在数据集 D 上的**泄露占比**：

```text
leak_rate(f, D) = 1 − n(landmark_0 下有效值) / n(landmark_none 下有效值)
```

即"该字段在 t0 时刻不可得（属于未来）的患者比例"。逐字段报告占比、所属时间家族、证据来源；**不设人为阈值**。汇总口径"泄露字段" = `leak_rate > 0` 的字段。

### 2.2 控制变量（H1b 与 H2 的铁律）

- H1b 两臂的**字段集、模板、编码、模型、划分完全一致**，唯一差异 = 是否施加 t0 landmark mask。禁止任何删字段、换模板、换编码、换划分的操作。
- H2 对比三臂全部走 A_pipeline 同一条链路（同编码器/模型/划分），差异只允许在字段集。
- 一切评估沿用现有口径：5 折 val c-index（`cv_c_mean`，5 折均值），不伪造独立测试集，`prefer_val=True`。

### 2.3 三档定义

| 档 | 含义 | 来源 |
|---|---|---|
| 报告值 | 含泄露（文献口径） | 现有 `results/A_manual/{dataset}[gdc]/cindex.csv`（S0 不删除） |
| 去泄露值 | 同字段集 + landmark_0 mask | H1b 臂 B（`results/A_manual_landmark/`） |
| 可达值 | 去泄露池上的贪婪搜索最优 | H2 臂 C |

### 2.4 工作与数据集

- "各工作" = A_pipeline 的 10 个论文方案：`MULTISURV`、`SURVPGC`、`MMSURV`、`INTEGRATIVE_DNN`、`HGCN_KIRC`、`HGCN_LIHC`、`HGCN_ESCA`、`HGCN_LUSC`、`HGCN_LUAD`、`HGCN_UCEC`（字段表在 `A_pipeline/templates/{scheme}/fields.json`）。
- 数据集（**本阶段**）= `projects/datasets.json` 中的 **33 个 TCGA** 队列。**TCGA 之外的外部数据集（CPTAC、MMRF 等）本阶段一律不纳入**（用户指令 2026-09-29），H4c 数据轴阶段再议。S1/S2 已产出的 CPTAC/MMRF 描述性记录保留在磁盘（gitignore 内）但不进入任何训练/选择实验。
- **方案 × 数据集绑定**：HGCN_* 六个方案各绑定其**对应癌种**（HGCN_KIRC→KIRC、HGCN_LIHC→LIHC、HGCN_ESCA→ESCA、HGCN_LUSC→LUSC、HGCN_LUAD→LUAD、HGCN_UCEC→UCEC），禁止把它们塞进其他数据集（用户纠正 2026-09-30）；泛癌种方案（MULTISURV、SURVPGC、MMSURV、INTEGRATIVE_DNN）暂按全部 33 TCGA，但记录为未解决问题 U2（见 §12）。
- **数据集选集一律读 H0 manifest，禁止在代码或计划中硬编码名单。**

### 2.5 时间点与 landmark 口径

- **landmark 定义 = 经典三要件**（Anderson 1983；van Houwelingen dynamic prediction / landmarking），三件事必须同时做到：
  1. **风险集**：只保留 T 时刻仍在风险集内的患者（排除 `ground_truth_time ≤ T` 者——T 前死亡者不在 T 风险集，T 前删失者无 T 后随访）；
  2. **时间原点平移**：终点时间改为 `gt − T`（c-index 对平移不变，但仍实现并做不变性自检，以符合规范）；
  3. **只用 T 前信息**：协变量取值仅保留 `t_hi ≤ T` 的槽位（现有值级 mask 已实现这一条）。
- 当前实现只有第 3 条——这是已知漏洞，S3/S4 必须补齐第 1、2 条。
- **默认 landmark = `landmark_0`**（t0 约束）：后续所有评估实验（H1b 臂 B、H2 搜索与三臂、H3b 主图）默认 t0。
- 365 / 730 作为敏感性；原 `landmark_none`（关 mask + R0 整层删 diagnoses/follow_ups，既非无处理也非规范处理）**更名 `static_only`**，**移出主图**，仅进补充材料。
- 两个概念澄清（勿混用）：
  1. **取值 mask 状态**：`off`（无 mask，取值全集）/ `0` / `365` / `730`。H1a 审计的 leak_rate 用 off 与 0 对比；H1b 臂 A = off（报告值对照臂）。
  2. **field-bank 筛选变体**：`landmark_0` / `landmark_365` / `landmark_730` / `static_only`（原 landmark_none）。H2 搜索池 = `landmark_0`；S5 生成时用新名，并同步更名 `rawdata_stats/{dataset}/landmark_none` 目录。

## 3. 步骤注册表与决策点

| 步 | 内容 | 关键产物 | 决策点 |
|---|---|---|---|
| S0 | 枚举并删除 E 系列结果文件 | 删除清单 | **D0** 删除范围 |
| S1 | **H0** 可用数据集评估 | `results/H0_dataset_availability/manifest.csv` | **D1** 门槛规则数值；**D2** landmark 有效事件口径 + MMRF 是否纳入 |
| S2 | H1a 泄露审计（无训练） | `results/leak_audit/` | 口径已锁定，轻确认 |
| S3 | A_pipeline `--landmark_time` 扩展 + 冒烟自检 | 自检报告 | **D3** 自检通过后放量 |
| S4 | H1b 批跑（选集 = manifest 主集+扩展集） | `results/A_manual_landmark/` | 异常 → 回推 H0 |
| S5 | Field Bank 模板补全 + landmark 变体生成 + univariate 补跑 | `outputs/*/field_bank/`、`results/univariate/` | 模板人工填写进度 |
| S6 | H2 贪婪批跑（主集）+ 三臂对照 | Δc、遗漏字段清单 | **D4** 最优组合口径（sig_stop vs best） |
| S7 | H3a 三档表 + H3b Spearman | `results_display/` | — |
| S8 | 回推 H0 manifest v2 + H4 规格起草 | manifest v2 | **D5** 数据集降级/剔除逐项确认 |

依赖：S0 → S1 → S2 → S3 → S4；S1 → S5 → S6 → S7；S4/S6 异常 → S8。

**执行纪律**：单步执行；每步有执行报告（追加到执行日志）；决策点未确认前禁止进入依赖该决策的下一步；每完成一步做一次 git 提交（见 §9）。**未在用户实验清单中明确的事项（数据集范围、口径、规则数值等），执行前必须先向用户报告并获确认，不得擅自扩大范围或替用户做决定。**

## 4. H0 规格：实验可用数据集评估

H0 是把"哪些数据集能进哪些实验"做成可复现、可审计、可回推的评估实验。现有 `rawdata_stats/_shared/event_impact_analysis/` 是 H0 的原型依据。

### 4.1 输入

- `rawdata_stats/_shared/event_summary.csv`、`rawdata_stats/{dataset}/event_stats.csv`（患者级事件表）
- `Clinic_Analyzer/data/splits/5foldcv/{study}/splits_*.csv`（每折事件数）
- `scripts/fold_event_counts.py`（每折事件数统计，可复用思路）

### 4.2 规则（初始版本，照搬 event_impact_analysis 建议；数值以 D1 确认为准，未确认前 manifest 标注 `provisional`）

1. `n_event ≥ 150`（每折 ≥30）→ **主集**（定量实验主体）；
2. `70 ≤ n_event < 150` → **扩展集**（报告但带 CI，不参与严格排名）；
3. `30 ≤ n_event < 70` → **补充集**（补充材料，bootstrap CI）；
4. `n_event < 30` → **排除集**（训练实验不跑，仅 H1a 审计）；
5. `event_rate < 0.1` → 降一级（次级规则）；
6. landmark 变体（365/730）的门槛用**过滤后有效事件数**重套，不用原始总数；有效事件数 = `#{event==1 且 ground_truth_time > T}`（经典 landmark 三要件，见 §2.5）；
7. 退化折（c-index 精确 0.0 / 1.0）→ 该 (dataset, scheme) 点标注并降级；
8. 多字段实验 EPV：每折事件数 ≥ 10 × 字段数。

### 4.3 产物

```text
results/H0_dataset_availability/
  manifest.csv            # dataset,tier,n_patients,n_event,event_rate,per_fold_events,
                          # effective_events_lm0/lm365/lm730,degen_folds,rule_hits,note
  {dataset}_profile.json
```

生成脚本：`scripts/run_h0_availability.py`（同输入重跑 diff=0 才合格）。

### 4.4 回推协议

执行期任一 (dataset, scheme) 出现：退化折、训练失败、折间 std 超阈值、其他数据质量问题 → 执行报告记录 → manifest 更新（降级或标注）→ **D5** 逐项由用户确认。manifest 更新后递增版本号（v1 → v2）。

## 5. H1a 审计规格

### 5.1 输入与范围

- 字段表：`A_pipeline/templates/{scheme}/fields.json`（10 方案，GDC 路径）。
- 数据集：**33 个 TCGA**；方案 × 数据集按 §2.4 绑定（HGCN_* 仅其对应癌种，泛癌种暂按 33 TCGA）。CPTAC/MMRF 不纳入（已产出的描述性记录保留磁盘，但不进汇总与图表）。
- 无训练，纯描述性统计。

### 5.2 计算

对每个 (dataset, scheme, field)：

1. 用 `src/discovery/field_bank.py::extract_field_bank_raw_values(case, field_path, landmark=True/False, landmark_time=0)` 逐患者提取；
2. `n_valid_none` = 取值 mask **关闭**时的有效值数（即取值全集，不是 static_only 变体）；`n_valid_t0` = landmark_0 下保留的有效值数；`leak_rate = 1 − n_valid_t0/n_valid_none`；
3. `family` = `src/discovery/landmark.py::timed_family_for_field(field_path)`；
4. 特判：
   - `derived.*` 字段：landmark 作用于其**底层槽位**（现有 `extract_derived_raw_values` 已支持 `landmark` 参数）；
   - `project.project_id`：常数，leak_rate = 0；
   - 不在 `rawdata_stats/{dataset}/landmark_0/kept_fields.json` 的字段：标记 `not_in_bank`（是"无依据"问题的证据之一，**不影响 H1b 中该字段的完整性**）。
5. 聚合：每方案每数据集：字段数、泄露字段数（rate>0）、泄露字段占比、平均 leak_rate；跨数据集聚合时并列 n_event。

### 5.3 产物

```text
results/leak_audit/
  {dataset}/{scheme}.json          # 逐字段: field, family, n_valid_none, n_valid_t0, leak_rate, not_in_bank
  leak_audit_summary.csv           # (dataset, scheme) 级聚合 + n_event 并列
results_display/leak_audit/        # 图: 每工作×癌种泄露占比、逐字段泄露率热图
```

新代码：`src/leak/`（audit.py、cli.py）+ `scripts/run_leak_audit.py` + `tests/test_leak_audit.py`。验收：抽查 3 个 (dataset, scheme, field) 与手工 JSON 核对一致。

## 6. H1b 规格

### 6.1 A_pipeline landmark 扩展（S3 实现）

- `A_pipeline/src/extract.py` 支持 `--landmark_time {0,365,730,none}`（默认 `none`，**行为与现有完全一致**）：按经典 landmark 三要件（§2.5）实现——① 协变量 mask：timed family 槽位只保留 `t_hi <= T` 的取值，其余按现有缺失规则处理（复用 `projects/src/discovery/landmark.py` 的患者级时间记录与 mask，A_pipeline 内通过 sys.path 接入 projects 的 `src`）；② 风险集：`ground_truth_time <= T` 的患者从训练/评估集排除；③ 时间原点：label 时间改为 `gt − T`，并做一次 c-index 平移不变性自检（365 上验证重 base 与不重 base 数值一致）。
- `pipeline` / `json2prompt` / `encode` / `baseline` 命令透传该参数；产物落 `outputs/{dataset}/A_manual/{scheme}/landmark_{T}/`（`none` 时维持现有目录不变）。
- cindex 结果落 `results/A_manual_landmark/{dataset}/cindex.csv`，**不覆盖** `results/A_manual/`；走现有 A_manual 队列调度（`A_pipeline/run.py cindex`）。

### 6.2 两臂定义

```text
臂 A（报告值对照）: 完整原字段集 × landmark_none（新链路）
臂 B（去泄露值）:   同一字段集 × landmark_0    ← 字段数相同，唯一差异 = mask
```

### 6.3 自检（S3 的放量前提，决策点 D3）

BRCA × MULTISURV：臂 A 经新链路跑通后与旧 `results/A_manual/TCGA-BRCA[gdc]/cindex.csv` 数值**必须完全一致**（diff=0）。不一致不允许放量，排查原因后重跑。

### 6.4 范围

10 方案 × (manifest 主集 + 扩展集) × 两臂；每 (scheme, dataset) 报告 `c(none)`、`c(0)`、`Δc = c(none) − c(0)`。

## 7. H2 规格

### 7.1 搜索

- 池：S5 补全后的 `landmark_0` field bank（当前缺口：bank 内 11 字段 vs kept 33–44，必须先补全）。
- 算法：复用 E2 的 `A2_greedy`（`src/selection/`，summary_only + SQLite 缓存 + sig_stop + 逻辑预算）。
- 数据集：manifest 主集；最优组合默认 = sig_stop 推荐子集（D4 待确认，另报历史 best）。

### 7.2 三臂对照（全部走 A_pipeline 链路，同编码器/模型/划分/seed）

```text
臂 B : 工作完整组合 × scheme 模板 × landmark_0   (= H1b 的去泄露值，字段数不变)
臂 B′: 工作完整组合 × bank 模板   × landmark_0   (custom scheme，模板控制臂)
臂 C : 贪婪最优组合 × bank 模板   × landmark_0   (custom scheme，fields 由搜索结果生成)
```

- custom scheme 机制：生成 `A_pipeline/templates/{scheme}/` 式目录（fields.json 由搜索结果生成、template.csv 取自 field bank 的模板表）。
- 头条 Δc = C − B′（模板、编码、模型、划分全同，唯一差异 = 字段集）；C − B 作交叉验证。
- **遗漏字段清单** = C 的字段 \ 该工作组合字段，附 bank 模板语义说明（"无依据导致遗漏"的物证）；字段数对比。

### 7.3 产物

`results/H2_greedy_vs_works/`（三臂 c-index 表、Δc、遗漏清单）+ `results_display/H2_greedy_vs_works/`（图）。

## 8. H3 规格

- **3a 三档表**：每 (dataset, work) 一行：报告值（旧 A_manual）、去泄露值（臂 B）、可达值（臂 C）、档间 Δ；主集定量、扩展集带 CI；并列 n_event / event_rate / 每折事件数。
- **3b 排序对照**：输入 `results/univariate/prompt/{landmark_tag}/{dataset}/mlp_clinic_flatten/field_cindex.csv`（S5 补跑后）；主图 = `landmark_0` vs `landmark_{365,730}` 的单字段 c-index 排名 Spearman ρ；`static_only` 对照进补充材料；每数据集排名变化最大的字段清单（Δrank 前 k，标升/降）。数据集口径：`n_event ≥ 100` 主表（17 个），70–100 带 CI。
- 产物：`results_display/H3_three_tiers/`、`results_display/H3_landmark_rank/`。

## 9. Git 提交协议

- **每完成一步做一次提交**，提交只包含本步的文件（`git add <具体路径>`，**禁止 `git add -A`** 或 `git add .`——工作树里有与 H 系列无关的历史修改）。
- `results/`、`results_display/`、`outputs/`、`rawdata_stats/` 已被 .gitignore，产物不入库；提交内容 = 代码、脚本、文档、测试。
- 提交信息：`S{n}: {步骤中文摘要}`，结尾加 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。
- 只做本地提交，不 push（除非用户明确要求）。

## 10. 执行日志协议

- **单文件归档**：`z_notes/H_series_execution_log.md`，所有执行报告追加到该文件（不另开文件）。
- 追加前先重读文件末尾，避免覆盖并发写入。
- 模板：

```markdown
## S{n} {步骤名}
- 时间 / 执行者
- 目标
- 输入（文件路径 + 行数/条数/hash）
- 命令与参数
- 产物（路径 + 行数/条数）
- 审计（自检项 + 实际结果）
- 偏差与原因（无则写"无"）
- 决策点：{D-id} {问题} → {结论 / 待用户确认}
- 状态：完成 / 阻塞（阻塞原因）
```

- 决策点状态表维护在日志头部，状态变化时更新对应行。

## 11. 禁止事项

- 不删除、不覆盖 `results/A_manual/`、`outputs/*/A_manual/`、`outputs/*/field_bank/`、`rawdata_stats/`。
- 不修改现有 5 折 split；不伪造独立测试集；不把 val 称为 test。
- 不修改 E 组代码（`src/selection` 的 SEAS/A3–A6/ANCHOR 等）——其去留由用户与执行方协商，本系列只读复用 A2_greedy/evaluator/cache/queue。
- 不在代码或配置中硬编码数据集分层名单（一律读 H0 manifest）。

## 12. 未解决问题（Open Issues）

- **U1（D1 门槛锚点）**：已弃用无推导的 0.05 断言。**用户数据协议（2026-09-30）——n_event 判据（作用=评估方差下限）已定**，适用于 H 系列全部 TCGA 使用（泛癌种工作同样适用）：

  | n_event 档 | 处理 | 33 TCGA 数据集 |
  |---|---|---|
  | ≥100 | 主图，干净集 | 15 个（PAAD、COAD、LGG、LIHC、LAML、BRCA、STAD、KIRC、BLCA、LUAD、LUSC、SKCM、HNSC、OV、GBM） |
  | 70–100 | 进主图，**必须报告 CI，不参与严格排名** | CESC、MESO、ESCA、UCEC、SARC |
  | 30–70 | 补充材料，bootstrap/重采样 CI，不排名 | UVM、ACC、UCS、KIRP |
  | <30 | 定量图不收录；单列"低事件组"定性讨论 | 9 个（READ、CHOL、THCA、KICH、PRAD、DLBC、THYM、TGCT、PCPG） |

  **B/C/D 判据：用户 2026-09-30 指令——暂不执行，保持简单**：B（多字段门槛：≥150 可跑 / 100–150 字段数≤3）、C（landmark 有效事件重套）**存档备查**（见执行日志 R5/R6），当前实验执行**全部按 A 判据**；D（次级修正）不采用。若后续需要再启用 B/C，再议。
- **U2（泛癌种方案绑定）**：MULTISURV / SURVPGC / MMSURV / INTEGRATIVE_DNN 是否按各自论文原始队列绑定，**暂按全部 33 TCGA 执行**，记录为未解决问题；待用户给出各论文队列口径后修正。
