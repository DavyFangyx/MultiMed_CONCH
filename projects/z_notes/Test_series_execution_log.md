# Test_ 系列执行日志

规格与口径唯一来源：`z_notes/Test_series_spec.md`。本文件是**所有执行报告的统一归档**，追加写，不另开文件；追加前先重读文件末尾。

## 决策点状态表

| ID | 决策点 | 状态 | 结论 |
|---|---|---|---|
| D0 | S0 删除范围（results/results_display 的 E1/E2/旧 greedy/univariate/linear_probe；是否连 outputs/*/greedy、outputs/*/univariate、Clinic_Analyzer/results 中间产物） | **已确认（方案 B）** | 删除：results/{E2_selection,univariate,greedy,linear_probe}、results_display/{univariate,greedy,linear_probe,E1_Fig2_Single-field c-index}、outputs/*/{greedy,univariate}（35 队列）、Clinic_Analyzer/results、Clinic_Analyzer/configs/{E2_selection,greedy,univariate}。保留：results/A_manual、results_display/FigA_Other_Paper_Works、outputs/*/{A_manual,field_bank}、rawdata_stats/。磁盘释放 ~200GB（1.1T→1.3T 可用）。 |
| D1 | Test_0 门槛与降级规则数值（照搬 event_impact_analysis 建议 vs 调整） | **已解决（2026-09-30，用户数据协议 A）** | 弃用无推导的 0.05 锚点。执行口径 = 用户数据协议 A（n_event 四档）：≥100 主图干净集；70–100 主图带 CI 不排名；30–70 补充材料 bootstrap CI；<30 不收录、单列低事件组定性讨论。适用于全部工作（含泛癌种）。B/C 存档不执行、D 不采用（R6）。 |
| D2 | landmark 有效事件口径（mask vs 排除患者）+ 数据集范围 | **已确认**（用户指令 2026-09-29） | **经典 landmark 三要件（Anderson 1983 / van Houwelingen）**：① 只保留 T 时刻仍在风险集内的患者（排除 `ground_truth_time ≤ T`）；② 时间原点平移到 T（`gt − T`，c-index 对其不变，仍实现以符合规范）；③ 协变量只用 T 前信息（现有 mask 已实现）。有效事件数 = `#{event==1 且 ground_truth_time > T}`。**数据集范围：仅 33 TCGA；TCGA 之外的外部数据集（CPTAC、MMRF 等）本阶段一律不纳入**，Test_4c 阶段再议。 |
| D3 | S3 自检（臂 A 与旧 A_manual 数值一致）通过后放量 | **已确认（2026-09-30）：放量，按三条硬条件执行** | ① 汇总 cindex 与旧表统一用同一 python 版本（本机默认 3.13.12），否则 `val_c_index_std` 末位 ULP 不同；② Test_1b 全程统一 label 源为 `Clinic_Analyzer/data/datasets_csv/metadata/`（两臂同源，Δc 不受影响；不回退旧源）；③ 一致性判据按模态区分：`clinic_cox` 逐位 diff = 0（✓ 已证），NN 模态用"同环境重跑逐位一致（det1 ✓）+ 换回旧 label 源可复现旧表（oldlabel 4/5 折逐位 ✓）"。**注意**：BRCA 单点 Δc（clinic_cox +0.0127 / mlp −0.0057）均落在折间 std（0.052–0.106）之内，须按 §4.2 规则 6 用 mask 后的有效事件数跨数据集聚合，且门槛数值待 U1（D1 的效应量先验）给出后再判定。 |
| D4 | Test_3 最优组合口径（sig_stop 推荐 vs 历史 best） | **已确认（R7）+ 修订（2026-10-04，用户确认）** | 贪婪用 gain-only δ=0.005 早停（2026-10-04 起：gain≥0.005 更新 k_star 且清零，gain<0.005 计数，连续 3 步停，k_sig=k−3；原 sig_stop 经 `--stop-mode sig` 保留）；另报历史 best；best 口径三臂表由用户自出 |
| D5 | 回推：数据集中途降级/剔除 | 待确认 | — |
| D6 | Test_5 三轴口径（HGCN 编码/模型、多模态子集、Q 修复路径） | **已确认（2026-10-03，三次修订）** | **HGCN 编码纳入 E 轴且先落地**（第三档，S11 只做编码侧：任意 scheme + landmark，pkl 格式不变，评估臂待模型接入后补跑）；**HGCN 模型不接入本轮**（用户移植的训练器为独立工作，M 轴不含）；多模态子集 = 15 主集 ∩ registry 5 集 = BRCA/COAD/KIRC/LIHC；Q = 先修复 Clinic_Analyzer 指标（对齐 SurvPGC `utils/survival_metrics.py`）再离线重算，双重验收 diff=0 |
| D7 | S10 Q 修复验收（在线 vs 离线 diff=0） | 待执行 | — |
| D8 | S11 HGCN L0-L5 等价性回归（等价→放行 / 不等价→冻结） | **已确认（2026-10-03）：等价→放行** | byte 级唯一差异 = summary.md 输出根路径行（构造性不可复现）；值级 96/96 全等 → 视为等价放行；既有 L0-L5 产物维持冻结不覆盖 |
| D9 | S13 Test_5 结论与 Test_4 三档表衔接 | 待执行 | — |

---

## S-1 准备：规格文档与执行日志

- 时间 / 执行者：2026-09-29 / Claude（主会话）
- 目标：建立 Test_ 系列单步执行框架：规格文档、步骤注册表、决策点清单、执行日志模板与 Git 提交协议。
- 输入：用户实验清单（Test_1–Test_4）、`project_overview.md`、`z_notes/E2_Selection_Gain_Algorithm/E2_selection_algorithm_design.md`、`rawdata_stats/_shared/event_impact_analysis/`。
- 命令与参数：无（纯文档）。
- 产物：`z_notes/Test_series_spec.md`、`z_notes/Test_series_execution_log.md`（本文件）。
- 审计：规格中锁定口径（定量泄露、控制变量、三档、Test_0 规则、Git 协议）与用户三轮反馈一致。
- 偏差与原因：无。
- 决策点：无新增；D0–D5 注册待确认。
- 状态：完成。

---

## S1 Test_0 可用数据集评估

- 时间 / 执行者：2026-09-29 / Claude（S1 执行 agent）
- 目标：(1) 只读调查 landmark 对生存终点与事件的处理方式（D2 事实基础）；(2) 实现 Test_0 可用数据集评估脚本与初版 manifest；(3) 不跑任何训练。
- 输入（文件路径 + 行数/条数/hash）：
  - `datasets.json`（177 行，35 队列 = 33 TCGA + CPTAC + MMRF，md5 `5918c06884bc`）
  - `rawdata_stats/_shared/event_summary.csv`（35 行 + 表头，md5 `e4fa8bfef99a`）
  - `rawdata_stats/{dataset}/event_stats.csv`（35 个，患者级 `submitter_id/event/ground_truth_time`）
  - `Clinic_Analyzer/data/splits/5foldcv/{study}/splits_*.csv`（35 个目录 × 5 折 = 175 个文件）
- 命令与参数：
  - `python3 scripts/run_Test_0_availability.py`（默认）；重跑一次 `--quiet` 做 diff 校验
  - `python3 -m pytest tests/test_0_availability.py -q`；`python3 -m pytest tests/ -q`
- 产物（路径 + 行数/条数）：
  - `results/Test_0_dataset_availability/manifest.csv`（36 行 = 表头 + 35 队列，md5 `55762283a740`）
  - `results/Test_0_dataset_availability/{dataset}_profile.json`（35 个）
  - `scripts/run_Test_0_availability.py`（533 行）、`tests/test_0_availability.py`（372 行）
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
   - 保留其余患者的**原 event 指示**（不重新定义终点；如需严格 re-baseline，时间轴改为 `gt-T`，但 c-index 对单调变换不变，故对 Test_1b/Test_2 无影响）。
2. **不推荐**沿用现状口径（只 mask）：该口径下 `effective_events_lmT ≡ n_event`，门槛重套退化为恒等，spec §4.2-6 失去意义；且 T 前已死亡患者仍带着"未来终点"留在训练/评估集里，是**终点侧的残留泄露**。

**口径差异的量级（候选数值已存 profile JSON，未写入 manifest）**——若采用严格口径，主集 12 个里 4 个会掉档：

| 队列 | n_event | lm365 | lm730 | 现状档 | 严格口径 lm730 档 |
|---|---|---|---|---|---|
| TCGA-BLCA | 182 | 101 | 36 | 主集 | 补充集 |
| TCGA-STAD | 175 | 78 | 23 | 主集 | 排除集 |
| MMRF | 191 | 118 | 47 | 主集 | 补充集 |
| TCGA-PAAD | 100 | 57 | 11 | 扩展集 | 排除集 |

（其余队列 lm0 与 n_event 基本相同：T=0 时严格口径只剔除 gt≤0 的极端个案，如 TCGA-ACC 34→33。）

### 任务 2：Test_0 脚本与初版 manifest

- 新代码：`scripts/run_Test_0_availability.py`（纯函数 `base_tier` / `classify_tier` / `degen_fold_indices` / `epv_field_budget` / `strict_landmark_events` 可单测；`run()` 端到端）。
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
| 测试 | `tests/test_0_availability.py` 20 passed；全量 `tests/` 123 passed, 6 skipped（无回归） |

### 偏差与原因

- **偏差 1（口径相关，非错误）**：spec §4.3 的 manifest 列含 `effective_events_lm*`，但 D2 未确认，故按任务要求**留空 + TODO**。候选数值（含"现状 mask-only ≡ n_event"与"严格排除 t≤T"两解）已写入每个 `{dataset}_profile.json` 的 `landmark.candidates`，供 D2 决策直接取用，无需重跑。
- **偏差 2（R7 定义细化）**：spec §4.2-7 原文为"c-index 精确 0.0/1.0"，但那需要训练结果；Test_0 不训练，故实现为**结构退化折**（折内 val 事件数 ≤1，其 c-index 必然只能取 0/1 或无定义）。该定义仅依赖 splits，可重复且不受 S0 删除结果文件影响。语义已写入 profile 的 `degen_fold_definition`。
- **偏差 3（R7 只标注未降级）**：spec §4.2-7 要求"标注并降级"，但降级动作依 §4.4 属 S8/D5 的逐项确认范围；本步只标注（`degen_folds` + `rule_hits` 含 `R7`），未改动 tier。已记入 D1 推荐意见。
- **偏差 4（R8 的粒度）**：R8 是 (dataset, scheme) 级约束（取决于方案字段数），Test_0 在数据集级无法判定命中；故只计算 `epv_field_budget` 并在预算为 0 时标 `R8`（此时任何多字段实验都不可行）。
- **偏差 5（命名）**：`datasets.json` 中该队列注册名为 `TCGA_LIHC`（下划线，其余为连字符），splits 目录为 `tcga_lihc`；脚本按统一规则转换，manifest 保留注册名原样，未做重命名。

### 决策点

- **D1** Test_0 门槛与降级规则数值 → **本步结论：照搬 spec §4.2 现值**（150/70/30、rate<0.1 降一级）；建议把 R7 由"仅标注"升级为"降级"。**待用户确认**（本步 manifest 的 tier 均标 `provisional`）。
- **D2** landmark 有效事件口径 + MMRF 是否纳入 → **本步结论（推荐）**：口径 = `mask（已实现）+ 排除 ground_truth_time ≤ T 的患者（S3/S4 需新增）+ 保留原 event 指示`，`effective_events_lmT = #{event==1 且 ground_truth_time > T}`；MMRF **纳入**。**待用户确认**。确认前：manifest 的 `effective_events_lm*` 保持留空，不推进 S3/S4。

### 状态

完成（本步产物就绪）；**S2 不受 D1/D2 阻塞可继续**（Test_1a 是纯描述性审计、全部数据集都做），但 **S3/S4 依赖 D2、S4/S6 选集依赖 D1，二者未确认前不推进**。

### 提交

`git add scripts/run_Test_0_availability.py tests/test_0_availability.py z_notes/Test_series_execution_log.md` → "S1: Test_0 可用数据集评估脚本与初版 manifest"（提交 hash 见日志末尾追加或 `git log -1`）。

---

## 口径变更 C1：默认 landmark_0；landmark_none 更名 static_only 移出主图

- 时间 / 执行者：2026-09-29 / Claude（主会话，用户指令）
- 目标：落实用户口径指令：后续实验的评估默认 landmark_0；现有 landmark_none（关 mask + R0 整层删 diagnoses/follow_ups）既非无处理也非规范处理，更名为 **static_only**，移出主图、仅进补充材料。
- 输入：用户指令（2026-09-29 会话内）。
- 命令与参数：无。
- 产物：`z_notes/Test_series_spec.md` §2.5 重写（两个概念澄清：取值 mask 状态 {off,0,365,730} vs field-bank 筛选变体 {landmark_0,365,730,static_only}）、§5.2 与 §8 相应措辞更新；本日志本条目。
- 审计：逐条核对影响面——S1 manifest（无影响，tier 与命名无关）；S2 Test_1a 审计（无影响：leak_rate 对比的是取值 mask off 与 t0，其"landmark_none 有效值"= 无 mask 取值全集，措辞已在 spec §5.2 澄清，无需重跑）；S3 A_pipeline `--landmark_time`（`none` = 无 mask 取值，与 static_only 概念不同，保留 none 值；S3 不受影响）；S5 生成 field-bank 变体时用新名 static_only（届时同步更名 rawdata_stats/{dataset}/landmark_none 目录）；Test_3b 主图改为 landmark_0 vs {365,730}，static_only 对照进补充。
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
- 审计：S1 的 D2 推荐与本指令一致；S1 的 strict_landmark_exclude_le_T 候选数值可直接采用，无需重跑。S2（Test_1a 审计）不受影响（leak_rate 是值级对比）。S3 受影响：实现范围从"仅 mask"扩大为三要件。
- 偏差与原因：无。
- 决策点：D2 口径部分已确认；D2 的 MMRF 是否纳入仍待用户确认。
- 状态：完成。

---

## S2 Test_1a 泄露审计

- 时间 / 执行者：2026-09-29 / Claude（S2 执行 agent）
- 目标：(1) 实现 Test_1a 泄露审计模块（**无训练**，纯描述性统计）：对 `datasets.json` 全部注册队列 × 10 个论文方案，逐字段量化 `leak_rate(f,D) = 1 − n_valid_t0 / n_valid_none`（= t0 时刻该字段不可得的比例）；(2) 产出 `results/leak_audit` 明细 + 汇总与 `results_display/leak_audit` 两张图；(3) 抽查 ≥3 个 (dataset, scheme, field) 与手工 JSON 核对（本步实际做 4 个）；(4) 不跑训练、不改 `src/` 其他模块与 `A_pipeline`。
- 输入（路径 + 条数/hash）：
  - `z_notes/Test_series_spec.md` §2.1/§2.4/§2.5/§5（口径唯一来源；C1 更名 static_only 后 §5.2 措辞已澄清，本步审计对象不变）
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

**抽查（规格要求 3 组，本步做 4 组）**：独立重算脚本只读原始 clinic JSON，逐患者手写 mask 规则（t_hi = ≥t_lo 的最早随访日，否则回退 TH2 = max(末次随访日, 末次疾病状态日, 复发日, 已定位事件日)；keep iff 状态非 unlocated/non_informative 且有限 t_hi ≤ 0）：

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
- **偏差 5（MMRF）**：已按 §5.1 纳入审计（Test_1a 为描述性审计，不依赖 D2）；其 Test_3 用途仍待 D2 确认。MMRF 的 10 行已进汇总表（`n_event=191`）。

### 决策点

- 无新增、未改动决策表（D0–D5 状态保持原样；D1/D2 属 S3/S4 与 S1 的范围）。本步不依赖任何未决决策点，可直接被后续步骤引用。

### 状态

完成。Test_1a 全部产物就绪；结论可直接用于 Test_3b 主图的"泄露背景"与 Test_1b 的字段完整性讨论。

### 提交

`git add src/leak scripts/run_leak_audit.py tests/test_leak_audit.py results_display/leak_audit z_notes/Test_series_execution_log.md` → "S2: Test_1a 泄露审计模块与全数据集审计结果"（其中 `results_display/leak_audit/scripts/audit_leak.py` 在 .gitignore 内，用 `git add -f` 单加；`results/**`、`results_display/**` 的 png/csv 产物不入库；未 push）。提交 hash：`git log -1 --format=%h`（见仓库历史）。

---

## S0 删除 E 系列结果文件

- 时间 / 执行者：2026-09-29 / Claude（主会话）
- 目标：按 D0（方案 B，用户确认）删除 E 系列结果文件与陈旧中间产物。
- 输入：D0 确认（方案 B）。
- 命令与参数：`rm -rf results/E2_selection results/univariate results/greedy results/linear_probe results_display/univariate results_display/greedy results_display/linear_probe "results_display/E1_Fig2_Single-field c-index" outputs/*/greedy outputs/*/univariate Clinic_Analyzer/results Clinic_Analyzer/configs/E2_selection Clinic_Analyzer/configs/greedy Clinic_Analyzer/configs/univariate`
- 产物：无（纯删除）。保留目录核对：results/{A_manual,Test_0_dataset_availability,leak_audit,README.md}、results_display/{FigA_Other_Paper_Works,leak_audit,README.md,scripts}、outputs/TCGA-BRCA/{A_manual,field_bank,longitudinal,schemes}、Clinic_Analyzer/configs/{A_manual,queue,running,done,failed,...}。
- 审计：删除前后 `df -h`：可用 1.1T → 1.3T（释放 ~200GB）；删除与保留清单与 D0 结论逐项一致。
- 偏差与原因：无。
- 决策点：D0 已确认并执行完毕。
- 状态：完成。

---

## 流程纠正 P1：范围越界与提前执行

- 时间 / 执行者：2026-09-29 / Claude（主会话，用户纠正）
- 事实与原因：① S1/S2 把 MMRF（及 CPTAC）纳入 Test_0 manifest 与 Test_1a 审计，并把"MMRF 是否纳入"作为决策点抛给用户——外部数据集从未出现在用户实验清单中，属**擅自扩大范围**；② 用户说"照搬现值 + R7 升级为降级"本意是**先展开说明情况**，主会话却直接派 agent 执行 D1 落地——**未确认即执行**。
- 纠正动作：D1 落地 agent 已终止；其未提交改动已回退（`git checkout` 两个 Test_0 文件）；manifest/profile 已用 S1 版脚本重生成恢复（md5 `55762283a740` 与 S1 记录一致）。
- 新口径（已写入 spec §2.4、§3）：本阶段数据集 = **仅 33 TCGA**；CPTAC / MMRF 等 TCGA 外数据集暂不纳入（Test_4c 阶段再议）；**未在用户实验清单中明确的事项，执行前必须先向用户报告并获确认**。
- 决策点：D1 仍待确认（用户听完展开说明后决定）；D2 数据集范围部分已确认（33 TCGA）。
- 状态：完成。

---

## S3 A_pipeline landmark 扩展与冒烟自检

- 时间 / 执行者：2026-09-29 ~ 09-30 / Claude（S3 执行 agent）
- 目标：(1) 给 A_pipeline 加 `--landmark_time {0,365,730,none}`，按 spec §2.5 / §6.1 实现经典 landmark 三要件；(2) 覆盖 `pipeline / json2prompt / encode / baseline / cindex`，默认 `none` 保持零行为变化；(3) BRCA × MULTISURV 冒烟自检（臂 A vs 旧 `results/A_manual/TCGA-BRCA[gdc]/cindex.csv`），为 D3 提供事实依据。
- 输入（文件路径）：
  - `z_notes/Test_series_spec.md`（§2.5 三要件、§6.1 实现点、§6.3 自检）、`A_pipeline/README.md`
  - 复用：`src/discovery/landmark.py::patient_landmark`（经 `A_pipeline/src/__init__.py` 的 sys.path 接入）、`src/time_stats.py::extract_patient_time_record`（槽位 `t_hi`）
  - 标签/划分：`Clinic_Analyzer/data/datasets_csv/metadata/tcga_brca.csv`（1051 行）、`Clinic_Analyzer/data/splits/5foldcv/tcga_brca/splits_*.csv`
- 命令与参数（示例，完整链路）：
  - `python A_pipeline/run.py json2prompt --dataset TCGA-BRCA --scheme MULTISURV --landmark_time 0`
  - `python A_pipeline/run.py encode --dataset TCGA-BRCA --scheme MULTISURV --landmark_time 0`
  - `python A_pipeline/run.py cindex --dataset TCGA-BRCA --scheme MULTISURV --landmark_time 0 --analyzer clinic_cox,mlp_clinic_mean`（走现有 A_manual 队列调度）
  - 平移不变性自检：同参数加 `--landmark_shift off`（生成 `__noshift` 变体）
  - 测试：`python -m pytest A_pipeline/tests -q` → 44 passed（其中 `tests/test_landmark_time.py` 25 个）

### 实现（file:line）

| 要件 | 位置 | 说明 |
|---|---|---|
| ① 协变量 mask（`t_hi ≤ T`） | `A_pipeline/src/landmark.py:187` `mask_case()`（timed 家族 `:31`、槽位索引 `:131`、保值规则 `:146`）；调用点 `A_pipeline/src/extract.py:103` | timed family 槽位只保留 `t_hi ≤ T` 的取值，其余按现有缺失规则处理；无时点家族不 mask；`landmark_time=None` 原样返回（默认路径零变化） |
| ② 风险集（排除 `gt ≤ T`） | `A_pipeline/src/landmark_labels.py:110-111`（`excluded_mask = gt_days <= T`）、`:131-132`（排除患者清单）、`:149-151`（统计入 sidecar） | 以"派生 label 文件"实现：被排除患者不在 label 文件中，`SurvivalDatasetFactory` 的 `label ∩ split` 交集自然把该患者从每折移除；**split 文件未改动** |
| ③ 时间原点平移（`gt − T`） | `A_pipeline/src/landmark_labels.py:114-116`（`shift_months = T/30.4375`，`kept[time_col] -= shift_months`）、`:142` | 平移后 label 落 `results/A_manual_landmark/labels/{study}__landmark_{T}.csv` + `.json` sidecar（rows/events/cases 前后、excluded_cases、shift_months）；`--landmark_shift off` 生成 `__noshift`（仅自检用） |
| 参数与透传 | `A_pipeline/src/cli.py:105-113`（`--landmark_time`）、`:114-122`（`--landmark_shift`）、`:151-155`（解析 + `hgcn_clinic` 拒绝）、`:203`、`:257-270`、`:299-330` | 默认 `none`：目录、run_name、conf 与旧链路逐字一致 |
| 产物路由 | `A_pipeline/src/landmark.py:57/75/82/125`（subdir / arm tag）；`A_pipeline/src/cindex.py:35-36`（`A_manual_landmark/runs`）、`:92`、`:110-117`、`:129-136`（run_name `{scheme}__landmark_{T}`）、`:224`、`:231-262`（conf 追加 `LABEL_FILE_PATH=`）、`:369-489`（`iter_cindex_jobs` / `_landmark_label_file`）、`:747+`（`run_cindex_queue`） | 编码产物落 `outputs/{dataset}/A_manual/{scheme}/landmark_{T}/`；cindex 产物只落 `results/A_manual_landmark/`。旧 `results/A_manual/` 未被写（`TCGA-BRCA[gdc]/cindex.csv` mtime 仍 2026-09-07 23:59） |
| 测试 | `A_pipeline/tests/test_landmark_time.py`（25 用例） | 构造小病例，覆盖 mask 只动 timed 槽、`none` 与旧实现逐值等价、目录/run_name/conf 路由、风险集与平移、`__noshift`、CLI 校验；不跑真实编码 |

### 冒烟自检（BRCA × MULTISURV，spec §6.3）

| 检查项 | 结果 |
|---|---|
| 臂 A `clinic_cox` vs 旧表 | **diff = 0**：`0.5056892222943474` / std `0.0646250202971734`，5 折 `val_cindex` 逐位一致 |
| 臂 A `mlp_clinic_mean` vs 旧表 | 首次 diff = **−0.0035722**（`0.6530100705066605` vs `0.6565822450248358`）→ 归因见下（label 源 + FP），非实现问题 |
| 编码复现 | 新链路重生成的 prompts 编码 1098/1098 `.pt` 与旧 `outputs/TCGA-BRCA/A_manual/MULTISURV/embeddings/pt` **逐位一致**（(10,512)，max_abs_diff = 0.0） |
| 字段集一致性（臂 A vs 臂 B） | 11 列同名同序、1098 患者同序；变化单元格只在 2 个 derived 治疗列（BRCA：pharmaceutical 173 / radiation 127）；LUAD 交叉验证只在 4 个诊断列（各 19）+ 2 个治疗列（123/124） |
| 时间平移不变性（T=365，shift on vs off） | 5 折逐位一致：mean `0.4849119865610933`，max delta = 0.0（`MULTISURV__landmark_365` vs `...__noshift`） |
| 风险集排除（T=0） | **`tcga_acc` 92→91（事件 34→33）**，与用户预期一致；`tcga_brca` 1051→1030（事件 146→144，排除 21 例）；35 个 label 文件排除 0–50 例。T=365：BRCA 876/事件 125（排除 175）；T=730：576/105 |
| Δc（BRCA × MULTISURV，同字段集、唯一差异 = landmark mask） | `clinic_cox`：**+0.0127481**（0.5056892222943474 − 0.49294108776358436；折间 std 0.0646 / 0.0519）；`mlp_clinic_mean`：**−0.0056904**（0.6530100705066605 − 0.6587004760401869；折间 std 0.0955 / 0.1058） |

