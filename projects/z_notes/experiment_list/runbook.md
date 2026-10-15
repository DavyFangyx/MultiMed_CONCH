# 实验执行手册:全链路 runbook(审查 → 编码 → 实验 → 报表)

> **唯一执行文档**:命令 + 判据都在本文件;顶部"一页速览"即速查,env 速查 / 已知坑见文末。
> **本文件是实验执行的权威手册**:阶段划分、命令、产物以这里为准。
> **分步手动执行**:长序列运行、部分节点需人工核查审计,不提供一键串行脚本;按下方阶段顺序逐阶段执行。
> 口径权威:`z_notes/experiment_list/experiment_list.md`(实验清单)、`z_notes/Test_series_spec.md`(规格)、
> 配置口径架构(配置=因子元组、实验=配置组、Test 无依赖、skip 机制)= `z_notes/experiment_list/experiment_list.md`「配置口径」节,
> `z_notes/protocol1_landmark/time_axis.md`(时间轴协议);目录命名见 `z_notes/experiment_list/naming_convention.md`。
> 所有命令都在 `projects/` 根目录执行。环境:训练 = conda env **SurvPGC**,编码 = conda env **conch**,
> 投递/监控 = **base python 3.13**。队列纪律:**上一步完成再走下一步**(不要并行 stage,除非明确说可并行)。
> **队列入口已收敛**:投递/监控一律 `bash scripts/exp_queue.sh <verb> --arm <臂>`
> (臂/别名/组:`python3 scripts/exp_queue.py list`;臂注册表与三 backend 见 `scripts/exp_queue.py` 头注释)。
> 执行统一为 `bash scripts/exp_queue.sh run`(无臂:conf 自描述,按名序调度;
> GPU 唯一旋钮 = 调用方 `CUDA_VISIBLE_DEVICES`,多卡分账 = 起多个 run 进程各绑一张卡)。

---

## 一页速览:全链路五阶段(阶段 0 = 前置闸门)

| # | 阶段 | 入口(projects/ 根目录执行) | 产物落点 |
|---|---|---|---|
| 0 | 前置闸门 | `python scripts/check_search_labels.py` | 只读报告,无产物 |
| 1 | 数据准备与原始文件审查(label 重建/split 重建/扫描/统计/筛选) | `rebuild_labels.py --all`(⓪a,可选) → `generate_5fold_splits.py --all --seed 1`(⓪b,可选) → `run_scan_fields.py` → `run_field_presence.py` → `run_field_stats.py --landmark_time 0` → `run_field_filter.py --landmark_time 0` → `run_event_stats.py` | `Clinic_Analyzer/data/splits/5foldcv/`、`rawdata_stats/{ds}/…`、`rawdata_stats/_shared/{landmark_0/,event_summary.csv}` |
| 2 | 编码(Field Bank / 方案 / label 派生) | `scripts/run_field_bank.py` → `run_a_manual.py`;`bash scripts/exp_queue.sh bank --arm test_1a_off` | `outputs/{ds}/field_bank/…`、`outputs/{ds}/A_manual/…`、`outputs/_raw/{ds}/…` |
| 3 | 实验(统一流水线) | 全部臂 `enqueue --arm <臂>`(幂等)→ 一条 `run` 跑干桶里所有 conf(无臂;失败重试/死进程补位/名序调度;一行一卡,`WORKERS` = 本卡同时跑的 conf 数)。实验与臂对照表见阶段 3 | 阶段 3"产物落点"表 |
| 4 | 报表(展示层,不训练) | `python results_display/scripts/{Test_1a_field_level,Test_1b_dataset_cindex,Test_2b_delta_report,Test_4_four_tiers}.py` | `results_display/` 4 个目录 |

**依赖关系(2026-10-14 起:Test 之间无先后依赖)**:

