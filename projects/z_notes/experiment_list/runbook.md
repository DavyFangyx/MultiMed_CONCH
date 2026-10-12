# 实验执行手册:全链路 runbook(审查 → 编码 → 实验 → 报表)

> **只想快速开跑:见同目录 `usage.md`(精简速查);本文件是完整版**,判据细节 / env 速查 / 已知坑以本文件为准。
> **本文件是实验执行的权威手册**:阶段划分、命令、判据、产物以这里为准。
> **分步手动执行**:长序列运行、部分节点需人工核查审计,不提供一键串行脚本(已撤销,见执行日志 P19);按下方阶段顺序逐阶段执行并核对判据。
> 口径权威:`z_notes/experiment_list/experiment_list.md`(实验清单)、`z_notes/Test_series_spec.md`(规格)、
> `z_notes/protocol1_landmark/time_axis.md`(时间轴协议);目录命名见 `z_notes/experiment_list/naming_convention.md`。
> 所有命令都在 `projects/` 根目录执行。环境:训练 = conda env **SurvPGC**,编码 = conda env **conch**,
> 投递/监控 = **base python 3.13**。队列纪律:**上一步判据满足再走下一步**(不要并行 stage,除非明确说可并行)。
> **队列入口已收敛**:投递/监控一律 `bash scripts/exp_queue.sh <verb> --arm <臂>`
> (臂/别名/组:`python3 scripts/exp_queue.py list`;臂注册表与三 backend 见 `scripts/exp_queue.py` 头注释)。
> 例外 = Test_3 搜索 / Test_6 的 **watch·drain**(动态槽位调度):留在 `scripts/Test_3_search_queue.py` / `scripts/t6_scheduler.sh`。

---

## 一页速览:全链路八阶段(阶段 0 = 前置闸门)

| # | 阶段 | 入口(projects/ 根目录执行) | 判据 | 产物落点 |
|---|---|---|---|---|
| 0 | 前置闸门 | `python scripts/check_search_labels.py` | 退出码 0 | 只读报告,无产物 |
| 1 | 数据准备与原始文件审查(label 重建/split 重建/扫描/统计/筛选) | `rebuild_labels.py --all`(⓪a,可选) → `generate_5fold_splits.py --all --seed 1`(⓪b,可选) → `run_scan_fields.py` → `run_field_presence.py` → `run_field_stats.py --landmark_time 0` → `run_field_filter.py --landmark_time 0` | 退出码 0;split 并集 == label 患者集(多模态 5 集 = 完备病例子集);`rawdata_stats/{ds}/landmark_0/kept_fields.json` 齐备(registry 全量 35 数据集) | `Clinic_Analyzer/data/splits/5foldcv/`、`rawdata_stats/{ds}/…`、`rawdata_stats/_shared/landmark_0/` |
| 2 | 编码(Field Bank / 方案 / label 派生) | `scripts/run_field_bank.py` → `run_a_manual.py`;`bash scripts/exp_queue.sh bank --arm test_1a_off` | 退出码 0;主集 Field Bank 基座齐备;off 臂 raw bank 齐(主集名单自动派生,权威见 cohort_rules §0.3;label 派生随 cindex 自动落盘) | `outputs/{ds}/field_bank/…`、`outputs/{ds}/A_manual/…`、`outputs/_raw/{ds}/…` |

| 3 | 实验(Test_1a / Test_2 / Test_3 / Test_5 / Test_6,各一个实验小节) | 每实验 = `enqueue --arm <臂>` → `drain --arm <臂> --gpus <卡> --workers <数>`(一条 drain 守到完成:失败重试/死进程补位/收尾报表,无 watch);Test_3 搜索与 Test_6 的动态槽位调度留在 `Test_3_search_queue.py` / `t6_scheduler.sh` | 各实验判据见小节(done == 期望数,exp_queue 派生) | 各实验小节"产物"栏 |
| 4 | 报表(展示层,不训练) | `python results_display/scripts/{Test_1a_field_level,Test_1b_dataset_cindex,Test_2b_delta_report,Test_4_three_tiers}.py` | 退出码 0(脚本幂等,可反复跑) | `results_display/` 4 个目录 |

**依赖关系(串行顺序的由来)**:

