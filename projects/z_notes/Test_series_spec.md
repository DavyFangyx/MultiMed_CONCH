# Test_ 系列实验规格（Test_1–Test_4 泄露与低估）

本文档是 Test_ 系列实验的**唯一口径来源与步骤注册表**。所有执行 agent 必须先读本文档，再读 `z_notes/Test_series_execution_log.md`（执行日志）。若本文档与仓库现状冲突，以本文档明确写出的规则为准，并在执行日志记录冲突与处理方式。

相关文档：项目口径见 `README.md`；三处目录命名公约（configs/results/results_display 以 Test 编号为主键）见 `z_notes/experiment_list/naming_convention.md`；可复用机制见 `z_notes/E2_Selection_Gain_Algorithm/E2_selection_algorithm_design.md`（E2 的评估器/缓存/搜索规格仍有效，但 E2 的算法竞赛目标作废）。

---

## 1. 目标

现有使用临床数据的生存预测工作，在选取临床字段时存在两个缺陷：

- **无时点约束** → 预测时点之后才产生的信息被纳入、临床模态被高估；
- **无依据** → 有效字段被遗漏、临床模态被低估。

Test_ 系列实验按两条论证链展开，**Test_1 是动机层**，分别指出"应该做但之前没人做"的两件事：

- **Test_1a**（时间轴链动机）：TCGA clinical 记录自带时间，同一字段在有无 t0 时间口径下 c-index 会实质变化 → 对 clinic 生存分析，按明确协议做字段的时间处理是**应该的**；之前的工作都没有做这种处理（这正是 Test_2 要展示的情况）。
- **Test_1b**（字段轴链动机）：字段在各个数据集中的预测能力各不相同 → 每个数据集在理论上存在属于自己的最优字段组合 → 针对数据集做合适的字段选择是**应该的**；之前的工作从文献/经验直接拿组合（这正是 Test_3 要展示的"次优"）。
- **Test_2**（时间轴链主体）证明高估存在：2a 审计（定量泄露占比）+ 2b 去泄露对照（控制变量，唯一差异 = landmark mask）。
- **Test_3**（字段轴链主体）在去泄露字段池上证明低估存在：贪婪搜索最优组合 vs 各工作去泄露后的组合——**收回** Test_1b 提出的"各数据集有各自最优组合"。
- **Test_4 三档汇总表**（非实验）：报告值 / 去泄露值 / 可达值三档对照，两个档差分别收口两条链——报告值−去泄露值 = 时间轴链收口（高估量），去泄露值−可达值 = 字段轴链收口（低估量）。
- **Test_5** 不变性（编码 / 模型 / 指标轴）——规格见 §8bis（用户 2026-10-03 确认后落地）；数据轴（外部数据集 CPTAC、MMRF 等）不在本阶段（§2.4）。

本阶段执行 Test_0、Test_1（动机）、Test_2（高估）、Test_3（低估）、Test_5（不变性，§8bis）；Test_4 是 Test_2+Test_3 的汇总产物表。

## 2. 锁定口径

### 2.1 泄露是定量指标

字段 f 在数据集 D 上的**泄露占比**（口径纠错后，用户 2026-09-30）：

```text
leak_rate(f, D) = #{患者: 该患者实际进入模型的值来自 t_hi > 0 的槽位} / #{患者: 管线产出有效值}
```

- 必须**直接使用论文管线（A_pipeline，不做泄露处理）实际提取的值**，并追溯每个值的来源槽位时点（t_hi）；任一来历槽位 `t_hi > 0` 即该患者泄露。
- 旧口径 `1 − n_valid_t0/n_valid_none`（"t0 完全缺失比例"）**作废**：它漏掉"t0 有值但管线取的是更晚值"的患者，且用的不是论文管线的提取逻辑（S2b 数字作废，按新口径重跑）。
- 逐字段报告占比、来源槽位家族；**不设人为阈值**。汇总口径"泄露字段" = `leak_rate > 0` 的字段。

### 2.2 控制变量（Test_2b 与 Test_3 的铁律）

- Test_2b 两臂的**字段集、模板、编码、模型、划分完全一致**，唯一差异 = 是否施加 t0 landmark mask。禁止任何删字段、换模板、换编码、换划分的操作。
- Test_3 对比两臂全部走 bank 切片同一条链路（同编码器/模型/划分），差异只允许在字段集。
- 一切评估沿用现有口径：5 折 val c-index（`cv_c_mean`，5 折均值），不伪造独立测试集，`prefer_val=True`。
- **max_epochs 全链统一 12（2026-10-09 用户拍板）**：搜索/单变量链（`selection/runner.py`、`greedy/cli.py`、`greedy/univariate_cli.py`、`run_selection_queue.py` 默认 12，`evaluate_clinic_dir` 恒显式传参）与 cindex 链（`Clinic_Analyzer/configs/defaults.conf` MAX_EPOCHS=12）同一训练配置；旧 20 轮默认已废止，§7.2 "reach 的 c-index 即搜索 best_cv_c_mean" 由此按构造成立。历史 20 轮口径产物已随 2026-10-09 全链清洗一并删除。

### 2.3 三档定义

| 档 | 含义 | 来源 |
|---|---|---|
| 报告值 | 含泄露（文献口径） | 现有 `results/Test_2b/arm_A/{dataset}[gdc]/cindex.csv`（T3 保留） |
| 去泄露值 | 同字段集 + landmark_0 mask（bank 切片，T31） | Test_3 臂 B（`results/Test_2b/arm_B/` 的 `Test_3_{work}_{ds}` 行） |
| 可达值 | 去泄露池上的贪婪搜索最优 | Test_3 臂 C |

### 2.4 工作与数据集

