# H 系列执行日志

规格与口径唯一来源：`z_notes/H_series_spec.md`。本文件是**所有执行报告的统一归档**，追加写，不另开文件；追加前先重读文件末尾。

## 决策点状态表

| ID | 决策点 | 状态 | 结论 |
|---|---|---|---|
| D0 | S0 删除范围（results/results_display 的 E1/E2/旧 greedy/univariate/linear_probe；是否连 outputs/*/greedy、outputs/*/univariate、Clinic_Analyzer/results 中间产物） | **已确认（方案 B）** | 删除：results/{E2_selection,univariate,greedy,linear_probe}、results_display/{univariate,greedy,linear_probe,E1_Fig2_Single-field c-index}、outputs/*/{greedy,univariate}（35 队列）、Clinic_Analyzer/results、Clinic_Analyzer/configs/{E2_selection,greedy,univariate}。保留：results/A_manual、results_display/FigA_Other_Paper_Works、outputs/*/{A_manual,field_bank}、rawdata_stats/。磁盘释放 ~200GB（1.1T→1.3T 可用）。 |
| D1 | H0 门槛与降级规则数值（照搬 event_impact_analysis 建议 vs 调整） | 待确认 | **推荐：照搬 spec §4.2 现值**（150/70/30、rate<0.1 降一级）。理由：event_impact_analysis 的折间 std 分档表（§五）显示 ≥150 档 std 0.019–0.052，正好落在"能分辨 0.05 差异"的门槛内侧；本步 manifest 已按此跑出 12/10/4/9 的分布，与原型 README 的 12/22(≥70)/4/9 完全吻合，无调整压力。**唯一建议微调**：把 R7（退化折）从"仅标注"升级为"降级"，因为 PCPG/TGCT/DLBC/THYM 的退化折来自结构性事件稀少，标注不足以保护聚合图。 |
| D2 | landmark 有效事件口径（mask vs 排除患者）+ MMRF 是否纳入 | **口径已确认**（用户指令 2026-09-29）；**MMRF 待确认** | **经典 landmark 三要件（Anderson 1983 / van Houwelingen）**：① 只保留 T 时刻仍在风险集内的患者（排除 `ground_truth_time ≤ T`）；② 时间原点平移到 T（`gt − T`，c-index 对其不变，仍实现以符合规范）；③ 协变量只用 T 前信息（现有 mask 已实现）。有效事件数 = `#{event==1 且 ground_truth_time > T}`。MMRF **推荐纳入**（n_event=191、每折 38–39、无退化折）；但其 landmark 变换幅度大（lm365→118、lm730→47），须按新口径重套档位后再决定是否进 S4/S6。 |
| D3 | S3 自检（臂 A 与旧 A_manual 数值一致）通过后放量 | 待确认 | — |
| D4 | H2 最优组合口径（sig_stop 推荐 vs 历史 best） | 待确认 | — |
| D5 | 回推：数据集中途降级/剔除 | 待确认 | — |

---

## S-1 准备：规格文档与执行日志

- 时间 / 执行者：2026-09-29 / Claude（主会话）
- 目标：建立 H 系列单步执行框架：规格文档、步骤注册表、决策点清单、执行日志模板与 Git 提交协议。
- 输入：用户实验清单（H1–H4）、`project_overview.md`、`z_notes/E2_Selection_Gain_Algorithm/E2_selection_algorithm_design.md`、`rawdata_stats/_shared/event_impact_analysis/`。
- 命令与参数：无（纯文档）。
- 产物：`z_notes/H_series_spec.md`、`z_notes/H_series_execution_log.md`（本文件）。
- 审计：规格中锁定口径（定量泄露、控制变量、三档、H0 规则、Git 协议）与用户三轮反馈一致。
- 偏差与原因：无。
- 决策点：无新增；D0–D5 注册待确认。
- 状态：完成。

---

## S1 H0 可用数据集评估

- 时间 / 执行者：2026-09-29 / Claude（S1 执行 agent）
- 目标：(1) 只读调查 landmark 对生存终点与事件的处理方式（D2 事实基础）；(2) 实现 H0 可用数据集评估脚本与初版 manifest；(3) 不跑任何训练。
- 输入（文件路径 + 行数/条数/hash）：
  - `datasets.json`（177 行，35 队列 = 33 TCGA + CPTAC + MMRF，md5 `5918c06884bc`）
  - `rawdata_stats/_shared/event_summary.csv`（35 行 + 表头，md5 `e4fa8bfef99a`）
  - `rawdata_stats/{dataset}/event_stats.csv`（35 个，患者级 `submitter_id/event/ground_truth_time`）
  - `Clinic_Analyzer/data/splits/5foldcv/{study}/splits_*.csv`（35 个目录 × 5 折 = 175 个文件）