```
阶段 1 审查 ─→ 阶段 2 编码 ─→ 阶段 3 实验(Test_1a ─┬─→ Test_2(2a → 2b)
                                              ├─→ Test_3(搜索 → 两臂 → Test_4)
                                              ├─→ Test_5(需 2b / 3 先落盘)
                                              └─→ Test_6(需 Test_1a 先验;建议最后跑))
阶段 4 报表 ← 上游 results/ 落盘后随时可跑(纯汇总)
```

- **并行例外**:Test_2(时间轴链)与 Test_3(字段轴链)互不依赖,允许同时投放;其余按编号串行。
- **GPU 纪律**:Test_5 硬约束只用 GPU 0-3 且放置时为空闲卡(4-7 不碰);编码默认卡见阶段 2(FIELD_BANK_GPU / A_PIPELINE_GPU 默认 6/7);最多 4 个 drainer;不 kill 他人进程。
- **训练范围(R13,2026-10-02)**:训练/搜索限 **label 患者集有效事件 ≥ 100 的主集**(名单自动派生不硬编码:`common.patient_set::main_datasets_by_label_events`;权威口径见 `z_notes/protocol0_cohort_selection/cohort_rules.md` §0.3);
  <100 档不新增训练(历史结果已随 T35 清洗;四档语义见数据集分档协议)。
- **队列四桶**:全实验共享 `Clinic_Analyzer/configs/{queue,running,done,failed}` 四桶(flat 布局,conf 名自带家族区分,见 `Clinic_Analyzer/configs/README.md`);+ `parked/` = 撤下但保留,不被 drainer 读取;
  判据一律 "queue 空 && running 空 && done ≥ 期望数"(桶里可能含历史超集,见"已知坑" 8)。

---

## 结果在哪看(总览)

| Test / 阶段 | `results/` | `results_display/` | 队列家族目录(`Clinic_Analyzer/configs/`) |
|---|---|---|---|
| 阶段 1 审查 | —(`rawdata_stats/{ds}/`) | — | — |
| 阶段 2 编码 | —(`outputs/{ds}/`、`outputs/_raw/{ds}/`) | — | — |
| Test_1a 单字段 | `results/Test_1a/arm_t0/`(软链 → `results/univariate/`)、`results/Test_1a/arm_off/` | `Test_1a_field_level/` | `Test_1a_t0`、`Test_1a_off` |
| Test_1b 各数据集分布 | (数据源 = `results/Test_1a/arm_t0/`) | `Test_1b_dataset_cindex/` | — |
| Test_2a 泄露审计 | `results/Test_2a_leak_audit/` | `Test_2a_leak_audit/` | — |
| Test_2b 去泄露对照 | `results/Test_2b/arm_A/`(报告值)、`arm_B/`(去泄露值) | `Test_2b_delta/` | `Test_2b_arms` |
| Test_3 搜索 + 两臂 | `results/Test_3_greedy_vs_works/`(+ `results/Test_3_search/cache.sqlite` 缓存) | `Test_3_greedy_vs_works/` | `Test_3_search`、`Test_3_arms` |
| Test_4 三档收口 | (汇总,无独立训练) | `Test_4_three_tiers/` | — |
| Test_5 不变性 | `results/Test_5_invariance/{5E_2b,5E_3,5M_2b,5M_3}/` | `Test_5_invariance/`(q_metrics.csv) | `Test_5_5E_2b`、`Test_5_5E_3`、`Test_5_5M_2b`、`Test_5_5M_3` |
| Test_6 算法选型 | `results/Test_6_search/` | `Test_6_search/`(decision.json) | `Test_6_search` |
| 阶段 8 报表 | — | `Test_1a_field_level/`、`Test_1b_dataset_cindex/`、`Test_2b_delta/`、`Test_4_three_tiers/` | — |

展示层文件前缀角色:`Main_` = 头条(回答命题)、`Appx_` = 附录、`Raw_` = 原始矩阵、`Meta_` = 元数据与审计。
`results/`、`results_display/`、`outputs/`、`rawdata_stats/` 均 gitignore(只入库 `results_display/scripts/`)。

---

## 阶段 0:前置闸门

```bash
# 在 projects/ 根目录;base python 3.13;只读
# 闸门:搜索链路 label 无 gt≤0 患者(FAIL → 先修 label,再投任何队列)
python scripts/check_search_labels.py
```