```
阶段 1 审查 ─→ 阶段 2 编码 ─→ 阶段 3 实验(每个 Test 独立 enqueue 自己配置组的 conf → 统一 run)
                                              · 同配置跨实验判重:先跑谁谁生成,后跑的直接 skip
                                              · greedy×lm0 的 conf 等搜索 result.json(生成器关系,非实验依赖)
阶段 4 报表 ← 上游 results/ 落盘后随时可跑(纯汇总;缺臂 = pending,不阻塞)
```

- **任何 Test 都可单独 enqueue → run**(含纯消费的 Test_1b / Test_4:它们同样生成自己配置组
  的全套 conf,与生产方实验同配置同名——先跑谁谁生成)。
- **GPU 纪律**:Test_5 只用 GPU 0-3(人肉纪律:执行行首 `CUDA_VISIBLE_DEVICES=0,1,2,3`,4-7 不碰);**GPU 选择一律 `CUDA_VISIBLE_DEVICES`**(唯一旋钮,每步命令行首给出);不 kill 他人进程。
- **skip 机制**(2026-10-14 拍板):run 认领 conf 后若结果已存在(cindex = OUT_DIR/.done,
  search = result.json),直接跳过并在日志写 `[run] skip`——跑任何实验都生成全套 conf,
  已完成的配置零重复算力;univariate 的 per-field reuse 等价覆盖(只补缺失字段)。
- **多卡分账(一行一卡)**:一条 run 命令 = 一张卡(`CUDA_VISIBLE_DEVICES` 绑定),`WORKERS` = **该卡同时跑的 conf 数**(每 conf 内固定 4 字段并发);
  多卡并行 = 起多个 run 各绑一张卡后台跑(共享桶原子认领,互不抢同一 conf,合计 2×WORKERS 进程):
  ```bash
  CUDA_VISIBLE_DEVICES=2 WORKERS=16 nohup bash scripts/exp_queue.sh run > /tmp/run_gpu2.log 2>&1 &
  CUDA_VISIBLE_DEVICES=3 WORKERS=16 nohup bash scripts/exp_queue.sh run > /tmp/run_gpu3.log 2>&1 &
  ```
  顺序分批 = 分批 enqueue(先投一批跑完,再投下一批)再逐批 run;每个 run 把当前桶里的 conf 跑干为止。
- **训练范围**:训练/搜索限 **label 患者集有效事件 ≥ 100 的主集**(名单自动派生不硬编码:`common.patient_set::main_datasets_by_label_events`;权威口径见 `z_notes/protocol0_cohort_selection/cohort_rules.md` §0.3);
  <100 档不新增训练(四档语义见数据集分档协议)。
- **队列四桶**:全实验共享 `Clinic_Analyzer/configs/{queue,running,done,failed}` 四桶(flat 布局,conf 名自带家族区分,见 `Clinic_Analyzer/configs/README.md`);+ `parked/` = 撤下但保留,不被 run 读取;
  桶计数可能含历史超集,判断完成一律用 `done ≥ 期望数`(见"已知坑" 7)。

---

## 结果在哪看(总览)

