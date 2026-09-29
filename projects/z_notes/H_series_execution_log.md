# H 系列执行日志

规格与口径唯一来源：`z_notes/H_series_spec.md`。本文件是**所有执行报告的统一归档**，追加写，不另开文件；追加前先重读文件末尾。

## 决策点状态表

| ID | 决策点 | 状态 | 结论 |
|---|---|---|---|
| D0 | S0 删除范围（results/results_display 的 E1/E2/旧 greedy/univariate/linear_probe；是否连 outputs/*/greedy、outputs/*/univariate、Clinic_Analyzer/results 中间产物） | 待确认 | — |
| D1 | H0 门槛与降级规则数值（照搬 event_impact_analysis 建议 vs 调整） | 待确认 | **推荐：照搬 spec §4.2 现值**（150/70/30、rate<0.1 降一级）。理由：event_impact_analysis 的折间 std 分档表（§五）显示 ≥150 档 std 0.019–0.052，正好落在"能分辨 0.05 差异"的门槛内侧；本步 manifest 已按此跑出 12/10/4/9 的分布，与原型 README 的 12/22(≥70)/4/9 完全吻合，无调整压力。**唯一建议微调**：把 R7（退化折）从"仅标注"升级为"降级"，因为 PCPG/TGCT/DLBC/THYM 的退化折来自结构性事件稀少，标注不足以保护聚合图。 |
| D2 | landmark 有效事件口径（mask vs 排除患者）+ MMRF 是否纳入 | 待确认 | **口径推荐：mask（已实现）+ 排除 t≤T 患者（需新增）+ 终点保持原 event**；有效事件数 = `#{event==1 且 ground_truth_time > T}`。理由见 S1 调查：现实现只 mask 字段值、不排除患者、不动终点，等价于"landmark 对事件数零影响"，无法支撑 §4.2-6 的"门槛重套"。MMRF **推荐纳入**（n_event=191、每折 38–39、无退化折，与 TCGA 主集同档）；但其 landmark 变换幅度大（lm365→118、lm730→47），须按新口径重套档位后再决定是否进 S4/S6。 |
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