- **判据**:退出码 0(`check_search_labels.py` 发现 gt≤0 会 `sys.exit(1)`)。
- **产物**:无(只读报告)。`check_search_labels` 打印每数据集 `n_gt_le_0` 明细与总线。
- 闸门脚本缺失时先补脚本再投任何队列(不阻塞下游的话可记入已知坑);脚本存在但失败 = 阶段失败。

---

## 阶段 1:数据准备与原始文件审查(label 重建 → split 重建 → 扫描 → 统计 → 筛选)

输入是**原始文件**(`ClinicDatasets/gdc_clinical/raw_json/{ds}.json`)与 t_write 另册,
label CSV 重建后供全链消费;不训练、不用 GPU;产物落 `Clinic_Analyzer/data/splits/` 与 `rawdata_stats/`。

```bash
# ⓪a label 重建(可选):t_write 另册 + 原始 JSON → 生存结局表;规则0 先删坏行
#    (gt≤0 全局剔除,cohort_rules §0.1)。只写 label/clinical CSV,不生成 split。
python Clinic_Analyzer/dataset_deployment/scripts/rebuild_labels.py --all
# ⓪b split 重建(可选):从现行 label metadata 重生成 5 折(seed 1 确定性分层轮转;
#    多模态 5 集自动做 W∩C∩G∩RNA 完备过滤 → 多模态功能不受影响)。
python Clinic_Analyzer/dataset_deployment/scripts/generate_5fold_splits.py --all --seed 1
# 判据:每数据集 split 并集 == label 患者集(多模态 5 集 = 完备病例子集)。

# ① 字段字典扫描:字段路径 + GDC 字典释义(失败 → 检查 ClinicDatasets/gdc_clinical/raw_json/ 原始文件是否齐)
python scripts/run_scan_fields.py --dataset all
# ①b 与官方 mapping 对照(字段存在性审计;只读)
python scripts/run_field_presence.py --dataset all

# ② 现行 landmark-first 统计:患者分母 = label 患者集(gt≤0 等"杂质"在字段级统计之前即被剔除),   # --landmark_time 0,365,730,none
#    t0 mask 口径,写 _shared/landmark_0/(失败 → 看 rawdata_stats/_shared/ 产物)
python scripts/run_field_stats.py --dataset all --landmark_time 0
# ③ R0-R6 筛选:自动消费 ② 的 landmark 统计,R3/R4 阈值可命令行改(失败 → 看排除日志 fliter_log/)
python scripts/run_field_filter.py --dataset all --landmark_time 0 \
    --R3_coverage 0.30 --R4_n_unique 2 --R4_mode_share 0.95 --write_templates

# 需要重生成/填充 Field Bank 长表模板时--write_templates

# ①c 时间字段统计(描述性,不阻塞下游;口径见 z_notes/protocol1_landmark/)
python scripts/run_time_stats.py --dataset all

```

- **判据**:各命令退出码 0;`rawdata_stats/{ds}/landmark_0/kept_fields.json` 齐备(registry 全量 35 数据集),
  且 `rawdata_stats/_shared/landmark_0/kept_fields.json` 落盘(筛选的共享口径)。
- **产物**:`rawdata_stats/{ds}/scanned_fields.json`、`rawdata_stats/{ds}/field_stats.csv`(raw 口径,供 off 臂对照)、
  `rawdata_stats/{ds}/landmark_0/{field_stats.csv,kept_fields.json,fliter_log/{exclusion_log.csv,field_registry.csv}}`、
  `rawdata_stats/_shared/{landmark_0/,field_presence*.csv,event_summary.csv}`。
- **口径(已扶正 2026-10-05)**:现行链 = landmark-first(统计在 Field Bank 同款 t_hi≤T mask 上算);
  raw-first 旧产物已废弃清理(见 `z_notes/Test_series_execution_log.md` D13 登记行)。完整 R0-R6 口径见 `z_notes/protocol2_field_processing/field_filter.md`。

---

## 阶段 2:编码(Field Bank / 方案 / label 派生)

把阶段 1 的筛选结果编成模型输入:Field Bank 文本基座、方案组合、论文/自定义方案(gdc 线)、off 臂 raw bank。
**编码一律 conch env**;GPU 由 `FIELD_BANK_GPU`(Field Bank)与 `A_PIPELINE_GPU` / `--gpu`(run_a_manual)控制,默认 7。