| Test / 阶段 | `results/` | `results_display/` | 队列家族目录(`Clinic_Analyzer/configs/`) |
|---|---|---|---|
| 阶段 1 审查 | —(`rawdata_stats/{ds}/`) | — | — |
| 阶段 2 编码 | —(`outputs/{ds}/`、`outputs/_raw/{ds}/`) | — | — |
| Test_1a 单字段 | `results/single_lm0/univariate/`(t0)、`results/single_raw/`(off) | `Test_1a_field_level/` | 四桶(`Test_1a_t0`/`Test_1a_off` conf 名) |
| Test_1b 各数据集分布 | (数据源 = `results/single_lm0/univariate/`) | `Test_1b_dataset_cindex/` | — |
| Test_2a 泄露审计 | `results/leak_audit/` | `Test_2a_leak_audit/` | — |
| Test_2b 去泄露对照 | `results/paper_raw/`(报告值)、`results/paper_lm0/`(去泄露值) | `Test_2b_delta/` | 四桶(`Test_2b_arms` conf 名) |
| Test_3 搜索 + 两臂 | `results/greedy_lm0/`(search/、cache.sqlite、compare/、two_arm.csv) | `Test_3_greedy_vs_works/` | 四桶(`Test_3_search`/`Test_3_arms` conf 名) |
| Test_4 四档收口 | (汇总,无独立训练) | `Test_4_four_tiers/` | — |
| Test_5 不变性 | `results/Test_5_invariance/{E_time,E_field,M_time,M_field}/` | `Test_5_invariance/`(q_metrics.csv) | `Test_5_E_time`、`Test_5_E_field`、`Test_5_M_time`、`Test_5_M_field` |
| Test_6 算法选型 | `results/Test_6_search/` | `Test_6_search/`(decision.json) | `Test_6_search` |
| 阶段 4 报表 | — | `Test_1a_field_level/`、`Test_1b_dataset_cindex/`、`Test_2b_delta/`、`Test_4_four_tiers/` | — |

展示层文件前缀角色:`Main_` = 头条(回答命题)、`Appx_` = 附录、`Raw_` = 原始矩阵、`Meta_` = 元数据与审计。
`results/`、`results_display/`、`outputs/`、`rawdata_stats/` 均 gitignore(只入库 `results_display/scripts/`)。

---

## 阶段 0:前置闸门

```bash
# 在 projects/ 根目录;base python 3.13;只读
# 闸门:搜索链路 label 无 gt≤0 患者(FAIL → 先修 label,再投任何队列)
python scripts/check_search_labels.py
```

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
# ⓪b split 重建(可选):从 label metadata 重生成 5 折(seed 1 确定性分层轮转;
#    多模态 5 集自动做 W∩C∩G∩RNA 完备过滤 → 多模态功能不受影响)。
python Clinic_Analyzer/dataset_deployment/scripts/generate_5fold_splits.py --all --seed 1

# ① 字段字典扫描:字段路径 + GDC 字典释义(失败 → 检查 ClinicDatasets/gdc_clinical/raw_json/ 原始文件是否齐)
python scripts/run_scan_fields.py --dataset all
# ② 与官方 mapping 对照(字段存在性审计;只读)
python scripts/run_field_presence.py --dataset all

# ③ landmark-first 统计:患者分母 = label 患者集(gt≤0 等"杂质"在字段级统计之前即被剔除);
#    --landmark_time 0/365/730/none;t0 mask 口径,写 _shared/landmark_0/(失败 → 看 rawdata_stats/_shared/ 产物)
python scripts/run_field_stats.py --dataset all --landmark_time 0
# ④ R0-R6 筛选:自动消费 ③ 的 landmark 统计,R3/R4 阈值可命令行改(失败 → 看排除日志 fliter_log/)
python scripts/run_field_filter.py --dataset all --landmark_time 0 \
    --R3_coverage 0.30 --R4_n_unique 2 --R4_mode_share 0.95 --write_templates

# 需要重生成/填充 Field Bank 长表模板时--write_templates

# ⑤ 时间字段统计(描述性,不阻塞下游;口径见 z_notes/protocol1_landmark/)
python scripts/run_time_stats.py --dataset all

# ⑥ 事件统计(label 患者集事件 + raw 审计双口径)
python scripts/run_event_stats.py --dataset all