### `mlp_clinic_mean` 首次 diff ≠ 0 的归因（两个诊断 run，非正式产物）

产物：`results/A_manual_landmark/runs/tcga_brca__MULTISURV__landmark_none__det1/`、`.../__landmark_none__oldlabel/`（日志 `/tmp/Test_1b_smoke/{det1,oldlabel}.log`）

| 探针 | 设置 | 结果 |
|---|---|---|
| `det1` | 与臂 A 完全同参重跑（同 label 源） | 5 折 `val_cindex` 与臂 A **逐位一致** → 同环境下分析器逐位可复现 |
| `oldlabel` | 同新链路，仅 `--label_file` 换回旧 run 所用的 SurvPGC 副本 | 第 0–3 折与旧表**逐位一致**；第 4 折 `0.7018519` vs 旧表 `0.6988889` |

- **主因：label 源差异**。旧 A_manual 共 625 个 run，其中 355 个（9 个 study：brca/coad/kich/kirc/kirp/lihc/prad/read/stad）的 `LABEL_FILE` 指向 `SurvPGC_github_init/datasets_csv/metadata/{study}.csv`，另 270 个（24 study）指向 `Clinic_Analyzer/...`；`Clinic_Analyzer/configs/defaults.conf:29` 的现行口径是**优先 Clinic_Analyzer**（该目录覆盖全部 35 队列，SurvPGC 仅 13 个），故新链路对所有 study 统一用 Clinic_Analyzer。两副本对共同 1051 例的 `survival_months`/`censorship` **逐位相同**，差异只在行序与 `slide_id` 命名；`_get_split_from_df` 按 label 行序构造数据集、`RandomSampler` 按固定 seed 打乱索引 → 同 seed 下批组成不同 → NN 权重不同（`clinic_cox` 闭式求解、对样本顺序不敏感，故仍逐位一致）。量化：换回旧 label 源后，臂 A 值 `0.6530101` → `0.6571748`（**+0.0041648**）。
- **次因：跨环境 FP 差异**。`oldlabel` 与 2026-09-06 旧 run 的全部 60 个 epoch 的 `val_loss` 都只在第 8–10 位有效数字上不同（fold0 epoch0：`0.4097603142031985` vs `0.40976031603936053`，随训练放大到 ~1e-4）；`val_cindex` 是排序统计量，第 0–3 折 60/60 个 epoch 完全一致，第 4 折 8/12 个 epoch 出现翻转 → 3 周前与现在的环境不保证 NN 逐位复现，残余 **−0.0005926**。
- 判据结论：`clinic_cox` 用"逐位 diff = 0"硬判据（✓）；NN 模态用等价判据"同环境重跑逐位一致（det1 ✓）+ 换回旧 label 源可复现旧表（4/5 折逐位 ✓）"。**旧表在 9 个 SurvPGC 时代 study 上的 NN 数值不可由新链路默认口径逐位复现**，属 label 源升级的既有事实，与 landmark 实现无关；Test_1b 两臂同源同环境，Δc 不受影响。

### 偏差与原因

- **偏差 1（python 版本影响汇总列末位）**：`val_c_index_std` 由汇总脚本计算，CPython ≥3.12 的 `sum()` 用 Neumaier 补偿求和、3.9 用朴素求和 → 同一批 `val_result_fold*.csv` 在 3.13/3.9 下末位 ULP 不同（`...01734` vs `...17339`）。处理：删掉自己刚写的 summary，用**默认 python 3.13.12** 重新汇总 → 与旧表逐位一致。**规则**：Test_1b 全程用同一 python 版本汇总。
- **偏差 2（误覆盖旧 prompts.csv，功能等价修复）**：09-29 23:33 单 JSON / 整目录两种用法混用时，曾把 `outputs/TCGA-BRCA/A_manual/MULTISURV/prompts.csv` 覆盖为按新链路生成的版本；事后用该文件重跑 `encode`，产出的 1098 个 `.pt` 与旧 `embeddings/pt` 逐位一致（max_abs_diff = 0.0），即**内容功能等价**，仅该文件 mtime 变化；`embeddings/`、`results/A_manual/` 均未被触碰。
- **偏差 3（治疗字段语义，供 Test_1b 解读）**：A_pipeline 的 `_therapy_flag`（`A_pipeline/src/extract.py:47`）只把 `treatment_type == "pharmaceutical therapy, nos" / "radiation therapy, nos"` 计入 yes/no，其余落 unknown，故 mask 后 BRCA 治疗两列变化 173/127 例；Test_1a 审计把整个 treatment 槽位（含全部治疗条目）计入（1094→26，leak 0.976）。两者口径不同，比较 `leak_rate` 与 `Δc` 时需注意。
- **偏差 4（工作区遗留改动随提交带入，非本步内容）**：`A_pipeline/src/cli.py` 的 cindex 参数 `--modality` → `--analyzer` 及 `A_pipeline/src/hgcn_clinic.py` 的共享词表改动是**本步之前**的工作区遗留 diff，我的 landmark 改动与其相邻，本步提交（按指令 `git add A_pipeline/src A_pipeline/tests`）会一并带入，特此标注。

### 决策点

- **D3 更新为：待确认（自检通过，附条件）**，推荐 **放量（S4）**，三条硬条件：① 汇总 cindex 与旧表统一用同一 python 版本（本机默认 3.13.12）；② Test_1b 全程统一 label 源为 `Clinic_Analyzer/data/datasets_csv/metadata/`（两臂同源，Δc 不受影响；不必回退旧源）；③ 一致性判据按模态区分（clinic_cox 逐位 diff=0；NN 用"同环境重跑逐位一致 + 换回旧源可复现"）。另：单点 Δc（clinic_cox +0.0127 / mlp −0.0057）均落在折间 std（0.052–0.106）之内，**必须按 §4.2 规则 6 用 mask 后的有效事件数聚合**后再判定，不可由单点下结论。
- 其余决策点（D0/D1/D2/D4/D5）状态不变。

### 状态

完成（自检通过：clinic_cox 逐位 diff = 0；mlp 差异已定位到 label 源 + 跨环境 FP，并用探针证明新链路忠实）。S4 放量待 D3 确认；确认前不放大批量。

### 提交

`git add A_pipeline/src A_pipeline/tests z_notes/Test_series_execution_log.md` → "S3: A_pipeline --landmark_time 扩展与冒烟自检"（未 push；未用 `git add -A`）。

---

## 口径记录 R1：D1 锚点未解决 + 方案×数据集绑定

- 时间 / 执行者：2026-09-30 / Claude（主会话，用户决议）
- 目标：落实用户两项决议并登记未解决问题。
- 内容：
  1. **D1（U1）**："0.05 有意义差异"无推导出处，不作门槛依据。D1 改由**用户给出效应量先验**（Test_1b/Test_2 的 Δc 至少要分辨到什么量级）反推每折事件数门槛；先验未给出前 manifest tier 保持 provisional、训练选集不做硬门槛（spec §12 U1）。
  2. **绑定**：HGCN_* 六方案各绑定对应癌种（KIRC/LIHC/ESCA/LUSC/LUAD/UCEC），禁止塞进其他数据集（spec §2.4）；泛癌种四方案（MULTISURV/SURVPGC/MMSURV/INTEGRATIVE_DNN）暂按全部 33 TCGA，记未解决问题 U2（spec §12）。
  3. 同步更新 spec §5.1 审计范围：33 TCGA × §2.4 绑定；CPTAC/MMRF 描述性记录保留磁盘但不进汇总。
- 待办（**未执行**，待用户确认）：S2 审计按新绑定重跑（HGCN_* 仅各自癌种 + 泛癌种 × 33 TCGA，剔除 CPTAC/MMRF 记录与无绑定组合）；A_manual 旧结果中无绑定的行不进任何表。
- 决策点：D1 → 未解决（U1）；无新决策点。
- 状态：完成（仅记录）。

---

## 口径记录 R2：用户数据协议（n_event 判据，部分）

- 时间 / 执行者：2026-09-30 / Claude（主会话，用户指令）
- 目标：记录用户给出的 Test_ 系列数据协议片段。
- 内容（用户 2026-09-30 粘贴）：

  | 判据 | 作用 | 规则 |
  |---|---|---|
  | n_event | 评估方差下限 | 主图 ≥100；30–70 补充材料；<30 排除 |

  适用于当前 Test_ 系列全部 TCGA 使用，泛癌种（通用字段）工作同样适用。
- 对 33 TCGA 的映射（按现有 event_summary）：≥100 → **15 个**（PAAD(100)、COAD(102)、LGG(126)、LIHC(132)、LAML(133)、BRCA(152)、STAD(175)、KIRC(177)、BLCA(182)、LUAD(188)、LUSC(220)、SKCM(223)、HNSC(224)、OV(349)、GBM(492)）；70–100 → **5 个**（CESC(72)、MESO(74)、ESCA(77)、UCEC(91)、SARC(99)）——**协议未覆盖此区间，待用户补**；30–70 → 4 个（UVM(33)、ACC(34)、UCS(35)、KIRP(44)）；<30 → 9 个（READ、CHOL、THCA、KICH、PRAD、DLBC、THYM、TGCT、PCPG）。
- 待补（已写入 spec §12 U1）：70–100 区间的处理规则；协议表是否还有其余判据行（event_rate / EPV / 退化折 / landmark 有效事件重套等）。
- 状态：完成（仅记录；Test_0 脚本未改，等协议补全后统一落地）。

---

## S2b Test_1a 审计按新绑定重跑

- 时间 / 执行者：2026-09-30 / Claude（S2b 执行 agent）
- 目标：(1) 把 `src/leak/` 的范围从「35 队列 × 10 方案全交叉」改为 **spec §2.4 绑定**——HGCN_* 六方案只跑各自癌种、泛癌种四方案 × 33 TCGA、CPTAC/MMRF 完全剔除（用户决议见本日志 R1）；(2) 删除旧产物（含 212 个越界/错误组合）并按新范围重算；(3) 抽查 2 组以上与手工 JSON 重算核对；(4) 重生成汇总与两张图；(5) 补绑定回归测试。全程无训练。
- 输入（路径 + 条数/hash）：
  - `z_notes/Test_series_spec.md` §2.4（方案×数据集绑定）、§5.1（审计范围）、§12 U2
  - `datasets.json`（35 队列 = 33 TCGA + CPTAC + MMRF，md5 `5918c06884bc`）
  - `A_pipeline/templates/{scheme}/fields.json`（10 方案字段表；**其 `datasets` 键是旧的全绑定，本步不读**）
  - 旧产物快照：`results/leak_audit/leak_audit_summary.csv`（350 行，md5 `cc7ece230a05`）→ 备份 `/tmp/leak_audit_summary_S2_old.csv`；旧 `results_display/leak_audit/leak_audit_{scheme,field}_mean.csv` → `/tmp/old_*.csv`
  - 实现参考（只读）：`src/discovery/field_bank.py::extract_field_bank_raw_values`、`src/discovery/landmark.py`、`src/time_stats.py::_collect_entity_slots`、`src/common/fields.py::get_primary_diagnosis`
- 命令与参数：
  - `python3 scripts/run_leak_audit.py --prune`（默认 `--binding spec`、`--landmark_time 0`；首跑 4.4 s，exit 0，prune 删 214 项）
  - 可重复性：同命令加 `--quiet` 重跑（第二次 prune 无删除项），`leak_audit_summary.csv` **两次 md5 均为 `b5de75584e9a1449bfca9d188e827cd6`**（diff = 0）
  - 抽查：`python3 /tmp/verify_leak_spotcheck_s2b.py`（只读原始 clinic JSON、**不 import `src/leak`**，按 `rawdata_stats/TIME_CRITERIA.md` 手写 mask 规则）
  - 出图：`python3 results_display/leak_audit/scripts/audit_leak.py`
  - 测试：`python3 -m pytest tests/test_leak_audit.py -q` → **17 passed**；`python3 -m pytest tests/ -q` → **140 passed, 6 skipped**（无回归）

### 1. 新范围实现位置

| 内容 | 位置 | 说明 |
|---|---|---|
| 绑定常量 | `src/leak/audit.py:TCGA_PREFIX` / `EXCLUDED_DATASETS=("CPTAC","MMRF")` / `HGCN_DATASET_BY_SCHEME`（六方案→癌种，`HGCN_LIHC→TCGA_LIHC` **下划线注册名**）/ `PAN_CANCER_SCHEMES`（四方案）/ `BINDING_SPEC|BINDING_ALL` | 绑定在代码内声明；**不读** `A_pipeline/templates/{scheme}/fields.json` 的 `datasets` 键（旧全绑定，已作废） |
| 绑定解析 | `tcga_dataset_names()`（注册表按 TCGA 前缀过滤 + 剔除集，**不硬编码 33 个名字**）、`scheme_dataset_binding()`（HGCN 绑定队列未注册或被剔除 → **直接 ValueError，不静默降级**；未登记方案按泛癌种但 kind 标 `pan_cancer_default`） | spec §2.4 |
| 执行计划 | `build_audit_plan()` / `plan_datasets()` / `plan_schemes()`；`run_audit(..., binding=, prune=)` 只对计划内数据集加载病例与方案字段 | `binding=all` 仅放宽方案绑定（ad-hoc 方案用），**两种模式都剔除 CPTAC/MMRF** |
| 落库元数据 | payload 新增 `scheme_binding`（`hgcn_cancer`/`pan_cancer`/`pan_cancer_default`）与 `binding_datasets`（该方案被允许的队列） | 供下游/出图脚本直接读，不再重复硬编码范围 |
| 旧产物清理 | `prune_stale_outputs()` + CLI `--prune`：删计划外的 `{dataset}/{scheme}.json` 与因此空掉的目录 | 只动本模块自己写的两层 JSON，不碰汇总表 |
| CLI | `src/leak/cli.py`：`--binding {spec,all}`（默认 spec）、`--prune`；完成行报「N 个绑定组合」 | |
| 出图脚本 | `results_display/leak_audit/scripts/audit_leak.py::load_bindings()` 从产物读绑定（缺字段时回退 §2.4 静态表）；标题/图例动态化；热图对「未绑定」格打 ×（区别于「方案不含此字段」的灰格） | 原 35 队列写死文案已改 |

### 2. 新范围清单与计数核对

| 方案 | 绑定 | 队列数 |
|---|---|---|
| MULTISURV / SURVPGC / MMSURV / INTEGRATIVE_DNN | 全部 33 TCGA（U2 未解决） | 33 × 4 |
| HGCN_KIRC / HGCN_LIHC / HGCN_ESCA / HGCN_LUSC / HGCN_LUAD / HGCN_UCEC | 各自癌种 `TCGA-KIRC` / `TCGA_LIHC` / `TCGA-ESCA` / `TCGA-LUSC` / `TCGA-LUAD` / `TCGA-UCEC` | 1 × 6 |

| 自检项 | 实际结果 |
|---|---|
| 组合数 = 4×33 + 6 = **138** | ✓ `build_audit_plan` = 138（去重后仍 138）；`run_audit` 报「33 个数据集 / 10 个方案 → 138 个绑定组合」 |
| 明细 JSON 数 | ✓ 138（`results/leak_audit/*/*.json`），旧 350 → 新 138，**删除 212（= HGCN 跨癌种 192 + CPTAC/MMRF 20）、新增 0** |
| 目录数/范围 | ✓ 33 个，全部 `TCGA-` 前缀；无 `CPTAC`、`MMRF` 目录 |
| HGCN 跨癌种文件 | ✓ 0（逐文件核对 `HGCN_DATASET_BY_SCHEME[scheme] == dataset`） |
| 每数据集方案集合 | ✓ 27 个队列 4 方案、6 个癌种队列 5 方案（= 4 泛癌种 + 本癌种 HGCN） |
| 汇总表 | ✓ 138 行 + 表头；无 CPTAC/MMRF 行 |
| 34 数据集集口径 | 注册表 TCGA 行集合与 `results/Test_0_dataset_availability/manifest.csv` 的 TCGA 行**完全一致**（33/33） |
| 数值口径未变 | ✓ **共享的 138 个组合，逐组合 `leaky_ratio`/`n_leaky`/`mean_leak_rate` 与旧表 100% 相同**（旧运行里这些组合的数值原样保留，差异只来自范围） |

### 3. 抽查（独立重算，只读原始 clinic JSON，不 import `src/leak`）

`python3 /tmp/verify_leak_spotcheck_s2b.py` → **ALL MATCH: True**（5/5）

| dataset × scheme × field | 审计 none→t0 (rate) | 独立重算 none→t0 | 结论 |
|---|---|---|---|
| **TCGA-LUSC × HGCN_LUSC × `derived.radiation_therapy`**（HGCN 绑定组） | 421 → 40 (0.9050) | 421 → 40 | 一致 |
| TCGA-LUSC × HGCN_LUSC × `exposures[].pack_years_smoked` | 427 → 427 (0.0000) | 427 → 427 | 一致（exposures 无时点家族，mask 不作用） |
| TCGA-UCEC × HGCN_UCEC × `derived.pharmaceutical_therapy` | 548 → 19 (0.9653) | 548 → 19 | 一致 |
| **TCGA-KIRP × SURVPGC × `diagnoses[].ajcc_pathologic_stage`**（泛癌种组） | 261 → 238 (0.0881) | 261 → 238 | 一致 |
| TCGA_LIHC × MULTISURV × `diagnoses[].ajcc_pathologic_stage`（泛癌种组，下划线注册名） | 354 → 353 (0.0028) | 354 → 353 | 一致 |

其中 TCGA-LUSC 的 `pack_years_smoked`（427→427）与 TCGA-KIRP 的 `stage`（261→238）与 S2 原始抽查的记录值**逐位相同**，说明共享组合没被重跑改变。

**独立重算脚本在 S2 版基础上修了两处（只影响重算脚本，审计实现未改）**——两处都是本次才暴露的实现细节：

1. **治疗的定点规则**：`time_stats._collect_entity_slots` 对两类记录给定点区间 `(0, 0)`（因此 t0 恒通过）——① 既往原发诊断 + 患者 `prior_malignancy=yes` 下的治疗；② `timepoint_category = Prior to Diagnosis` 且父诊断 `prior_treatment=yes`。**普通治疗没有 `t_lo==0` 的捷径**（`start=0` 的记录 t_hi 仍走 TH1b/TH2，如 TCGA-66-2759 `Radiation, External Beam` start=end=0、随访 762 天 → t0 不通过）。S2 版脚本把 `t_lo==0` 一律当通过，LUSC 上因此偏 39 人（多算通过）。
2. **`diagnoses[]` 叶子字段的主诊断规则**：`field_bank._valid_raw_values` 只在**主诊断带该键时**取主诊断的值，否则回落到任意诊断的取值。TCGA-ZP-A9D1（主诊断缺 `ajcc_pathologic_stage`、既往原发诊断是 `Stage I`）即此型；S2 版脚本只查主诊断，TCGA_LIHC 上偏 1 人。

两条规则补进重算脚本后 5/5 完全一致；审计侧数字**一次都没有改**（本步未修改任何提取/mask 实现）。S2 记录的「负性治疗记录不建槽位」规则依旧成立（`treatment_or_therapy=no` 的记录 mask 臂看不到、无 mask 臂仍计入）。

### 4. 新老结果差异

**(a) 方案级（跨队列平均 leaky_ratio，降序；HGCN 为单队列值，泛癌种为 33 队列均值）**

| 方案 | 旧 mean（35 队列） | 新 mean | 新 n | 新绑定 | 变化原因 |
|---|---|---|---|---|---|
| HGCN_UCEC | 0.467 | **0.667** | 1 | TCGA-UCEC | 变 = 旧运行里 TCGA-UCEC 单队列值（0.667） |
| HGCN_LUAD | 0.407 | **0.625** | 1 | TCGA-LUAD | 旧本癌种值 0.625 |
| HGCN_LUSC | 0.314 | **0.444** | 1 | TCGA-LUSC | 旧本癌种值 0.444 |
| MULTISURV | 0.343 | 0.352 | 33 | 33 TCGA | 剔 CPTAC/MMRF（旧值 0.20/0.20）后略升 |
| HGCN_LIHC | 0.329 | 0.333 | 1 | TCGA_LIHC | 旧本癌种值 0.333 |
| MMSURV | 0.263 | 0.261 | 33 | 33 TCGA | 剔 CPTAC/MMRF（0.60/0.00）后略降 |
| HGCN_KIRC | 0.296 | 0.250 | 1 | TCGA-KIRC | 旧本癌种值 0.250 |
| SURVPGC | 0.200 | 0.192 | 33 | 33 TCGA | 剔 CPTAC/MMRF（0.50/0.167）后略降 |
| HGCN_ESCA | 0.299 | 0.182 | 1 | TCGA-ESCA | 旧本癌种值 0.182 |
| INTEGRATIVE_DNN | 0.114 | 0.111 | 33 | 33 TCGA | 剔 CPTAC/MMRF（0.333/0.000）后略降 |

- **HGCN 六方案的数值一字未改**（= 各自癌种队列上的旧值），变的只是口径：旧排名里 HGCN 的位次是「拿六个数各平均 35 个癌种」得来的，**本无意义**（同一方案被塞进 32 个非本文队列）；新口径下 HGCN 只报自己癌种，与泛癌种方案的「33 队列均值」**不可直接横向比较**（n=1 vs n=33），跨工作排名须并列 n 与队列名。
- **泛癌种四方案**：剔除 CPTAC/MMRF 后均值变化都在 ±0.01 内（CPTAC/MMRF 的旧值见上表），排名不变（MULTISURV > MMSURV > SURVPGC > INTEGRATIVE_DNN）。
- 新口径下的跨工作排名（仅列位次，不代表同尺度）：**HGCN_UCEC 0.667 > HGCN_LUAD 0.625 > HGCN_LUSC 0.444 > MULTISURV 0.352 > HGCN_LIHC 0.333 > MMSURV 0.261 > HGCN_KIRC 0.250 > SURVPGC 0.192 > HGCN_ESCA 0.182 > INTEGRATIVE_DNN 0.111**。

**(b) 队列级（33 队列 × 绑定方案的平均 leaky_ratio）**：最高 TCGA-UCEC 0.54 > TCGA-LUAD 0.532 > STAD/SKCM/PRAD 0.508；最低 BRCA/CHOL/DLBC/LAML/MESO 0.05。与 S2 的结论方向一致（HGCN 有绑定方案的癌种被抬升）。

**(c) 字段级（跨队列平均 leak_rate，前 7）**：`derived.pharmaceutical_therapy` 与 `derived.radiation_therapy` 仍并列第一 **0.935**（旧 0.939；39/39 记录里都 >0 且都 `not_in_bank`）> `ajcc_pathologic_m` 0.077（旧 0.107）> `_t` 0.060 > `_n` 0.058 > `ajcc_staging_system_edition` 0.050 > `ajcc_pathologic_stage` 0.037（旧 0.071）。**诊断分期族的均值普遍下降**，原因是分母从 35 队列变为 33（并把 6 个癌种队列里 HGCN 只算本癌种），`morphology` 与 `site_of_resection_or_biopsy` 的可见记录数 105 → 3、`primary_diagnosis` 105 → 35（前者只被 HGCN_ESCA/LUSC/LUAD 用，后者还被泛癌种 SURVPGC + HGCN_ESCA/UCEC 用——`n_entries` 的下降是绑定的直接后果，不是数据变化）。完全不泄露的仍是 `demographic.*` / `exposures.*` / `project.project_id`。
- 逐字段记录数：**2520 → 840**（22 个不同字段不变）；`not_in_bank` 482 条；`leak_rate_undefined` 36 条。

### 审计（自检项 + 实际结果）