```bash
# 在 projects/ 根目录;编码一律 conch env;GPU 由下面两个变量控制(FIELD_BANK_GPU 默认 6,A_PIPELINE_GPU 默认 7)
# Field Bank 编码卡(卡被占 → 改这里或临时 export 覆盖)
export FIELD_BANK_GPU="${FIELD_BANK_GPU:-6}"
# run_a_manual 编码卡(--gpu 优先于本变量)
export A_PIPELINE_GPU="${A_PIPELINE_GPU:-7}"

# 2.1 Field Bank 文本基座(landmark_0,现行取值口径)= Test_1a t0 臂 / Test_3 的字段基座;失败 → 先补阶段 1
conda run -n conch python scripts/run_field_bank.py --dataset all --landmark_time 0 --encoding prompt

# 2.3 论文 / 自定义方案(gdc 线;入口 scripts/run_a_manual.py,现三子命令 = baseline / hgcn_clinic / cindex;
#    原 json2prompt / encode / pipeline 已随 apipe 全量编码路径删除(T31 + 2026-10-09 收尾),
#    文本嵌入一律 bank 切片:Test_3_* 用 scripts/Test_3_arms.py encode,零 CONCH 重编码)
# baseline:baseline 模型训练(失败 → 先看 pipeline 是否已跑完)
conda run -n conch python scripts/run_a_manual.py baseline --dataset all --scheme paper
# hgcn_clinic:HGCN 临床绑定(走 base python;失败 → 确认该方案已注册)
python scripts/run_a_manual.py hgcn_clinic --dataset all --scheme paper
# 单方案点名(HGCN 绑定 / Test_3 自定义方案):
#   python scripts/run_a_manual.py hgcn_clinic --dataset TCGA-LAML --scheme MULTISURV

# 2.4 Test_1a off 臂 raw Field Bank(mask off;唯一差异 = 取值 mask;产物 outputs/_raw/;失败 → 重跑本行,已存在的跳过)
bash scripts/exp_queue.sh bank --arm test_1a_off
# 校验 主集 raw bank 齐备
bash scripts/exp_queue.sh check --arm test_1a_off

# 2.5 label 派生(Test_1a t0/off/merged 三臂前置):univariate 训练要求派生 label 已存在
#    (risk set + 时间平移,写 results/Test_2b/arm_B/labels/;cindex 路径会自动派生,univariate 不会)
python scripts/derive_landmark_labels.py --landmark_time 0
```

- **判据**:各命令退出码 0;`bash scripts/exp_queue.sh check --arm test_1a_off` 通过(raw bank 齐,主集派生);
  主集的 `outputs/{ds}/field_bank/prompt/landmark_0/field_index.json` 存在。
- **产物**:`outputs/{ds}/field_bank/prompt/landmark_0/{prompts.csv,embeddings/pt/*.pt,field_index.json}`、
  `outputs/{ds}/A_manual/{scheme}/[landmark_0/]`、
  `outputs/_raw/{ds}/field_bank/prompt/no_mask/`(off 臂 raw bank)。
- **label 派生(患者线,与字段线正交)**:landmark 三要件(风险集只留 gt>T、终点平移 gt−T、gt≤0 全局剔除)
  落 `results/Test_2b/arm_B/labels/{study}__landmark_0.csv`;cindex 路径评估时自动派生,
  univariate(t0/off/merged 三臂)不自动 → 前置用 `scripts/derive_landmark_labels.py`(本阶段 2.5);
  字段线与患者线在评估(阶段 3~7 的 cindex)汇合。
- 卡缺件补救:阶段 4/5/6 的 queue 入口自带 `encode` / `Test_3_arms.py encode` / 缺编码报告,按需补齐即可。

---

## 阶段 3:实验(Test_1a / Test_2 / Test_3 / Test_5 / Test_6)

所有实验收进本节,一个实验一个小节:投放 → 训练(drain 一条命令守到完成,自带失败重试、
死进程补位、收尾报表)→ 判据。规格与口径见 `z_notes/Test_series_spec.md` 与
`z_notes/experiment_list/experiment_list.md`;管线阶段依据见 `z_notes/tcga_pipeline/tcga_pipeline.md` ⑤~⑦。