- "各工作" = A_pipeline 的 10 个论文方案：`MULTISURV`、`SURVPGC`、`MMSURV`、`INTEGRATIVE_DNN`、`HGCN_KIRC`、`HGCN_LIHC`、`HGCN_ESCA`、`HGCN_LUSC`、`HGCN_LUAD`、`HGCN_UCEC`（字段表在 `templates/manual_schemes/{scheme}/fields.json`，句式模板已删除 T31）。
- 数据集（**本阶段**）= `projects/datasets.json` 中的 **33 个 TCGA** 队列。**TCGA 之外的外部数据集（CPTAC、MMRF 等）本阶段一律不纳入**（用户指令 2026-09-29），Test_5c 数据轴阶段再议。S1/S2 已产出的 CPTAC/MMRF 描述性记录保留在磁盘（gitignore 内）但不进入任何训练/选择实验。
- **方案 × 数据集绑定**：HGCN_* 六个方案各绑定其**对应癌种**（HGCN_KIRC→KIRC、HGCN_LIHC→LIHC、HGCN_ESCA→ESCA、HGCN_LUSC→LUSC、HGCN_LUAD→LUAD、HGCN_UCEC→UCEC），禁止把它们塞进其他数据集（用户纠正 2026-09-30）；泛癌种方案（MULTISURV、SURVPGC、MMSURV、INTEGRATIVE_DNN）暂按全部 33 TCGA，但记录为未解决问题 U2（见 §12）。
- **数据集选集一律读 Test_0 manifest，禁止在代码或计划中硬编码名单。**

### 2.5 时间点与 landmark 口径

- **landmark 定义 = 经典三要件**（Anderson 1983；van Houwelingen dynamic prediction / landmarking），三件事必须同时做到：
  1. **风险集**：只保留 T 时刻仍在风险集内的患者（排除 `ground_truth_time ≤ T` 者——T 前死亡者不在 T 风险集，T 前删失者无 T 后随访）；
  2. **时间原点平移**：终点时间改为 `gt − T`（c-index 对平移不变，但仍实现并做不变性自检，以符合规范）；
  3. **只用 T 前信息**：协变量取值仅保留 `t_hi ≤ T` 的槽位（现有值级 mask 已实现这一条）。
- **三要件已全部落地（P1，2026-09-30）**：① mask 在 `src/manual_pipeline/landmark.py`（值级 `t_hi <= T`，复用 `src/time_stats.py` 槽位；原 A_pipeline 已吸收，2026-10-09 订正）；② 风险集与 ③ 平移在 `src/manual_pipeline/landmark_labels.py`（派生 label 文件排除 `gt <= T`、终点改为 `gt − T`，split 文件不动；平移为固定协议动作，无开关——不变性已由历史自检证实，`--landmark_shift` 自检开关已移除）。口径总表见 `z_notes/time_axis/time_axis.md` §3。
- **默认 landmark = `landmark_0`**（t0 约束）：后续所有评估实验（Test_2b 臂 B、Test_3 搜索与两臂）默认 t0。
- **患者资格（2026-10-05 用户拍板）**：`ground_truth_time ≤ 0` 的患者（`days_to_death=0` 占位坑 + 负末次随访，见 `time_axis.md` §2.3）从**所有实验的所有臂**（含报告值对照臂 `landmark_none`）中全局剔除；split 文件不动。实现落点 `Clinic_Analyzer/datasets/dataset_survival.py`（读 label 后即过滤，NaN 保留）；与 landmark 要件②的区别：要件②只作用于 landmark 臂（按 T），本条是跨臂全局数据质量过滤。
- **主诊断判定（2026-10-06 修正）**：`get_primary_diagnosis` 按 `days_to_diagnosis` 最小锚定主诊断（flag 仅同 days 时 tie-break）——GDC `diagnosis_is_primary_disease` 是"研究重点疾病"归属标记而非时间锚点（SKCM 75% 错位，见 `time_axis.md` §2.3）。所有臂（含报告值对照臂）与泄露审计共用该判定。
- 365 / 730 作为敏感性；原 `landmark_none`（landmark off，取值不裁剪）**现名 `no_mask`（2026-10-08 更名；2026-10-05—10-08 间曾被误称 `static_only`）**，**移出主图**，仅进补充材料。
- 两个概念澄清（勿混用；字段线内部再分三模式）：
  1. **取值 mask 状态**：`off`（无 mask，取值全集）/ `0` / `365` / `730`。Test_2a 审计的 leak_rate 用 off 与 0 对比；Test_2b 臂 A = off（报告值对照臂）。
  2. **field-bank 字段线三模式（2026-10-08 拍板，互斥）**：`landmark_{0,365,730}`（数值 landmark，要件① t_hi≤T 裁剪）/ `no_mask`（landmark off，不裁剪，diagnoses/follow_ups 全量 raw 取值；`--landmark_time none` 为其别名）/ `static_only`（新语义：剔除字段路径以 `diagnoses[]`/`follow_ups[]` 开头的全部字段，只留稳定字段；`run_field_bank.py --static_only` 生成，产物 `outputs/{ds}/field_bank/{enc}/static_only/`）。Test_3 搜索池 = `landmark_0`；历史 `rawdata_stats/{dataset}/landmark_none` 目录已随更名迁移。

## 3. 步骤注册表与决策点