| 自检项 | 实际结果 |
|---|---|
| 138 组合计数 | ✓ 见上表 |
| 旧产物清理彻底 | ✓ 350 JSON / 35 目录 → 138 JSON / 33 目录；无 CPTAC/MMRF、无 HGCN 跨癌种 |
| 可重复性 | ✓ 两次运行 `leak_audit_summary.csv` md5 相同（`b5de75584e9a1449bfca9d188e827cd6`）；第二次 `--prune` 零删除 |
| 共享组合数值未变 | ✓ 138/138 与旧表逐组合相同（`added=0`） |
| 抽查 | ✓ 5/5 与独立重算一致（含 1 组 HGCN 绑定 + 2 组泛癌种 + 2 组附赠）。注：**本步抽查数超过规格要求的 3 组** |
| 绑定测试 | ✓ `tests/test_leak_audit.py` 10 → **17 用例**：HGCN 六方案只允许本癌种（含 `TCGA_LIHC` 下划线）、HGCN 绑定队列缺失/被剔除时 ValueError、泛癌种含全部 33 TCGA、CPTAC/MMRF 两种 binding 模式下都不出现、`build_audit_plan` = 4×33+6 = 138（`all` 模式 = 330）、`prune_stale_outputs` 删除计划外 JSON 与空目录、payload 记录绑定元数据、**templates/fields.json 的 `datasets` 键不影响范围**（写入错误的全绑定仍只产 3 个组合） |
| 全量测试 | ✓ `tests/` 140 passed, 6 skipped（无回归） |
| 未跑训练 / 未改他人文件 | ✓ 只改 `src/leak/**`、`tests/test_leak_audit.py`、`results_display/leak_audit/scripts/audit_leak.py`，未触碰 `src/` 其他模块、`A_pipeline/`、spec |
| 产物路径 | `results/leak_audit/{dataset}/{scheme}.json`（138）、`results/leak_audit/leak_audit_summary.csv`（138 行，md5 `b5de75584e9a1449bfca9d188e827cd6`）、`results_display/leak_audit/leak_audit_{overview,fields}.png` + `leak_audit_{scheme,field}_mean.csv` |

### 偏差与原因

- **偏差 1（数据集名单来源：注册表而非 Test_0 manifest）**：spec §2.4 同时写了「数据集 = datasets.json 中的 33 个 TCGA」与「选集一律读 Test_0 manifest，禁止硬编码名单」。本步取**注册表 + TCGA 前缀 + 显式剔除集**：manifest 的 tier 仍随 D1 未锁定且含 CPTAC/MMRF 两行，若读 manifest 会把外部数据集重新带回来。已核对两者 TCGA 行集合**完全一致（33/33）**；本实现也没有硬编码 33 个名字（用前缀规则 + 排除集）。
- **偏差 2（`HGCN_LIHC` 用下划线注册名）**：绑定表写 `TCGA_LIHC`（`datasets.json` 注册名，S1 偏差 5），而非连字符形式；测试对该下划线名做了显式断言。
- **偏差 3（未登记方案的默认）**：非 §2.4 登记、也非 HGCN 的方案（如测试用 `FAKE`）按泛癌种处理，但 payload 的 `scheme_binding` 标 `pan_cancer_default`，便于事后识别；如后续要禁止，可加 `--binding` 的第三个取值。
- **偏差 4（重算脚本两处规则修正）**：见抽查节。**只改抽查脚本，审计实现与产物不变**；S2 的结论在此两处上不受影响（当时抽查的组合恰好不触发）。
- **偏差 5（旧产物删除范围）**：按用户确认，删除仅限 `results/leak_audit/` 下旧产物（`results/**` 已在 .gitignore，不入库）；`results/A_manual`、`outputs/**`、`rawdata_stats/**` 未动。

### 决策点

- **无新增、未改动决策点状态表**（D0–D5 保持原样）。U2（泛癌种是否按各自论文队列绑定）仍待用户；本步按「全部 33 TCGA」执行。

### 状态

完成。Test_1a 产物已按新绑定（138 组合）重算、重绘并通过抽查与绑定回归测试；旧 350 组合产物已删除。后续 Test_3b 的「泄露背景」应引用本步的新汇总表（注意 HGCN 为单队列值）。

### 提交

`git add src/leak scripts/run_leak_audit.py tests/test_leak_audit.py results_display/leak_audit z_notes/Test_series_execution_log.md` → "S2b: 审计按新绑定重跑(HGCN仅本癌种,剔除CPTAC/MMRF)"（`results_display/leak_audit/scripts/audit_leak.py` 在 .gitignore 内，用 `git add -f` 单加；png/csv 产物不入库；未 push）。

---

## 口径记录 R3：数据协议 n_event 判据补全（用户答复）

- 时间 / 执行者：2026-09-30 / Claude（主会话，用户答复）
- 目标：记录用户对 R2 两个待补问题的答复与计数校正。
- 内容：
  1. **70–100 区间**：进主图，**必须报告 CI，不参与严格排名**（CESC、MESO、ESCA、UCEC、SARC）；依据 README §五.2"放宽到 ≥70 时必须报告 CI、不参与严格排名"；其折间 std 0.035–0.081 档比 30–70 档（0.079–0.113）好一档。
  2. **33 TCGA 计数校正**：README 的 17/22/12 按 35 数据集（含 MMRF/CPTAC）计算；33 TCGA 口径下：≥100 → **15**；≥70 → **20**；≥150–200（多字段实验）→ **10**（GBM/OV/HNSC/SKCM/LUSC/LUAD/BLCA/KIRC/STAD/BRCA）。
  3. **n_event 判据完整 4 档**（已写入 spec §12 U1）：≥100 主图干净集；70–100 主图带 CI 不排名；30–70 补充材料 bootstrap CI；<30 不收录、单列"低事件组"定性讨论。
- 待补：用户标注协议还有 B/C… 节（多字段实验/EPV、landmark 有效事件重套、event_rate 降级、退化折），粘贴被截断，等用户补发。
- 状态：完成（仅记录；Test_0 脚本仍不改，等协议补全后统一落地）。

---

## 口径记录 R4：D3 放量确认

- 时间 / 执行者：2026-09-30 / Claude（主会话，用户确认）
- 目标：记录 D3 确认。
- 内容：用户确认 S4 放量，按三条硬条件执行（python 3.13.12 统一汇总、label 源统一 Clinic_Analyzer metadata、按模态分判据）。S4 训练网格 = 138 组合（HGCN_* 6 癌种 + 泛癌种 × 33 TCGA）× 两臂 × {clinic_cox, mlp_clinic_flatten}；优先级：≥70（20 数据集）先跑，30–70 次之，<30 低事件组后置（其输出仅定性讨论，不进定量图——按协议 A 节）。
- 决策点：D3 已确认。
- 状态：完成。

---

## 口径记录 R6：执行简化——按 A 判据，B/C 存档不执行，D 不采用

- 时间 / 执行者：2026-09-30 / Claude（主会话，用户指令）
- 目标：落实用户简化指令。
- 内容（用户原话要点）：B、C 不重要，一开始执行怎么简单怎么来，不要执着；全部试验按 A 执行都可以；D 不用管。
- 生效口径：
  1. 实验执行**全部按 A 判据**（n_event 四档：≥100 主图干净集；70–100 主图带 CI 不排名；30–70 补充材料；<30 低事件组定性讨论）；
  2. B（多字段门槛）与 C（landmark 有效事件重套）**存档备查、不执行**（spec §12 U1）；
  3. D（次级修正）**不采用**；
  4. S4 网格恢复 **138 组合**（已通知执行 agent 撤销 48 组合修正），优先级按 A：≥100 与 70–100 共 20 数据集（86 组合）先跑 → 30–70（16）→ <30（36）；训练不过滤，报告按 A 四档分层。
- 决策点：无新增。
- 状态：完成。

---

## S4 Test_1b 批跑放量

- 时间 / 执行者：2026-09-30 / Claude（S4 执行 agent，接替中断的前任）
- 目标：138 组合 × 2 臂（A=landmark_none 新链路报告值对照、B=landmark_0 三要件全开）× 2 分析器（clinic_cox + mlp_clinic_flatten，text 编码）= 552 conf，按数据协议 A 分波投放；臂 A 结果落 `results/A_manual_landmark/`，绝不触碰 `results/A_manual/`。
- 输入：
  - `z_notes/Test_series_spec.md`（§2.2/§2.4/§2.5/§6/§12）、本日志 S3/R4/R6、`results/Test_0_dataset_availability/manifest.csv`（35 行，n_event 列）
  - `results/A_manual/{33 数据集}/cindex.csv`（旧表）、`outputs/{dataset}/A_manual/{scheme}/`（臂 A embeddings 复用源）、`Clinic_Analyzer/data/datasets_csv/metadata/`（统一 label 源，33 TCGA 齐全）

### 前置核对（R6 指定四点）

**a. 旧表行覆盖**：33 表 × 5 分析器（mlp_clinic_mean/flatten、snn×2、clinic_cox）。按 §2.4 绑定清点：MULTISURV/INTEGRATIVE_DNN × 33、SURVPGC × 4（BRCA/COAD/READ/LIHC）、MMSURV × 6（BRCA/COAD/ESCA/LUAD/STAD/LIHC）、HGCN_* × 各自癌种——**138 组合中有 56 个（SURVPGC 29 + MMSURV 27）旧表无行**（旧 A_manual 未跑这些队列的这两方案），这些组合的 clinic_cox 无可比行，按 D3-3 记为"旧表无该行，非不一致"。

**b. GPU/环境**：8×L40。投放时 nvidia-smi：GPU 0–4 被 zuorongchang/chenzhiyu 训练占满；GPU 5/6/7 为 zhoukeru 干预实验（标记 --allow-cotenancy）。决策：训练 drainer 用 GPU 5（当前仅本批 ~4GB/46GB）；编码走 A_pipeline 默认 DEFAULT_GPU="7"（现空）。conda：SurvPGC 3.9.25（run.sh 训练）、conch 3.10.20（编码）、base python 3.13.12（**汇总/投放/校验，硬条件 D3-1**）。

**c. label 源**：33 TCGA metadata CSV 齐全；`results/A_manual_landmark/labels/` 上任 agent 只留下 tcga_brca 3 个文件，已用 `landmark_labels.build_landmark_label_file` 派生补齐 **32 个 `__landmark_0.csv` + sidecar**（33/33；排除数例：brca 1051→1030、acc 92→91、coad 429→409、laml 186→173、prad 500→500、tgct 247→247）。

**d. 臂 A 复用**：82/138 组合已有 `outputs/{ds}/A_manual/{scheme}/embeddings/pt`（MULTISURV/INTEGRATIVE_DNN×33 + HGCN×6 + SURVPGC×4 + MMSURV×6），**只读复用，未重生成**（旧表 mtime 2026-09-07 23:59、旧 embeddings 2026-09-06 均未变）；缺的 56 组合臂 A embeddings 经 `--landmark_time none` 新链路生成（写入原本不存在的目录，无覆盖）。

### 网格与优先级（138 组合，按 A 判据，训练不过滤）

- 波 1（≥100 的 15 + 70–100 的 5 = 20 数据集，86 组合）：**A1 160 + A1H 12 + B1 160 + B1H 12 = 344 conf 已全部投放**；
- 波 2（30–70：UVM/ACC/UCS/KIRP，16 组合，64 conf）与波 3（<30：9 数据集，36 组合，144 conf）：编码已全部完成，conf 由 watch 进程在波 1 队列排空后自动按序投放（或手动 `bash scripts/s4_Test_1b_queue.sh enqueue A2/B2/A3/B3`）。

### 投放/完成计数（收尾时点）

- 编码：193 个 pipeline 任务（臂 A 56 + 臂 B 137，波 1→3 排序）**192 完成、0 真实失败**（1 条为清单表头误入，已修脚本）。
- conf：投放 344/552（波 1 全量）；done 135/552，failed 0；drainer（GPU 5，8 workers）与 watch 进程仍在后台运行。
- 新代码（本步提交）：`scripts/s4_enqueue.py`（enqueue/summarize/status/emit-encodes，读 manifest 分波、不硬编码名单，无 drain）、`scripts/s4_Test_1b_queue.sh`（encode/drain/watch/status 编排）、`scripts/s4_validate_firstwave.py`（diff-cox / prompts 审计 / 同环境重跑比对）。

### 首波校验（三条硬条件，收尾时点快照）

**① python 3.13.12 统一汇总**：前任遗留的 GBM×MULTISURV arm A clinic_cox 行 std 末位 ULP 不一致（`...1313` vs 旧表 `...13131`，系 SurvPGC 3.9 汇总所致），已删行后用 3.13.12 重汇总 → **与旧表逐位 diff=0**；此后所有 enqueue/drainer/summarize 均在 3.13.12 下运行。

**② label 源统一 Clinic_Analyzer metadata（两臂同源）**：臂 A conf 无 LABEL_FILE_PATH → run.sh 默认取 Clinic_Analyzer；臂 B conf 带 LABEL_FILE_PATH 指向派生 `__landmark_0.csv`（由同一 Clinic_Analyzer 源派生）；抽查 `tcga_blca__MULTISURV__landmark_0` run 的 effective_config 确认。

**③ 按模态一致性判据**：
- clinic_cox 臂 A vs 旧表逐位 diff：**已比 45 组合，diff=0 42 个，不符 3 个**，均已归因：
  1. `COAD×INTEGRATIVE_DNN`（旧 0.496015348 / 新 0.495923773）：oldlabel 探针（换回 SurvPGC label+clinical 重跑）= 新链路结果 **5 折全帧逐位一致** → 与 label 源无关，系旧环境（2026-09-07，Clinic_Analyzer 磁盘代码在 .gitignore 内无版本）训练动力学 FP 漂移，量级 9.2e-5，远小于折间 std 0.111；
  2. `LIHC×MULTISURV`（0.479899412 / 0.479612985）：oldlabel 探针 val_cindex **5 折逐位 = 新链路**（loss 4 折末位不同，系 SurvPGC 副本行序差异改变 batch 组成）→ 同属旧环境 FP 漂移，2.9e-4，std 0.064 内；
  3. `STAD×INTEGRATIVE_DNN`（0.532964423 / 0.514300510）：**实质性差异，归因=旧 label 源缺患者**——SurvPGC 副本比 Clinic_Analyzer 少 67 例（其中 67/67 在 5 折 splits 内、26 个事件），旧表 STAD 各行是在不完整患者集上算的。同型：kich 少 47、prad 少 97、read 少 14（全部在 splits 内）；brca/coad/kirc/kirp/lihc 无 splits 内病例差（共享病例的 survival_months/censorship 9/9 研究逐位相同）。
- mlp 同环境重跑一致性（det1，改 RUN_NAME 重跑同 conf）：BLCA×MULTISURV、BRCA×MULTISURV、ESCA×HGCN_ESCA（mlp_clinic_flatten）**3/3 组合 5 折全帧逐位 ALL MATCH**。
- 控制变量审计（两臂字段表逐字一致，抽查 9 组）：BRCA×MULTISURV、ACC/BLCA×{MULTISURV,SURVPGC,MMSURV,INTEGRATIVE_DNN}——列集/列序、患者行序、行数全部一致，差异只出现在取值单元格（MULTISURV 仅 2 个 derived 治疗列变化：BRCA 173/127、BLCA 82/44、ACC 59/17，与 S3 记录一致；其余方案字段在 t0 掩码下取值不变）。**失败 0**。
- 臂 B 三要件落盘抽查：`tcga_blca__MULTISURV__landmark_0` 用派生 label（split 文件未动）、landmark_0 embeddings 目录正确。

### 预计墙钟与续跑方法

- 实测吞吐：8 workers / GPU 5，42 min 完成 132 run（64 mlp + 71 cox，mlp 有效并行 ≈5.5×）。**预计总墙钟 ≈ 4–5 小时**（波 1 剩余 ~1.5h + 波 2/3 ~1.5h），即 2026-09-30 午后可全部完成。
- 续跑（自动化）：watch 进程（PID 见 S4_watch.log）在队列排空时按 A1→B1→A2→B2→A3→B3 投放下一波、drainer 退出时自动重启、每 5 min 汇总表行、552 全 done 自动退出。
- 手动续跑（watch 失效时）：`bash scripts/s4_Test_1b_queue.sh status` 看进度 → `bash scripts/s4_Test_1b_queue.sh enqueue <下一波 slice>` → `bash scripts/s4_Test_1b_queue.sh drain` 重启 drainer → 完成后 `python3 scripts/s4_enqueue.py --slice <slice> --summarize` 汇总。failed conf 重跑 enqueue 即自动重入队。全部命令要求 base python 3.13.12。
- 监控：`A_pipeline/S4_drain.log`（训练）、`A_pipeline/S4_watch.log`（投放节奏）、`A_pipeline/S4_summary.log`、`bash scripts/s4_Test_1b_queue.sh status`；首波校验重跑 `python3 scripts/s4_validate_firstwave.py --diff-cox`。

### 偏差与原因

1. 前任遗留 48 组合网格**已按 R6 作废**，未使用；其 GBM 表行 ULP 问题已修（见首波校验 ①）。
2. 前任遗留 `outputs/TCGA-READ/A_manual/L0/landmark_0` 等非网格目录未动。
3. 臂 A 缺 embeddings 的 56 组合（SURVPGC/MMSURV 旧 A_manual 未跑）按新链路在空目录生成——属补建非覆盖。
4. 编码 worker 首行误把清单表头当任务执行（1 次无害失败），脚本已改为 grep 过滤。
5. det1 首次 sed 拼 RUN_NAME 时引入反斜杠，两进程已 kill 并以 python 重写 conf 后重跑（残留部分目录被同名前缀重跑覆盖，无影响）。
6. `s4_enqueue.py` 的 summarize 沿用 `run_cindex_queue` 的 `{name}[{source}]` 表目录键，与旧 A_manual 表目录一致。

### 决策点

- 无新增；决策点状态表未改。D3 三条硬条件已按模态执行并逐条核验（clinic_cox 不符组合已列出并归因，供用户裁定是否接受"旧环境 FP 漂移 + 旧 label 源缺患者"两类归因）。

### 状态

完成（本步范围：现场清理、前置核对、全量编码、波 1 全量投放、首波校验、自动化续跑部署）。批跑本体仍在后台进行（done 135/552 @ 收尾），按上文续跑方法直至 552 完成；未谎报全部完成。

### 提交

`git add scripts/s4_enqueue.py scripts/s4_Test_1b_queue.sh scripts/s4_validate_firstwave.py z_notes/Test_series_execution_log.md` → "S4: Test_1b 批跑放量(138组合×2臂×2分析器)"（未 push；未用 git add -A）。

---

## S4 批跑恢复记录（07:27）

- 时间 / 执行者：2026-09-30 07:27 / Claude（主会话，定时检查触发）
- 目标：修复批跑停滞。
- 事实：watch 与 drainer 于 02:30 后退出（最后日志 02:30:22 投放 slice A2）；07:10 检查时 queue=32、running=0、done=345、failed=0——watch 逻辑只在队列空时才重启 drainer，队列有积压时不会拉起，属脚本缺陷。
- 动作：S4_GPU_TRAIN=7 重启 drainer（GPU 5 已被他人占用 22GB，改 GPU 7）；07:27 起 8 workers 排空；encode 列表已清空（剩余 0）。
- 审计：重启后 45s 内 running=8、训练日志正常滚动；done 345/552、failed 0。
- 决策点：无。
- 状态：完成（批跑恢复排空中，预计 1–1.5 小时完成）。

---

## S4 批跑恢复记录 2（07:40，GPU 迁移）

- 时间 / 执行者：2026-09-30 07:40 / Claude（主会话，用户指令）
- 目标：按用户指令把训练迁出 GPU 7（用户有进程），改用 GPU 2/3/4。
- 动作：停止 GPU 7 上的 watch/drainer 进程树；回收 8 个 running conf 回 queue；以 CUDA_VISIBLE_DEVICES=2,3,4 重启 drainer（8 workers）与 watch。
- 结果：done 345→365（迁移前又完成 20）；被中断的 8 个 conf（KIRP/UCS 臂 A mlp）进 failed 桶，属 kill 中断而非真实失败，watch 下一轮 enqueue 会自动重入队；当前 running=4、queue=0，排空中。
- 决策点：无。
- 状态：完成。

---

## S4 Test_1b 批跑完成

- 时间 / 执行者：2026-09-30 08:06 / watch 自动（Claude 主会话记录）
- 目标：记录批跑完成。
- 事实：08:06:18 watch 判定 ALL 552 done；done=553（含 1 个旧冒烟 conf）、failed=0、queue/running=0。
- 产物核验：results/A_manual_landmark/ 下 33/33 个 TCGA 的 cindex.csv 就位（16 行=4 泛癌种×2 臂×2 分析器；HGCN 绑定癌种 20 行；BRCA 含 S3 冒烟行 20+）；failed 桶已空（被中断的 8 个 KIRP/UCS 已重跑成功）。
- 审计：watch 自修复循环闭环（07:36/07:38/07:43/07:55 四次拉起 drainer，B2/B3 自动投放），无人工干预到完成。
- 决策点：无。
- 状态：完成。

---

## 口径记录 R7：D4 确认

- 时间 / 执行者：2026-09-30 / Claude（主会话，用户确认）
- 内容：Test_2 贪婪搜索使用**阈值早停**，增长阈值 **0.005**——即沿用 E2 规格第 9 节 sig_stop（gain(k) < 0.005 且 paired Wilcoxon p >= 0.05 连续 3 步停止，推荐 k_sig = k-3 前缀；另报历史 best）。
- 决策点：D4 已确认。
- 状态：完成。

---

## Test_1b Δc 报表

- 时间 / 执行者：2026-09-30 / Claude（Test_1b 报表执行 agent）
- 目标：按 spec §6.4 产出「报告值 vs 去泄露值」Δc 对照报表（纯汇总，不跑训练）：每 (dataset, scheme, analyzer) 报告 c(臂A none)、c(臂B landmark_0)、Δc = c(A) − c(B)（Δc>0 = 去泄露后下降 = 高估证据）；数据集分层按协议 A（n_event 四档）；汇总统计只报效应量、方向一致率与 CI，不做 0.05 显著性宣称。
- 输入：
  - `results/A_manual_landmark/{33 TCGA}[gdc]/cindex.csv` + `run_config.json`（S4 两臂产物，556 行 = 552 网格 + 4 条 BRCA S3 冒烟行）
  - `results/A_manual_landmark/runs/**/val_result_fold*.csv`（5 折 × 552 run 的折文件，全部完整）
  - `rawdata_stats/_shared/event_summary.csv`（35 行，取 33 TCGA 行做 n_event 分层）
  - `results/A_manual_landmark/labels/{study}__landmark_0.json`（33 个，审计用排除清单）
  - 结果分层核对：≥100 → 15 个、70–100 → 5 个（CESC/MESO/ESCA/UCEC/SARC）、30–70 → 4 个（UVM/ACC/UCS/KIRP）、<30 → 9 个，与 spec §12 U1 一致。
- 命令与参数：
  - `python3 results_display/scripts/Test_1b_delta_report.py --audit`（python 3.13.12，与 S4 汇总同版本）
  - 可复跑：同命令连跑两次，stdout 与全部产物文件（26 个）md5 逐字节一致（diff=0）。
- 表结构说明（S4 产物 → 报表）：
  - S4 表：`dataset` 列（如 `TCGA-BRCA[gdc]`，LIHC 为 `TCGA_LIHC[gdc]` 下划线）；`scheme` 列 = `{scheme}__landmark_{none|0}`，**臂标记 = 后缀**（none=臂A 报告值对照，0=臂B 去泄露值）；`modality` 列 = 分析器（本报表只取 `clinic_cox` 与 `mlp_clinic_flatten`，即 S4 网格的 2 个分析器）；BRCA 表内 `landmark_365`/`noshift`/`mlp_clinic_mean` 为 S3 冒烟行，按「臂 ∈ {none,0} × 分析器 ∈ {cox,flatten}」过滤后恰好 552 行、每 (dataset, scheme, analyzer) 恰好 2 臂、HGCN 仅出现在绑定癌种表（20 行表），网格结构零异常。
  - 报表列：`dataset/scheme/analyzer/tier/n_patients/n_event/event_rate` + `c_report/c_report_std`（臂A，折文件重算）+ `c_deleaked/c_deleaked_std`（臂B）+ `delta/delta_fold_std/delta_ci_lo/delta_ci_hi`（折内配对 t(4) 95% CI，5 折）+ `c_report_table/c_deleaked_table/delta_table`（S4 汇总表冻结值，对照用）+ `table_stale` + `n_folds`。