> **workers 语义**(2026-10-12 用户拍板):**一个 worker 执行一个 conf 文件**,`WORKERS=N` = 同时并行
> N 个 conf(数据集);conf 内部字段串行。不再用多个 worker 并发执行同一个 conf。

### Test_1a 单字段泄露对照(t0 / off 两臂)

```bash
# 前置 = 阶段 2:Field Bank 基座 + off 臂 raw bank + 派生 label 齐备
# t0 臂(mask 开,landmark_0)
bash scripts/exp_queue.sh enqueue --arm test_1a_t0
CUDA_VISIBLE_DEVICES=2,3,4 WORKERS=8 bash scripts/exp_queue.sh drain --arm test_1a_t0
# off 臂(mask 关,no_mask raw bank)
bash scripts/exp_queue.sh enqueue --arm test_1a_off
CUDA_VISIBLE_DEVICES=7 WORKERS=8 bash scripts/exp_queue.sh drain --arm test_1a_off
# 两臂患者集一致性审计(可选)
python scripts/Test_1a_audit_arms.py
```

- **判据**:两家族 queue+running 空 且 done == 期望数(exp_queue 派生);drain 退出码 0。
- **产物**:`results/Test_1a/{arm_t0,arm_off}/`(每数据集 `field_cindex.csv`)。

### Test_2 时间轴链(2a 审计 → 2b 训练)

```bash
# 2a 逐字段 leak_rate 审计(描述性,不训练)
python scripts/run_leak_audit.py
# 2b 训练:补切片 → 逐波投放(依赖 Test_3 的 generate/encode 先行,见下)
bash scripts/exp_queue.sh encode --arm test_2b
bash scripts/exp_queue.sh enqueue --arm test_2b --slice A1   # 按 wave_order 逐波投
CUDA_VISIBLE_DEVICES=5 WORKERS=8 bash scripts/exp_queue.sh drain --arm test_2b
python3 results_display/scripts/Test_2b_delta_report.py     # 两臂对照
```

- **判据**:`Test_2b_arms` queue+running 空 且 done == 期望数(组合数 × 臂 × 分析器,exp_queue 派生);对照表落盘。
- **产物**:`results/Test_2a_leak_audit/`、`results/Test_2b/{arm_A,arm_B}/`(bank 切片口径;apipe 历史冻结已清)。

### Test_3 字段轴链(搜索 → 两臂 → Test_4)

```bash
# 5a 搜索(动态槽位调度保留在 Test_3_search_queue.py,不并入 exp_queue)
bash scripts/exp_queue.sh enqueue --arm test_3_search
T3_SEARCH_WORKERS=16 nohup python scripts/Test_3_search_queue.py watch --gpus 1,0,3,4,5,6 --interval 60 \
    > results/Test_3_greedy_vs_works/logs/watch.log 2>&1 &
# 5b 两臂(臂 B deleak / 臂 C reach;零 CONCH 重编码)
python scripts/Test_3_arms.py generate --arm b
python scripts/Test_3_arms.py encode --arm b --gpu 1 --parallel 3
bash scripts/exp_queue.sh enqueue --arm test_3_arms --variant b
CUDA_VISIBLE_DEVICES=1 WORKERS=2 bash scripts/exp_queue.sh drain --arm test_3_arms
python scripts/Test_3_arms.py generate --arm ksig
python scripts/Test_3_arms.py encode --arm ksig --gpu 1 --parallel 3
bash scripts/exp_queue.sh enqueue --arm test_3_arms --variant ksig
CUDA_VISIBLE_DEVICES=1 WORKERS=2 bash scripts/exp_queue.sh drain --arm test_3_arms
python scripts/Test_3_compare.py --all
# 5c Test_4 三档收口(纯汇总,不训练)
python results_display/scripts/Test_4_three_tiers.py
```

- **判据**:`Test_3_search` done == 主集数;`Test_3_arms` done == 组合数(均 exp_queue 派生);`two_arm.csv` 落盘。
- **产物**:`results/Test_3_greedy_vs_works/`、`results_display/Test_4_three_tiers/`。

### Test_5 不变性(Test_2b / Test_3 之后)