| 步 | 内容 | 关键产物 | 决策点 |
|---|---|---|---|
| 编号 | 内容 | 关键产物 | 决策点 |
|---|---|---|---|
| T3 | 枚举并删除 E 系列结果文件 | 删除清单 | **决策点 T3** 删除范围 |
| T1 | **Test_0** 可用数据集评估 | `results/Test_0_dataset_availability/manifest.csv` | **D4** 门槛规则数值；**D1/D2** landmark 有效事件口径与数据集范围 |
| T2 | Test_2a 泄露审计（无训练） | `results/Test_2a_leak_audit/` | 口径已锁定，轻确认 |
| P1 | A_pipeline `--landmark_time` 扩展 + 冒烟自检 | 自检报告 | **决策点 P1** 自检通过后放量 |
| T4 | Test_2b 批跑（选集 = manifest 主集+扩展集） | `results/Test_2b/arm_B` | 异常 → 回推 Test_0 |
| T11/T13 | Field Bank 模板补全 + landmark 变体生成 + univariate 补跑（t0 臂，Test_1a/1b 数据源） | `outputs/*/field_bank/`、`results/Test_1a/arm_t0/` | 模板人工填写进度 |
| T13 | **Test_1a** 对照臂（mask off，`raw` 变体）+ Δc_field 表 | `results/Test_1a/arm_off/`、`results_display/Test_1a_field_level/` | 依赖 Test_2a 审计出 leak_rate 列 |
| T11 | **Test_1b** 各数据集 Cindex 分布 + 跨数据集字段分布 + top-k 重叠度 | `results_display/Test_1b_dataset_cindex/` | top-k 的 k 取值 |
| T14 | Test_3 贪婪批跑（主集）+ 两臂对照（原三臂，T31 更名） | Δc、遗漏字段清单 | **T5/T25** 最优组合口径（sig_stop vs best → gain-only） |
| T23 | Test_4 三档汇总表（收口，非独立实验） | `results_display/Test_4_three_tiers/` | — |
| D9 | 回推 Test_0 manifest v2（Test_5 规格已提前落地，见 §8bis） | manifest v2 | **D9** 数据集降级/剔除逐项确认 |
| T20 | **Test_5 规格落地 + HGCN 产物备份**（§8bis） | 仓库外备份 + 校验记录 | **T21** 路线 A、多模态子集 4 个——已确认（2026-10-03） |
| P3/P4/P7 | Q 指标修复（对齐 SurvPGC）+ 离线重算 | `Clinic_Analyzer/utils/survival_metrics.py`、`results_display/scripts/Test_5_q_recompute.py`、`q_metrics.csv` | 在线 vs 离线 diff=0 |
| P5 | HGCN 编码落地（hgcn_clinic 任意 scheme + landmark 支持，pkl 格式不变）+ L0-L5 等价性回归 | 扩展后的 hgcn_clinic.py、L0-L5 diff=0 报告 | **P6** 等价→放行 / 不等价→冻结 |
| P8/T22 | baseline 编码产物 + Test_5 conf 批跑（5E_2b/5E_3/5M_2b/5M_3）——训练限 **GPU 0–3**（公共服务器 4 卡上限，用户 2026-10-03），Test_3 收尾后启动 | `outputs/*/A_manual/baseline/`、`configs/Test_5_*/`、`results/Test_5_invariance/` | — |
| T28 | Test_5 报告（不变性矩阵收口） | `results_display/Test_5_invariance/` | **T28** 与 Test_4 三档表衔接 |

依赖：T3 → T1 → T2 → P1 → T4；T1 →（数据源 T11/T13）→ T14 → T23；T4/T14 异常 → D9。Test_1a 的 leak_rate 交叉列依赖 Test_2a 出数——**编号顺序 ≠ 执行顺序**，Test_1a 先出 c(off)/c(t0)/Δc_field，leak_rate 列后填。Test_5 链：T20 → P3/P4/P7 → P5 → P8/T22 → T28；T20 不依赖 T14/T23 收尾，但 P8/T22 批跑与 Test_3 续跑共享 GPU/队列资源，执行时协调。

**执行纪律**：单步执行；每步有执行报告（追加到执行日志）；决策点未确认前禁止进入依赖该决策的下一步；决策点确认后做一次 git 提交（见 §9）。**未在用户实验清单中明确的事项（数据集范围、口径、规则数值等），执行前必须先向用户报告并获确认，不得擅自扩大范围或替用户做决定。**

## 4. Test_0 规格：实验可用数据集评估

Test_0 是把"哪些数据集能进哪些实验"做成可复现、可审计、可回推的评估实验。现有 `rawdata_stats/_shared/event_impact_analysis/` 是 Test_0 的原型依据。

### 4.1 输入

- `rawdata_stats/_shared/event_summary.csv`、`rawdata_stats/{dataset}/event_stats.csv`（患者级事件表）
- `Clinic_Analyzer/data/splits/5foldcv/{study}/splits_*.csv`（每折事件数）
- `scripts/fold_event_counts.py`（每折事件数统计，可复用思路）

### 4.2 规则（初始版本，照搬 event_impact_analysis 建议；数值以 D4 确认为准，未确认前 manifest 标注 `provisional`）

1. `n_event ≥ 150`（每折 ≥30）→ **主集**（定量实验主体）；
2. `70 ≤ n_event < 150` → **扩展集**（报告但带 CI，不参与严格排名）；
3. `30 ≤ n_event < 70` → **补充集**（补充材料，bootstrap CI）；
4. `n_event < 30` → **排除集**（训练实验不跑，仅 Test_2a 审计）；
5. `event_rate < 0.1` → 降一级（次级规则）；
6. landmark 变体（365/730）的门槛用**过滤后有效事件数**重套，不用原始总数；有效事件数 = `#{event==1 且 ground_truth_time > T}`（经典 landmark 三要件，见 §2.5）；
7. 退化折（c-index 精确 0.0 / 1.0）→ 该 (dataset, scheme) 点标注并降级；
8. 多字段实验 EPV：每折事件数 ≥ 10 × 字段数。

### 4.3 产物

```text
results/Test_0_dataset_availability/
  manifest.csv            # dataset,tier,n_patients,n_event,event_rate,per_fold_events,
                          # effective_events_lm0/lm365/lm730,degen_folds,rule_hits,note
  {dataset}_profile.json
```

生成脚本：`scripts/run_Test_0_availability.py`（同输入重跑 diff=0 才合格）。

### 4.4 回推协议

执行期任一 (dataset, scheme) 出现：退化折、训练失败、折间 std 超阈值、其他数据质量问题 → 执行报告记录 → manifest 更新（降级或标注）→ **D5** 逐项由用户确认。manifest 更新后递增版本号（v1 → v2）。

## 5. Test_2a 审计规格

### 5.1 输入与范围

- 字段表：`A_pipeline/templates/{scheme}/fields.json`（10 方案，GDC 路径）。
- 数据集：**33 个 TCGA**；方案 × 数据集按 §2.4 绑定（HGCN_* 仅其对应癌种，泛癌种暂按 33 TCGA）。CPTAC/MMRF 不纳入（已产出的描述性记录保留磁盘，但不进汇总与图表）。
- 无训练，纯描述性统计。

### 5.2 计算（新口径，T18 重写；旧数作废）

对每个 (dataset, scheme, field)，**逐患者**追溯"实际进入模型的值"的来源槽位时点：