- 命令与参数：
  - `python3 scripts/run_h0_availability.py`（默认）；重跑一次 `--quiet` 做 diff 校验
  - `python3 -m pytest tests/test_h0_availability.py -q`；`python3 -m pytest tests/ -q`
- 产物（路径 + 行数/条数）：
  - `results/H0_dataset_availability/manifest.csv`（36 行 = 表头 + 35 队列，md5 `55762283a740`）
  - `results/H0_dataset_availability/{dataset}_profile.json`（35 个）
  - `scripts/run_h0_availability.py`（533 行）、`tests/test_h0_availability.py`（372 行）
  - 注：`results/**` 已被 .gitignore，产物不入库。

### 任务 1：D2 事实调查（只读，未修改任何代码）

**结论：landmark 变体下只有"mask 未来取值"，没有"排除 t<T 的患者"，且生存终点完全不受 landmark 影响。**

证据（代码位置）：

| 事实 | 位置 | 说明 |
|---|---|---|
| mask 是**值级**掩码，保留列与患者 | `src/discovery/landmark.py:1-12`（模块 docstring） | "keep a slot iff … finite t_hi <= T. **T is an external landmark start time in days, not the survival endpoint.**" / "dropped values become the existing missing placeholder, **they do not remove columns**" |
| mask 判定式 | `src/discovery/landmark.py:120-132` `slot_passes_landmark()` | `days = record_hi or record_days; return days <= last_time`；`last_time` = landmark 天数 T |
| 只构造时间槽状态，不含事件/终点 | `src/discovery/landmark.py:94-104` `patient_landmark()` | 返回 `{last_time, slots, record}`，无 event/time 过滤 |
| **终点定义完全无 landmark** | `src/time_stats.py:722-754` `extract_patient_time_record()` | `event` / `ground_truth_time` 只由原始 case JSON（vital_status、days_to_death、follow_ups）导出；**函数签名没有 landmark 参数** |
| landmark_tag 只影响目录与字段表 | `src/greedy/cli.py:384-414` | `tag = landmark_tag_from_args(args)` → 结果目录、`load_candidate_fields(... landmark_tag=tag)`、`dataset_field_bank_dir(..., tag)`；`resolve_patient_universe(..., label_file=args.label_file, ...)` 的 label/splits 与 landmark 无关 |
| 患者集 = 字段库患者 ∩ label 患者，无 landmark 排除 | `src/greedy/data.py:228-258` | 取交集；事件来自 `load_events()`（`src/greedy/data.py:215-225`，读 label 的 `censorship` 列） |
| 子进程命令不带 landmark | `src/greedy/clinic.py:335-356, 398-428` | landmark_tag 仅用于 `analyzer_results_dir()` 落盘路径；`evaluate.py` 调用参数无 landmark |
| Clinic_Analyzer 无任何 landmark 概念 | `Clinic_Analyzer/evaluate.py:104`；`Clinic_Analyzer/utils/process_args.py:93-105`；`Clinic_Analyzer/datasets/dataset_survival.py:530-555` | `infer_standard_paths(study, which_splits, type_of_path, ...)` 不含 landmark；label_file / split_dir / 折归属均 landmark 无关 |
| A_pipeline 目前**尚无** landmark 支持 | `A_pipeline/src/`（grep `landmark` 零命中） | `--landmark_time` 为 S3 待实现项（spec §6.1） |

**经验证据（35/35 一致）**：`rawdata_stats/{dataset}/landmark_{none,0,365,730}/kept_fields.json` 的 `n_patients` 在四个 landmark 标签下**完全相同**（逐队列核对 35/35）；字段清单在 lm0/365/730 间也完全相同。即 landmark 只改变"每患者每字段是否有值"，不改变患者集，也不改变字段集。

**D2 推荐口径（两点）**

1. **有效事件数定义**（用于 spec §4.2-6 的"门槛重套"）：
   `effective_events_lmT = #{ i : event_i == 1 且 ground_truth_time_i > T }`
   即"在 T 时刻仍处于随访中、且事件发生在 T 之后"的患者数。配套要求（S3/S4 须实现，当前缺失）：
   - **排除** `ground_truth_time <= T` 的患者（T 前已死亡者不是 T 时刻的风险集；T 前删失者无 T 后随访），
   - 保留其余患者的**原 event 指示**（不重新定义终点；如需严格 re-baseline，时间轴改为 `gt-T`，但 c-index 对单调变换不变，故对 H1b/H2 无影响）。