```bash
bash scripts/exp_queue.sh enqueue --arm test_5
bash scripts/exp_queue.sh scheduler    # 后台多卡调度:GPU 硬约束 0-3 空闲卡自动放置(日志 results/Test_5_invariance/logs/)
bash scripts/exp_queue.sh summarize --arm test_5
bash scripts/exp_queue.sh q_recompute  # 判据:diff=0
```

- **判据**:四子检查(5E_2b/5E_3/5M_2b/5M_3)queue+running 空 且 done == 期望数(exp_queue 派生;多模态 conf 在 parked);`q_recompute` diff=0。
- **产物**:`results/Test_5_invariance/{子检查}/`、`results_display/Test_5_invariance/q_metrics.csv`。
- 停止调度器:`bash scripts/exp_queue.sh scheduler_stop`。

### Test_6 搜索算法选型(Test_1a 先验就绪后;建议最后跑)

```bash
# 试点 24 个搜索(3 数据集 × 8 算法);GPU 0-3 共 8 槽 × 8 workers(脚本内固定;nohup,日志 /tmp/t6_scheduler.log)
bash scripts/t6_scheduler.sh
python scripts/run_bakeoff_report.py --results-root results/Test_6_search/prompt \
    --extra-roots results/Test_3_greedy_vs_works/search --budget_cap 500
```

- **判据**:`Test_6_search` queue+running 空 且 done ≥ 24;`decision.json` 落盘(人工确认)。
- **产物**:`results/Test_6_search/`、`results_display/Test_6_search/{gap_table,win_rate,ranks,anytime,decision.json}`。

---

## 阶段 4:报表(展示层,不训练)

```bash
# Test_1a 两臂对照图 / Δc 排序 / leak×Δc 交叉(4 个脚本都幂等,可直接重跑;base python 3.13)
python results_display/scripts/Test_1a_field_level.py
# Test_1b 单字段分布 / top-k 重叠
python results_display/scripts/Test_1b_dataset_cindex.py
# Test_2b Δc 森林图 / 汇总表
python results_display/scripts/Test_2b_delta_report.py
# Test_4 三档表(同阶段 5c;可在此重跑)
python results_display/scripts/Test_4_three_tiers.py
```

- **判据**:4 个脚本退出码 0(产物已存在也照跑,幂等);对应输出文件存在。
- **产物**:`results_display/Test_1a_field_level/`、`Test_1b_dataset_cindex/`、`Test_2b_delta/`、`Test_4_three_tiers/`
  (文件前缀角色 `Main_`/`Appx_`/`Raw_`/`Meta_`;每目录 README.md 有逐文件含义)。
- 依赖:各脚本只读 `results/` 与 `rawdata_stats/`,上游阶段未落盘时会报缺件——先补上游再跑本阶段。

---

## env 变量速查

> 队列 drain 路径只有三个通用变量:`CUDA_VISIBLE_DEVICES`(GPU)/ `WORKERS`(并发)/ `PYTHON3`(解释器),不再有按臂前缀的变量族。
> 编码路径另有少量专属变量:`FIELD_BANK_GPU`(Field Bank 编码卡)、`ENC_GPU`(raw bank 编码卡)、`CONCH_PYTHON`(conch env 解释器),见阶段 2。

| 变量 | 默认 | 用途 |
|---|---|---|
| `CUDA_VISIBLE_DEVICES` | 按臂注册表默认(见 `scripts/exp_queue.py` 臂定义 gpus_default) | GPU 选择(队列 drain 路径通用;也可用 `--gpus`/`--gpu` flag 覆盖) |
| `WORKERS` | 8(按臂默认) | 训练并发(数据集内字段级并行;也可用 `--workers` flag) |
| `PYTHON3` | python3 | exp_queue/drainer 的解释器(训练子进程由各入口自行拉起) |

已知坑清单

1. **(已修,留档;脚本已退休)** `s5_univariate_queue.sh`(现 `bash scripts/exp_queue.sh … --arm test_1a_t0`)早期 `DS_LIST`/`EXPECTED` 是全 33 队列遗留、`QUEUE_ROOT` 是旧名 `configs/univariate`;
   现已按 label 患者集有效事件 ≥ 100 派生主集、`QUEUE_ROOT=configs/Test_1a_t0`。