1. **取值 = 论文管线本身**：调用 `A_pipeline/src/extract.py::extract_values(case, landmark_time=None)`
   （`landmark_time=None` = 无任何泄露处理），得到该患者该字段实际进入模型的值；
   实现上另有一份**镜像追溯**给出该值的来源实体，逐患者与管线取值比对，不一致即报错
   （`src/leak/provenance.py::a_pipeline_provenance`）。**不再**用
   `extract_field_bank_raw_values(landmark=True/False)` 做 t0/tN 两次计数。
2. **来源槽位时点**：来源实体映射到 `src/time_stats.py` 的时间槽
   （`extract_patient_time_record(case)["_slots"]`，按对象身份 id 索引），取该槽位的
   `record_hi` = `t_hi` 与 `record_status`。判据与 §2.5 的槽位口径、与
   `discovery.landmark.slot_passes_landmark`（`t_hi ≤ T` 才保留）同源；状态按
   `z_notes/time_axis/time_axis.md` §4.1 逐条处理：
   `point`/`bounded` 有限 `t_hi > 0` → 泄露；`lo_only`（`t_hi = +∞`，"任何有限 T 都不放行"）→ 泄露；
   `unlocated`/`non_informative`（无 `t_hi`，无法断言属于未来）**不判泄露**，单列
   `n_unlocated_source`，并给出 `n_t0_blocked` = 泄露 ∪ 未定位（该值在 t0 门控下会被丢弃的患者数，
   供与旧口径对照）。
3. **逐患者判定**：值 **有效**（≠ 该字段缺失占位符）时——任一来历槽位按上条判为"未来" → 该患者计入
   分子 `n_leak`；全部来历槽位 `t_hi ≤ 0` / 无时点家族 / 未定位 → 不泄露。
   无效值的患者不计入分母（`n_valid` = 管线产出有效值的患者数）；`n_valid = 0` 时
   `leak_rate = NaN` 且 `leak_rate_undefined = true`。
   **`leak_rate = n_leak / n_valid`**（无人工阈值）。
4. **family** = `src/discovery/landmark.py::timed_family_for_field(field_path)`；无时点家族
   （demographic / exposures / family_histories / project）恒不泄露。逐字段并报
   `source_slot_families`（泄露患者的来源槽位家族）与 `max_source_t_hi`（如 `3801.0`）。
5. **特判**：
   - `derived.*` 字段：按 A_pipeline 自身的派生逻辑追到底层槽位
     （`derived.pharmaceutical_therapy` / `derived.radiation_therapy` → `diagnoses[].treatments[]`，
     `derived.years_smoked` → `exposures[]`（`year_of_diagnosis` 分支另计诊断槽位）），
     **不是**旧实现的"源路径 raw 值"近似；`audited_path` 列记底层路径；
   - `project.project_id`：常数，无来源实体 → `n_no_source = n_valid`，leak_rate = 0；
   - 取值模式（`audit_mode` 列）：字段在 A_pipeline `extract_values` 取值表内 →
     `a_pipeline`（本规格要求的口径）；只在 Field Bank 宇宙（如 Test_1a kept 字段、
     `diagnoses[].tumor_focality`）→ `field_bank`
     （`extract_field_bank_value(landmark=False)` + 同规则来源追溯；用于 §5bis 的 leak_rate 交叉列，
     取值 mask 关闭与 Test_1a arm_off 同源）；
   - 不在 `rawdata_stats/{dataset}/landmark_0/kept_fields.json` 的字段：标记 `not_in_bank`
     （是"无依据"问题的证据之一，**不影响 Test_2b 中该字段的完整性**）。
6. 聚合：每方案每数据集：字段数、泄露字段数（`n_leak > 0`）、泄露字段占比、平均 leak_rate、
   分子/分母合计（`n_leak_total` / `n_valid_total`）；跨数据集聚合时并列 n_event。

### 5.3 产物

```text
results/Test_2a_leak_audit/
  {dataset}/{scheme}.json          # 逐字段: field, family, audited_path, audit_mode, n_valid, n_leak,
                                   #         leak_rate, leak_rate_undefined, n_lo_only_source,
                                   #         n_unlocated_source, n_untimed_source, n_no_source,
                                   #         n_t0_blocked, source_slot_families, source_slot_statuses,
                                   #         max_source_t_hi, not_in_bank
  {dataset}/G1_{md5(field_idx)}.json  # Test_1a 消费的逐字段审计（§5bis）：33 数据集 × 各自
                                   #   landmark_0 kept 字段（1083 个）；scheme 名 =
                                   #   greedy.embeddings.subset_scheme_name([field_idx])，
                                   #   schema 对齐 results_display/scripts/Test_1a_field_level.py
  leak_audit_summary.csv           # (dataset, scheme) 级聚合 + n_event 并列
results_display/Test_2a_leak_audit/ # 图: 每工作×癌种泄露占比、逐字段泄露率热图
```

新代码：`src/leak/`（`provenance.py` 值来源追溯引擎、audit.py、cli.py）+
`scripts/run_leak_audit.py` + `tests/test_leak_audit.py`。
产物**不含时间戳**（`audit_version` 为常量），同一命令重跑逐字节一致（`diff -r` = 0）。
验收：抽查 ≥3 个 (dataset, scheme, field) 与手工 JSON 核对一致（独立脚本，不 import `src/leak`）。

## 5bis. Test_1a 单字段泄露对照（时间轴链动机 + Test_2b 的机制解释）

- **动机**（用户指令 2026-09-30）：TCGA clinical 记录自带时间，同一字段在有无 t0 时间口径下 c-index 会实质变化——时间处理是应该的；且 Test_2a 只测"可得性"（leak_rate），Test_2b 整组合 Δc≈0 时读者无法解释"为何存在泄露却没有转化为高估"。单字段对照把两个实验连起来。
- **做法**：对每个 (dataset, field)（field = landmark_0 kept 字段集；dataset 仅 label 宇宙有效事件 ≥ 100 的 13 个主集，见登记表 T12/T39）：
  - 臂 off：同患者集（排除 gt≤0，与 Test_2b 臂 B 一致）、取值 **mask 关闭** → c(field, off)；
  - 臂 t0：同患者集、mask 开 → c(field, landmark_0)；
  - Δc_field = c(off) − c(t0)，与 Test_2a 审计的 leak_rate 交叉。