2. **不推荐**沿用现状口径（只 mask）：该口径下 `effective_events_lmT ≡ n_event`，门槛重套退化为恒等，spec §4.2-6 失去意义；且 T 前已死亡患者仍带着"未来终点"留在训练/评估集里，是**终点侧的残留泄露**。

**口径差异的量级（候选数值已存 profile JSON，未写入 manifest）**——若采用严格口径，主集 12 个里 4 个会掉档：

| 队列 | n_event | lm365 | lm730 | 现状档 | 严格口径 lm730 档 |
|---|---|---|---|---|---|
| TCGA-BLCA | 182 | 101 | 36 | 主集 | 补充集 |
| TCGA-STAD | 175 | 78 | 23 | 主集 | 排除集 |
| MMRF | 191 | 118 | 47 | 主集 | 补充集 |
| TCGA-PAAD | 100 | 57 | 11 | 扩展集 | 排除集 |

（其余队列 lm0 与 n_event 基本相同：T=0 时严格口径只剔除 gt≤0 的极端个案，如 TCGA-ACC 34→33。）

### 任务 2：H0 脚本与初版 manifest

- 新代码：`scripts/run_h0_availability.py`（纯函数 `base_tier` / `classify_tier` / `degen_fold_indices` / `epv_field_budget` / `strict_landmark_events` 可单测；`run()` 端到端）。
- 规则实现（spec §4.2）：R1 `n_event≥150`→主集；R2 `70–150`→扩展集；R3 `30–70`→补充集；R4 `<30`→排除集；R5 `event_rate<0.1` 降一级（严格小于，恰好 0.1 不降）；R7 结构退化折 = 折内 val 事件数 ≤1 的折数（c-index 只能取精确 0/1 或无定义）；R8 EPV 字段预算 = `floor(min(每折事件数)/10)`。R6（landmark 重套）因 D2 未定，未实施。
- **tier 全部标注 `provisional`**（D1 未确认）：manifest `note` 列每行以 `provisional(D1)` 开头。
- **`effective_events_lm0/lm365/lm730` 三列留空**，`note` 内每行写 `effective_events_lm*: TODO(D2)`；候选口径的两个数值存 `{dataset}_profile.json` 的 `landmark.candidates`（`current_implementation` + `strict_landmark_exclude_le_T`，含每折受限版）。
- MMRF 行 `note` 含 `口径待 D2`。
- 每折事件数取 `splits_{i}.csv` 的 **val** 列（该仓库 val≡test，已验证），按折号**数字**升序，`|` 连接。

**manifest 初版分层名单（provisional，D1 待确认）**

| tier | 数量 | 队列（括号内为 n_event） |
|---|---|---|
| 主集 main | 12 | CPTAC(700)、TCGA-GBM(492)、TCGA-OV(349)、TCGA-HNSC(224)、TCGA-SKCM(223)、TCGA-LUSC(220)、MMRF(191)、TCGA-LUAD(188)、TCGA-BLCA(182)、TCGA-KIRC(177)、TCGA-STAD(175)、TCGA-BRCA(152) |
| 扩展集 extended | 10 | TCGA-LAML(133)、TCGA_LIHC(132)、TCGA-LGG(126)、TCGA-COAD(102)、TCGA-PAAD(100)、TCGA-SARC(99)、TCGA-UCEC(91)、TCGA-ESCA(77)、TCGA-MESO(74)、TCGA-CESC(72) |
| 补充集 supplementary | 4 | TCGA-KIRP(44)、TCGA-UCS(35)、TCGA-ACC(34)、TCGA-UVM(33) |
| 排除集 excluded | 9 | TCGA-READ(28)、TCGA-CHOL(22)、TCGA-THCA(16)、TCGA-KICH(13)、TCGA-PRAD(10)、TCGA-DLBC(9)、TCGA-THYM(9)、TCGA-TGCT(7)、TCGA-PCPG(6) |

- R5 命中（rate<0.1）5 个队列：PCPG(0.0335)、PRAD(0.0200)、TGCT(0.0283)、THCA(0.0316)、THYM(0.0726)；**均已在排除集，降级无实际位移**，与 event_impact_analysis README §五 的观察一致（"70–150 区间没有 rate<0.1 的"）。
- R7 命中（结构退化折）4 个队列：PCPG(4 折)、TGCT(3 折)、DLBC(1 折)、THYM(1 折)，全部在排除集。
- R8 命中（EPV 预算 = 0，即最小折事件数 < 10）13 个队列：全部排除集 + ACC/KIRP/UCS/UVM（补充集，每折 6–8 事件）。
- 与 `event_impact_analysis/README.md` §五 对照：主集 12 个 = README 的"≥150 → 12 个"；≥70 合计 22 个 = README 的"放宽到 ≥70（22 个）"；排除集 9 个 = README 的"排除 <30 的 9 个"。**完全吻合**。