- 关键发现（本步审计发现的 S4 汇总时序伪影，未改 results/，只在本报表内处理）：
  1. **S4 汇总表 100/552 行是跑动中途快照**：`A_pipeline/src/cindex.py::_merge_cindex_rows` 首次写入后不再更新行，晚完成的 run 被冻结在部分折的均值上（例：BLCA×MMSURV flatten 臂A 表值 0.640341 vs 5 折实值 0.645855；分布：臂A 42 / 臂B 58；cox 17 / flatten 83）。本报表 c 值一律按 `read_cindex` 同算术（纯 python sum）从折文件重算，冻结值保留在 `*_table` 列，`table_stale` 标记（75 对至少一臂冻结）。建议后续步骤重跑 summarize 更新 S4 表（不在本步范围）。
  2. **86/276 对 Δc 精确为 0 是真实结构效应，非复用伪影**（经 run.log 逐 epoch 核对，臂 B 确以派生 label 训练、case 数正确减少）：
     - 57 对：该数据集 landmark 排除数 = 0 且方案字段在 t0 掩码下无取值变化 → 两臂输入完全相同 → 结果逐位相同；
     - 29 对：排除数 > 0 但被排除者全部为 `ground_truth_time ≤ 0` 且删失（如 CESC 13/13 为 censored、gt=0）→ 对 c-index 无可比对贡献（c-index 只数可比对），移除不改变数值；含事件（gt<0 死亡）的排除才会改变 c（如 BLCA 2/4 为事件，Δc ≠ 0）。
- 核心结论（Δc = 报告值 − 去泄露值；Δc>0 = 高估证据）：
  - **main 档（15 数据集）**：方向一致率最高 = **MULTISURV × clinic_cox：10/15（0.667），mean +0.0063，bootstrap CI (−0.0026, +0.0145)**；正向数据集 = GBM +0.0307、SKCM +0.0252、HNSC +0.0219、STAD +0.0187、LGG +0.0176、KIRC +0.0159、LUAD +0.0130、BRCA +0.0127、PAAD +0.0099、COAD +0.0045；负向 = LAML −0.0301、LUSC −0.0172、LIHC −0.0146、BLCA −0.0142、OV −0.0001。其余方案 × 分析器方向一致率 0.067–0.467、跨数据集均值 −0.005 ~ −0.001，CI 全部跨 0。全 276 对 Δc>0 仅 81（29%），**无数据集级系统性高估证据**；幅度均落在折间 std 之内。
  - **SKCM 全线负 Δc**（flatten −0.059 ~ −0.099、cox −0.038 ~ −0.039，5 折配对 CI 多不跨 0）：去泄露后 c-index 上升——SKCM 的 t0 后信息反而引入噪声，与高估假设方向相反，值得单列解读。
  - **main_ci 档（5 数据集，必须带 CI、不排名）**：幅度小（|mean| ≤ 0.012），多数接近 0，CI 全跨 0；HGCN_ESCA flatten +0.0127、HGCN_UCEC flatten +0.0415（n=1 单点）。
  - **supp 档（4 数据集，30–70）**：clinic_cox 16 对 Δc 全部 ≤ 0（MULTISURV mean −0.0479、CI (−0.0797, −0.0198)），即小事件组去泄露后 c 上升；flatten 方向混杂。n=4 且方差大，仅定性。
  - **low 档（9 数据集，<30，仅定性）**：多对精确 0（同上结构效应）；MULTISURV flatten mean +0.0500（CI (+0.0106, +0.1014)，7/9>0）为全表最大正向均值，但属最低事件档、仅定性讨论。
  - **HGCN 绑定癌种单点（n=1，不可与 15 数据集均值直接比）**：UCEC cox −0.0523 / flatten +0.0415；ESCA cox −0.0120 / flatten +0.0127；LUAD flatten −0.0621；LIHC flatten −0.0397；KIRC cox +0.0059 / flatten +0.0113；LUSC cox +0.0039 / flatten −0.0040。
  - 汇总口径：paired Wilcoxon 以数据集为样本、5 折均值为配对值（summary 表 `wilcoxon_stat/p` 只作数值参考，不做显著性结论）；方向一致率 = Δc>0 比例；CI = bootstrap（B=10000，seed=0，数据集级重采样）+ 行级折内配对 t(4) CI。
- 产物（`results_display/Test_1b_delta/`，gitignore 内不入库；全部 26 个文件）：
  - `Test_1b_delta_main.csv`（172 行 = 128 main + 44 main_ci，tier 列标注 CI 要求）、`Test_1b_delta_supp.csv`（32 行）、`Test_1b_delta_low.csv`（72 行）、`Test_1b_delta_summary.csv`（44 行 = 方案 × 分析器 × 档组汇总）
  - `Test_1b_delta_forest_{scheme}_{analyzer}.png` × 20（每方案×分析器森林图，行=数据集、误差棒=折内配对 95% CI、按协议 A 分档标注、Δc 符号色编码）+ `Test_1b_delta_overview_{analyzer}.png` × 2（跨方案均值条形 + bootstrap CI + 方向一致率直标）
  - 脚本：`results_display/scripts/Test_1b_delta_report.py`（入库；`--audit` 固定种子抽查、同输入重跑 diff=0）
- 审计（抽查 3 组，固定种子 20260930，ALL PASS）：
  | 抽查组 | Δc 手算（折文件独立算术） | 与表一致 |
  |---|---|---|
  | TCGA-THYM × MULTISURV × clinic_cox | 0.3916461916 − 0.4661889162 = **−0.0745427245** | ✓（low 档，stale=False） |
  | TCGA-SKCM × SURVPGC × mlp_clinic_flatten | 折文件重算 | ✓ |
  | TCGA-LAML × MULTISURV × mlp_clinic_flatten | 折文件重算 | ✓ |
  每组另核 4 项全过：Δc 独立重算一致、stale 标记自洽、SEED 两臂一致（config.snapshot SEED=0）、臂B = 臂A − 排除患者（5 折逐一核对 slide id，`.svs` 后缀归一；如 BLCA 逐折差集恰为 4 名排除者）。字段集控制变量已由 S4 校验（9 组抽查），本步未重复。
- 偏差与原因：
  1. S4 汇总表冻结行问题（见「关键发现 1」）：本报表改用折文件口径并在 `*_table` 列保留冻结值；**未修改 results/A_manual_landmark 任何文件**。
  2. 折内配对 CI 的配对口径：臂 B 每折患者集 = 臂 A − 排除患者（landmark 要件①），两臂折号来自同一 split 源文件；配对 Δc 按同折号相减，排除患者造成的折间患者集差异已计入 CI 方差。
  3. 图内文字全部用英文（matplotlib 默认字体无 CJK 字形）；图配色用参考调色板红/蓝发散对（light 表面，validate_palette.js 全项通过）。
- 决策点：无新增，未改动决策点状态表。
- 状态：完成。
- 提交：`git add results_display/scripts/Test_1b_delta_report.py z_notes/Test_series_execution_log.md` → "Test_1b: Δc 对照报表(报告值vs去泄露值)"（png/csv 产物在 gitignore 内不入库；未 push；未用 git add -A）。

---

## 口径记录 R8：新增 Test_1c 实验

- 时间 / 执行者：2026-09-30 / Claude（主会话，用户指令）
- 内容：新增 **Test_1c 单字段泄露对照**——per-field univariate 的 c(field, mask off) vs c(field, landmark_0)，与 Test_1a 的 leak_rate 做交叉表，串联 Test_1a 与 Test_1b（解释"为何存在泄露却没有转化为整组合高估"），并预判哪些字段的泄露理论上能动 Δc（spec §5bis）。
- 执行安排：S5（field bank lm0 重生成 + univariate 补跑）完成后执行；实现 = 新增 field bank 变体 `raw`（lm0 字段集 + mask 关闭）+ 两臂同患者集（gt≤0 排除,复用 S4 派生 label 机制）。
- 决策点：无。
- 状态：完成（注册；执行待 S5 结束）。

---

## 口径纠错 R9：Test_1a leak_rate 定义（用户指令）

- 时间 / 执行者：2026-09-30 / Claude（主会话，用户粘贴评审意见）
- 事实：审计的 leak_rate = 1 − n_valid_t0/n_valid_none（src/leak/audit.py:293）衡量的是"字段在 t0 时点完全缺失的患者比例"，不是"模型输入里混入了未来信息的患者比例"；且审计用的是 Field Bank 提取逻辑，不是论文管线（A_pipeline）实际喂给模型的值。
- 纠错（已写入 spec §2.1）：leak_rate = 实际进入模型的值来自 t_hi>0 槽位的患者比例——直接跑论文方案（不进行泄露处理）并追溯每个值的来源槽位时点。旧口径作废，S2b 数字作废，重跑 S2c。
- 决策点：无。
- 状态：完成（口径更新；S2c 待执行）。

---

## 实验命题总表（语义口径，2026-09-30 补写；2026-10-02 按两条论证链重组）

每个实验 = 实验内容 + 它要论证的命题（括号内是对该术语的解释）+ 状态 + 产物位置。**组织原则：一个 Test = 一个实验（对应一个命题），一个实验可以对应多张表；表本身不是实验**（Test_4 三档表即汇总产物，不占实验命题）。

### 关键定义（全系列共用）

- **预测时点 t0** = 诊断日（landmark_0）。
- **泄露（leakage）** = 预测时点 t0 之后才产生的、却被模型输入使用的信息。操作化定义：对患者某字段，**实际进入模型的值来自 `t_hi > 0` 的时间槽**（该值的产生时点晚于 t0）；任一来历槽位 `t_hi > 0` 即该患者在该字段上泄露。`leak_rate(f) = 泄露患者数 / 管线产出有效值的患者数`（逐字段定量，不设阈值）。
- **经典 landmark 三要件**：① 风险集 = 只保留 `ground_truth_time > T` 的患者；② 时间原点平移到 T（`gt − T`）；③ 协变量只用 T 前信息（槽位 `t_hi ≤ T`）。
- **去泄露值** = 同一字段集 + 三要件（t0）下的评估值；**高估** = 临床模态的预后表现被人为抬高（混入预测时点之后的信息，使报告的 c-index 高于规范时间处理后的 c-index；判定 = Δc > 0 且跨数据集方向一致）；**低估** = 临床模态的预后表现被人为压低（无依据的选字段漏掉了有效字段，使报告的组合 c-index 低于可达值；判定 = 可达值 > 去泄露值）。

### 各实验（内容 + 命题 + 状态 + 产物）

| 实验 | 实验内容 | 论证的命题 | 状态 | 产物位置 |
|---|---|---|---|---|
| **Test_0** 可用数据集评估 | 按事件数/删失对 33 TCGA 分层（协议 A 四档） | 哪些数据集在统计上支撑定量结论（n_event 是评估方差下限；低事件集只能定性讨论）——两链共同的准入前提 | ✅ 完成，分层规则执行中 | `results/Test_0_dataset_availability/`、`scripts/run_Test_0_availability.py` |
| **Test_1a** 单字段泄露对照（时间轴链动机） | per-field c(mask off) vs c(t0)，与 Test_2a 的 leak_rate 交叉 | TCGA clinical 记录自带时间，同一字段在有无 t0 口径下 c-index 会实质变化——对 clinic 生存分析，按协议做字段时间处理是**应该的**（之前的工作都没做）；兼作 Test_2b"为何泄露未转为组合高估"的机制解释 | ✅ 完成（15 主集两臂，Δc 报表 22:10 重出；leak_rate 列已由 S2c 补齐 468/468） | `results_display/Test_1a_field_level/` |
| **Test_1b** 各数据集 Cindex 情况（字段轴链动机） | 单字段 c-index：各数据集分布 + 跨数据集字段分布 + top-k 重叠度 | 字段能力随数据集而异，每个数据集理论上有各自最优字段组合——针对数据集选字段是**应该的** | 🔧 执行中（数据源 S5 已齐） | `results_display/Test_1b_dataset_cindex/`（原 E1 Fig2 升级） |
| **Test_2a** 泄露审计（时间轴链主体） | 对每个论文方案，**不进行时间处理**，追溯每个患者实际进入模型的值来自哪个时间槽 | 论文方案在无时点约束下，模型输入里混入了多少预测时点之后才产生的信息（泄露：值来自 t_hi > 0 的槽位） | ✅ 完成（S2c 新口径重跑：138 组合 = 33 TCGA × 10 方案，仅 4 个方案字段泄露） | `src/leak/`、`results/Test_2a_leak_audit/` |
| **Test_2b** 去泄露对照（时间轴链主体） | 同一字段集两臂：臂A 含泄露 vs 臂B landmark_0，唯一差异 = mask，Δc = A−B | 泄露信息确实抬高了临床模态的预后表现（高估：含泄露的 c-index 被人为抬高、超过规范时间处理后的真实能力） | ✅ 完成（552 confs，33 TCGA×两臂×Cox/MLP），Δc 报表已出：无数据集级系统性高估，MULTISURV×Cox 方向一致率最高 10/15 | `results/A_manual_landmark/`、`results_display/Test_2b_delta/` |
| **Test_3** 贪婪搜索对照（字段轴链主体） | A2 前向贪婪 + sig_stop 0.005 在 landmark_0 池找最优组合，vs 各工作去泄露组合（三臂 Δc、遗漏字段清单） | 各工作的字段组合在去泄露池上是**次优**的（低估：无依据的字段选择漏掉了本可带来额外预测力的有效字段）——**收回** Test_1b 的"各数据集有各自最优组合" | ⏸ 提前终止（2026-10-02 用户指令）：搜索 9/15 进行中被叫停，B′ 617 confs 完成，C 未开始；结果留盘可续跑 | `scripts/Test_3_custom_scheme.py`、`scripts/Test_3_compare.py`、`results/Test_3_greedy_vs_works/` |
| **Test_4 三档汇总表**（非实验） | 报告值 / 去泄露值 / 可达值 | 两链收口：报告值−去泄露值 = 时间轴链收口（高估量）；去泄露值−可达值 = 字段轴链收口（低估量） | ⏸ 前两档数据已齐（Test_2b），可达值待 Test_3 | 未生成 |
| **Test_5** 不变性 | 编码轴/模型轴/数据轴重复 Test_2b 与 Test_3 | 以上结论不随编码、模型、数据改变——偏差来自数据本身，不是某条管线的产物 | 📋 仅占位（后期，Test_1–Test_3 完成后再说） | spec §12 未解决问题 |


| **基础建设** | 经典 landmark 三要件（A_pipeline 扩展）、方案×数据集绑定、数据协议 A、执行日志/规格/逐步提交 | 不是单一命题，而是使上述命题成立的前提：① 评估管线的 landmark 必须符合经典三要件（风险集/时间平移/T 前协变量），否则"去泄露值"无定义；② 每个工作的字段组合只在其设计癌种上绑定评估，否则"该工作"的口径失真；③ 定量结论只在统计能力足够的数据集上成立（协议 A） | ✅ 全部落地 | `A_pipeline/src/landmark*.py`、`z_notes/Test_series_spec.md`、执行日志 |


---

## 口径记录 R10：Test_3b 取消

- 时间 / 执行者：2026-09-30 / Claude（主会话，用户指令）
- 内容：Test_3b（单字段排序 Spearman 对照）不用做，用户已自行删除；命题总表与 spec 中相关条目已移除（历史日志条目保留不动）。
- 决策点：无。
- 状态：完成。

---

## 口径记录 R11：实验编号重组（2026-10-02，用户指令）

- 时间 / 执行者：2026-10-02 / Claude（主会话）
- 目标：按用户决议重组实验编号与组织思路。spec §1/§3/§5bis/§5ter/§8、本日志命题总表已同步改写；`z_notes/experiment_list/experiment_list.md` 为速查清单。

### 新组织（两条论证链 + 动机层）

| 新编号 | 内容 | 原编号 | 命题落点 |
|---|---|---|---|
| **Test_1a** | 单字段泄露对照（时间轴链动机） | Test_1c | 时间口径会实质改变单字段评估值，规范时间处理应该做 |
| **Test_1b** | 各数据集 Cindex 情况（字段轴链动机） | E1（9f64feb） | 字段能力随数据集而异，各数据集有各自最优组合，选字段应该做 |
| **Test_2a** | 泄露审计（时间轴链主体） | Test_1a | 高估证据（定量泄露占比） |
| **Test_2b** | 去泄露对照（时间轴链主体） | Test_1b | 高估证据（Δc，552 confs 已完成） |
| **Test_3** | 贪婪搜索对照（字段轴链主体） | Test_2 | 低估证据（可达值），收回 Test_1b 的不均衡 |
| **Test_4** | 三档汇总表（**非实验**） | Test_3a | 两链收口：报告−去泄露 = 时间轴；去泄露−可达 = 字段轴 |
| **Test_5** | 不变性（占位） | Test_4 | 后期 |

- 组织原则（用户 2026-10-02）：**一个 Test = 一个实验（对应一个命题），一个实验可以对应多张表；表本身不是实验**。原 Test_3a 只是表，占实验编号是原组织错误。
- Test_1b 新增两个量化指标（用户同意）：① 同一字段跨数据集 c-index 分布；② 各数据集 top-k 字段重叠度（k ∈ {5,10,20}，决策点 S5c）。
- 现状核对（本步）：S5 univariate 补跑 **33/33 done、failed 0**（`results/univariate/prompt/landmark_0/`，mlp_clinic_flatten × seed 0）；Field Bank 模板 **33/33 填齐**（bank_rows = kept+1）。
- 编号顺序 ≠ 执行顺序：Test_1a 的 leak_rate 交叉列依赖 Test_2a 新口径审计（用户接手）出数，先报 c(off)/c(t0)/Δc_field。
- 归档纪律（用户指令）：**每完成一步，存档（本日志追加）+ 上传（git commit 并 push origin）**。
- 历史条目保留不动：旧编号（Test_1a/1b/1c/2/3a/3b/4 及 H 系列）仅存在于本日志历史条目与旧提交中，R10 的"Test_3b 取消"指旧编号的"单字段排序对照"。
- 决策点：无新增。
- 状态：完成（spec/日志/实验清单/脚本改名随本次提交）。

---

## R12 重组落地：规格/日志/脚本改名与归档（2026-10-02）

- 时间 / 执行者：2026-10-02 / Claude（主会话）
- 内容：spec 全文改名与两链叙事；命题总表重写；脚本与产物目录改名：
  - `results_display/scripts/E1_Fig2_Single-field c-index.py` → `Test_1b_dataset_cindex.py`
  - `results_display/scripts/Test_1b_delta_report.py` → `Test_2b_delta_report.py`（产物目录 `Test_1b_delta/` → `Test_2b_delta/`）
  - `scripts/Test_2_custom_scheme.py` → `Test_3_custom_scheme.py`、`scripts/Test_2_compare.py` → `Test_3_compare.py`
  - `A_pipeline/templates/Test_2_MULTISURV_TCGA-ACC/` → `Test_3_MULTISURV_TCGA-ACC/`
  - `scripts/s4_Test_1b_queue.sh` → `s4_Test_2b_queue.sh`
  - 移除 `z_notes/H_series_spec.md`、`z_notes/H_series_execution_log.md`（Test_ 系列文档为准）
  - 新增 `z_notes/experiment_list/experiment_list.md`（速查清单）
- 状态：完成。

---

## S5c: Test_1b 各数据集 Cindex 情况（字段轴链动机）落地（2026-10-02）

- 时间 / 执行者：2026-10-02 / Claude（S5c 执行 agent）
- 目标：Test_1b 三量化指标落地（① 各数据集单字段 c-index 分布（原 E1 Fig2 升级）；② 同一字段跨数据集分布；③ top-k 字段重叠度 k∈{5,10,20}）；改写 `results_display/scripts/Test_1b_dataset_cindex.py`，输入改为 S5 产物（旧 `results/univariate` 已在 S0 删除，改为直接解析 `results/univariate/prompt/landmark_0/{ds}/mlp_clinic_flatten/field_cindex.csv`，不经旧 collect 模块）。纯分析，无训练。

### 输入（先核验完整性）

- `datasets.json`：数据集名单唯一来源（禁用硬编码）；过滤 `startswith("TCGA")`（大小写不敏感）得 **33** 个（`TCGA_LIHC` 是下划线命名，若严格按 `TCGA-` 会漏成 32，故按前缀 "TCGA" 匹配）。
- `results/univariate/prompt/landmark_0/{33 ds}/mlp_clinic_flatten/field_cindex.csv`：33/33 存在、全部 `status=ok`；每数据集行数 == `rawdata_stats/{ds}/landmark_0/kept_fields.json` 字段数，合计 **1083** 行（(dataset, field) 值），**188** 个不同字段。
- `results/Test_0_dataset_availability/manifest.csv`：33 行；`note` 列全部以 `provisional(D1)` 开头 → 不采信其 tier。
- `rawdata_stats/_shared/event_summary.csv`：n_event / n_patients / event_rate（与 manifest 的 n_event 逐行一致，已核）。

### 命令与参数

```
python3 results_display/scripts/Test_1b_dataset_cindex.py            # 生成全部产物
python3 results_display/scripts/Test_1b_dataset_cindex.py --audit    # 追加 3 组 (dataset, field) 抽查
# 可选：--out_dir / --analyzer / --top_k 5,10,20 / --min_datasets 10
```

分档口径（D1 provisional 的处置）：manifest 非 provisional 才采信 manifest tier；本步 33 行全 provisional，故按协议 A 从 n_event 重算（≥100 main / 70–100 main_ci / 30–70 supp / <30 low），逐行写 `tier_source` 列并在图注标注。结果：**main=15、main_ci=5、supp=4、low=9**（main=15 与 experiment_list 中 Test_3 主集 15 个一致）。

### 产物（`results_display/Test_1b_dataset_cindex/`，png/csv 不入库）

- 图 5：`Test_1b_per_dataset_profile.png`（原 E1 Fig2 升级：共享字段轴 37 字段 × 33 数据集，分层分隔线+文字标注）、`Test_1b_per_dataset_distribution.png`（指标 a）、`Test_1b_cross_dataset_field_distribution.png`（指标 b）、`Test_1b_topk_overlap_matrix.png`（指标 c：k=5/10/20 三张 528 对数据集两两重叠率热图）、`Test_1b_topk_overlap_summary.png`（指标 c 汇总：均值/中位 + 逐 k 零共享占比）
- 表 7：`Test_1b_dataset_summary.csv`、`Test_1b_field_summary.csv`、`Test_1b_cindex_matrix.csv`（数据集 × 字段全矩阵）、`Test_1b_topk_members.csv`、`Test_1b_topk_pairwise_k{5,10,20}.csv`、`Test_1b_topk_overlap_summary.csv`、`Test_1b_metrics.json`

### 量化结论（不均衡幅度）

**(a) 各数据集单字段分布**：1083 值中 77.4%（838/1083）单字段 c ≥ 0.5。
- 各数据集 top-1：**0.572（TCGA-LUSC）.. 0.930（TCGA-THCA），跨度 0.358**；中位 0.666。
- 各数据集字段中位 c：0.407（TCGA-PCPG）.. 0.567（TCGA-THCA），跨度 0.160。
- 数据集内字段跨度（max−min）：中位 0.230、最大 0.608（TCGA-DLBC）→ 同一数据集内换字段的收益空间与跨数据集差同量级。
- 33 个数据集的 top-1 落在 **18 个不同字段**：age_at_diagnosis 覆盖 6 个、ajcc_pathologic_n 5 个、ajcc_pathologic_t 4 个，其余 15 个字段各自只在 1 个数据集夺冠 → "每个数据集有各自最优字段"的直接证据。

**(b) 跨数据集同字段分布**（37 个覆盖 ≥10 数据集的公共字段）：同一字段的跨数据集 c-index 跨度中位 **0.230**、最大 **0.691**（`diagnoses[].age_at_diagnosis`，33/33 数据集）、最小 0.004；**17/37 字段跨度 ≥ 0.25**，仅 7/37 ≤ 0.10 → 单字段判别力高度随数据集变化，字段清单不可跨数据集照搬。

**(c) top-k 重叠度**（528 对数据集，重叠率 = |∩|/k）：
- k=5：均值 0.149、中位 0.200、Jaccard 0.090；**249/528（47.2%）对数据集 top-5 零共享**。
- k=10：均值 0.197、中位 0.200；72/528（13.6%）零共享；top-10 共涉及 112 个不同字段，**62 个只出现在一个数据集的 top-10，0 个字段进入全部 33 个数据集**。
- k=20：均值 0.327、中位 0.300；0 对零共享；148 个字段、70 个唯一、0 个进入全部。
→ 低位重叠 + 无字段通吃 ⇒ 跨数据集最优组合不通用，直接支持 Test_3 的 per-dataset 贪婪搜索（即 Test_1b 的动机命题）。

### 审计