- **产物**：`results_display/Test_1a_field_level/`：leak_rate × c(off) × c(t0) × Δc_field 交叉表（逐 dataset 与跨数据集聚合）+ 散点/热图（x=leak_rate, y=Δc_field）；输出"理论上能动组合 Δc 的字段清单"（leak_rate 高且 |Δc_field| 非平凡）。
- **实现**：新增 field bank 变体 `raw`（字段列表 = landmark_0 kept，取值 mask 关闭，提取 landmark=False），univariate 评估两臂共用同患者集（复用派生 label 机制（P1），gt≤0 排除）。
- **验收**：抽查 3 个 (dataset, field) 手算一致；两臂患者集逐位一致；交叉表与 Test_2a 审计 leak_rate 数值一致。

### 5bis.1 landmark-first 字段准入（t0 口径，2026-10-05）

- **动机**（用户指令 2026-10-05）：§5bis 的 kept 字段集是在原始数据上按 R3/R4 筛选的，landmark mask 在 Field Bank 取值时才生效——部分字段 mask 前覆盖率 40%、mask 后只剩 5% 甚至 0，其 t0 臂实际是全占位符（常数特征，c≈0.5），Δc 是"字段整个消失"造成的，不应计入"时间处理改变评估值"的统计。实测 15 主集 468 对 (dataset, field) 中 124 个（26.5%）t0 覆盖率 < 0.30（68 个 ≈ 0），集中在 `diagnoses[].treatments[].*`（剂量类）、`follow_ups[]`、`molecular_tests[]` 等。
- **准入口径**：先 landmark 再处理——字段统计（coverage / unique_count / mode_share）在 Field Bank 同款 landmark mask 上计算（`extract_field_bank_raw_values`，与 t0 臂 .pt mask 严格同源），再跑现有 R0-R6 筛选 `--R3_coverage 0.30 --R4_n_unique 2 --R4_mode_share 0.95`。
- **产物（已扶正为现行链，2026-10-05 用户拍板）**：
  - t0 口径统计：`rawdata_stats/{dataset}/landmark_0/field_stats.csv` + `rawdata_stats/_shared/landmark_0/field_stats.csv`（根级 `field_stats.csv` 保持 raw 口径，作为 off 臂覆盖度对照）；
  - 现行筛选产物：`rawdata_stats/{dataset}/landmark_0/{kept_fields.json, fliter_log/...}` + `_shared/landmark_0/kept_fields.json`——由 landmark-first 统计筛得；`run_field_filter` 在 landmark 开启且对应 landmark 统计存在时默认消费它（显式 `--stats_csv` 仍可覆盖）；
  - 运行：`scripts/run_field_stats.py --landmark_time 0` → `scripts/run_field_filter.py --landmark_time 0`（两步开放接口，R3/R4 阈值可命令行覆盖）；验收器 `scripts/validate_t0stats_vs_masks.py`；
  - raw-first 旧口径产物已移走（`z_notes/backup/landmark_first_promotion_20261005/`），旧下游运行已删除，清理清单 `z_notes/cleaned_runs_landmark_first_20261005.md`。
- **Test_1a 报表联动**：`Appx_field_delta.csv` 新增 `coverage_off / coverage_t0 / t0_filter_status / t0_filter_rule / t0_filter_trigger` 列（全部行）；头条统计、Main_ 图、`Main_field_ranking.csv`、influential 清单、`Raw_delta_matrix.csv`、Meta 头条数字只在准入集上计算；被排除字段单列 `Appx_excluded_fields.csv`。
- **存在性头条图**（用户指令 2026-10-05）：新增 `Main_field_existence.png`（两面板：coverage(off)→coverage(landmark_0) 崩塌散点 + 逐数据集准入/R3/R4 构成），承载修正后的头条命题「时间口径决定单字段是否存在」。
- **验收**：t0 stats coverage 与 t0 臂 .pt mask 逐字段比对 max_abs_diff ≤ 1e-5；报表重跑 diff=0。
- **边界**：field bank 与 Test_1a/1b 等下游按新 kept 字段集重跑（范围见待决事项 T30）；`results/Test_2a_leak_audit` 的 G1 逐字段审计按新 kept 列表 field_idx 重排后需重跑（审计归用户接手）。

## 5ter. Test_1b 各数据集 Cindex 情况（字段轴链动机）

- **动机**（用户指令 2026-10-02）：字段在各个数据集中的预测能力各不相同 → 每个数据集在理论上存在属于自己的最优字段组合 → 针对数据集做合适的字段选择是应该的。Test_1b 用单字段 c-index 量化这种不均衡，作为 Test_3（选字段）的存在理由。
- **数据源**：univariate 补跑结果（Test_1a t0 臂数据源） `results/Test_1a/arm_t0/prompt/landmark_0/{dataset}/mlp_clinic_flatten/field_cindex.csv`（33/33 已完成；5 折 × seed 0，同 Test_1a t0 臂）。**不新增训练**。
- **分析（三个量化指标）**：
  1. **各数据集单字段 c-index 分布**（原 E1 Fig2 升级版）：per-dataset 单字段 c-index 条形/分布图，按协议 A 四档分层标注；
  2. **同一字段跨数据集 c-index 分布**：量化字段能力随数据集的变异（对公共字段）；
  3. **top-k 字段重叠度**：各数据集按单字段 c-index 取 top-k（建议 k ∈ {5, 10, 20}，决策点 T11）后两两/整体重叠，重叠低 = 最优组合确实因数据集而异。
- **产物**：`results_display/Test_1b_dataset_cindex/`（图 + 聚合表）；脚本 `results_display/scripts/Test_1b_dataset_cindex.py`（由原 `E1_Fig2_Single-field c-index.py` 重命名扩展）。
- **验收**：同输入重跑 diff=0；抽查 3 个 (dataset, field) 与 `field_cindex.csv` 手算一致；与协议 A 分档并列 n_event。