### 审计（自检项 + 实际结果）

| 自检项 | 实际结果 |
|---|---|
| 覆盖 datasets.json 全部注册队列 | 35/35（manifest 35 行 + 35 个 profile） |
| 重跑 diff=0（可重复） | 通过：manifest `diff=0`；35 个 profile 逐字节比对全部一致 |
| 与独立原型对照 | 与 event_impact_analysis README §五 的三个档位计数（12 / 22 / 9）完全一致 |
| 每折事件数来源正确性 | `splits_*.csv` 的 val 列 = test 列（已验证 brca/mmrf/cptac/lihc/ov）；sum(val 事件) 与 event_summary.n_event 差 ≤6（差异来自未进任何折的患者），已记入 profile 的 `n_event_in_splits` |
| 队列名→splits 目录映射 | `TCGA-*`→`tcga_*`、`TCGA_LIHC`→`tcga_lihc`、`MMRF/CPTAC`→`mmrf/cptac`，35/35 全部命中 |
| 未跑训练 / 未碰真实数据做测试 | 通过：脚本无任何模型调用；测试全部用 `tmp_path` 假数据 |
| 未修改 src/ 与 A_pipeline/ | 通过：本步仅新增 2 个文件 + 追加本日志 |
| 测试 | `tests/test_h0_availability.py` 20 passed；全量 `tests/` 123 passed, 6 skipped（无回归） |

### 偏差与原因

- **偏差 1（口径相关，非错误）**：spec §4.3 的 manifest 列含 `effective_events_lm*`，但 D2 未确认，故按任务要求**留空 + TODO**。候选数值（含"现状 mask-only ≡ n_event"与"严格排除 t≤T"两解）已写入每个 `{dataset}_profile.json` 的 `landmark.candidates`，供 D2 决策直接取用，无需重跑。
- **偏差 2（R7 定义细化）**：spec §4.2-7 原文为"c-index 精确 0.0/1.0"，但那需要训练结果；H0 不训练，故实现为**结构退化折**（折内 val 事件数 ≤1，其 c-index 必然只能取 0/1 或无定义）。该定义仅依赖 splits，可重复且不受 S0 删除结果文件影响。语义已写入 profile 的 `degen_fold_definition`。
- **偏差 3（R7 只标注未降级）**：spec §4.2-7 要求"标注并降级"，但降级动作依 §4.4 属 S8/D5 的逐项确认范围；本步只标注（`degen_folds` + `rule_hits` 含 `R7`），未改动 tier。已记入 D1 推荐意见。
- **偏差 4（R8 的粒度）**：R8 是 (dataset, scheme) 级约束（取决于方案字段数），H0 在数据集级无法判定命中；故只计算 `epv_field_budget` 并在预算为 0 时标 `R8`（此时任何多字段实验都不可行）。
- **偏差 5（命名）**：`datasets.json` 中该队列注册名为 `TCGA_LIHC`（下划线，其余为连字符），splits 目录为 `tcga_lihc`；脚本按统一规则转换，manifest 保留注册名原样，未做重命名。

### 决策点

- **D1** H0 门槛与降级规则数值 → **本步结论：照搬 spec §4.2 现值**（150/70/30、rate<0.1 降一级）；建议把 R7 由"仅标注"升级为"降级"。**待用户确认**（本步 manifest 的 tier 均标 `provisional`）。
- **D2** landmark 有效事件口径 + MMRF 是否纳入 → **本步结论（推荐）**：口径 = `mask（已实现）+ 排除 ground_truth_time ≤ T 的患者（S3/S4 需新增）+ 保留原 event 指示`，`effective_events_lmT = #{event==1 且 ground_truth_time > T}`；MMRF **纳入**。**待用户确认**。确认前：manifest 的 `effective_events_lm*` 保持留空，不推进 S3/S4。

### 状态

完成（本步产物就绪）；**S2 不受 D1/D2 阻塞可继续**（H1a 是纯描述性审计、全部数据集都做），但 **S3/S4 依赖 D2、S4/S6 选集依赖 D1，二者未确认前不推进**。

### 提交

`git add scripts/run_h0_availability.py tests/test_h0_availability.py z_notes/H_series_execution_log.md` → "S1: H0 可用数据集评估脚本与初版 manifest"（提交 hash 见日志末尾追加或 `git log -1`）。

---