- **可重复性（diff=0）**：两次独立运行（不同 out_dir）14/14 产物**字节级一致**（5 张 PNG + 7 CSV + metrics.json；PNG 无时间戳、排序与数值格式固定、抽样 seed 固定 AUDIT_SEED=20261002）；交付目录与验证运行逐字节一致。
- **抽查 3 组**（与源 CSV 手算一致，全精度 diff=0）：TCGA-GBM × `diagnoses[].treatments[].treatment_anatomic_sites` = 0.5013796431989072；TCGA-ESCA × `diagnoses[].pathology_details[].lymph_nodes_positive` = 0.534564751019368；TCGA-SARC × `diagnoses[].pathology_details[].tumor_depth_descriptor` = 0.49464080353292345。校验链：手算 mean(per_fold raw JSON) == CSV `c_index_mean` == 脚本内部 record == field_summary，`[audit] ALL PASS`。
- 数据完整性：33/33 CSV、status 全 ok、行数 == kept_fields 字段数（1083）、188 字段、manifest 与 event_summary 的 n_event 一致。

### 偏差与原因

- manifest 33 行全 provisional → 按上文重算 tier 并标 `tier_source`（`protocolA_provisional_manifest`），图/表注明；manifest 若日后转正只需重跑。
- 分层不用颜色（避免与 red/blue 发散对撞车），用分隔线 + 文字标注（沿用 Test_2b 惯例）；颜色只承载两个语义：c-index vs 0.5 极性（红/蓝发散对）、重叠率量级（单色蓝顺序）。
- 图表风格沿用既有 matplotlib 约定（英文标签，默认字体无 CJK 字形）；调色板与 `Test_2b_delta_report.py` 的红/蓝发散对一致，已过 dataviz 验证器（对 + 顺序色阶）。

### 决策点

- 无新增待决项。本步固化：① top-k 重叠口径按**字段名集合**（非索引），重叠率 = |∩|/k（对称），另报 Jaccard；k 固定 {5,10,20}；② 公共字段阈值 ≥10 数据集（37 字段）；③ tier 来源优先级 = manifest 非 provisional > 协议 A on n_event。

### 状态

完成（脚本 + 本日志随本次提交入库；产物 `results_display/Test_1b_dataset_cindex/` 就绪，供 Test_3 动机与 Test_4 引用）。

---

## 口径记录 R13：训练范围限定 n_event ≥ 100（2026-10-02，用户指令）

- 时间 / 执行者：2026-10-02 / Claude（主会话，用户指令）
- 内容：**后续训练类实验只在 n_event ≥ 100 的 15 个数据集上训练**——PAAD、COAD、LGG、LIHC、LAML、BRCA、STAD、KIRC、BLCA、LUAD、LUSC、SKCM、HNSC、OV、GBM。70–100 / 30–70 / <30 档**不新增训练**；其已有训练结果（Test_2b 552 confs、S5 t0 臂 33 队列、Test_1b 分析）保留磁盘，报告端仍按协议 A 四档分层（70–100 带 CI 不排名、30–70 补充材料、<30 定性）。Test_3 的"主集 15 个"与此口径一致。
- 用户附统计依据：100–150 档 5 个（std 0.036–0.056，每折 20–30 事件）；≥150 档 12 个（std 0.019–0.052，每折 ≥30 事件）。
- 生效动作：已通知 S5b（Test_1a off 臂）执行 agent 限流到 15 个主集；spec §5bis、§12 与 experiment_list 同步更新。
- 决策点：无新增（R6 的"训练不过滤"被本记录取代）。
- 状态：完成。

---

## S6 提前终止与归档（2026-10-02 晚，用户指令）

- 时间 / 执行者：2026-10-02 22:30 / Claude（主会话，用户指令"先提前结束，归档当前结果"）
- 停止的进程：Test_3 搜索 drainer（9 个数据集 runner）+ watch（`Test_3_search_queue.py`）+ 臂 C 接力链（`Test_3_arm_c_chain.sh`）；全部 SIGTERM，已确认 **0 残留**。Test_1a 相关进程此前已自然结束。
- 当前进度快照：
  - **Test_1a（S5b）**：15/15 主集全部完成、0 failed；收尾钩子已于 22:10 自动重出 Δc 报表（`results_display/Test_1a_field_level/`，含 mask_unaffected 噪声对照组）；`results/univariate_raw/_s5b_report.json` 在档。leak_rate 列待 Test_2a 审计出数后填。
  - **Test_3（S6）**：搜索 9/15 数据集进行中被叫停（BLCA/BRCA/COAD/GBM/HNSC/KIRC/LAML/LGG/LUAD，各 G1–G3 步中间产物留盘，0 个 result.json）；臂 B′ **617/617 confs 完成、0 failed**；臂 C 未开始；`three_arm.csv` 仅表头。
- 留盘（未删除）：`results/Test_3_greedy_vs_works/`（search/ 中间评估、logs/、missed_fields.csv、three_arm.csv 表头）、`Clinic_Analyzer/configs/` 各队列桶、`results/univariate_raw/`、`results/univariate/`。
- 续跑方法（届时）：`bash scripts/Test_3_queue.sh all_status` 看状态；重启搜索 watch/drainer（命令见 S6 日志条目或该脚本）；臂 C 链由 result.json 落盘自动触发。搜索实测约 1.5h/步（GPU 与他人共存），可加 GPU（0/6/7 空闲）提速。
- 决策点：无新增。
- 状态：完成（批跑全部停止，结果归档，本条目 + 命题总表状态随本次提交）。

---

## S5b: Test_1a off 臂（单字段泄露对照，mask off）落地（2026-10-02）

- 时间 / 执行者：2026-10-02 / Claude（S5b 执行 agent，Test_1a off 臂；规格 §5bis，范围按 R13）
- 目标：实现并投放 Test_1a 的 **off 臂**——字段集与 t0 臂完全相同（landmark_0 的 kept 字段），
  唯一差异 = 取值 mask 状态（off，`raw` 变体）；患者集与 t0 臂逐位一致（S4 派生 label，gt≤0 排除）。
  产出 Δc_field = c(off) − c(t0) 逐 (dataset, field) 表与 `results_display/Test_1a_field_level/` 交叉表骨架
  （leak_rate 列留空标 `pending_test_2a`，待用户新 Test_2a 逐字段审计出数后重跑自动填列）。

### 输入

- `results/univariate/prompt/landmark_0`（t0 臂，S5 已完成 33/33）；`results/Test_0_dataset_availability/manifest.csv`
  与 `rawdata_stats/_shared/event_summary.csv` 的 n_event（R13 名单派生，不硬编码）；33 数据集清单取自
  datasets.json（TCGA- 前缀）；S4 派生 label（`--label_tag landmark_0`）。

### 命令与参数

- raw Field Bank 构建（conch env 3.10.20，GPU 7）：`python3 scripts/s5b_build_raw_field_bank.py --dataset all`
  （与 t0 bank 构建同法：全部 prompt 单次全局 tokenize(`padding=True,truncation=True`) → 批量
  `encode_text(..., embed_cls=False)` + L2 归一化；落盘 `outputs/_raw/{ds}/field_bank/prompt/landmark_none/`
  与 `raw_value_diff.json` 取值差异审计）
- 队列（base python 3.13.12）：`bash scripts/s5b_univariate_queue.sh bank/check/enqueue/trim/drain/watch/status/report`；
  job_key = `4f95c1617ab5`（≠ t0 臂 `7eba8097c4ca`，root = `Clinic_Analyzer/configs/univariate_raw/`）
- 训练（每 GPU 一个 drainer，`--workers 8`，3 卡 GPU 7/2/6；co-tenancy 允许）：
  `python3 scripts/run_univariate_cindex.py --landmark_time none --extraction_mask off --label_tag landmark_0
  --field_bank_root|--embeddings_root outputs/_raw --results_dir results/univariate_raw
  --queue_root Clinic_Analyzer/configs/univariate_raw --encoding prompt --analyzer mlp_clinic_flatten
  --seed 0 --workers 8 --dataset <R13 15 主集>`
- 两臂一致性抽查：`python3 scripts/s5b_audit_arms.py --pair TCGA-BLCA:0 TCGA-BLCA:7 TCGA-GBM:0 TCGA-GBM:7
  TCGA-COAD:0 TCGA-COAD:8`（字段名同序 / 逐折 splits 三列患者集逐位一致 / 逐折 pkl 键集合一致 / Δc）
- 报表：`python3 results_display/scripts/Test_1a_field_level.py --audit`

### 产物

- 代码（入库）：`scripts/s5b_build_raw_field_bank.py`、`scripts/s5b_univariate_enqueue.py`、
  `scripts/s5b_univariate_queue.sh`、`scripts/s5b_audit_arms.py`、`tests/test_univariate_raw_arm.py`（15 用例）；
  改造 `src/greedy/univariate_cli.py`（`--extraction_mask off`、`--label_tag`、`--field_bank_root`/`--embeddings_root`/
  `--results_dir` 重定向与 guard：off 臂必须显式声明患者集）、`src/greedy/clinic.py`（`_relative_to_results`
  先剥离 `results_dir_base` 再回退规范根，修掉 `{base}/{base}/…` 双层嵌套）、`src/greedy/clinic_evaluator.py`
  （`label_file`/`results_dir_base` 透传）；`results_display/scripts/Test_1a_field_level.py` 与
  `results_display/README.md` Test 系列小节
- 结果（不入库）：`results/univariate_raw/univariate/prompt/landmark_none/{ds}/{mlp_clinic_flatten,runs}`、
  `results/univariate_raw/_audit_pairs.json`；报表目录 `results_display/Test_1a_field_level/`（8 表/图 + metrics + audit json）

### 审计

- **两臂一致性抽查 6/6 通过**（3 数据集 × 2 字段，含 timed 与 non-timed 各半）：字段名同序、逐折
  splits_{i}.csv 的 train/val/test 患者集**逐位一致**、逐折 `split_{i}_results.pkl` 键集合一致；
  `all_ok=True`（`results/univariate_raw/_audit_pairs.json`）。
- **取值差异只出现在会被 mask 影响的字段**：raw vs lm0 全量比对 1083 (dataset×field) 行，504 字段行 /
  67,926 cells 有改动，**非 timed 家族改动字段 = 0**（33/33 数据集 `untimed_changed_fields: []`）。
- **患者集同源**：off 臂 label 显式 `--label_tag landmark_0`（S4 派生 label，gt≤0 排除），抽查确认两臂
  n_patients/n_event/splits/pkl 键全同。
- **可复跑 diff=0**：报表脚本两次独立运行（不同 out_dir）全部产物（含 audit json）**字节级一致**。
- **回归**：`python3 -m pytest tests/ -q` → 185 passed / 6 skipped（无回归；新增 15 用例）。
- **首批数据（3/15 数据集就绪，97 对字段）**：Δc 均值 +0.0255 / 中位 +0.0027，范围 [−0.0134, +0.1953]；
  其中 **17 个字段 Δc ≥ 0.05 全部落在 mask_affected 组**（GBM treatments 家族前 5 名 +0.151..+0.195）。

### 偏差与原因

- **R13 限流**：off 臂训练范围限定 n_event ≥ 100 的 15 主集（名单从 manifest 派生）。已投放的 17 个
  非主集 conf 用 `trim` 撤到 `Clinic_Analyzer/configs/univariate_raw/parked/`（不删除）；ACC 等已完成的
  非主集结果保留磁盘、**不进报表**（报表脚本按 manifest n_event 过滤，覆盖度只会是 15 主集）。
- **编码噪声本底（重要）**：两臂嵌入来自两次独立构建（raw bank vs lm0 bank）。CONCH 文本编码
  **对全局 padding 长度不敏感度有限**（同文本在不同全局 padding 下 cos≈0.78–0.93），且 bank 构建是
  全局 tokenize，raw bank 的长文本会拉长整个 build 的 padding → 即使取值未被 mask 改动的字段，
  嵌入也有轻微差异、Δc 非零。应对：报表增设"mask_unaffected 对照组"（本底）列/图/指标
  （`mask_affected`、`value_cells_changed`、`delta_c_by_mask_group`、`Test_1a_delta_by_mask_group.png`）；
  首批 3 数据集显示本底可控（n=58：均值 +0.0017、中位 +0.0007、p90|Δc|=0.0107、无一个 >0.05），
  被 mask 改动组显著更大（n=39：均值 +0.0609、中位 +0.0308、p90=0.1517）。**Δc 归因于 mask 需显著超过本底**。
- GPU 争用：先 `nvidia-smi` 选最闲卡（7/2/6），与他 agent 进程共卡（不动他人进程）；一次自愈循环
  重放 stale pidfile 导致 GPU 2 上出现重复 drainer，已 kill 孤儿进程（1301277）并 `recover` 归还 running→queue。
- `src/discovery/field_bank.py` 有一行与本步无关的未提交改动（`FIELD_BANK_GPU` 环境变量，树内无使用者），
  **不随本步提交**；`scripts/s5_univariate_enqueue.py` 为其作者未跟踪文件，亦不代提交。

### 决策点

- **待上报**：① 噪声本底口径（如上）已固化进报表，Δc 结论一律以"显著超过 mask_unaffected 本底"为准；
  ② R13 覆盖度：报表只覆盖 15 主集，非主集结果保留但不入表；③ leak_rate 列暂空（`pending_test_2a`），
  待用户新 Test_2a 逐字段审计（`results/leak_audit/{dataset}/G1_*.json`）出数后重跑报表自动填列。

### 状态

进行中：off 臂训练 3/15 完成（BLCA 44、COAD 34、GBM 19 字段），11 个主集在队列（3 running / 9 queued / 0
failed），3 个 drainer（GPU 7/2/6）+ watch 后台运行（自愈：drainer 死后拉起 / failed 重试 ≤3 / running 回收 /
全 done 自动 report）。Δc_field 表与 `results_display/Test_1a_field_level/` 已按现有 3 数据集出数，
其余 12 个数据集完成后重跑同一脚本即补齐（脚本幂等、diff=0）。

---

## S6: Test_3 字段轴链落地（贪婪 vs 工作组合三臂，2026-10-02）

- 时间 / 执行者：2026-10-02 / Claude（S6 执行 agent）
- 目标（spec §7）：① 接管前任遗留的 E2 基础设施改动并补齐 sig_stop 早停测试；② 校验 landmark_0 搜索池；③ R13 主集（n_event ≥ 100，15 个）A2_greedy × mlp_clinic_flatten × seed 0 × 5 折搜索（D4 早停 + 历史最优）；④ 三臂对照——臂 B（工作组合 × scheme 模板，复用 Test_2b）、臂 B'（工作组合 × bank 模板）、臂 C（贪婪最优 × bank 模板），头条 Δc = C − B'，交叉核对 C − B；⑤ 遗漏字段清单（C \ 工作组合，附 bank 语义）+ 跨四工作组合的覆盖率表。

### 输入

- `z_notes/Test_series_spec.md`（§2.4 绑定 / §7 Test_3 / §9 Git / §10 日志 / §11 禁令）、`z_notes/E2_Selection_Gain_Algorithm/E2_selection_algorithm_design.md`、experiment_list Test_3 行、本日志 R7（D4 确认）/R13。
- 搜索池：`outputs/{ds}/field_bank/prompt/landmark_0/`（prompt bank + CONCH 嵌入）——**先核验再放量**：15/15 主集齐备（field_index.json + 每患者 pt；行数=患者数），本次未新增生成（0 个缺失）。
- 数据集名单：`results/Test_0_dataset_availability/manifest.csv` 与 `rawdata_stats/_shared/event_summary.csv` 双源交叉核对（`Test_3_common.load_n_event`，不一致即抛错），主集 = n_event ≥ 100 的 15 个，**不硬编码**；`TCGA_LIHC` 为下划线命名（按 "TCGA" 前缀匹配，严格 "TCGA-" 会漏成 14）。

### 遗留设施接管（采纳的他人未提交修改，全部纳入本次提交）

- `scripts/run_e2_selection_queue.py`：新增 `--inner_analyzer`（逗号分隔，每个 analyzer 独立 conf/结果目录）+ `LEGACY_ARG_KEYS={"inner_modality"→"inner_analyzer"}` 兼容映射 + 空 dataset 守卫。
- `src/selection/runner.py`：多 analyzer 循环（输出目录 `.../{modality}/seed_0`），prior/anchor 按 (modality, seed) 取，timing train_args_hash 并入 modality。
- `src/selection/report.py`：modality 升为分组维度（聚合/H1/H2/anytime/anchor-gap 图与 CSV 名称均含 modality）。
- `tests/test_e2_queue.py`：新增 legacy 键映射与「job_key 随 inner_analyzer 分家」两测试。
- 未改动 E 组算法本体（`stopping.py` 的 SigStop(delta=0.005, patience=3) 与 A2_greedy 均为既提交版本，只读复用；本步新增 `tests/test_e2_greedy_sigstop.py` 锁定 D4 口径：三连无改进（gain<0.005 且 Wilcoxon p≥0.05）触发、混合情形复位、stop 时 `recommended_subset`=k_sig 点、`best_subset`=历史最优、缓存复用零物理训练）。

### 命令与参数（本步产物全部在 `results/Test_3_greedy_vs_works/`）

```bash
# 搜索：15 主集 × A2_greedy × landmark_0 × mlp_clinic_flatten × seed 0（9 槽并发，避开 GPU 7=S5b）
python3 scripts/Test_3_search_queue.py enqueue --gpus 1,0,3,4,5,6,4,5,3
nohup python3 scripts/Test_3_search_queue.py watch --gpus 1,0,3,4,5,6,4,5,3 --interval 60 &
# 三臂 B'：generate → encode（conch env，GPU 1）→ enqueue → drain（GPU 1，workers 2）
python3 scripts/Test_3_arms.py generate --arm bp
python3 scripts/Test_3_arms.py encode   --arm bp --gpu 1 --parallel 3
python3 scripts/Test_3_arms.py enqueue  --arm bp
python3 scripts/Test_3_arms.py drain    --gpu 1 --workers 2
python3 scripts/Test_3_arms.py summarize --arm bp
# 三臂总表（臂 C 待搜索 result.json 落盘后 generate --arm ksig 再补齐）
python3 scripts/Test_3_compare.py --all
# 总入口：bash scripts/Test_3_queue.sh {search_watch|arms_encode_bg|arms_drain|compare|all_status}
```

- A_pipeline 两处缺口（`expand_cindex_jobs` 静态方案白名单拒自定义方案；`encode.run_encode` 硬设 `CUDA_VISIBLE_DEVICES=DEFAULT_GPU="7"`）**不改其源文件**（他人工作树有未提交修改），由 `scripts/Test_3_pipeline_one.py` 进程内补：运行时把 Test_3 方案追加进 `config.PAPER_SCHEMES`（与 cindex 共享同一 list 对象）并改写 paths/encode 的 `DEFAULT_GPU`；磁盘文件零改动（测试断言 schemes.json 字节不变）。
- 方案登记：64 个 Test_3_* 自定义方案写入 `A_pipeline/templates/{name}/`（fields.json/template.csv/Test_3_meta.json）并登记 `schemes.json` `_schemes`（幂等）；模板取自 `templates/field_bank/{ds}/landmark_0/FIELD_BANK.csv` 的 template 列，字段无 bank 句子时回退工作方案自身句子并记入 meta 的 `fallback_fields`（控制变量：字段集与工作组合**逐字段一致**，只换模板）。
- 表目录坑（记录）：`scripts/s4_enqueue.py` 的表键是 `{dataset}[gdc]`，summarize 必须传 `dataset_name=f"{dataset}[gdc]"`，否则 Test_3 行会另建无后缀表与臂 B 行分家。

### 产物

- `results/Test_3_greedy_vs_works/search/{ds}/mlp_clinic_flatten/seed_0/{evaluations.jsonl,result.json}`（进行中）。
- `results/Test_3_greedy_vs_works/three_arm.csv`、`missed_fields.csv`、`compare/{ds}__{work}.json`、`search_summary.csv`（搜索完成后由 report 写）；展示副本 `results_display/Test_3_greedy_vs_works/`（不提交）。
- 新增代码：`scripts/Test_3_{common,search_queue,custom_scheme,compare,arms,pipeline_one}.py`、`scripts/Test_3_queue.sh`；测试：`tests/test_test3_{common,search_queue,arms_chain}.py`、`tests/test_e2_greedy_sigstop.py`。

### 审计

- 单测：新 4 个 E2/Test_3 测试文件 + 全量 `python3 -m pytest tests/`（base 3.13.12）= **185 passed, 6 skipped**，无回归。
- 三臂链路冒烟（TCGA-LAML，MULTISURV 例）：B（Test_2b 表内行）0.5436 vs B'（bank 模板）**0.5997** vs C（待搜索）；compare 数学路径以 B' 冒充 C 验证 Δc 与遗漏字段链路通过；臂 C 缺行时按预期 `MissingArm` 记 pending 不中断。
- 手算抽查 ≥2（5 折 val_cindex 均值/标准差 vs 表内行，1e-9 级一致）：TCGA-LAML MULTISURV B' = 0.599741142836（std ddof=1 = 0.074326）；TCGA-BLCA MULTISURV B' = 0.652529260943（std = 0.054227）。
- 控制变量核对：抽查 (LAML/LIHC/BRCA) 的 B' fields.json 字段集与对应 work 方案**完全一致**，datasets 标签正确。
- 遗留差异（不处理，仅记录）：`A_pipeline/templates/Test_3_MULTISURV_TCGA-ACC/`（R12 改名遗留、未登记 schemes.json、ACC 不在主集）保持原样不动。

### 偏差与原因

- **方案 C 位号取自 `recommended_subset`（sig_stop 参考点）**，历史最优 `best_subset` 另存 result.json 并在 report/status 中同报（D4 要求）——臂 C 用 recommended，附录可另行核对 best。
- 三臂表目录初版误建为无后缀（`results/A_manual_landmark/TCGA-LAML/`），已删除并按 S4 约定改回 `{dataset}[gdc]`。
- encode 的 GPU：任务要求避开 GPU 7（S5b 占用），编码与 cindex 训练均走 GPU 1（编码期显存 ~1.3 GB/进程）；搜索 drainer 槽位 `1,0,3,4,5,6` 有重复条目（每卡多槽）以在他人低载 GPU 上并发，绝不触碰他人进程。

### 决策点

- 无新增待决项。固化：① 搜索池 = landmark_0 prompt bank（与 Test_3b 取消后的口径一致）；② 臂 C 位号 = recommended_subset，best 附录；③ 遗漏字段按字段名集合差（C \ work），语义列取 bank 模板句子；④ A_pipeline 缺口走进程内补丁，源文件零改动。

### 状态

- 搜索：9/15 在跑（BLCA/BRCA/COAD/GBM/HNSC/KIRC/LAML/LGG/LUAD），6 个待槽（LUSC/OV/PAAD/SKCM/STAD/LIHC）；截至本条目 LAML 26 evals、KIRC 12、BLCA 11、COAD 10（池规模 21–39 字段/数据集）；watch 自愈进程已挂（`results/Test_3_greedy_vs_works/logs/watch.log`），全 done 自动写 `search_summary.csv` 并退出。
- 三臂 B'：64/64 方案生成+编码完成；enqueue created=60 existing=4；drain 进行中（cindex 队列 done 567，本批完成 14/64，2 running 48 queued，零 failed）。
- 续跑命令：`bash scripts/Test_3_queue.sh search_status`；LAML 搜索出 result.json 后 `python3 scripts/Test_3_arms.py generate --arm ksig && ... encode/enqueue/drain --arm ksig`（方案名 `Test_3_greedy_{ds}`）；全部完成后 `python3 scripts/Test_3_arms.py summarize --arm bp && python3 scripts/Test_3_compare.py --all`。
- 提交：本步代码/脚本/测试/文档入库（results/、results_display/ 按纪律不提交）。

**补记（20:10）**：为避免人工守候搜索结果，新增 `scripts/Test_3_arm_c_chain.sh`（后台轮询：某数据集 `result.json` 落盘即自动 `generate --arm ksig` → `encode` → `enqueue`，15/15 就绪后自动 drain + summarize + `compare --all`），已以 nohup 挂起（日志 `results/Test_3_greedy_vs_works/logs/arm_c_chain.log`）。臂 best 附录（历史最优 `best_subset`）未自动跑，需要时：`python3 scripts/Test_3_arms.py generate/encode/enqueue/drain --arm best`。

**补记 2（20:30）**：`Test_3_compare.py` 补齐 spec §7.3 的展示层图：`--all` 在有三臂行时输出 `results_display/Test_3_greedy_vs_works/three_arm_delta.png`（左：每数据集均值 Δc 头条 C−B′ 与交叉 C−B；右：Δc vs 遗漏字段数散点）；英文标签（沿既有 matplotlib 约定，默认字体无 CJK 字形）。新增测试 `test_batch_writes_table_missed_and_figure`（表/遗漏清单/镜像/图路径全链路，空表不画图）。

---

## 维护（M1）命名统一重构：Test 编号为主键的三处目录公约