2. **flag 必须下划线拼写**:`run_selection_queue.py` / `run_selection.py` 用 `--stop_mode`、`--budget_cap`、`--landmark_time`;
   连字符会被 queue 的 `_command()` 重建链路拒收(单测抓不到,投递后才发现)。
3. **评估缓存**:`results/Test_3_search/cache.sqlite` 的 key 含 label 哈希 + schema `e2-v2`;
   任何 label 改动旧行自动 miss 重训(不报错,无需手清)。
4. **自愈循环的停止**:Test_5 `scheduler`(原 `Test_5_scheduler.py`,已并入 `exp_queue.py`)是后台自愈循环,
   停止用 `bash scripts/exp_queue.sh scheduler_stop`(只 kill 自己写的 `scheduler.pid`);Test_3 搜索的动态槽位
   调度仍在 `scripts/Test_3_search_queue.py`,它一轮跑完自动 report 退出。
   **不要直接 kill 无关进程**;drain 自带自愈与收尾报表——drain 进程被杀后重跑同一条 drain 命令即续(会自动补位、回收、重试)。
5. **搜索链路患者口径 = 字段库 ∩ label**:label 文件若带 gt≤0 患者会被计入训练风险集 → 阶段 0 闸门 `check_search_labels.py` 不过就先修 label。
6. **冻结线 PGC**:`A_pipeline_pgc/run.py`(L0-L5 / D0-D5)**默认拒绝任何编码运行,必须显式 `--force`**;
   重生成前先核对契约 §3"什么会破坏冻结"并按 §4 SOP 走(`z_notes/protocol2_field_processing/frozen_schemes_contract.md`)。日常只读。
7. **landmark-first 已扶正(2026-10-05)**:`run_field_stats.py` / `run_field_filter.py` 的 `--landmark_time` 为必填;
   筛选默认消费 `_shared/landmark_0/field_stats.csv`(landmark-first),raw-first 产物已废弃;
   两条链的区别只在"筛选统计用不用 mask 过的值"(取值 mask 一直在 Field Bank 提取期生效)。
8. **桶内数字可能是历史超集**:判据用 `done ≥ 期望数`。已知:`Test_2b_arms` 552(历史期望 256,现行 240)、
   `Test_1a_t0`/`Test_1a_off` 桶计数为历史遗留值(含 33 队列全量与两种 conf 命名);全清重跑后按主集 × kept 字段数投放(以 exp_queue 实际入队数为准)。报告分层时按数据集分档协议区分主集/旁支。
9. **Test_5 的 parked 与缺编码**:`5M_2b` 的 `survgc_f`/`survpgc_f`(多模态 3 集 conf)默认撤到 `parked/`
   (需 slide 级 label metadata;决定后用 `--include-multimodal` 或手工 mv 回 `queue/`);
   `enqueue` 对缺编码的 (dataset, scheme, arm) 会 **SKIP 并列出**,不报错——看 `status` 的"缺编码"段。
10. **Test_6 的 `--out` 必须含 ds(+algo)**:防不同 (ds, algo) 串目录;`t6_scheduler.sh` 已按此写好,手工补跑请照抄。
11. **`results/Test_1a/arm_t0` 是指向 `results/univariate` 的软链**(命名公约迁移遗留),不是真目录;删改前先 `ls -la` 确认。
12. **分步手动执行**:无自动串行脚本(一键串行设计已撤销,见执行日志 P19);每个阶段按命令块复制粘贴执行,
    阶段判据以本文件"一页速览/各阶段判据"为准,判据满足再走下一步。
13. **Test_3 搜索队列有 4 个"遗留键" conf**:LUAD/LUSC/OV/PAAD 的 conf 名里嵌的 job_key 来自更早一次带
    **相对 `--out`**(`results/Test_3_greedy_vs_works/search/{ds}`)的调用,现行 argv 是绝对 `--out`
    (commit 1bb2a36 起)——两者结果文件同路径,只是键不同。`exp_queue.py status --arm test_3_search`
    会把这类 conf 标 `(遗留键)`;`recover/retry` 按 dataset 后缀 glob 定位,仍能正确操作。
    **不要对真实搜索根跑 `enqueue`**(旧脚本同样会按新键再造 4 个重复 conf;重复 conf 不改变结果,但会白跑一轮)。