## 口径变更 C1：默认 landmark_0；landmark_none 更名 static_only 移出主图

- 时间 / 执行者：2026-09-29 / Claude（主会话，用户指令）
- 目标：落实用户口径指令：后续实验的评估默认 landmark_0；现有 landmark_none（关 mask + R0 整层删 diagnoses/follow_ups）既非无处理也非规范处理，更名为 **static_only**，移出主图、仅进补充材料。
- 输入：用户指令（2026-09-29 会话内）。
- 命令与参数：无。
- 产物：`z_notes/H_series_spec.md` §2.5 重写（两个概念澄清：取值 mask 状态 {off,0,365,730} vs field-bank 筛选变体 {landmark_0,365,730,static_only}）、§5.2 与 §8 相应措辞更新；本日志本条目。
- 审计：逐条核对影响面——S1 manifest（无影响，tier 与命名无关）；S2 H1a 审计（无影响：leak_rate 对比的是取值 mask off 与 t0，其"landmark_none 有效值"= 无 mask 取值全集，措辞已在 spec §5.2 澄清，无需重跑）；S3 A_pipeline `--landmark_time`（`none` = 无 mask 取值，与 static_only 概念不同，保留 none 值；S3 不受影响）；S5 生成 field-bank 变体时用新名 static_only（届时同步更名 rawdata_stats/{dataset}/landmark_none 目录）；H3b 主图改为 landmark_0 vs {365,730}，static_only 对照进补充。
- 偏差与原因：无。
- 决策点：无新增（用户已拍板，直接生效）。
- 状态：完成。

---

## 口径变更 C2：经典 landmark 三要件

- 时间 / 执行者：2026-09-29 / Claude（主会话，用户指令）
- 目标：修正现有 landmark 规则的漏洞。经典 landmark 分析（Anderson 1983；van Houwelingen dynamic prediction / landmarking）要求三件事同时做到：① 只保留 T 时刻仍在风险集内的患者；② 时间原点平移到 T（gt−T）；③ 协变量只用 T 前信息。现有实现只有 ③（值级 mask），① ② 缺失——① 是患者集偏差（T 前死亡者带着"未来终点"留在集内），② 对 c-index 不变但为规范实现。
- 输入：用户指令（2026-09-29 会话内）。
- 命令与参数：无（规格文档更新；已通过 SendMessage 将新要求补发给正在执行的 S3 agent）。
- 产物：spec §2.5（三要件定义）、§4.2-6（有效事件数口径）、§6.1（S3 实现要求：mask + 风险集排除 + gt−T + 平移不变性自检）；本日志 D2 行更新（口径部分标记已确认，MMRF 部分仍待确认）。
- 审计：S1 的 D2 推荐与本指令一致；S1 的 strict_landmark_exclude_le_T 候选数值可直接采用，无需重跑。S2（H1a 审计）不受影响（leak_rate 是值级对比）。S3 受影响：实现范围从"仅 mask"扩大为三要件。
- 偏差与原因：无。
- 决策点：D2 口径部分已确认；D2 的 MMRF 是否纳入仍待用户确认。
- 状态：完成。

---

## S2 H1a 泄露审计

- 时间 / 执行者：2026-09-29 / Claude（S2 执行 agent）
- 目标：(1) 实现 H1a 泄露审计模块（**无训练**，纯描述性统计）：对 `datasets.json` 全部注册队列 × 10 个论文方案，逐字段量化 `leak_rate(f,D) = 1 − n_valid_t0 / n_valid_none`（= t0 时刻该字段不可得的比例）；(2) 产出 `results/leak_audit` 明细 + 汇总与 `results_display/leak_audit` 两张图；(3) 抽查 ≥3 个 (dataset, scheme, field) 与手工 JSON 核对（本步实际做 4 个）；(4) 不跑训练、不改 `src/` 其他模块与 `A_pipeline`。
- 输入（路径 + 条数/hash）：
  - `z_notes/H_series_spec.md` §2.1/§2.4/§2.5/§5（口径唯一来源；C1 更名 static_only 后 §5.2 措辞已澄清，本步审计对象不变）
  - `datasets.json`（35 队列 = 33 TCGA + CPTAC + MMRF，md5 `5918c06884bc`）
  - `A_pipeline/templates/{scheme}/fields.json`（10 个方案字段表，spec §2.4 名单：MULTISURV / SURVPGC / MMSURV / INTEGRATIVE_DNN / HGCN_{KIRC,LIHC,ESCA,LUSC,LUAD,UCEC}）
  - `rawdata_stats/{dataset}/landmark_0/kept_fields.json`（35 个，判定 `not_in_bank`）
  - `rawdata_stats/_shared/event_summary.csv`（35 行，汇总表并列 `n_event`/`event_rate`）
  - 实现参考（只读）：`src/discovery/field_bank.py::extract_field_bank_raw_values`/`load_kept_fields`、`src/discovery/landmark.py::timed_family_for_field`/`patient_landmark`、`src/common/fields.py::field_gdc_path`、`src/common/datasets.py`