- 时间 / 执行者：2026-10-02 / Claude（主会话）
- 目标：`Clinic_Analyzer/configs`（实验定义）、`results`（结果）、`results_display`（展示）三处目录以 Test 编号为主键统一命名，同一实验在三处用同一名字，便于检索。
- 用户决策（2026-10-02）：① 全量统一（共享家族拆分：A_manual→Test_2b_arms+Test_3_arms 等）；② 物理迁移等当前跑批（Test_3 搜索/三臂、Test_1a off 臂）自然结束后执行；③ 遗留目录归档到 `results/_archive/`。
- 公约与对照表：`z_notes/experiment_list/naming_convention.md`（唯一权威）；实验清单 `experiment_list.md`、三处 README 已按新名更新。
- 执行方式：分步进行，每步一次本地提交（不 push）：① 基线归档（1ca3f45）；② 公约文档 + README（本步）；③ 代码路径登记与新旧兼容；④ configs 家族物理迁移（drain-gated）；⑤ results/results_display 物理迁移与收尾。
- 状态：进行中（截至本条目完成第 ①② 步）。

**补记（2026-10-02 深夜，M1 完成）**：迁移四步全部完成并逐步提交——① 基线 `1ca3f45`；② 公约文档+README `c08bf04`；③ 代码路径登记+兼容 `60148c6`；④ configs 物理迁移 `b698cb7`（E2_selection 的 9 个 stale running conf 恢复回 queue）；⑤ results/results_display 物理迁移（本步）。迁移后 resolve 全命中新名；tests/ 186 passed+6 skipped、A_pipeline 44 passed。规格文档产物路径已同步新名；执行日志历史条目未改。

---

## S5d: 结果文件 Main/Appx/Raw/Meta 前缀重组与脚本同步（条件化字段主表，2026-10-02）

- 时间 / 执行者：2026-10-02 深夜 / Claude（结果展示层整理 agent）
- 目标：把三个结果目录（`results_display/{Test_1a_field_level,Test_1b_dataset_cindex,Test_2b_delta}`）的文件角色前缀约定（用户指令 2026-10-02）落到生成脚本——① 输出文件名改前缀；② 输入路径同步新树；③ 新增条件化字段主表 `Main_field_ranking.csv`；④ 重跑验证 diff=0；⑤ 清理旧名遗留。**目录结构不动**（主键 = Test 编号，`z_notes/experiment_list/naming_convention.md`），纯分析不训练。

### 前缀公约（用户指令 2026-10-02）

- `Main_` = 头条（回答命题）、`Appx_` = 附录（明细/主表补充）、`Raw_` = 原始矩阵、`Meta_` = 元数据与审计；三个目录内**平铺，无子目录**；各目录 README.md 为逐文件地图。
- 旧名 → 新名逐项对应：Test_1a 11 项（含新表）、Test_1b 14 项、Test_2b 26 项（4 CSV + 22 PNG）。

### 输入（全部新树，ls 核实内部层后照现状改）

- Test_1a：t0 臂 `results/Test_1a/arm_t0/prompt/landmark_0/{ds}/mlp_clinic_flatten/field_cindex.csv`；off 臂 `results/Test_1a/arm_off/univariate/prompt/landmark_none/{ds}/mlp_clinic_flatten/field_cindex.csv`（16 个数据集目录 = 主集 15 + TCGA-ACC）；主集名单仍由 `results/Test_0_dataset_availability/manifest.csv` 的 n_event ≥ 100 派生（15 个），**不硬编码**。
- Test_1b：t0 臂同源路径（33/33 齐备）；名单 datasets.json + manifest + event_summary 分层。
- Test_2b：`results/Test_2b/arm_B/{ds}[gdc]/cindex.csv`（S4 summarize 把报告臂 `{scheme}__landmark_none` 与去泄露臂 `{scheme}__landmark_0` 写进同一张表，配对即取此表；c 值以 run 折文件为准）+ `arm_B/labels/`（审计）。
  注：`results/Test_2b/arm_A/{ds}[gdc]/cindex.csv` 是论文报告值原表（4 方案 × 5 modality，行名无 landmark 后缀），只作 Test_4 三档参考，**不参与 Δc 配对**（同链路对照才可比）——已写进脚本 docstring。
- 路径构造仍走 `src/common/paths.py` 的 `test_results_dir` / `remap_legacy_result_path`（新名优先，LEGACY 回退仅兜底陈旧 run_config，脚本字面量只写新名）。

### 命令与参数（base python 3.13.12）

```bash
python3 results_display/scripts/Test_1a_field_level.py --audit
python3 results_display/scripts/Test_1b_dataset_cindex.py --audit
python3 results_display/scripts/Test_2b_delta_report.py --audit
```

（均默认 out_dir = 各自结果目录；Test_1a/Test_1b 默认 `--t0_root/--univariate_root` 已是 arm_t0 新路径。）

### 产物

- `Test_1a_field_level/`：`Main_mask_group_delta.png`、**`Main_field_ranking.csv`（新）**、`Appx_{off_vs_t0,delta_by_dataset,delta_distribution}.png`、`Appx_{field_delta,dataset_summary,influential_fields}.csv`、`Raw_delta_matrix.csv`、`Meta_{metrics,audit}.json`。
- `Test_1b_dataset_cindex/`：`Main_{per_dataset_profile,topk_overlap}.png`、`Main_{topk_overlap,dataset_summary}.csv`、`Appx_{per_dataset_distribution,cross_dataset_field_spread,topk_overlap_matrix}.png`、`Appx_{field_summary,topk_members}.csv`、`Appx_topk_pairwise_k{5,10,20}.csv`、`Raw_cindex_matrix.csv`、`Meta_metrics.json`。
- `Test_2b_delta/`：`Main_{overview_clinic_cox,overview_mlp_clinic_flatten}.png`、`Main_delta_summary.csv`、`Appx_forest_{scheme}_{analyzer}.png` ×20、`Appx_delta_{main,supp,low}.csv`。

### 条件化主表口径（`Main_field_ranking.csv`）

- **只统计取值确实被 mask 改动的行**（`mask_affected=True`，来自 `outputs/_raw/{ds}/field_bank/prompt/landmark_none/raw_value_diff.json` 的 changed_cells > 0）；未改动行是噪声本底，不参与排序。
- 列：`field` / `n_datasets_total`（该字段有配对行的数据集数）/ `n_datasets_affected`（取值被改动的数据集数 = 涉及面）/ `median_delta_among_affected`（仅 affected 子集的中位 Δc = 大小）/ `frac_abs_delta_ge_0p05`（affected 子集中 |Δc| ≥ 0.05 占比 = 一致性）/ `max_abs_delta`（该字段**全部**数据集上的 max |Δc|）。
- 排序：`median_delta_among_affected` 降序；无 affected 数据集的字段排表尾（中位/占比列留空）。一致性阈值 0.05 固化为常量 `CONSISTENCY_DELTA`（列名固定，不随 CLI 阈值变）。
- 旧的**无条件** `Test_1a_field_summary.csv` 删除；其内部聚合（`summarize_fields`）保留但不落盘，只用于 `Raw_delta_matrix.csv` 的字段列序（|Δc 均值| 降序）——该列序是既有产物既定口径，改则破坏 diff=0。

### 审计

- **重跑 diff=0（脚本级）**：三个脚本同输入重跑，产物与改名后磁盘文件**逐字节一致**——Test_1a 10/10、Test_1b 14/14、Test_2b 26/26 = **50/50**（`Main_field_ranking.csv` 为新增，磁盘原先没有）。
- **连跑两次稳定性**：第二次连跑后 51/51 产物 sha256 不变（11+14+26，含新表）。
- **清单核对（新逻辑）**：三脚本 main() 末尾新增 `check_out_dir_inventory`——遍历 out_dir 核对本脚本产物清单（新前缀名集合）并对清单外文件告警（README.md 白名单）；首跑在 Test_2b 报出 26 个旧名遗留，清理后二跑零告警。
- **--audit 抽查（逻辑未改）**：Test_1a 3 组 OK（BRCA idx28/38、PAAD idx10，重跑 Meta_audit.json 与磁盘逐字节一致）；Test_1b ALL PASS（GBM/ESCA/SARC × 字段，per_fold 独立重算）；Test_2b ALL PASS（3 组 × 4 项检查：Δc 独立重算 / stale 标记自洽 / SEED 两臂一致 / 臂B=臂A−排除患者 5 折）。
- **新表抽查（3 字段，与 `Appx_field_delta.csv` 手算核对）**：`treatment_type_administered`（total 2 / affected 2 / median 0.136279 / frac 1.0 / maxabs 0.195297）、`route_of_administration`（3/3/0.116070/1.0/0.134370）、`menopause_status`（1/0/—/—/0.000259）——n_affected 与 median_among_affected 全部一致。
- **旧名遗留清理**：`Test_2b_delta/` 内 26 个旧名文件逐个 sha256 与新名文件核等后删除（目录 53 → 27 文件）；Test_1a/Test_1b 无旧名遗留。

### 偏差与原因

- `Test_1a_field_level/README.md` 结论句「mask 改动的字段 Δc 均值 **+0.061**」与当前产物口径对不上：产物 `Meta_metrics.json` 的 `delta_c_by_mask_group.mask_affected.delta_mean` = **+0.034**（未改动组 +0.001）；另试算逐字段均值/逐数据集均值/|Δc| 均值/timed_family 分组等口径均非 0.061，疑为 off 臂未跑齐时的中间数（早期 2 数据集冒烟值为 +0.087）。**未改用户结论文本**（本步只同步文件名），在此标记待用户裁定。
- `Appx_leak_vs_delta.png` 为条件产物：Test_2a 逐字段审计（`results/Test_2a_leak_audit/{ds}/G1_*.json`）未出数 → 不生成，`Meta_metrics.json` 记 `leak_rate_status=pending_test_2a`；已在 Test_1a README 注明。
- 三个目录内 README.md 被 `projects/.gitignore`（`results_display/**`）忽略：本步提交只含已跟踪的 `results_display/README.md`，目录内 README 留在磁盘不入库（如需入库须 `git add -f`，未做）。
- 新树路径本身与脚本既有常量一致（前步 S5c/M1 已改过路径，本步只核实）：off 臂内部层确为 `univariate/prompt/landmark_none`（保留层，非旧名残留）。

### 决策点

- ① `max_abs_delta` 取"该字段全部数据集"（列名无 affected 限定词，中位/占比两列已显式限定 affected）——脚本 docstring 与目录 README 均写明。
- ② 一致性阈值 0.05 固化常量，不随 `--delta_threshold`（0.01）/`--leak_threshold` 变。
- ③ `Raw_delta_matrix.csv` 列序沿用既有 |Δc 均值| 降序（内部聚合），不用新表排序——保 diff=0。
- ④ Test_2b 两臂都从 arm_B 汇总表读（同链路配对），arm_A 原表不参与 Δc；docstring 已澄清。
- ⑤ 脚本新增"产物清单核对"只打印告警、不改产物（不影响 diff=0 口径）。

### 状态

- 完成：三脚本输出名 / 输入路径 / docstring 产物清单 / 清单核对全量同步；三个目录重跑 diff=0（50/50 改名文件逐字节一致 + 新表生成）；旧名遗留清零。
- 本步提交（**本地提交，不 push**）：`results_display/scripts/{Test_1a_field_level,Test_1b_dataset_cindex,Test_2b_delta_report}.py`、`results_display/README.md`（Test 系列索引，含新表入口）、本日志条目。
- 遗留：① 上述 +0.061 数字待用户裁定；② Test_2a 逐字段审计出数后重跑 Test_1a 脚本即自动补 `leak_rate` 列 + `Appx_leak_vs_delta.png`（无需改代码）。

---

## S2c: Test_2a 泄露审计按新口径重跑（值来源槽位 t_hi 判定）（2026-10-03）

- 时间 / 执行者：2026-10-03 / Claude（S2c 执行 agent，用户指令）。
- **交接记录**（R9 → 用户 → 本步）：R9（2026-09-30）记录的旧口径纠错当时"已写入 spec §2.1，S2c 待执行"，并注明纠错由用户接手；本次用户下达执行指令 = 交接完成，本步即 S2c 落地。上述"遗留 ②"（Test_1a leak_rate 列待 Test_2a 出数）在本步一并关闭。

### 新口径（唯一依据 = spec §2.1，§5.2 已重写）

- `leak_rate(f, D) = #(实际进入模型的值来自 t_hi > 0 槽位的患者) / #(管线产出有效值的患者)`；无人工阈值；**泄露字段 = leak_rate > 0**。
- 旧口径 `1 − n_valid_t0/n_valid_none`（"t0 完全缺失比例"）作废，**S2b 旧数字作废**（S2b 产物本身未动，仅其"泄露率"交叉数值作废）。
- 取值 = 论文管线本身（`A_pipeline/src/extract.py::extract_values(case, landmark_time=None)`，无任何泄露处理），**不是** Field Bank 提取逻辑；来源槽位时点 = `src/time_stats.py` 的 t_hi（与 Test_2b landmark 三要件同机制）。
- 状态处理按 `z_notes/time_axis/time_axis.md` §4.1：`point`/`bounded` 有限 t_hi > 0 → 泄露；`lo_only`（t_hi = +∞，"任何有限 T 都不放行"）→ 泄露；`unlocated`/`non_informative`（无 t_hi）→ **不判泄露**，单列 `n_unlocated_source`；另报 `n_t0_blocked` = 泄露 ∪ 未定位（与旧口径对照用）。无时点家族（demographic/exposures/family_histories/project）恒不泄露。

### 实现（工作区改动审查结论）

- 用户工作区唯一的源码改动是 `results_display/Test_2a_leak_audit/scripts/audit_leak.py`（非 `src/leak/`）：† 脚注澄清"不在 Field Bank ≠ 不进模型"——**采纳**（与 spec 一致，保留进本步提交）；同文件其余部分仍是旧口径（读 `n_valid_none`/`n_valid_t0`/`mask_applicable`、脚注写 `1 − n_valid_t0/n_valid_none`）——**照新口径改写**：逐字段行改读 `n_valid`/`n_leak`/`n_t0_blocked`/`max_source_t_hi`/`audit_mode`（新增 `n_a_pipeline` 聚合列替换 `n_masked`），脚注/图题改为新定义文本，并加"非新口径产物即报错"守卫（缺 `n_leak_total`/`n_valid_total` 列时提示先 `--prune` 重跑）；两张图与两张聚合表已按新口径重出。
- `src/leak/`：新增 `provenance.py`（值来源追溯引擎：A_pipeline 取值镜像 + 逐患者比对不一致即报错；来源实体 → 槽位；`derived.*` 按 A_pipeline 自身派生逻辑追底层槽位；Field Bank 模式复用 `extract_field_bank_value(landmark=False)` + 同规则追溯）；`audit.py` 重写为新口径逐字段统计 + 每数据集共享用例缓存 + G1 逐字段产物；`cli.py` 去 `--landmark_time`、加 `--no_g1`。只读复用 A_pipeline / discovery / time_stats，未改其实现。
- 取值模式（`audit_mode` 列）：字段在 A_pipeline `extract_values` 表内 → `a_pipeline`（本规格要求）；只在 Field Bank 宇宙（Test_1a kept 字段）→ `field_bank`（`landmark=False`，与 Test_1a off 臂同源）。

### 产物（138 + 1083）

- `results/Test_2a_leak_audit/{dataset}/{scheme}.json` **138 个**（33 TCGA × 10 方案，§2.4 绑定：HGCN_* 仅其癌种、泛癌种 × 33，剔除 CPTAC/MMRF；数据集名单来自 `datasets.json`，无硬编码）+ `leak_audit_summary.csv` **138 行**；Test_1a 消费的 `{dataset}/G1_{md5(field_idx)}.json` **1083 个**（33 数据集 × 各自 landmark_0 kept 字段）。
- 旧口径产物用 `--prune` 清理后重出；产物无时间戳（`audit_version` 常量），同命令重跑 `diff -r` = **0**（已产出的真实根目录上核对）。
- 全量数字：`n_leak_total` 合计 1020 / `n_valid_total` 合计 247538（合计率 0.41%）；仅 4 个方案字段泄露：`diagnoses[].prior_treatment`（跨队列 mean 0.0219，max 0.7232 = SKCM 337/466）、`diagnoses[].primary_diagnosis`（mean 0.0205，max 0.7170 = SKCM 337/470）、`derived.radiation_therapy`（mean 0.0198，max 0.1871）、`derived.pharmaceutical_therapy`（mean 0.0193，max 0.1899）；138 组合中 34 个 ≥ 1 个泄露字段（MULTISURV 33 队列里 15 个有，HGCN 6 个各 1–3 个，SURVPGC 1 个，MMSURV/INTEGRATIVE_DNN 为 0）。

### 验证

- **独立抽查 5 组**（`/tmp/s2c_spotcheck.py`，**不 import `src/leak`**：自读 clinic JSON + 自写字段级规则与槽位映射计数，取值另与 A_pipeline / Field Bank 官方函数逐病例交叉验证）：全部 PASS——①SKCM/SURVPGC/`diagnoses[].primary_diagnosis` 337/470=0.717021；②SKCM/MULTISURV/`diagnoses[].prior_treatment` 337/466=0.723176（含 unlocated 来源病例）；③BRCA/MULTISURV/`derived.pharmaceutical_therapy` 14/333=0.042042；④BRCA/G1_4e732ced34/`diagnoses[].treatments[].therapeutic_agents` 756/774=0.976744（field_bank 模式）；⑤SKCM/MULTISURV/`demographic.race` 0/460（无时点家族恒不泄露）。①另用完全不依赖 time_stats 的 raw 判据（`days_to_diagnosis > 0`）复核：337 = 337，逐病例 0 例分歧；旁证中发现 `days_to_diagnosis = −2` 的点病例（TCGA-EB-A4OY，t_hi = −2 ≤ 0 不判泄露），佐证"判据用 t_hi 而非原值非缺失"的必要性。
- **重跑 diff=0**：真实根目录同命令重跑并 `diff -r` = 0（已述）；`tests/test_leak_audit.py` 重写为 29 个用例（含 future-slot → 泄露、t_hi ≤ 0 → 不泄露、lo_only → 泄露、unlocated → 不泄露但计数、无时点家族恒不泄露、derived 追底层槽位、G1 schema 对齐 Test_1a 消费端、重跑逐字节一致、CLI 产物/`--no_g1` 等）。
- **全量 pytest 无回归**：`python3 -m pytest tests/ -q` = **198 passed, 6 skipped**（提交前基线 17 个旧用例已被新用例集替换并扩充）。
- 已知口径怪癖（记录不改）：A_pipeline 的 `clean_value` 只认 5 个占位符（含 "not reported"），raw 的 "not evaluated" 等会被当作有效值 → 这些患者计入分母。

### Test_1a 联动（关闭遗留 ②）

- 重跑 `python3 results_display/scripts/Test_1a_field_level.py`：`leak_rate` 列 **468/468 全部填充**（`leak_rate_status = ok`，此前全为 `pending_test_2a`）；`Appx_influential_fields.csv` 由空表 → **97 行**；`Appx_leak_vs_delta.png` 新生成；`Meta_metrics.json` 的 `n_leak_available=468 / leak_scatter_plotted=true`。
- **未受影响产物逐字节一致**（8 个：`Appx_dataset_summary.csv`、`Appx_delta_by_dataset.png`、`Appx_delta_distribution.png`、`Appx_{off_vs_t0}.png`、`Main_field_ranking.csv`、`Main_mask_group_delta.png`、`Raw_delta_matrix.csv`、`Meta_audit.json`）；仅 3 个 leak 相关产物变化（`Appx_field_delta.csv`、`Appx_influential_fields.csv`、`Meta_metrics.json`）+ 1 个新增（`Appx_leak_vs_delta.png`）——符合预期。
- 新列样例（`Appx_field_delta.csv`）：`TCGA-OV / diagnoses[].treatments[].treatment_dose / leak_rate=1.000000, Δc=+0.081860`；`TCGA-HNSC / number_of_fractions / 1.000000, +0.062431`；`TCGA-LGG / clinical_trial_indicator / 1.000000, +0.024600`；清单里高 leak 字段基本全为 `diagnoses[].treatments[].*`（field_bank 模式，治疗槽位晚于 t0）。

### 决策点

- ① 泄露判据按 spec §2.1 取 `t_hi > 0`；`lo_only` 按 time_axis.md §4.1 判泄露（当前数据 0 例），`unlocated`/`non_informative` 不判泄露但单列计数——三者不混入 `leak_rate`。
- ② `n_leak_total/n_valid_total` 为字段级分子分母的**直接求和**（非率平均），供对照审计口径。
- ③ Test_1a kept 字段中不在 A_pipeline 取值表的（1083 个条目的 648 个）走 `field_bank` 模式并在行内记 `audit_mode`——spec §5.2 第 5 条；A_pipeline 宇宙内字段一律 `a_pipeline`。
- ④ Test_2a 展示脚本的 † 脚注按用户改动保留（"不在 Field Bank ≠ 不进模型"）。
- ⑤ 每个方案字段的 `not_in_bank`（多数为 True）只作"无依据"证据，不代表不进模型。

### 状态

- 完成：spec §5.2/§5.3 重写、新口径实现（`src/leak/provenance.py` + audit/cli）、138 + 1083 产物重出（prune + diff=0）、5 组独立抽查 PASS、全量 pytest 198 passed、Test_1a 联动补齐（468/468）与未受影响产物 byte 一致核对、Test_2a 展示脚本与图按新口径重出。
- 本步提交：`src/leak/{provenance.py,audit.py,cli.py}`、`tests/test_leak_audit.py`、`z_notes/Test_series_spec.md`、`results_display/Test_2a_leak_audit/scripts/audit_leak.py`、本日志条目；`scripts/run_leak_audit.py` 无改动（薄封装）。提交后 push origin main（用户明确要求）。
- 遗留：① S5d 记的 `Test_1a_field_level/README.md` "+0.061" 数字仍待用户裁定（本步未动）；② Test_1a 目录内 README 仍不入库（gitignore）。

---

## S6 续跑：Test_3 搜索与臂 C 链恢复（2026-10-03）

- 时间 / 执行者：2026-10-03 14:00–14:40 / Claude（S6 续跑执行 agent，用户指令"续跑"）
- 目标：按"R13 / S6 提前终止与归档"条目给出的续跑方法恢复 Test_3 批跑——① 现场核实队列与搜索中间态；② 重启搜索 watch + drainer（自愈：drainer 死后拉起 / failed 限次重试 / running 回收 / 全 done 自动 report 退出）；③ 重启臂 C 接力链（result.json 落盘即 generate→encode→enqueue，15/15 就绪后自动 drain + summarize bp/ksig + `Test_3_compare.py --all`）；④ 验证与进度估计。
- 输入：`z_notes/Test_series_spec.md` §7/§9/§10、本日志 R13 与 S6 提前终止条目、`z_notes/experiment_list/naming_convention.md`（目录已迁移新名）。

### 现场核实（开工快照，与指令描述一致）

- 搜索队列 `Clinic_Analyzer/configs/Test_3_search/`：queue 9 / running 0 / done 0 / failed 0 + **missing 6**（LUSC、OV、PAAD、SKCM、STAD、TCGA_LIHC 从未投放）。9 个 queue conf 仍带上次的 `claimed_*` 字段（claimed_pid 全为已死进程）；`recover` 只扫 running 桶，但 claim 迁移时会重写这些字段，不影响续跑。
- 搜索中间产物：9/15 数据集有 `search/{ds}/mlp_clinic_flatten/seed_0/evaluations.jsonl`（19–106 evals，LAML 最远到 k=6）与 `clinic/jobs/G1_*.json`；0 个 result.json；E2 评估缓存 `results/Test_3_search/cache.sqlite` 424 条。
- 臂 B′：`configs/Test_3_arms/` done 64 / queue 0 / running 0 / failed 0（64 = 15 主集 §2.4 绑定，KIRC/LIHC/LUAD/LUSC 各 +1 HGCN）；但 LUSC/OV/PAAD/SKCM/STAD 的 arm_B 汇总表缺 Test_3_* 行（上次 drain 结束后未 summarize）。
- 臂 C：未开始（`three_arm.csv` 仅表头）。脚本名与路径与指令一致（`scripts/Test_3_queue.sh`、`scripts/Test_3_arm_c_chain.sh`）。

### 命令与参数

```bash
bash scripts/Test_3_queue.sh search_enqueue      # created=6 existing=9 → queue 15
T3_SEARCH_GPUS="0,2,3,4,5,6,0,2,3,4,5,6,0,2,3" T3_INTERVAL=60 \
  setsid bash scripts/Test_3_queue.sh search_watch            # 15 槽；log results/Test_3_greedy_vs_works/logs/watch.log
python3 scripts/Test_3_arms.py summarize --arm bp             # 补 5 数据集 B′ 行（64/64）
T3_ENC_GPU=1 T3_GPU=1 T3_WORKERS=8 T3_POLL=120 \
  setsid nohup bash scripts/Test_3_arm_c_chain.sh >> results/Test_3_greedy_vs_works/logs/arm_c_chain.log 2>&1 &
```