## 6. Test_2b 规格

### 6.1 A_pipeline landmark 扩展（P1 实现）

- `A_pipeline/src/extract.py` 支持 `--landmark_time {0,365,730,none}`（默认 `none`，**行为与现有完全一致**）：按经典 landmark 三要件（§2.5）实现——① 协变量 mask：timed family 槽位只保留 `t_hi <= T` 的取值，其余按现有缺失规则处理（复用 `projects/src/discovery/landmark.py` 的患者级时间记录与 mask，A_pipeline 内通过 sys.path 接入 projects 的 `src`）；② 风险集：`ground_truth_time <= T` 的患者从训练/评估集排除；③ 时间原点：label 时间改为 `gt − T`，并做一次 c-index 平移不变性自检（365 上验证重 base 与不重 base 数值一致）。
- `pipeline` / `json2prompt` / `encode` / `baseline` 命令透传该参数；产物落 `outputs/{dataset}/A_manual/{scheme}/landmark_{T}/`（`none` 时维持现有目录不变）。
- cindex 结果落 `results/Test_2b/arm_B/{dataset}/cindex.csv`，**不覆盖** `results/Test_2b/arm_A/`；走现有 Test_3_arms 队列调度（`A_pipeline/run.py cindex`）。

### 6.2 两臂定义

```text
臂 A（报告值对照）: 完整原字段集 × landmark_none（新链路）
臂 B（去泄露值）:   同一字段集 × landmark_0    ← 字段数相同，唯一差异 = mask
```

### 6.3 自检（P1 的放量前提，决策点 P1）

BRCA × MULTISURV：臂 A 经新链路跑通后与旧 `results/Test_2b/arm_A/TCGA-BRCA[gdc]/cindex.csv` 数值**必须完全一致**（diff=0）。不一致不允许放量，排查原因后重跑。

### 6.4 范围

10 方案 × (manifest 主集 + 扩展集) × 两臂；每 (scheme, dataset) 报告 `c(none)`、`c(0)`、`Δc = c(none) − c(0)`。

## 7. Test_3 规格

### 7.1 搜索

- 池：模板补全后的 `landmark_0` field bank（2026-10-02 现状核对：33/33 模板已填齐）。
- 算法：复用 E2 的 `A2_greedy`（`src/selection/`，summary_only + SQLite 缓存 + 早停 + 逻辑预算）。
- 数据集：manifest 主集；最优组合默认 = 早停推荐子集（T5 已确认：0.005 阈值，另报历史 best）。
- **T25 修订（2026-10-04，用户确认）**：早停口径由 sig_stop 改为 **gain-only δ=0.005**——去掉 paired Wilcoxon p<0.05 门槛（n=5 时 p<0.05 要求 5/5 折全正，过严）；新判定：gain ≥ 0.005 → 更新 k_star 且 count=0；gain < 0.005 → count+1；连续 3 步停，k_sig=k−3；delta/patience 数值不变；历史 best 仍另报。实现为 `--stop-mode {sig,gain_only}`（sig 保留为默认）；Test_3 重跑使用 gain_only（stop_reason 记 "gain_stop"）。

### 7.2 两臂对照（全部走 bank 切片链路，同编码器/模型/划分/seed）

> 臂语义唯一来源 = `z_notes/experiment_list/arm_registry.md`；本节的 `deleak` / `reach` 即注册表短标签。

```text
deleak : 工作完整组合 × landmark_0   (去泄露值;原"臂 B′"更名而来;切片自 field bank)
reach  : 贪婪最优组合 × landmark_0   (可达值;fields 由搜索结果生成;切片自 field bank)
```

> 先编码,后实验:field bank 是一次性统一编码基座,臂条件 = {F 字段组合, T 时间口径} 二元组,
> "bank 切片"是装配操作而非条件因子(见 arm_registry.md 核心模型)。

- **T31 修订（2026-10-07，用户拍板）**：编码统一为 field bank 一种模板源——论文方案的句式模板（template.csv）分支整体删除，`manual_schemes` 只保留 fields.json 字段登记（元数据）；原"臂 B（scheme 模板）"随之退役，原"臂 B′（bank 模板）"更名为**臂 B**（现名 `deleak`）。三臂变两臂。
- **编码路径**：任何字段组合（论文的、贪婪的）一律按字段索引**切片 bank 嵌入矩阵**（零 CONCH 重编码，与 E2 搜索评估器同路径，切片与 bank 行逐位一致）。`--landmark_time` 值域：`0|365|730`（mask 开）、`none`/`no_mask`（landmark off，mask 关 + 与 landmark_0 同字段集，时间轴对照用；Test_3 侧 bank 变体名 `raw`）、`static_only`（稳定字段子集，剔除 `diagnoses[]`/`follow_ups[]` 字段，字段集不同；2026-10-08 新语义，`run_field_bank.py --static_only` 生成）。三者不可混用。
- deleak 字段集 = 论文方案 fields.json ∩ bank 字段索引；不在 bank 的字段记入遗漏清单（"无依据导致遗漏"的物证）。
- 头条 Δc = reach − deleak（模板、编码、模型、划分全同，唯一差异 = 字段集）。
- 时间轴对照（mask 效应） = report（工作组合 × `raw` bank）− deleak（landmark_0）；报告值 = 论文历史报告数（外部数字，不复跑）。
- reach 的 c-index 即搜索 result.json 的 `best_cv_c_mean`（同嵌入、同模型、同 5 折、同 seed）；如需独立落表训练，走与 deleak 相同的切片流程。

### 7.3 产物

`results/Test_3_greedy_vs_works/`（两臂 c-index 表、Δc、遗漏清单）+ `results_display/Test_3_greedy_vs_works/`（图）。

## 8. Test_4 三档汇总表（非实验，收口 Test_2+Test_3）