- 命令与参数：
  - `python3 scripts/run_leak_audit.py`（默认 `--dataset all --schemes <10 方案> --landmark_time 0 --event_summary rawdata_stats/_shared/event_summary.csv`）；再同命令 `--quiet` 重跑一次做可重复性校验
  - `python3 -m pytest tests/test_leak_audit.py -q` → 10 passed
  - `python3 results_display/leak_audit/scripts/audit_leak.py`（出图 + 聚合表）
  - 抽查：`python3 /tmp/verify_leak_spotcheck.py`（临时脚本，只读原始 clinic JSON、**不 import `src/leak`**，按 `rawdata_stats/TIME_CRITERIA.md` 手写 mask 规则独立重算）
- 产物（路径 + 条数/hash）：
  - `results/leak_audit/{dataset}/{scheme}.json`（**350 个** = 35 队列 × 10 方案；逐字段 `field/family/n_valid_none/n_valid_t0/leak_rate/leak_rate_undefined/not_in_bank` + 审计元数据 `audited_path/audit_mode/mask_applicable/n_values_none/n_values_t0`）
  - `results/leak_audit/leak_audit_summary.csv`（**350 行** + 表头，md5 `cc7ece230a05`；列见 spec §5.2-5 + `n_not_in_bank/n_leak_rate_undefined/n_event/event_rate`）
  - 代码：`src/leak/__init__.py`、`src/leak/audit.py`（431 行）、`src/leak/cli.py`（78 行）、`scripts/run_leak_audit.py`（17 行，thin entry，与 `scripts/run_univariate_cindex.py` 同型）、`tests/test_leak_audit.py`（280 行）
  - 图：`results_display/leak_audit/leak_audit_overview.png`（A 工作 × 癌种 leaky_ratio 热图，黑框标 HGCN 工作与其同癌种队列；B 各工作跨队列分布）、`results_display/leak_audit/leak_audit_fields.png`（A 逐字段 × 工作平均 leak_rate 热图；B 字段级泄露强度）、`results_display/leak_audit/scripts/audit_leak.py`（409 行）、`results_display/leak_audit/leak_audit_{scheme,field}_mean.csv`
  - 注：`results/**`、`results_display/**`、`*.png`、`*.csv` 均在 `.gitignore` 内，故产物目录不入库；`results_display/leak_audit/scripts/audit_leak.py` 不在 `!results_display/scripts/**` 白名单内，提交时用 `git add -f` 单加（图片/CSV 仍不入库）。

### 审计

**覆盖**：35/35 队列（含 MMRF）× 10/10 方案 = 350 个 (dataset, scheme) 组合；2520 条 (dataset, scheme, field) 记录，去重后 **22 个不同字段**；无缺文件、无异常退出。`n_event/event_rate` 在 350 行全部并上（无缺失）。

**抽查（规格要求 3 组，本步做 4 组）**：独立重算脚本只读原始 clinic JSON，逐患者手写 mask 规则（t_hi = ≥t_lo 的最早随访日，否则回退 h2 = max(末次随访日, 末次疾病状态日, 复发日, 已定位事件日)；keep iff 状态非 unlocated/non_informative 且有限 t_hi ≤ 0）：

| dataset × scheme × field | 审计记录 none→t0 (rate) | 独立重算 none→t0 | 结论 |
|---|---|---|---|
| TCGA-LUSC × HGCN_LUSC × `exposures[].pack_years_smoked` | 427 → 427 (0.0000) | 427 → 427 | 一致（exposures 无时点家族，mask 不作用） |
| TCGA-ESCA × HGCN_ESCA × `derived.radiation_therapy` | 165 → 11 (0.9333) | 165 → 11 | 一致（见下"负性记录"） |
| CPTAC × SURVPGC × `diagnoses[].ajcc_pathologic_stage` | 1410 → 0 (1.0000) | 1410 → 0 | 一致（CPTAC 分期全部落在 t0 之后） |
| TCGA-KIRP × SURVPGC × `diagnoses[].ajcc_pathologic_stage` | 261 → 238 (0.0881) | 261 → 238 | 一致 |