- GPU 现场自察：8 卡全部空闲（他人 S5b 进程已结束，GPU 7 不再被占）；按"勿动他人进程"留 GPU 1 给编码 + 臂 C drain（8 workers）、GPU 7 作余量，搜索用 0,2,3,4,5,6（15 槽 = 0/2/3 各 3、4/5/6 各 2；每 drainer 实测 1.1–1.8 GB 显存，卡利用率 60–96%）。

### 审计（抽查与核验）

- 15/15 搜索 drainer 起跑（queue 15→running 15，0 failed）；watch 每 60 s 记 done/running/queue/failed。
- **恢复语义**：重跑的 evaluations.jsonl 先追加上次结果的 cache 命中行（`physical_cache_hit=true`），LAML 106→212 行，未重算（缓存 424 条命中）。
- 臂 B′ 汇总补齐：LUSC/OV/PAAD/SKCM/STAD 各 4–5 行，15/15 主集齐（64 行）。
- **折文件手算抽查**：全部 64 条 B′ 行 vs `results/Test_2b/arm_B/runs/{study}__{scheme}__landmark_0/mlp_clinic_flatten/val_result_fold{0..4}.csv` 末行均值 —— **64/64 逐位一致**（含 std，1e-12 级）。示例：TCGA-BLCA MULTISURV B′ = 0.6525292609427339（std 0.05422664486967521）、TCGA-LAML MULTISURV B′ = 0.599741142836137（std 0.07432604899992913）。
- **修复 1 行 B′ 陈旧值（LUAD × MULTISURV）**：表内 0.6647328174441 = 仅前 4 折均值（std 0.0546046），实测 5 折 = 0.6781159771803179。根因 = summarize 与该 run 末折并发（fold4 落盘 20:41:28 前后读取）；`_merge_cindex_rows` 只保留既有行不刷新，且表由 `run_config.json` 的 rows 重建（只改 CSV 会被覆盖）。处置：从 `run_config.json` rows 摘除该行 → 重跑 `summarize --arm bp --datasets TCGA-LUAD` 重新 derive → 复核 5 行全一致（旧 run_config 备份 `/tmp/Test_3_luad_run_config.json.bak`；只重写该表的 Test_3 行，臂 B 行未动）。
- **附带发现（未改，上报）**：Test_2b arm_B 汇总表 `results/Test_2b/arm_B/{ds}[gdc]/cindex.csv` 的 `*__landmark_0 × mlp_clinic_flatten` 行 **32/64 与折文件不符**（同一读竞态，如 LAML MULTISURV = 前 4 折、LAML SURVPGC = 前 2 折、KIRC HGCN_KIRC = 仅 fold0 且 std=0.0）。这些行是 Test_4「去泄露值」档与 Test_3 表 `delta_C_minus_B` 交叉列的数据源，且 `_merge_cindex_rows` 永不自愈。修复需删 stale 行（CSV + `run_config.json`）后重跑对应 `summarize`——会改动 Test_2b 产物与既有展示层，**未擅自执行，待用户裁定**。

### 进度与预计（14:12 快照）

- 每 eval ≈ 106 s（5 折 MLP，数据集内串行）；15 数据集并行。各集已评估数：LAML 108（k=6 收尾）、KIRC 59、BLCA 54、COAD 48、LGG 40、LUAD 39、GBM 34、HNSC 26、BRCA 19、PAAD 2、LIHC 1，LUSC/OV/SKCM/STAD 起步中（0）。
- 池规模 19–45 字段；按 sig_stop 早停推测单集需 ~150–250 evals → 4.5–7.5 h；**首个 result.json 预计由 LAML 出**（k=4/5/6 增益均 <0.005，三连无改进即停），随后臂 C 链自动接力；三臂总表预计当晚（14:08 起算 5–8 h）。
- 查进度 / 续跑命令：`bash scripts/Test_3_queue.sh all_status`；`tail -f results/Test_3_greedy_vs_works/logs/{watch,arm_c_chain}.log`；搜索 drainer 死后由 watch 自动拉起，watch 本身若被 kill 则重跑本条 `search_watch`（幂等，会从 running 桶恢复在跑任务）。

### 偏差与原因

- 无脚本/路径口径偏差（现场与指令一致）；搜索并发从上次 9 槽提至 15 槽（GPU 全空闲，加快补齐 6 个未投放数据集）。
- 未触碰 GPU 7 上他人的任何进程；未删任何中间产物或队列 conf。

### 决策点

- 无新增。**待用户裁定**：Test_2b arm_B 表 32/64 行陈旧（影响 Test_4 去泄露值档与 Test_3 的 C−B 交叉列），是否按上述方案修复。

### 状态

- 进行中：搜索 15/15 running（0 done / 0 failed）；臂 C 接力链已挂后台轮询等待首个 result.json。三条自愈链路（搜索 watch、臂 C 接力链、队列 recover/retry）均已部署。
- 提交：本条目正文在写入后 11 s 被并发的 S2c 提交 `027673b` 先行带入（其 `git add` 覆盖到本文件；内容与本人所写一致，未覆盖他人条目）；本步骤另以独立提交 "S6 续跑: Test_3 搜索与臂 C 链恢复" 落库该行的补记，并 push origin main（无脚本改动，只 add 本日志）。

### 补记（14:40，ETA 修正与现场续报）

- **ETA 修正（上一节"首个 result.json 预计由 LAML 出（~10 分钟）"的推测不成立）**：核对 `src/selection/stopping.py`（SigStop）后确认：停判计数 `no_improvement` 需**同时**满足 gain < 0.005 **且** Wilcoxon p ≥ 0.05；若 gain < delta 但 p < 0.05（显著变差）则 `count=0` **清零重数**。LAML 实测 k=4 −0.00248 / k=5 −0.00196 / k=6 −0.00495 后并未停（k=6 处被清零），14:40 已推进到 k=7，首停点不可预判（取决于各 k 的 Wilcoxon 结果）。
- 现场池规模（k=1 跑完才确知）：BLCA 44、COAD 34、LUAD 32、LGG 30、HNSC 29、KIRC 22、LAML 21、BRCA 20、GBM 19；小池（LUSC/OV/SKCM/STAD/LIHC）k=1 未完（暂知 ≤8）。**全梯上界 = P(P+1)/2**（`config.budget_for`，无更紧 cap）：BLCA ≤990 evals、COAD ≤595、LUAD ≤528、LGG ≤465、LAML ≤231；按实测 110–540 s/eval，最坏情形单集 ~7–30 h（实际应远早于穷尽停，但不可承诺时刻）。首个 result.json 更可能先由小池数据集（梯子短）产出。
- 14:40 现场：15/15 running、0 failed、0 result.json；watch（PID 3715209）与臂 C 链（PID 3724666）均存活；臂 C 触发验证（generate custom scheme → encode → enqueue）因首个 result.json 未落盘而**待续**。已重挂监视（60 s 轮询 result.json 计数 + watch/chain 存活；落盘 / 15 全完成 / 进程死亡即报）。
- **14:42 GPU 竞争 → 臂 C 链改卡**：用户并行起了 Table3_MissingRate 实验（PID 3791694/3791712/3791517/3791547，各 ~21 GB，14:20 起），占满 GPU 0/1（现场余量 0.9 GB / 3.2 GB）。搜索 drainer 已分配显存不受影响（GPU 0 上 3 槽照跑）；但臂 C 的 encode + 8 worker drain 放 GPU 1 会 OOM。处置：终止旧链（PID 3724666）→ `T3_ENC_GPU=7 T3_GPU=7 T3_WORKERS=8 T3_POLL=120` 重启（新 PID 3904207，14:43:12），GPU 7 空闲（余 45.4 GB）；链幂等（当时尚未处理任何数据集），日志续写同一文件，监视改挂新 PID。**他人进程一律未动**。注意：GPU 0 余量紧，若其上任一搜索 drainer 死亡被 watch 拉起，~540 MiB 分配可能失败并触发限次重试（3 次后记 failed，需人工补投）。

---

## S6 续跑补记: 修复 Test_2b 臂 B 陈旧行（用户裁定，2026-10-03 15:00–15:25）

- 依据：上一补记上报的"Test_2b 臂 B 表 32/64 行陈旧（summarize 与末折并发读竞态）"，用户裁定**执行修复**：删陈旧行 → 重跑 summarize 从折文件重新汇总 → 全量复核。
- 口径（先审计后动手，脚本 `/tmp/Test_2b_armB_fix.py`，审计与修复同源）：
  - 陈旧判据升级为 **per-fold 前缀判定**——表内 `val_per_fold` 恰为 run 目录 `val_result_fold*.csv` 末行 `val_cindex` 序列的**前缀**（长度 1–4 / 5）即"末折未落盘时的部分读"；均值比较用 1e-9 容差（此前严格相等把 PAAD SURVPGC 的 1-ulp 求和序差也计入，容差后归为正常）。
  - 审计结果：64 条臂 B `{work}__landmark_0 × mlp_clinic_flatten` 行中 **32 条 prefix-陈旧 / 32 条正常 / 0 条其他**，与上次上报一致。
  - 说明：表内 `results_dir` 仍写迁移前旧路径 `results/A_manual_landmark/...`（该目录已不存在），属历史元数据串；物理 run 即 `results/Test_2b/arm_B/runs/...`（M1 迁移改名），故从新树重 derive 正确。
- 动作：
  1. 备份 13 个受影响表 → `/tmp/Test_2b_armB_backup/{ds}[gdc]/{run_config.json,cindex.csv}.bak`；
  2. 从 `run_config.json` 的 rows **仅摘除这 32 条陈旧行**（其余行/字段/其他 modality 行不动；CSV 由 summarize 重建）；
  3. 重跑 `summarize_dataset`（复用 S4 `_jobs_for_combos(arm=B)` 同源 job 定义；表目录断言 `results/Test_2b/arm_B/{ds}[gdc]`）。
- 前后计数（每表行数不变 = 删 k 补 k）：COAD 3、GBM 4、HNSC 3、KIRC 2、LAML 2、LGG 1、LUAD 3、LUSC 3、OV 3、PAAD 1、SKCM 2、STAD 3、TCGA_LIHC 2，合计 **32 行**；13 表 rows 数逐一不变（KIRC/LUAD/LUSC/LIHC 25 行、其余 20 行），CSV 行数 == run_config rows 数。
- 验证（修复后全量复核）：
  - **臂 B：64/64 行与折文件手算一致（均 5 折齐全，1e-9 容差）**；
  - **臂 B′（Test_3_*）：64/64 行仍一致**（本次未触及）；
  - 典型 before→after：LAML MULTISURV 0.54356(4折,std 0.0926)→**0.56091**(5折)；KIRC HGCN_KIRC 0.80387(1折,std 0)→**0.70273**(5折,std 0.0876)；STAD SURVPGC 0.51310(1折,std 0)→**0.57545**(5折)；LUSC SURVPGC 0.61444(3折)→**0.57946**(5折)；COAD SURVPGC 0.70346(2折)→**0.71549**(5折)。
- 影响面：Test_2b 臂 B 展示值与 Test_3 表 `B_c / delta_C_minus_B`（交叉列；头条 Δc=C−B′ 不受影响）、Test_4「去泄露值」档的数据源随之更新；**下游展示/汇总重出（Test_2b 图、Test_4 表）为另一步，本步未执行**。
- 未动：任何 run 目录/折文件/队列 conf/中间产物/他人进程；仅改表文件（results/ 不入库）。
- 提交：本条目（只 add 执行日志）。

---

## S9 Test_5 规格落地 + HGCN 产物备份（2026-10-03）

- 时间 / 执行者：2026-10-03 / Claude Code（用户指令）
- 目标：把 Test_5（不变性：E/M/Q 三轴）规格写入 `z_notes/Test_series_spec.md` §8bis 并同步 `z_notes/experiment_list/experiment_list.md`；按用户指令在修改前备份既有 HGCN 编码产物。
- 输入：`z_notes/Test_series_spec.md`（Test_5 占位）、`z_notes/experiment_list/experiment_list.md`、`outputs/{9 数据集}/A_manual/HGCN_clinic/`（L0–L5）、SurvPGC 参考实现（`utils/survival_metrics.py`、`results_display/scripts/Table1_{IBS_AUC,Cindex_Main,CoxBreslow_Forward}.py`）、Clinic_Analyzer 指标实现（`utils/core_utils.py:535-617`）。
- 产物：
  - `z_notes/Test_series_spec.md`：§1 定位更新、§3 注册表新增 S9–S13、新增 §8bis（Test_5 规格：命题/三轴/四子检查/锁定基线/HGCN 路线 A 与等价冻结规则/Q 修复清单/验收与产物）。
  - `z_notes/experiment_list/experiment_list.md`：总表 Test_5 行 + 协议段替换占位。
  - 备份 `/data/fangyuxuan/projects/medical_dl/backups/HGCN_clinic_2026-10-03/`（9 数据集 × L0–L5，1.4G，**仓库外**）。
- 命令与参数：
  - 备份：`cp -a outputs/{BRCA,COAD,KICH,KIRC,KIRP,LIHC,PRAD,READ,STAD}/A_manual/HGCN_clinic → 备份目录`；校验 `diff -rq`（TCGA-KICH 全目录一致）+ `du -sh`（1.4G）。
- 审计（自检项 + 实际结果）：
  - 备份与源逐字节一致（KICH 抽检 diff=0，其余 cp -a 同源命令）。
  - 规格要点与用户 2026-10-03 三项指令逐条对应：路线 A ✓（§8bis.3）；多模态子集 BRCA/COAD/KIRC/LIHC ✓（§8bis.2，KIRP 44 事件被协议 A 排除）；Q 先修复再迁移 ✓（§8bis.4，6 处缺陷逐条列明）。
  - 锁定基线（landmark_0、5 折 seed 0、协议 A 15 主集只训不扩）与控制变量纪律（唯一差异 = 被换轴；hgcn 臂为配对例外并标注）写入 §8bis.1/§8bis.5。
  - confs 估计 ≈546（prompt 臂复用既有产物零新增），写入 §8bis.2。
- 偏差与原因：无。
- 决策点：**D6**（三轴口径）→ 已确认（2026-10-03），结论见决策点状态表；D7/D8/D9 待 S10/S11/S13 执行时确认。
- 状态：完成。下一步 S10（Q 指标修复 + 离线重算）。

---

## S10a Q 指标修复（代码 + 单元测试，2026-10-03）

- 时间 / 执行者：2026-10-03 / Claude Code 子 Agent（用户指令"每阶段测试/归档/提交，继续推进"）
- 目标：按 spec §8bis.4 修复 Clinic_Analyzer 的 IBS/时依 AUC 计算（6 处缺陷），先落代码与测试，不跑任何训练。
- 输入：SurvPGC 参考实现（`utils/survival_metrics.py`、`utils/core_utils.py:1391-1403/1944-2091/2730-2738`）、Clinic_Analyzer `utils/core_utils.py` 旧 `_calculate_metrics`（:535-617）。
- 产物：
  - `Clinic_Analyzer/utils/survival_metrics.py`——逐字节移植 SurvPGC 原版（md5 `b0e0f134b81c2f022e10838798d1baf9`，与源一致）。
  - `Clinic_Analyzer/utils/core_utils.py`——6 处编辑（md5 提交时 `06bd14fc599e36683dfe3680c500a6d7`）：共享指标层导入；新增 `_collect_train_survival_risks`（:363，移植 SurvPGC :1391-1403）；`_calculate_metrics` 重写（:558-708：删硬编码网格/`np.append(iauc_list,0)`，edges 插值、Breslow 分支、守卫 NaN 语义、负时间过滤）；`_summary` 加 `train_survival_risks` 透传（:710/:807）；`_step` 对 cox 在 test 前收集训练折 risk（:893-896）；6 个裸 `except:` 全部改为打印原因。
  - `projects/tests/test_survival_metrics.py`——21 用例（两模块逐函数 np.allclose 等价、已知值锚点、守卫 NaN、cox Breslow、负时间等价性、`_summary` 传参）。
- 命令与参数：`PYTHONPATH=/tmp/s10a_pytest_env /data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python -m pytest tests/test_survival_metrics.py -q`（pytest 装入 /tmp 临时目录，未改任何 conda env）。
- 审计（自检项 + 实际结果）：
  - 新用例 **21 passed**（复跑两次一致）；base env 既有套件 198 passed / 7 skipped；A_pipeline 44 passed——无回归。
  - **控制流结论**：val IBS/BS/iauc 只进 `val_result_fold*.csv` 日志与 wandb（wandb 只记 c-index/loss/ipcw，core_utils.py:853-880），**不参与最优 epoch 与剪枝**；val_cindex 参与控制（:859-860）→ c-index 计算**逐位保持旧实现**（NaN 删除后、负时间过滤前，:606-611），并以负时间行用例证明 c-index/IBS/AUC 均不受影响（参考实现把 c-index 放在过滤后，此为唯一结构性偏离，数值等价）。
  - 现场并发核查：`Clinic_Analyzer/utils/` 有并发 worker 在改（hgcn_train.py/hgcn_data/general_utils.py/process_args.py，19:14–19:20 新建/修改，已按新签名适配 train risks 收集）；本步的 core_utils.py 编辑现场完好（六处标记 grep 齐、测试通过）。
- 偏差与原因：**`Clinic_Analyzer/` 整体被 .gitignore 忽略**（`*` + `*/`，仅 .gitignore 本身入库，历史唯一提交 4870cdf）→ 本步提交只含测试与日志，Clinic_Analyzer 代码改动以 md5 记录于本条目；是否 force-add 入库**待用户裁定**。hgcn_train.py（bin=None 无 train risks）的旧 0 契约未动（与参考一致，用例固定）。
- 决策点：**D7**（在线 vs 离线 diff=0）——代码侧落地完成，验收待 S10b 离线重算脚本与 S12 新臂实测。
- 状态：完成（S10a）。下一步 S10b（离线重算脚本 `results_display/scripts/Test_5_q_recompute.py`）。

- 补记（2026-10-03 晚，用户裁定）：① **Clinic_Analyzer 代码不入库**（维持 .gitignore 现状，方案 B）——后续各阶段该目录改动一律以 md5 记于执行日志，提交只含 tracked 区域文件；② **HGCN 模型/训练器由用户自行移植**进 Clinic_Analyzer 内部（`utils/hgcn_train.py`、`utils/hgcn_data/`，范围限该目录、不动其他代码）——S11 我方范围相应调整为：A_pipeline `hgcn_clinic` 任意 scheme 编码扩展 + L0-L5 等价性回归（对冻结备份 diff=0）+ 与用户 harness 对接，不重复移植模型。

---

## Test_5 方案修订：HGCN 不纳入（用户指令，2026-10-03 晚）

- 用户已完成 HGCN 训练器向 Clinic_Analyzer 内部的移植（独立工作，范围限该目录、不动其他代码）。
- **Test_5 不运行 HGCN 模型/编码，维持原有方案**：E 轴 = prompt / baseline 两档；M / Q 轴不变。spec §8bis 同步修订（§8bis.1 E 轴两档；§8bis.2 合计 ≈388 confs；§8bis.3 改为"HGCN 不纳入 + 既有产物冻结"；§8bis.5 删配对例外；§3 注册表 S11 取消、依赖链 S9→S10→S12→S13）。
- 既有 `outputs/*/A_manual/HGCN_clinic/`（9 数据集 L0–L5）冻结（不覆盖、不重跑、不扩展）；仓库外备份保留（S9）。
- 状态：S10b 进行中（离线重算脚本），不受本修订影响。

---

## Test_5 方案修订②：HGCN 编码先落地、模型暂不接入（用户指令，2026-10-03 晚）

- 修订①理解有误（把"模型不接入"扩大成了"编码也剔除"），**以本条为准**：E 轴保留 hgcn_clinic（全连接图节点）编码并**先落地**（S11 编码侧：任意 scheme + landmark 支持，pkl 格式不变，不加模型消费方）；**HGCN 模型暂不接入**（用户移植的训练器为独立工作），E=hgcn 评估臂（5E_2b/5E_3 hgcn 行，≈188 confs）**待模型接入后再跑**，届时另定对接协议。本轮 = baseline 编码臂 + M 轴臂，≈388 confs。
- spec §8bis 同步修订：§8bis.1 三编码；§8bis.2 分"本轮 ≈388 / hgcn 待模型 ≈188 / 全量 ≈546"；§8bis.3 改为"编码先落地、模型暂不接入 + L0-L5 等价性回归要求继续有效"；§3 S11 恢复（仅编码侧）、依赖链 S9→S10→S11→S12→S13。
- 既有 HGCN 编码产物冻结 + 仓库外备份（S9）的要求继续有效（S11 会改 hgcn_clinic.py）。
- 状态：S10b 已完成（另见 S10b 条目）。

---

## S10b 离线 Q 重算脚本 + 训练侧 metrics-input 落盘（2026-10-03）

- 时间 / 执行者：2026-10-03 / Claude Code 子 Agent
- 目标：按 spec §8bis.4 建离线重算链路——既有 conf 从 pkl 重算 Q 电池（c-index/IBS/AUC@24/60/IPCW）；未来 run 逐折落 metrics-input 供精确重算（diff=0，D7 路径）。
- 输入：S10a 修复后的 `Clinic_Analyzer/utils/survival_metrics.py` / `core_utils.py`；各 run 目录 `split_{fold}_results.pkl`、`splits_{fold}.csv`、`test_result.csv`、`experiment.txt`、`s_{fold}_checkpoint.pt`。
- 产物：
  - `results_display/scripts/Test_5_q_recompute.py`（1218 行；CLI `--results-root`（多根）/`--out`/`--modalities`/`--cox-device`（默认 cpu）/`--limit`/`--folds`/`--confs`；Q_COLUMNS 与规格一致；纯函数可单测）。
  - `Clinic_Analyzer/utils/core_utils.py` 增 `_dump_metrics_input`（:710-723）与逐折 dump 块（:824-853，payload 含 edges/risk/censor/times/by_bin/train_risks/survival_train/slide_ids/metrics），`_summary` 加 `metrics_input_path`，`_step` 测试折调用点 :942-945；**不改变任何计算**（md5 `9ba56e1380b6bc56bbfeb6fc0da88e2b`，mtime 19:30:18，与并发 worker 无冲突——worker 只动 hgcn_train.py/general_utils.py/process_args.py）。
  - `projects/tests/test_Test5_q_recompute.py`（670 行，23 用例）。
- 审计（自检项 + 实际结果）：
  - 测试 **44 passed**（23 新 + 21 S10a 回归，5.38 s，复跑一致）；镜像等价用例：合成数据上 `calculate_metrics_mirror == core_utils._calculate_metrics` 四场景逐位一致；dump 路径三方一致（diff ≤ 1e-8）。
  - 冒烟（全 cpu，输出只落 /tmp，未写 results/）：LAML/BLCA/ACC 共 5 conf，c-index 与 csv 对齐 ≤ 5.55e-17（多数 0.0）；IBS/AUC 出真实值（例：BLCA SURVPGC mlp fold0 ibs=0.2054 / auc24=0.5995 / auc60=0.6361）；**cox 路径实测**（LAML fold0，cpu 4.8 s，cindex diff=0.0，auc24=0.3821 / auc60=0.3991——csv 旧值为 0，正是修复点）。
  - cohort 定义镜像核实：train+val+test 三 loader metadata 直接 concat 无去重（core_utils.py:348-361/:887；LAML=206 行含 33 重复 case）；bins = uncensored qcut(n_bins=4)（dataset_survival.py:313-321），edges=bins[1:]；守卫与 NaN 语义与在线一致；c-index 先于负时间过滤（刻意保留，:606-611）。
  - 已知限制：pkl 键 12 位 case_id（多 slide 覆盖）——现 33 TCGA label 均 rows == 唯一 case == 唯一 slide，无碰撞；旧 test_result.csv 的 IBS/iauc 为坏层产物（非有效参照），自检只对 c-index；dump 路径尚无真实产物（由新 run 产生，S10c/S12 首跑时核对 dump diff=0）。
  - 附带发现（非本步引入）：`pytest tests/` 全目录因既有 `tests/test_event_stats.py` 采集失败（`scripts/run_event_stats.py:37` 用 py3.9 不支持的 `pd.DataFrame | None` 标注）——待用户决定是否修。
- 偏差与原因：Clinic_Analyzer 改动按裁定不入库（md5 记于本条）。
- 决策点：D7 待 S10c/S12（新 run dump diff=0 + 在线 vs 离线一致）。
- 状态：完成（S10b）。下一步 S10c（arm_A/arm_B 全量重算）。

---

## S11 HGCN 编码侧落地（任意 scheme + landmark + 等价性回归，2026-10-03）