- **定位**（用户指令 2026-10-02）：Test_4 不是独立实验，只是 Test_2（高估链）与 Test_3（低估链）的**汇总产物表**——一个 Test 可以对应多张表，表本身不占实验命题。两个档差分别收口两条链：报告值−去泄露值 = 时间轴链收口；去泄露值−可达值 = 字段轴链收口。
- **3a 三档表**：每 (dataset, work) 一行：报告值（冻结 apipe 历史 = 旧 A_manual，待 report 臂 bank 重建替换）、去泄露值（deleak 臂 = Test_3_{work}_{ds} bank 行）、可达值（reach 臂 = 搜索 best_cv_c_mean）、档间 Δ；主集定量、扩展集带 CI；并列 n_event / event_rate / 每折事件数。
- 产物：`results_display/Test_4_three_tiers/`。

## 8bis. Test_5 规格（不变性：编码 / 模型 / 指标轴）

> 臂（实验条件）定义唯一来源 = `z_notes/experiment_list/arm_registry.md`。Test_5 子检查 =
> 轴 × 臂对：{5E_2b,5M_2b} 重复 {`report`, `deleak`}，{5E_3,5M_3} 重复 {`deleak`, `reach`}。
> 历史字母代号 A/B/Bp/C 已退役；apipe 全量编码路径已删除（T31 + 2026-10-09 收尾），
> 5E_2b/5M_2b 的历史产物基于已删编码，bank 重建批次待排期。

### 8bis.1 命题与三轴

Test_5 = 一个命题（不变性）：**Test_2b（时间轴链）与 Test_3（字段轴链）的结论在换编码、换分析器、换指标后依然成立**。被检验的两个结论：

- 2b 结论：无数据集级系统性高估（臂 A−B 的 Δc 模式与方向一致率）；
- 3 结论：贪婪可达 > 工作组合（Δc = C − B）。

三轴候选（基线加粗）：

| 轴 | 候选 | 来源 |
|---|---|---|
| E 编码 | **prompt**（CONCH 文本塔 `(n_fields,512)`）/ baseline（onehot_ordinary D-向量）/ hgcn_clinic（全连接图节点,1024 pad） | A_pipeline `--encoding text/baseline`、`hgcn_clinic` 子命令 |
| M 分析器 | **mlp_clinic_flatten** / snn_clinic_flatten / clinic_cox / survgc_f、survpgc_f（多模态） | Clinic_Analyzer `--modality` |
| Q 指标 | **cv_c_mean**（5 折 val c-index）/ IBS（月网格 1–60）/ 时依 AUC@24/60 / IPCW c-index | 修复后的 sksurv 指标层（§8bis.4） |

**锁定基线**（除被换轴外一律不变）：E=prompt、M=mlp_clinic_flatten、Q=cv_c_mean、landmark_0、5 折 × seed 0、协议 A 训练范围（**只在 label 宇宙有效事件 ≥ 100 的 13 个主集上新增训练**，R13；低档数据集不新增训练）。

### 8bis.2 四个子检查

| 子检查 | 换的轴 | 重复什么 | 范围（13 主集） | 新 confs（估计） |
|---|---|---|---|---|
| 5E_2b | E→baseline（本轮）；E→hgcn_clinic（编码先落地，评估臂待 HGCN 模型接入后补跑） | Test_2b 臂对 {`report`（mask 关）/`deleak`（lm0）}，字段集、模板、划分全同 | 绑定 combos ≈64 × 2 臂 × 2 编码 | ≈256（本轮 ≈128） |
| 5E_3 | E→baseline（本轮）；E→hgcn_clinic（同上，待模型） | Test_3 臂对 {`deleak`/`reach`}（固定字段组合重评，不重跑贪婪搜索） | 13 主集 × (4 deleak + 1 reach) | ≈65（本轮 ≈33） |
| 5M_2b | M→snn_clinic_flatten；M→survgc_f/survpgc_f | Test_2b 臂对 {`report`/`deleak`}（prompt 复用既有编码产物） | ≈64 × 2 臂 × snn；4 多模态数据集 × 绑定 × 2 臂 × 2 模型 | ≈128 + ≈72 |
| 5M_3 | M→clinic_cox | Test_3 臂对 {`deleak`/`reach`}（prompt 复用） | 13 主集 × (4 deleak + 1 reach) | ≈65 |

**本轮合计 ≈388 confs**（prompt 臂全部复用 Test_2b/Test_3 既有产物，零新增）；hgcn 评估臂 ≈188 confs 待模型接入后补跑，全量 ≈546。

- **多模态子集（用户确认 2026-10-03；2026-10-09 随 13 主集收窄）** = 协议 A 13 主集 ∩ registry 多模态 5 数据集 = **BRCA / LIHC**（COAD 90、KIRC 86 出主集；KIRP 44 事件被排除）。survgc_f / survpgc_f 只在这 2 个数据集上跑。

### 8bis.3 HGCN：编码先落地、模型暂不接入（用户指令 2026-10-03）

- **编码保留并先落地**：hgcn_clinic（全连接图节点,1024 pad）为 E 轴第三档；P5 完成编码侧扩展——任意 scheme（fields.json 驱动 + GDC 字典类型分类）+ landmark 支持（现 CLI 明确不支持 `--landmark_time`，cli.py:155-156）——产物沿用既有 pkl 格式（`x_cli.pkl`/`edge_index_cli.pkl`），**不加模型消费方**。
- **模型暂不接入**：用户已移植进 Clinic_Analyzer 的 HGCN 训练器为独立工作；E=hgcn 的评估臂（5E_2b/5E_3 的 hgcn 行）**待模型接入后再跑**，届时另定对接协议。本轮 M 轴不含 HGCN 模型。
- **L0-L5 等价性回归（原要求继续有效）**：P5 修改 hgcn_clinic.py 后，重跑 L0-L5 编码与冻结备份 `diff -r` = 0 才放行；否则既有 `outputs/{9 数据集}/A_manual/HGCN_clinic/`（L0–L5）冻结（不覆盖、不重跑），新产物另立命名空间。备份在仓库外 `/data/fangyuxuan/projects/medical_dl/backups/HGCN_clinic_2026-10-03/`（1.4G，S9 日志）。
- Clinic_Analyzer 侧零改动。

### 8bis.4 Q 指标修复（对齐 SurvPGC 参考实现）