**抽查中的定位过程（实现细节，重要）**：ESCA × `derived.radiation_therapy` 首算 t0=14，与记录的 11 差 3 人。逐患者打印后定位到 `src/time_stats.py::_collect_entity_slots` 对 `treatment_or_therapy == "no"` 的负性治疗记录**不建槽位**（`_is_negative_therapy`）——mask 臂看不到这类记录，而非 mask 臂走原路径仍会抽到。把该规则补进独立重算后 4/4 完全一致。结论：审计数字与 Field Bank/mask 现有实现自洽；副作用是 derived 治疗字段的 `leak_rate` 略偏高（负性记录被当作"未来可得"）。本步按现状记录、未改口径（改口径属 S3/A_pipeline 范围）。

**可重复性**：同命令重跑一次（单次全量 82 s，exit 0），`leak_audit_summary.csv` 与首跑 **`diff` = 0**（两次 md5 均为 `cc7ece230a05`）；抽查 2 个逐字段 JSON 对比一致（仅 `generated_at` 时间戳不同）。

**测试**：`tests/test_leak_audit.py` 10 passed（全部用构造的小 JSON 病例，未碰真实数据、未跑 Clinic_Analyzer），覆盖：患者级 leak_rate 被 t0 mask 生效（2→1 = 0.5）、无时点字段永不被 mask、`project.project_id` 常数零泄露、derived 字段按底层槽位审计且与源路径计数一致、derived 底层为无时点家族时零泄露、`n_valid_none=0` → NaN + 标志位且 NaN 不进均值、`not_in_bank` 标记（含 kept_fields 缺失时全 False + `kept_fields_available=false`）、方案字段表读取去重、汇总 CSV 列序与 event 并列、CLI 端到端（tmp 数据集/templates/event_summary）。

**未跑训练 / 未改他人文件**：通过（本步只新增 `src/leak/`、`scripts/run_leak_audit.py`、`tests/test_leak_audit.py`、`results_display/leak_audit/`，并追加本日志）。

### 头部结论（谁泄露最严重 / 典型泄露字段）

- **方案级（跨 35 队列平均 leaky_ratio，降序）**：HGCN_UCEC **0.467** > HGCN_LUAD 0.407 > MULTISURV 0.343 > HGCN_LIHC 0.329 > HGCN_LUSC 0.314 > HGCN_ESCA 0.299 > HGCN_KIRC 0.296 > MMSURV 0.263 > SURVPGC 0.200 > INTEGRATIVE_DNN **0.114**。即：**HGCN 系列（尤其 UCEC/LUAD）与 MULTISURV 泄露占比最高，INTEGRATIVE_DNN 最低**；UCEC 高的直接原因是方案只有 6 个字段，两个 derived 治疗字段一泄露就把占比顶到 0.67。
- **字段级（跨队列平均 leak_rate）**：`derived.radiation_therapy` 与 `derived.pharmaceutical_therapy` 是唯一"全队列级"泄露源——**34/35 队列 rate>0，平均 0.939**（TCGA-BRCA 0.976 = 1094→26；TCGA-UCEC 0.965 = 548→19；TCGA-LUAD 0.900 = 468→47），即 90%+ 患者的治疗记录都发生在 t0 之后。
- 第二梯队：**诊断分期/形态学族**，量级小一个数量级——`ajcc_pathologic_m` 0.107 / `_t` 0.093 / `_n` 0.089 / `staging_system_edition` 0.081 / `ajcc_pathologic_stage` 0.071 / `morphology`、`primary_diagnosis`、`site_of_resection_or_biopsy` 0.066–0.087。MMSURV / SURVPGC / INTEGRATIVE_DNN 的泄露字段**全部**是这一族（例：CPTAC × SURVPGC stage 1410→0，rate 1.0；CPTAC × MMSURV T/N/M 均 1.0）。
- **完全不泄露**：`demographic.*`（age/sex/race）、`exposures.*`、`project.project_id` —— 与 spec §2.3 的"只有 timed 家族被 mask"一致。
- **队列差异**：平均 leaky_ratio 最高 TCGA-HNSC/KIRP/LUAD/LUSC/PAAD 0.493，最低 TCGA-BRCA/CHOL/DLBC/ESCA/LAML 0.177；差异由方案字段数（字段越少、单个 derived 字段占比越高）与诊断分期是否整体落在 t0 后决定。
- **"无依据"旁证（本步只记录，不改决策表）**：`demographic.age_at_index` 在 **35/35** 队列 `not_in_bank`（Field Bank 用的是 `diagnoses[].age_at_diagnosis`），`project.project_id` 35/35、`derived.*` 245/245 亦不在 bank。审计未因 `not_in_bank` 跳过任何字段。

### 偏差与原因