```

- **产物**:`rawdata_stats/{ds}/scanned_fields.json`、`rawdata_stats/{ds}/field_stats.csv`(raw 口径,供 off 臂对照)、
  `rawdata_stats/{ds}/landmark_0/{field_stats.csv,kept_fields.json,fliter_log/{exclusion_log.csv,field_registry.csv}}`、
  `rawdata_stats/_shared/{landmark_0/,field_presence*.csv,event_summary.csv}`、

- **口径**:现行链 = landmark-first(统计在 Field Bank 同款 t_hi≤T mask 上算);
  完整 R0-R6 口径见 `z_notes/protocol2_field_processing/field_filter.md`。

---

## 阶段 2:编码(Field Bank / baseline / hgcn / label 派生)

把阶段 1 的筛选结果编成模型输入。所有命令在 projects/ 根目录、conch env 下运行;GPU 由行首 `CUDA_VISIBLE_DEVICES` 控制。

### 2.1 Field Bank 文本基座(主线唯一 CONCH 编码,最先做)

把每个 kept 字段写成句子,交给 CONCH 编码成向量。主线全部实验(Test_1a 单字段、Test_2b/Test_3/Test_5 的 text 臂)
的输入都从这里按字段位号取列,**零重编码**。

```bash
CUDA_VISIBLE_DEVICES=6 conda run -n conch python scripts/run_field_bank.py --dataset all --landmark_time 0 --encoding prompt
```

产物:`outputs/{ds}/field_bank/prompt/landmark_0/{prompts.csv, embeddings/pt/*.pt, field_index.json}`。

### 2.2 onehot_ordinary bank(Test_5 E 轴的第二档,与 prompt bank 同机制)

原始临床值按 GDC 字典定型:分类字段 onehot(全局共享词表),连续/有序字段数值。
与 prompt bank 一样是"每字段一行 + field_index.json"的 bank,臂组合在训练时按索引取列,
**没有独立的物化编码线**(原 A_manual/baseline 已退役)。

```bash
# landmark_0 变体(E_time deleak / E_field 两臂用;--dataset all 拟合全局共享词表)
conda run -n conch python scripts/run_field_bank.py --dataset all --landmark_time 0 --encoding onehot
# raw 变体(mask 关,E_time report 臂用)
conda run -n conch python scripts/run_field_bank.py --dataset all --landmark_time none --encoding onehot
```

产物:`outputs/{ds}/field_bank/onehot/{landmark_0,no_mask}/{field_index.json, embeddings/pt/*.pt}`。

### 2.3 hgcn_clinic 编码(图节点 pkl,Test_5 E 轴的第三档)

```bash
python scripts/run_a_manual.py hgcn_clinic --dataset all --scheme paper
```

hgcn 无法 bank+索引(图节点依赖完整字段集拓扑),按方案物化;本轮 E_time/E_field 只跑
onehot_ordinary 档,hgcn 档的评估臂等 HGCN 模型接入后再跑。

### 2.4 Test_1a off 臂 raw bank(mask 关)

与主 bank 唯一差异 = 取值 mask(不裁剪时间泄露)。已存在的自动跳过,可反复跑。

```bash
bash scripts/exp_queue.sh bank --arm test_1a_off
bash scripts/exp_queue.sh check --arm test_1a_off   # 校验主集 raw bank 齐备
```

产物:`outputs/_raw/{ds}/field_bank/prompt/no_mask/`。

### 2.5 label 派生(univariate 臂前置)

landmark 三要件(风险集只留 gt>T、终点平移 gt−T、gt≤0 全局剔除)落成派生结局表。
cindex 路径评估时会自动派生;univariate(t0/off 两臂)不自动,必须这里先生成。

```bash
python scripts/derive_landmark_labels.py --landmark_time 0
```

产物:`results/labels/{study}__landmark_0.csv`(患者线共享资产,四家消费)。

### 2.6 搜索字段语义缓存(Test_3 / Test_6 搜索前置)

```bash
# Test_3/Test_6 的 SEAS 系搜索算法需要每个字段的"语义向量"——把字段名 + GDC 字典释义编码成 CONCH 向量,用于语义感知的搜索。
python scripts/pregen_field_semantics.py
```

- **训练时索引(2026-10-13 拍板)**:cindex 臂不物化切片文件——conf 的
  `CLINIC_DIR_PATH` 指向 bank 的 embeddings/pt,`FIELD_TEMPLATE`/`FIELD_GREEDY` 给出字段名单来源,
  analyzer 在训练时现场解析"名单 ∩ bank → 位号 → 取列";conf 记 `BANK_FP`(bank 字段指纹,
  对不上即失败 = 防 bank 重建后静默漂移);解析结果写各 run 的 `field_resolution.json` 留痕。
  阶段检查(主线外,只读):`python3 scripts/check_arm_fields.py --arm {raw,lm0,deleak,reach}`。

---

## 阶段 3:实验(统一流水线:全部 enqueue → 一条 run)

**实验与臂对照**(读者先看这张表;臂语义权威 = `z_notes/experiment_list/arm_registry.md`):

| 编号 | 实验 | 臂 / 子检查 | 说明 |
|---|---|---|---|
| Test_1 单字段 c-index | 每个字段单独训练一个模型 | 1a 泄露对照:t0 / off | t0 = landmark_0 mask 开;off = mask 关(raw bank);两臂同患者集 |
|  |  | 1b 各数据集分布 | 无训练;enqueue 与 test_1a_t0 同 conf(判重共享),只读结果 |
| Test_2 时间轴链 | "没做时间处理会不会高估" | 2a 泄露审计 | 逐字段量化 leak_rate,不训练 |
|  |  | 2b 去泄露对照 | 报告值(raw)vs 去泄露值(lm0),Δc = 报告 − 去泄露 |
| Test_3 字段轴链 | "没选字段会不会低估" | 3a 搜索 | 贪婪搜索找每数据集最优字段组合 |
|  |  | 3b 两臂 | 去泄露值(论文组合)vs 可达值(搜索最优),Δc = 可达 − 去泄露 |
| Test_4 四档收口 | 两链结论的汇总表 | 非实验 | enqueue = 四配置组全套 conf(与 2b/3arms 判重共享);报表四列 + 档间 Δ |
| Test_5 不变性 | 换编码/换模型/换指标后结论还成立吗 | E_time / E_field | E 轴换 onehot_ordinary;`*_time` = 时间轴链臂对 {report,deleak},`*_field` = 字段轴链臂对 {deleak,reach} |
|  |  | M_time / M_field | M 轴换分析器(snn / survgc_f / cox);同上配对 |
| Test_6 搜索算法选型 | 哪个搜索算法最好 | 24 个搜索 | 3 数据集 × 8 算法,试点定胜者 |

**统一投放**(每个实验独立 enqueue 自己配置组的 conf,与顺序无关;每条一行,幂等可重跑):

```bash
# ---- 全部实验各自 enqueue(同配置跨实验判重:先跑谁谁生成,后跑的直接 skip)----
bash scripts/exp_queue.sh enqueue --arm test_1a_t0          # Test_1a t0 臂(单字段 lm0)
bash scripts/exp_queue.sh enqueue --arm test_1a_off         # Test_1a off 臂(单字段 raw)
bash scripts/exp_queue.sh enqueue --arm test_1b             # Test_1b(纯消费 single×lm0;conf 与 t0 判重共享)
python scripts/run_leak_audit.py                            # Test_2a 泄露审计(不训练,即时产出)
bash scripts/exp_queue.sh enqueue --arm test_2b             # Test_2b 两臂(报告值/去泄露值)
bash scripts/exp_queue.sh enqueue --arm test_3_search       # Test_3 搜索(greedy 字段名单的生成器)
bash scripts/exp_queue.sh enqueue --arm test_3_arms         # Test_3 两臂(deleak;reach 见下)
bash scripts/exp_queue.sh enqueue --arm test_4              # Test_4 四档纯消费(四配置组全套 conf)
bash scripts/exp_queue.sh enqueue --arm test_5              # Test_5 四子检查(E_time/E_field/M_time/M_field)
bash scripts/exp_queue.sh enqueue --arm test_6_search --budget_cap 400 # Test_6 24 个搜索(3 数据集 × 8 算法)

# ---- 执行:一条 run 跑干桶里所有 conf(一行一卡;多卡起多个 run 各绑一卡)----
CUDA_VISIBLE_DEVICES=6 WORKERS=8 bash scripts/exp_queue.sh run   # 后台;日志 results/logs/

# ---- reach(greedy×lm0)的 conf 等搜索 result.json(生成器关系,非实验依赖):
#      搜索跑完后重投一次补齐(判重,只补缺失的 reach conf)----
bash scripts/exp_queue.sh enqueue --arm test_3_arms --variant reach
bash scripts/exp_queue.sh enqueue --arm test_4                # 判重后同样只补 reach conf
CUDA_VISIBLE_DEVICES=7 WORKERS=8 bash scripts/exp_queue.sh run
```

**汇总与对照**(训练完成后;全部是 results_display/scripts 的只读脚本,幂等):

```bash
python3 results_display/scripts/Test_2b_summarize.py                # Test_2b 两臂折文件 → 表
python3 results_display/scripts/Test_3_arms_summarize.py --arm deleak
python3 results_display/scripts/Test_3_arms_summarize.py --arm reach
python scripts/Test_3_compare.py --all                              # 两臂 Δc + 遗漏字段
python3 results_display/scripts/Test_5_summarize.py --sub all       # Test_5 四子检查 → 表
nice -n 10 /data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python \
    results_display/scripts/Test_5_q_recompute.py \
    --results-root results/Test_5_invariance --out /tmp/test_5_q_metrics.csv --merge
python scripts/run_bakeoff_report.py --results-root results/Test_6_search/prompt \
    --extra-roots results/greedy_lm0/search --budget_cap 500
```

**产物落点**:

| 实验 | `results/` | `results_display/` |
|---|---|---|
| Test_1a | `results/{single_lm0/univariate/,single_raw/}` | `Test_1a_field_level/` |
| Test_1b | (数据源 = Test_1a t0 臂) | `Test_1b_dataset_cindex/` |
| Test_2a | `results/leak_audit/` | `Test_2a_leak_audit/` |
| Test_2b | `results/{paper_raw,paper_lm0}/` | `Test_2b_delta/` |
| Test_3 | `results/greedy_lm0/`(search/、cache.sqlite、two_arm.csv) | `Test_3_greedy_vs_works/` |
| Test_4 | (汇总,无独立训练) | `Test_4_four_tiers/` |
| Test_5 | `results/Test_5_invariance/{子检查}/` | `Test_5_invariance/` |
| Test_6 | `results/Test_6_search/` | `Test_6_search/`(decision.json) |

> **workers 语义**(2026-10-13):`WORKERS=N` = **这张卡上同时跑的 work(conf)数**(各卡独立:
> 卡 6 `WORKERS=8` = 6 上 8 个 conf;每 conf 内固定 4 字段并发,即每卡 4×N 个训练进程)。

## 阶段 4:报表(展示层,不训练)

```bash
# Test_1a 两臂对照图 / Δc 排序 / leak×Δc 交叉(4 个脚本都幂等,可直接重跑;base python 3.13)
python results_display/scripts/Test_1a_field_level.py
# Test_1b 单字段分布 / top-k 重叠
python results_display/scripts/Test_1b_dataset_cindex.py
# Test_2b Δc 森林图 / 汇总表
python results_display/scripts/Test_2b_delta_report.py
# Test_4 四档表(同阶段 3c;可在此重跑)
python results_display/scripts/Test_4_four_tiers.py
```

- **产物**:`results_display/Test_1a_field_level/`、`Test_1b_dataset_cindex/`、`Test_2b_delta/`、`Test_4_four_tiers/`
  (文件前缀角色 `Main_`/`Appx_`/`Raw_`/`Meta_`;每目录 README.md 有逐文件含义)。
- 依赖:各脚本只读 `results/` 与 `rawdata_stats/`,上游阶段未落盘时会报缺件——先补上游再跑本阶段。

---

## env 变量速查

> 队列执行路径只有三个通用变量:`CUDA_VISIBLE_DEVICES`(GPU)/ `WORKERS`(并发)/ `PYTHON3`(解释器)。
> GPU 唯一旋钮 = `CUDA_VISIBLE_DEVICES`(每步命令行首给出)。
> 编码路径另有 `CONCH_PYTHON`(conch env 解释器路径,非 GPU 旋钮),见阶段 2。

| 变量 | 默认 | 用途 |
|---|---|---|
| `CUDA_VISIBLE_DEVICES` | 调用方命令行使(无默认) | GPU 唯一旋钮;run 内所有 conf 共享该值,多卡分账 = 起多个 run 进程各绑一张卡 |
| `WORKERS` | run 默认 16 | **这张卡上同时跑的 conf 数**(各卡独立;每 conf 内 4 字段并发) |
| `PYTHON3` | python3 | exp_queue 的解释器(训练子进程由各入口自行拉起) |

已知坑清单

1. **search 链 flag 必须下划线拼写**:`run_selection.py` 用 `--stop_mode`、`--budget_cap`、`--landmark_time`(argparse 声明即如此);enqueue 模板已按此写,手工补跑请照抄。
2. **评估缓存**:`results/greedy_lm0/cache.sqlite` 的 key 含 label 哈希 + schema `e2-v2`;
   任何 label 改动旧行自动 miss 重训(不报错,无需手清)。
3. **run 被杀即续**:`run` 自带自愈(死进程补位/失败重试/名序调度),被 kill 后重跑同一条 run 命令即可;
   **不要直接 kill 无关进程**。
4. **搜索链路患者口径 = 字段库 ∩ label**:label 文件若带 gt≤0 患者会被计入训练风险集 → 阶段 0 闸门 `check_search_labels.py` 不过就先修 label。
5. **冻结线 PGC**:`A_pipeline_pgc/run.py`(L0-L5 / D0-D5)**默认拒绝任何编码运行,必须显式 `--force`**;
   重生成前先核对契约 §3"什么会破坏冻结"并按 §4 SOP 走(`z_notes/protocol2_field_processing/frozen_schemes_contract.md`)。日常只读。
6. **landmark-first**:`run_field_stats.py` / `run_field_filter.py` 的 `--landmark_time` 为必填;
   筛选默认消费 `_shared/landmark_0/field_stats.csv`;两条链的区别只在"筛选统计用不用 mask 过的值"(取值 mask 一直在 Field Bank 提取期生效)。
7. **完成判据 = `status` 退出码 0**(queue+running+failed 空,机器可判);conf 桶只是队列档案,全清重跑后以实际入队数为准。
8. **Test_5 的 parked 与缺编码**:`M_time` 的 `survgc_f`/`survpgc_f`(多模态 3 集 conf)默认撤到 `parked/`
   (需 slide 级 label metadata;决定后用 `--include-multimodal` 或手工 mv 回 `queue/`);
   `enqueue` 对缺编码的 (dataset, scheme, arm) 会 **SKIP 并列出**,不报错——看 `status` 的"缺编码"段。
9. **Test_6 的 `--out` 必须含 ds(+algo)**:防不同 (ds, algo) 串目录;enqueue 模板已按此写,手工补跑请照抄。
10. **univariate 结果已按配置口径物理迁移(2026-10-13/14)**:t0 臂 = `results/single_lm0/univariate/`,off 臂 = `results/single_raw/`(旧 Test 树入 `results/backup/`;旧 run_config.json 里的旧路径由 paths.py LEGACY remap 兜底)。
11. **分步手动执行**:无自动串行脚本;每个阶段按命令块复制粘贴执行,上一步完成再走下一步。
12. **存量旧键 conf 已随 2026-10-13 验收清理删除**(含 4 个"遗留键"搜索 conf);enqueue 按精确名幂等判重,不会重复造 conf。