Clinic_Analyzer 现有 `utils/core_utils.py::_calculate_metrics`（:535-617）6 处缺陷（均静默降级为 0）：① 无共享指标层；② 评估网格硬编码 `[min+eps,12,36,60]`（应为月网格 1–60 / landmark [24,60]）；③ 生存曲线未插值到网格；④ AUC 列错位 + `np.append(iauc_list,0)` 多塞元素；⑤ 无守卫（不可用应记 nan 非 0）；⑥ cox 路径完全缺失（clinic_cox 的 IBS/AUC 恒 0）。修复 = 逐字移植 SurvPGC `utils/survival_metrics.py` + 按 SurvPGC `core_utils.py:1944-2091` 重写 + 移植 `_collect_train_survival_risks`（cox Breslow）+ 裸 except 改打印原因。

离线重算（不新增训练）：离散模型从各折 `split_{fold}_results.pkl` 的 logits 重建生存曲线；cox 模型用 checkpoint 做 train-forward 补 Breslow（仿 SurvPGC `results_display/scripts/Table1_CoxBreslow_Forward.py`，args 重建走 experiment.txt + confs）。对既有 Test_2b/Test_3 全部 confs 与 Test_5 全部新臂统一出 Q 电池（c-index / IBS / AUC@24 / AUC@60 / IPCW）；**新臂"在线写入值 = 离线重算值"（diff=0）为双重验收**。

### 8bis.5 验收与产物

- 控制变量审计：每 conf 唯一差异 = 被换轴；重跑 diff=0。
- 统计口径：方向一致率（Test_2b 的 10/15 同款）+ paired Wilcoxon（Test_3 sig_stop 同款）。
- 产物：`results/Test_5_invariance/{5E_2b,5E_3,5M_2b,5M_3}/`、`results_display/Test_5_invariance/`（每子检查对照表 + Q 四指标并排表 + 2×3 不变性矩阵收口）；命名全程 `Test_5_*`（configs / results / results_display）。

## 9. Git 提交协议

- **只有明确的决策点（用户拍板/口径确认）才可以成为一次提交**（用户指令 2026-10-05）。脚本小改、改名、以及决策点的单步实现**不单独提交**，随所属决策点一起提交。
- 提交只包含本决策点的文件（`git add <具体路径>`；工作树有他人并发修改时禁止 `git add -A`）。
- `results/`、`results_display/`、`outputs/`、`rawdata_stats/` 已被 .gitignore，产物不入库；提交内容 = 代码、脚本、文档、测试。
- 提交信息：`{决策点摘要}`，结尾加 `Co-Authored-By: Claude Code <noreply@anthropic.com>`。
- 决策点提交后 push 到 origin。

## 10. 执行日志协议

- **单文件归档**：`z_notes/Test_series_execution_log.md`，所有执行报告追加到该文件（不另开文件）。
- **2026-10-05 起**：本文件为统一"改动登记"表（改动名称 | git 提交 | 时间 | 简单描述，全量历史已重排入表），新改动追加一行即可，不再使用下方 S{n} 模板（旧长篇日志归档于 `backup/execution_log_legacy_20261005.md`）。
- 追加前先重读文件末尾，避免覆盖并发写入。
- 历史模板（2026-10-05 前）：

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

- 不删除、不覆盖 `results/Test_2b/arm_A/`、`outputs/*/A_manual/`、`outputs/*/field_bank/`、`rawdata_stats/`。
- 不修改现有 5 折 split；不伪造独立测试集；不把 val 称为 test。
- 不修改 E 组代码（`src/selection` 的 SEAS/A3–A6/ANCHOR 等）——其去留由用户与执行方协商，本系列只读复用 A2_greedy/evaluator/cache/queue。
- 不在代码或配置中硬编码数据集分层名单（一律读 Test_0 manifest）。

## 12. 未解决问题（Open Issues）

- **U1（D12 门槛锚点）**：已弃用无推导的 0.05 断言。**用户数据协议（2026-09-30）——n_event 判据（作用=评估方差下限）已定**，适用于 Test_ 系列全部 TCGA 使用（泛癌种工作同样适用）。**2026-10-09 修订（用户拍板）**：门槛计数口径 = **label 宇宙有效事件**（患者级前置过滤同口径；raw n_event 含 gt≤0 等从不进训练的病例），主集由此收敛为 13 个。

  | n_event 档（label 宇宙有效事件） | 处理 | 33 TCGA 数据集 |
  |---|---|---|
  | ≥100 | 主图，干净集 | **13 个**（PAAD、LGG、LIHC、LAML、BRCA、STAD、BLCA、LUAD、LUSC、SKCM、HNSC、OV、GBM；COAD 90、KIRC 86 出主集） |
  | 70–100 | 进主图，**必须报告 CI，不参与严格排名** | CESC、MESO、ESCA、UCEC、SARC、COAD、KIRC |
  | 30–70 | 补充材料，bootstrap/重采样 CI，不排名 | UVM、ACC、UCS、KIRP |
  | <30 | 定量图不收录；单列"低事件组"定性讨论 | 9 个（READ、CHOL、THCA、KICH、PRAD、DLBC、THYM、TGCT、PCPG） |

  **训练范围（T12，2026-10-02 用户指令；2026-10-09 修订口径）**：后续训练类实验**只在 label 宇宙有效事件 ≥ 100 的 13 个数据集上训练**；<100 档不新增训练，其已有训练结果按协议 A 分层报告（70–100 带 CI 不排名、30–70 补充、<30 定性）。Test_3 的主集即这 13 个。

  **B/C/D 判据：用户 2026-09-30 指令——暂不执行，保持简单**：B（多字段门槛：≥150 可跑 / 100–150 字段数≤3）、C（landmark 有效事件重套）**存档备查**（见执行日志 R5/R6），当前实验执行**全部按 A 判据**；D（次级修正）不采用。若后续需要再启用 B/C，再议。
- **U2（泛癌种方案绑定）**：MULTISURV / SURVPGC / MMSURV / INTEGRATIVE_DNN 是否按各自论文原始队列绑定，**暂按全部 33 TCGA 执行**，记录为未解决问题；待用户给出各论文队列口径后修正。