- **偏差 1（口径：计数单位）**：spec §5.2-2 字面写"有效值**数**"，实现按**患者数**（有 ≥1 个有效值的患者数）计数。理由：§2.1 把 leak_rate 定义为"该字段在 t0 时刻不可得的**患者**比例"，且 Field Bank 的缺失 mask 本身就是患者级（`generate_field_bank_prompt_row` 中 `valid = bool(valid_vals)`）。为避免二义，JSON 同时保留取值级计数 `n_values_none/n_values_t0`（本步不参与聚合），如需切换口径可零成本重算。
- **偏差 2（口径：derived.* 特判不可照字面执行）**：spec §5.2-4 括号称"现有 `extract_derived_raw_values` 已支持 landmark 参数"——该函数**只适用 4 个纵向变化字段**（ECOG/Karnofsky/BMI/weight change，需 `is_derived_field` 为真且 `landmark` 传 extract_state dict），对论文级 `derived.radiation_therapy` / `derived.pharmaceutical_therapy` / `derived.years_smoked` 一律返回 `[]`。故按该条**主句**（"landmark 作用于其底层槽位"）实现：用 `src/common/fields.py::field_gdc_path` 映射到底层槽位后审计槽位本身——治疗两字段 → `diagnoses[].treatments[].treatment_or_therapy`（family `diagnoses_treatments`，会 mask），`derived.years_smoked` → `exposures[].exposure_duration_years`（无时点家族）。无时点底层按构造声明 `mask_applicable=false`、leak_rate 恒 0（JSON 的 `audit_mode` 区分 `derived_slot` 与 `longitudinal_derived`，可事后识别）。
- **偏差 3（实现一致性发现，非错误）**：见"审计"节的负性治疗记录规则；使 derived 治疗字段 `leak_rate` 略偏高。未改现有实现。
- **偏差 4（`not_in_bank` 粒度）**：按字段路径与 `kept_fields.json` **精确匹配**，不做等价字段归并；`demographic.age_at_index` 与 bank 的 `diagnoses[].age_at_diagnosis` 语义相同但路径不同，故被标 `not_in_bank`——这正是"无依据"问题的原始形态，保留原样以便其他步骤引用。
- **偏差 5（MMRF）**：已按 §5.1 纳入审计（H1a 为描述性审计，不依赖 D2）；其 H3 用途仍待 D2 确认。MMRF 的 10 行已进汇总表（`n_event=191`）。

### 决策点

- 无新增、未改动决策表（D0–D5 状态保持原样；D1/D2 属 S3/S4 与 S1 的范围）。本步不依赖任何未决决策点，可直接被后续步骤引用。

### 状态

完成。H1a 全部产物就绪；结论可直接用于 H3b 主图的"泄露背景"与 H1b 的字段完整性讨论。

### 提交

`git add src/leak scripts/run_leak_audit.py tests/test_leak_audit.py results_display/leak_audit z_notes/H_series_execution_log.md` → "S2: H1a 泄露审计模块与全数据集审计结果"（其中 `results_display/leak_audit/scripts/audit_leak.py` 在 .gitignore 内，用 `git add -f` 单加；`results/**`、`results_display/**` 的 png/csv 产物不入库；未 push）。提交 hash：`git log -1 --format=%h`（见仓库历史）。

---

## S0 删除 E 系列结果文件

- 时间 / 执行者：2026-09-29 / Claude（主会话）
- 目标：按 D0（方案 B，用户确认）删除 E 系列结果文件与陈旧中间产物。
- 输入：D0 确认（方案 B）。
- 命令与参数：`rm -rf results/E2_selection results/univariate results/greedy results/linear_probe results_display/univariate results_display/greedy results_display/linear_probe "results_display/E1_Fig2_Single-field c-index" outputs/*/greedy outputs/*/univariate Clinic_Analyzer/results Clinic_Analyzer/configs/E2_selection Clinic_Analyzer/configs/greedy Clinic_Analyzer/configs/univariate`
- 产物：无（纯删除）。保留目录核对：results/{A_manual,H0_dataset_availability,leak_audit,README.md}、results_display/{FigA_Other_Paper_Works,leak_audit,README.md,scripts}、outputs/TCGA-BRCA/{A_manual,field_bank,longitudinal,schemes}、Clinic_Analyzer/configs/{A_manual,queue,running,done,failed,...}。
- 审计：删除前后 `df -h`：可用 1.1T → 1.3T（释放 ~200GB）；删除与保留清单与 D0 结论逐项一致。
- 偏差与原因：无。
- 决策点：D0 已确认并执行完毕。
- 状态：完成。