- 时间 / 执行者：2026-10-03 / Claude Code 子 Agent
- 目标：按 spec §8bis.3 落地 E=hgcn 编码侧（模型不接入）：hgcn_clinic 支持任意已注册 scheme + landmark 取值 mask + 输出根覆盖；对冻结备份做 L0-L5 等价性回归（D8 证据）。
- 输入：`A_pipeline/src/hgcn_clinic.py`（L0-L5 白名单、无 landmark）、`A_pipeline/src/cli.py:155-156`（拒绝 landmark）、`A_pipeline/src/baseline.py` 的 GDC 字典三分类、冻结备份 `/data/fangyuxuan/projects/medical_dl/backups/HGCN_clinic_2026-10-03/`。
- 产物（全部 tracked 区域）：
  - `A_pipeline/src/hgcn_clinic.py`（+~200 行）：任意 scheme 解析（fields.json 驱动）；新字段分类 = 冻结三分类 → BASELINE_DICTIONARY_FIELD_TYPES → keep_none（零节点）；L0-L5 占位词汇 shim；`run_hgcn_clinic(landmark_time, landmark_subdir)`；summary 增 display_fields/landmark_time。
  - `A_pipeline/src/cli.py`：删 hgcn_clinic 的 landmark 拒绝；新增 `--hgcn_out_root`；hgcn 作业分支路由 out_root/landmark。
  - 测试：`tests/test_hgcn_clinic_schemes.py`（17 用例）+ `A_pipeline/tests/test_landmark_time.py`（CLI 路由替换旧拒绝测试）+ `test_a_pipeline.py`（scheme 断言更新）。
  - 文档：`A_pipeline/README_usage.md`、`README.md` 更新 hgcn_clinic 用法。
- 审计（自检项 + 实际结果）：
  - 测试 **61 passed**（17 新 + 44 A_pipeline，1.38 s，复跑一致）。
  - **等价性回归**（KICH 109 + LIHC 365 患者，L0-L5，写 /tmp/s11_hgcn_regress）：`diff -r` 仅 `summary.md` 差 1 行（`- output:` 根路径——输出根覆盖导致，匹配它必须写入 outputs/，被冻结规则禁止，属构造性不可复现）；**值级 96/96 文件全等**（x_cli/ttt/t_cli/edge_index pkl 逐值相等、JSON deep-equal、summary 去行后相等）。
  - **发现的既有漂移（非本步引入，已中和）**：`templates/L{0-5}/fields.json` 于 2026-09-08 从占位符迁移为 GDC 路径，而冻结产物（09-01）携带占位符——不加处理的重跑会仅因命名改写 4 个元数据文件。`artifact_field_name()` shim 恢复冻结词汇，故 L0-L5 默认输出与冻结产物逐字节一致。
  - 真实数据冒烟：Test_3_greedy_TCGA-LAML（LAML 200 患者）→ 4 个 bank 字段为 keep_none 零节点、其余 3 字段 100% 观测；MULTISURV → ordinal stage + 3 个字典名义字段按数据集拟合；`--landmark_time 0` 落 `…/{scheme}/landmark_0/`。
  - outputs/ 零写入（HGCN_clinic 下全部文件仍为 09-01 日期）。
- 偏差与原因：无（hgcn_clinic 的 `all`/`manual` 语义刻意只含 L0-L5，防污染冻结树）。
- 决策点：**D8** 实质等价成立（byte 级唯一差异 = 输出根路径行）——**用户已确认（2026-10-03）：等价→放行**；既有 L0-L5 产物维持冻结不覆盖。
- 状态：完成（S11）。E=hgcn 评估臂待模型接入后再定（遗留：模型侧消费方、cindex --encoding hgcn、keep_none 节点处理方式未决）。

---

## S10d Q 重算自检失败调查与修复（2026-10-03）

- 时间 / 执行者：2026-10-03 / Claude Code 子 Agent
- 目标：查清 S10c 全量重算中 7 个 cox 折 c-index 自检失败（diff 4e-4~6.7e-3）的根因并修复；复核枚举完整性。
- 根因（数值证明）：cox 的 `split_{fold}_results.pkl` 每折只有 **1 行**（cox loader 把 batch 覆写为 len(split)，`patient_results` 按 batch 键坍缩）→ 脚本必须重做前向；CPU 前向与训练时 GPU 前向差 ~1 float32 ULP（~1e-8），sksurv `tied_tol=1e-8` 为绝对阈值，恰好跨界的可比对在 tied/有序间翻转 → c-index 恰差 0.5/n_pairs。7 折全部落在该格点上；行集不一致假设被排除（行/事件/时序全同、无 case 前缀重复）。
- 修复（`results_display/scripts/Test_5_q_recompute.py`）：cox 重构两模式（per-patient batch=1 / online 全批组合）；`pick_cox_reconstruction` 自动修复策略（与 csv 更近才采用，否则保留快路径）；pkl 复用门槛改为"覆盖全部 loader 行"；新增 `--cox-test-batch {auto,per_patient,online}`、`--merge`、`_collect_split_rows`（绕过 patient_results 坍缩）。
- 审计（自检项 + 实际结果）：
  - 测试 **51 passed**（44 + 7 新，复跑一致）。
  - 枚举完整性：arm_B 实有 **349 conf**（264 = 33 数据集 × 8 主方案 + 85 个 Test_3/HGCN/det1/oldlabel 额外 conf）；arm_A 136 conf。CSV 0 孤儿行（每行都有磁盘 pkl）。
  - 缺口处置：arm_A `mlp_clinic_flatten` 136 refs/676 折已补算并入（pkl-only，max |diff| 1.1e-16）；arm_A cox 410 折与 arm_B `mlp_clinic_mean` 4 refs 见补记（后台补跑）。
  - 最终 CSV：**3791 行、0 重复**、除 3 行修复外其余 3112 行与 S10c 逐字节一致；3 行修复（paad lm0/lm_none f1、coad lm0 f0）diff=0；**4 行未能复现**（acc MMSURV lm0/lm_none f4、sarc f0、ucec f3，均非 15 主集）——需训练时 GPU 的 float32 原值，CPU 任何组合都复现不出，判定为环境受限而非脚本缺陷，未强行放行（可选后续：GPU 空闲时重跑这 4 个 conf 的 cox 前向取原值）。
- 偏差与原因：无。
- 决策点：无新增。
- 状态：完成（S10d）。**15 主集相关 Q 电池全部自检干净**。

### 补记（S10d-2，arm_A cox 补跑 + GPU 政策，2026-10-03 晚）

- arm_A cox 410 折后台补跑完成并入 q_metrics.csv（现 4221 行）；**15 折自检失败**（KIRC HGCN_KIRC f0/f1/f4、LIHC HGCN_LIHC f0/f1/f3/f4、LIHC MULTISURV 全 5 折、SARC INTEGRATIVE_DNN f0、STAD INTEGRATIVE_DNN f0/f4，diff 3e-4~3e-2）。
- 根因判断（与 arm_B 的 tie 翻转不同）：arm_A 是旧时代 run——experiment.txt 的 `label_file` 指向旧源 `SurvPGC_github_init/datasets_csv/metadata/tcga_lihc.csv`，`results_dir` 为旧路径 `results/A_manual/...`；自检参照的 csv c-index 由旧代码/旧 label 源产生，当前代码前向无法逐位复现。属已知时代差异（D3 曾记录 label 源迁移），非脚本缺陷。处置：行保留（`source=pkl_recompute`，recomputed 值 = 当前代码口径），abs_diff 列如实记录；报告层按"旧时代 arm_A cox"标注，不参与严格排名。
- **GPU 政策（用户指令 2026-10-03）**：本机为公共服务器，用户 GPU 范围 = **0–3（最多 4 张）**。Test_5 后续训练批跑（S12b）一律限定 GPU 0–3 并现场协调；我方当前进程（编码/重算）零 GPU 占用；现场超限（S6 搜索占 0,2,3,4,5,6 + Table3 占 0/1）属 S6 会话与用户任务，未擅动。
- **S12b 推迟至 S6 收尾后启动**（用户指令）。

---

## S12a baseline 编码批产（5E 臂数据准备，2026-10-03）

- 时间 / 执行者：2026-10-03 / Claude Code 子 Agent（CPU-only，零 GPU）
- 目标：为 5E_2b/5E_3 的 baseline（D-向量）臂批产编码，范围 = 15 主集 × 绑定方案 × 两臂 + Test_3 B′ 臂；不跑训练。
- 命令与参数（目录约定以代码为准）：`baseline.py:135-145`（paper/custom → `{out_root}/baseline/{scheme}[/landmark_T]`）、`cli.py:330`（out_root）、`landmark.py:74-79,97-117`（arm A ≡ `--landmark_time none`）；① 共享 vocab 全量流 `baseline --dataset all --scheme paper --baseline_out /tmp/s12a_build`（重定向防覆盖 5 个 lizhe 重叠数据集元数据）；② 分数据集 `--landmark_time 0/… --baseline_stats_dir outputs/{ds}/A_manual/baseline/metadata`；③ B′ 走 `apply_patches` 进程内路由（custom scheme 不被 CLI 白名单接受，同 `scripts/Test_3_arms.py` 惯例）。
- 产物：**188 个编码**（armA 64 + armB 64 + B′ 60）、94,498 个 .pt；共享表 `A_pipeline/baseline_onehot_mapping_tables/gdc/`（33 TCGA、22 字段、min_count 5）；`/tmp/s12a_baseline_manifest.csv`（188 行）；批脚本 `/tmp/s12a_batch.sh`、日志 `/tmp/s12a_baseline_encode.log`。
- 审计（自检项 + 实际结果）：
  - **188/188 患者集与 prompt 编码逐位一致**（0 失配）；B′ vs 同字段集 paper 臂 60/60 字节一致（证明进程内路由等价）；
  - 抽查 **18/18 手算一致**（min-max 与 one-hot 索引，含 `__MISSING__`=0）；
  - **幂等**：同命令重跑 run1/run2，`diff -r` 15/15 数据集与元数据全同；
  - 写范围审计：仅新增 `outputs/{ds}/A_manual/baseline/**` 与 CLI 规范路径 `outputs/{ds}/A_manual/metadata/landmark_0/*.json`（15×3，新增不覆盖）；lizhe 表与重叠数据集元数据 md5 未动；pycache 0；
  - 附带观察：S6 会话期间写了 `.claude/settings.local.json`（非本步，仅记录）。
- 偏差与原因：arm C/greedy 按规格跳过（模板仅 2/15，待 S6 搜索）；HGCN_* 的 Test_3 变体不在 B′ 范围。
- 决策点：无新增。
- 状态：完成（S12a）。**S12b 训练推迟**（用户指令：S6 收尾后、限 GPU 0–3）；S12b 所需 clinic_dir / LABEL_FILE_PATH / EXP_GROUP 映射已在任务报告中列明（arm A = `baseline/{scheme}/embeddings/pt` + 旧 label 回退；arm B/B′ = `…/landmark_0/…` + `results/Test_2b/arm_B/labels/{study}__landmark_0.csv`；B′ 需经 `apply_patches` 路由）。

---

## S6 续跑：Test_3 局部三臂表（预览，2026-10-04 09:44–09:52）

- 时间 / 执行者：2026-10-04 / Claude Code 子 Agent（用户指令：不等 15 集齐，先用已有 result.json 的数据集出**局部三臂表**）
- 现状确认（09:44 现场，以现场为准）：
  - result.json **6/15**：TCGA-GBM、KIRC、LAML、LGG、OV、PAAD；搜索 watch（PID 3577525，9 集在跑，GPU 0/2/3/4/5/6）**全程未触碰**；
  - 臂 C 链（PID 3904207，19 h）已对这 6 集完成 generate → encode（gpu 7）→ enqueue：`Test_3_arms` 队列恰为这 6 个 greedy conf（`tcga_{ds}__Test_3_greedy_TCGA-{DS}__landmark_0__mlp_clinic_flatten.conf`），**无缺口，未补跑**。
- arms drain（09:46:26–09:48:58，GPU 1 × workers 6；避开搜索占用的 0/2/3/4/5，用户 Table3 已结束故 GPU 1 空闲；GPU 7 留给链内 encode）：done 64 → **70**、failed 0；6 个 greedy run 各 5 折齐（`results/Test_2b/arm_B/runs/tcga_{ds}__Test_3_greedy_TCGA-{DS}__landmark_0/mlp_clinic_flatten/`）。
- summarize：`Test_3_arms.py summarize --arm ksig --datasets <6 集>`（名单由现场 result.json 存在性导出，非硬编码）→ 6 张 `{ds}[gdc]` 表各 +1 行（greedy × mlp_clinic_flatten）；**无重复行键，CSV 与 run_config.json 行键逐一对齐**（GBM 21 / KIRC 26 / LAML·LGG·OV·PAAD 各 21 行）。
- 比较：`Test_3_compare.py --all` → **pairs=64 done=25 pending=39，未报错**——实测确认脚本对缺 result.json 的数据集只记 pending（`MissingArm` 捕获后 continue），**无需修改**。产物：`results/Test_3_greedy_vs_works/three_arm.csv`（25 行）、`missed_fields.csv`（112 行）、`compare/{ds}__{work}.json` 25 份、`results_display/Test_3_greedy_vs_works/`（csv 副本 + Δc 图）。
- 抽查（表内前 2 行，逐位核对）：三臂 mean/std 与折文件手算（`val_result_fold*.csv` 末行 `val_cindex`，5 折 mean/std ddof=1）**逐位一致**，`run_config.json` 的 `val_per_fold` 亦逐位一致：
  - TCGA-GBM / MULTISURV：B 0.671778/0.023908、B′ 0.667205/0.022165、C 0.542832/0.037079，Δc(C−B′)=−0.124373；
  - TCGA-GBM / SURVPGC：B 0.627797/0.028854、B′ 0.625925/0.027189、C 0.542832/0.037079，Δc(C−B′)=−0.083093。
- **局部 Δc = C − B′ 摘要（25 个 (数据集 × 工作组合)，已完成 6 集）**：
  - 全体：mean **−0.0282**、median **−0.0416**、Δc>0 仅 **5/25（20%）**；交叉口径 Δc=C−B mean −0.0272（同向）；
  - 分数据集 mean Δc：PAAD **+0.0746**（4 行中 3 正）> KIRC −0.0019（5 行中 2 正）> LGG −0.0382 > LAML −0.0493 > OV −0.0657 > GBM −0.0950；
  - 贪婪字段数 vs 工作组合字段数：OV 1、GBM 3、LGG 4、PAAD 6、LAML 7、KIRC 9（工作侧 3–10）——胜/负与字段数不单调（PAAD 6 字段仍胜，KIRC 9 字段仅打平）。
- pending 清单（39 pair，缺 result.json 故缺 C 臂）：BLCA、BRCA、COAD、HNSC、LUAD、LUSC、SKCM、STAD、TCGA_LIHC 各 4 组合，另加 HGCN_LUAD/LUSC/LIHC 三个专属对——待各自 result.json 落盘后由臂 C 链自动 generate/encode/enqueue。
- 说明：**本表为预览版**（15 集齐后由链尾 `summarize --arm bp/ksig` + `compare --all` 重出完整版）；链内新产的 `A_pipeline/templates/Test_3_greedy_*`（6 个）与 `schemes.json` 注册项属链产物（10-03 16:23–10-04 07:38 生成，非本步），**留在工作区不入库**，随完整版一并提交。
- 偏差与原因：无。
- 决策点：无新增。
- 状态：完成（局部三臂表预览）。
- 提交：本条目（只 add 执行日志）。


---

## S6 续跑：Test_3 停止标准口径变更（gain-only δ=0.005）与 15 集重跑（2026-10-04）

- 时间 / 执行者：2026-10-04 / Claude Code（用户指令：当前剪枝标准过严，停止标准改为 gain-only δ=0.005；立即停掉 9 个在跑旧标准搜索换新标准重跑；best 口径三臂表由用户自出，不归本步）。
- 现状确认（现场，以现场为准）：
  - 旧 watch PID 3577525（`--gpus 0,2,3,0,2,3,0,2,3,4,5,6,4,5,6`，1h10m 前重启过）+ 9 个新一代 drainer（run_e2_selection_queue.py，GPU 0/2/3 上 32 workers、4/5 上 16 workers）+ 臂 C 链 PID 3904207（19h41m，轮询态）；
  - 另有 **25 个 PPID=1 的孤儿 run_e2_selection.py**（9h15m，更早 drainer 世代遗留，与新一代同写 9 个数据集的 out 目录）及其 evaluate.py 子进程——一并清理；
  - result.json 6/15 done（GBM/KIRC/LAML/LGG/OV/PAAD）；B′ 64 conf 全在 arms done 桶（无 pending）；局部三臂表 25 行（09:44–09:52 预览版）。
- 口径变更（用户确认，D4 修订）：早停 sig_stop（gain<0.005 且 Wilcoxon p≥0.05 连续 3 步）→ **gain-only δ=0.005**（gain≥0.005 更新 k_star 且 count=0；gain<0.005 计数；连续 3 步停，k_sig=k−3；delta/patience 不变；历史 best 仍另报）。动机：n=5 时 Wilcoxon p<0.05 ⟺ 5/5 折全正（最小 p=0.03125），过严——OV recommended 被卡在 1 字段（0.5828，best 4 字段 0.6116）。理论性质：gain_only 计数序列逐点 ≥ sig → 停点 ≤ 旧停点，重跑路径不延伸，几乎全缓存命中。
- 代码改动（`--stop-mode {sig,gain_only}`，sig 保留默认以锁旧口径）：
  - `src/selection/stopping.py`：SigStop 加 `mode` 参数（非法值 raise ValueError）；update() 按 mode 分支（gain_only 不看 p，p 仍计算记录）；返回 dict 形状不变。
  - `src/selection/search/greedy.py`：构造透传 `stop_mode`；gain_only 早停 reason="gain_stop"（sig 仍 "sig_stop"）；metadata 加 stop_mode。
  - `src/selection/runner.py`：argparse `--stop-mode`（choices 引用 config.STOP_MODES）；run_one 对 A2_greedy 传 stop_mode；result.json/run_config.json 加 stop_mode 字段（cache 指纹不含，不受影响）。
  - `src/selection/config.py`：STOP_MODES/DEFAULT_STOP_MODE 常量。`scripts/run_e2_selection_queue.py`：parser 同款参数（job_key 共同源头）。`scripts/Test_3_search_queue.py`：_runner_argv 注入 `--stop-mode gain_only`。`scripts/Test_3_common.py`：STOP_MODE="gain_only"。
  - `tests/test_e2_greedy_sigstop.py`：旧 5 例保绿（默认 sig）+ 新 4 例（gain_only 混合情形更新 k_star / 微小显著增益计数 / 非法 mode 抛错 / GreedySearcher+run_one 端到端 gain_stop）。全量 `pytest tests/` 220 passed, 8 skipped。
- 切换序列（按序）：归档旧标准产物 → 杀臂 C 链 → 杀 watch → pkill 两代搜索进程（bracket 正则防自匹配；首轮 pkill 自匹配误杀本 shell，已换写法补杀）→ recover + 15 个旧 conf park 进 parked_rekey（40 个）→ LGG 冒烟（GPU 3，gain_only，physical_trains=0，stop_reason=gain_stop，k_sig=4，recommended 与旧 sig 版相同——停点相同属理论预期）→ 重投 15 个（新 job_key，created=15 existing=0）→ 新 watch（PID 115457，`--gpus 0,2,3`，T3_SEARCH_WORKERS_MAP="0:32,2:32,3:32"，日志 watch_gain_only.log）。
- 归档物证：`results/Test_3_greedy_vs_works/archive_sigstop_20261004/`（6 个 done 数据集 result.json+evaluations.jsonl、three_arm.csv 25 行、missed_fields.csv、compare/ 25 份）——用户出 best 口径三臂表用，重跑不覆盖。
- 偏差与原因：
  - 现场除 9 个在跑外还发现 25 个孤儿旧标准进程（两代同写 out 目录），一并清理；
  - GPU 回归用户 0–3 政策（旧 watch 占 0-6 共 15 槽）；GPU 1 上发现 Test_5 5M_2b drainer（BLCA×SURVPGC，非本步范围，未触碰），新 watch 与其共存于 0/2/3；
  - pkill 首轮因模式串出现在本 shell 命令行中自匹配被杀（exit 144），换 bracket 正则完成。
- 决策点：**D4 修订已确认（2026-10-04）**。
- 状态：进行中（15 集搜索重跑，watch 115457；完成后跑臂 C 链重出三臂表）。

---

## S6 续跑：Test_4 三档汇总表（局部预览，2026-10-04 10:30–10:52）

- 时间 / 执行者：2026-10-04 / Claude Code 子 Agent（用户指令：Test_4 三档汇总表先做一版局部）
- 新增：脚本 `results_display/scripts/Test_4_three_tiers.py`（纯汇总，可复跑）+ 测试
  `tests/test_test4_three_tiers.py`（7 用例）+ 产物目录 `results_display/Test_4_three_tiers/`
  （`Main_three_tiers.csv` 64 行、`Main_tier_summary.csv`、README）。
- 口径：每 (dataset, work) 一行三档——①**报告值** = `results/Test_2b/arm_A/{ds}[gdc]/cindex.csv`
  的 `{work}` 行（论文报告原值）；②**去泄露值** = arm_B 表 `{work}__landmark_0` 行（S6 已修复口径）；
  ③**可达值** = `three_arm.csv` 的 `C_c`（Test_3 臂 C；附 B′ 对照列与 `delta_C_minus_Bp`）。
  档间 Δ：Δ1=报告−去泄露、Δ2=去泄露−可达。主口径 mlp_clinic_flatten，clinic_cox 交叉列。
  缺臂哲学与 Test_3_compare 一致：缺可达值的行**整行保留**、C 列与 Δ2 记 `pending`；arm_A 无该行
  记 `n/a`（SURVPGC/MMSURV 的非原文数据集）。分层 = 协议 A 四档（n_event 从 manifest 与
  event_summary **交叉核对**读，不硬编码）。
- 局部结果（64 行 = 15 主集 × 工作组合；R13 主集全为 `main` 档，四档机制为扩范围预留）：
  - 可达值 **25 行**（6 集）/ `pending_C` **39 行**（9 集：BLCA、BRCA、COAD、HNSC、LUAD、LUSC、
    SKCM、STAD、TCGA_LIHC 各 4 组合 + HGCN_LUAD/LUSC/LIHC 3 对）；报告值缺 22 行（SURVPGC 12 + MMSURV 10）；
  - Δ1（42 行）：mean **−0.0032**、median +0.0001（与 Test_2b 主结论一致：无系统性高估）；
  - Δ2（25 行）：mean **+0.0272**、median +0.0425，可达值反超仅 5/25（PAAD 3、KIRC 2）；
    Δ2 与 Test_3 交叉口径 Δc=C−B（mean −0.0272）互为镜像。
- 抽查（`--audit`，前 2 个可达值行三档逐位）：
  - GBM×INTEGRATIVE_DNN：报告 0.630881、去泄露 0.630277、Δ1 +0.000604、可达 0.542832、Δ2 +0.087445；
  - GBM×MULTISURV：报告 0.671706、去泄露 0.671778、Δ1 −0.000072、可达 0.542832、Δ2 +0.128946；
  - 每行核对：三档值 = 源表重读逐位一致；报告/去泄露值 = 折文件重算逐位一致（<1e-12）；
    Δ = 手算差 6 位舍入严格相等；cox 列同源；`n_fields_work` 与 three_arm 一致 —— **ALL PASS**。
- 测试与回归：`tests/test_test4_three_tiers.py` 7 passed（四档边界 / 三档装配与 Δ / 缺可达值不中断 /
  全缺不崩溃·空表与缺文件两态 / 写出与聚合 / three_arm 对齐 + 缺 n_event 显式报错）；
  全量 `pytest tests/ -q` = **227 passed, 8 skipped**；脚本幂等（重跑 diff=0）。
- 说明（**预览版**）：可达值产自 Test_3 **旧 sig 停点**（δ=0.005 + Wilcoxon 门控，与
  `archive_sigstop_20261004/three_arm.csv` 为同一份 09:49 快照）；D4 修订（2026-10-04，
  `stop_mode=gain_only`）15 集重跑完成后，本表随 three_arm.csv 重出，对应数据集 C 值与 Δ2 会变。
  搜索 watch（旧 3577525 / 新 115457）与臂 C 链全程未触碰。
- 偏差与原因：无。
- 决策点：无新增。
- 状态：完成（Test_4 局部三档表预览）。
- 提交：脚本、测试、本条目；产物 `results_display/Test_4_three_tiers/*.csv` 与目录 README 被
  `.gitignore` 忽略（`results_display/**` / `*.csv`），留在磁盘不入库（如需入库按 S5d 惯例 `git add -f`）。
