# 实验清单与协议速查

口径唯一来源:`z_notes/Test_series_spec.md`(规格)与 `z_notes/Test_series_execution_log.md`(执行日志)。本文件只是一页速查,冲突时以规格为准。臂(实验条件)定义唯一来源 = [arm_registry.md](arm_registry.md)(臂 = {F 字段组合, T 时间口径} 二元组 + 语义名,统一 field bank 编码基座,字母代号已退役)。三处目录命名(configs/results/results_display)的唯一公约见 [naming_convention.md](naming_convention.md)。全量重跑操作手册见 [runbook.md](runbook.md)。

## 背景(一句话)

对 **33 个 TCGA 队列**做生存预测(OS,c-index),临床字段经 CONCH 编码。之前发表的工作在临床字段使用上有两个缺陷:**无时点约束**(混入诊断时点 t0 之后的信息 → 高估)与**无依据选字段**(漏掉有效字段 → 低估)。

## 组织思路(两条论证链 + 动机层)

**Test_1 是动机层**,分别指出"应该做但之前没人做"的两件事;Test_2/Test_3 是两条链的主体;Test_4 四档对照表是两链的收口产物,**不是实验**。组织原则:**一个 Test = 一个实验(对应一个命题),一个实验对应多张表;表本身不占实验编号**。

```
        时间轴链                                  字段轴链
Test_1a 单字段泄露对照                     Test_1b 各数据集 Cindex 分布
   "同一字段,t0 口径下 c-index 会变"          "同一字段,不同数据集能力不同;
                                              每个数据集有各自最优组合"
        ↓                                        ↓
Test_2  之前的工作没做时间处理 → 高估       Test_3 之前的工作没选字段 → 低估
   2a 审计(leak_rate)                        贪婪搜索找最优组合
   2b 去泄露对照(Δc = 报告−去泄露)            两臂对照(Δc = 可达−工作组合)
        ↓                                        ↓
        └─────────── Test_4 四档对照表收口 ───────────┘
        报告值 − 去泄露值 = 时间轴链收口(高估量)
        去泄露值 − 可达值  = 字段轴链收口(低估量)
```

## 核心口径(全系列共用)

- **评估**:5 折交叉验证的 val c-index(`cv_c_mean` 5 折均值),不伪造独立测试集。
- **landmark = 经典三要件**(t0 = 诊断日):① 风险集只留 `ground_truth_time > T`;② 终点平移到 `gt − T`;③ 协变量只取 `t_hi ≤ T` 的槽位。默认 `landmark_0`。
- **数据集分档协议(n_event 四档)**:≥100 主图干净集;70–100 主图带 CI 不排名;30–70 补充材料;<30 低事件组定性。
- **执行口径(训练 vs 报告)**:训练范围(T12,2026-10-02;2026-10-09 修订口径)= **label 患者集有效事件 ≥ 100 的 14 个数据集**(2026-10-12 label 全表口径重建后 KIRC 175 回归;COAD 95 出主集);70–100 / 30–70 / <30 档**不新增训练**(历史结果已随 T35 全链清洗;定量报告表只有 14 主集行,低档无生产方;四档语义用于 Test_0 分类与定性讨论)。Test_3 主集即这 14 个。
- **方案 × 数据集绑定(138 组合)**:泛癌种 4 方案(MULTISURV / SURVPGC / MMSURV / INTEGRATIVE_DNN)× 33 TCGA;HGCN_* 6 方案各绑定本癌种(KIRC / LIHC / ESCA / LUSC / LUAD / UCEC)。

## 配置口径

实验与结果按**配置**组织,不按 Test 编号组织:Test 是"要证明什么",配置是"在什么条件下做"。
(历史上实验按 Test 编号组织、结果按条件组合存放,Test 之间互相引用对方目录,造成语义套叠
与虚假依赖——本口径即为此而设。)

**配置 = 条件因子元组**,是训练的最小原子:

| 因子 | 取值 | 说明 |
|---|---|---|
| F 字段组合 | single(单字段)/ paper(论文方案)/ greedy(搜索最优) | |
| T 时间口径 | raw(mask 关)/ lm0(landmark_0 三要件) | |
| E 编码器 | prompt / onehot_ordinary / hgcn_clinic | 只在 Test_5 换,不进配置名;主线 = prompt |

- **配置名 = F×T**,不含 Test 编号:results/ 目录 = `paper_raw` / `paper_lm0` /
  `greedy_lm0` / `single_lm0` / `single_raw`;cindex 行键 = `work_raw_*` / `work_lm0_*` /
  `greedy_lm0_*`。
- **实验 = 配置组**:每个 Test 只声明它需要哪些配置(总表"配置组"列),enqueue 生成对应
  conf、统一 run 执行;共享的配置结果谁先生成谁落盘,后跑的 Test 直接 skip
  (cindex = OUT_DIR/.done、search = result.json;univariate 靠 per-field reuse 只补缺失字段)。
- **results/ 按配置存放**,results_display/ 的 Test 是配置的**消费者**:每个 Test 只挑它
  声明的配置组做对比/画图,Test 之间不互相读对方中间产物。
- **Test 无依赖,全部可单跑**:任何 Test 都可以独立 enqueue → run;缺失的配置结果按缺臂
  pending 处理,不阻塞。纯消费实验(Test_1b / Test_4)同样有自己的 enqueue 臂——生成
  自己配置组的全套 conf,与生产方实验**同配置同名**:先跑谁谁生成,后跑的直接 skip。
  greedy × lm0 的字段名单来源 = 搜索——搜索是 greedy 配置的生成器,不是实验依赖。

## 实验清单总表

| 实验 | 命题 | 配置组 |
|---|---|---|
| **Test_1a** 单字段泄露对照(时间轴链动机) | 同一字段 mask off vs t0 的 c 之差 × leak_rate | single × {raw, lm0} |
| **Test_1b** 各数据集 Cindex 情况(字段轴链动机) | 单字段 c 分布、跨数据集分布、top-k 重叠 | single × lm0 |
| **Test_2a** 泄露审计(时间轴链主体) | 60 组合逐字段量化 leak_rate | — |
| **Test_2b** 去泄露对照(时间轴链主体) | 同字段集两臂 Δc = 报告 − 去泄露 | paper × {raw, lm0} |
| **Test_3** 贪婪搜索对照(字段轴链主体) | 两臂 Δc = 可达 − 工作组合 → 低估证据 | paper × lm0、greedy × lm0 |
| **Test_4 四档对照表**(非实验) | 报告值 / 去泄露值 / 可达值 / 原始可达值,两链收口 | paper × {raw, lm0}、greedy × {raw, lm0} |
| **Test_5** 不变性 | 换 E/M/Q 轴后两条链的结论不变 | 上述配置组 × E/M/Q |
| **Test_6** 搜索算法选型(字段轴链选型) | 同预算下哪个搜索算法能找到最好的字段组合 | A1–A6 + SEAS 对比 |

## 各实验协议

### Test_1a 单字段泄露对照(时间轴链动机)

- **数据集**:14 主集(label 患者集有效事件 ≥100)× landmark_0 kept 字段集(逐字段)。
- **两臂**:臂 off = 取值 mask 关闭(`raw` 变体,落点 `results/single_raw/`);臂 t0 = mask 开(落点 `results/single_lm0/univariate/`,= univariate 已完成);**两臂同患者集**(S4 派生 label,gt≤0 排除)。
- **评估器**:`mlp_clinic_flatten`(univariate 单字段,与 t0 臂一致)。
- **轮数 / 协议**:5 折 × seed 0 × 2 臂,逐字段;Δc_field = c(off) − c(t0) 与 Test_2a 的 leak_rate 交叉(leak_rate 列后填,依赖用户接手的新审计)。产物 `results_display/Test_1a_field_level/`。
- **merged t0 臂（噪声本底归零变体，2026-10-08 T32）**:两臂编码 batch_size 差异（64/256）的 GEMM 舍入（~7e-7）是 mask_unaffected Δc 本底的根因；merged 变体把未改动单元格直接复用 off 臂行（`outputs/_merged`，零 CONCH 重编码），两臂输入位同 → mask_unaffected Δc 精确 0（显示脚本 `--strict_noise_floor` 断言）。产物已随旧树清理，待补跑（BRCA/GBM 待 raw bank 新字段表重建）。

### Test_1b 各数据集 Cindex 情况(字段轴链动机)

- **数据集**:14 主集(label 患者集有效事件 ≥100;T40 补:Test_1b 降级 14 集)。
- **评估器**:不新增训练——数据源 = univariate 结果(Test_1a t0 臂) `results/single_lm0/univariate/prompt/landmark_0/{ds}/mlp_clinic_flatten/field_cindex.csv`(14/14)。
- **轮数 / 协议**:三个量化指标:① 各数据集单字段 c-index 分布(原 E1 Fig2 升级);② 同一字段跨数据集 c-index 分布;③ top-k 字段重叠度(k ∈ {5,10,20},决策点 S5c)。验收:重跑 diff=0 + 抽查 3 个 (dataset, field)。产物 `results_display/Test_1b_dataset_cindex/`。

### Test_2a 泄露审计(时间轴链主体)

- **数据集**:14 主集(与训练范围统一,数据集分档协议≥100 档)× 10 方案按绑定 = **60 组合**(4 泛癌种 × 14 + 4 HGCN 本癌种在主集内)。
- **评估器**:无(描述性统计,不训练)。直接跑论文管线(A_pipeline,不做泄露处理)逐字段追溯每个值来源槽位的 t_hi;新口径 leak_rate = 值来自 t_hi>0 槽位的患者比例。
- **轮数 / 协议**:单次全量 + 重跑 diff=0;抽查 ≥3 个 (dataset, scheme, field) 与手工核对。**纠错由用户接手**。产物 `results/leak_audit/`。

### Test_2b 去泄露对照(时间轴链主体)

- **数据集**:14 主集 × 10 方案按绑定(60 组合 × 2 臂 × 2 评估器 = 240 confs);历史 apipe 口径 = 33 TCGA × 138 组合(552 confs,已冻结清洗)。
- **两臂**:臂 A = 原字段集 × mask 关闭(报告值对照);臂 B = 同字段集 × landmark_0 三要件(去泄露值)。**唯一差异 = mask**。现行编码 = field bank 切片(F×T 名 work_raw_*/work_lm0_*);历史 apipe 全量 CONCH 路径已退役删除(见 arm_registry 退役臂表)。
- **评估器**:`clinic_cox` + `mlp_clinic_flatten`(2 个)。
- **轮数 / 协议**:5 折 × seed 0 × 2 臂 × 2 评估器 = **240 confs**(现行 bank 口径;历史 apipe 552 confs 已冻结清洗);控制变量审计、按模态一致性判据验收。产物 `results/{paper_raw,paper_lm0}/`、`results_display/Test_2b_delta/`。
- **结论**:无数据集级系统性高估;MULTISURV × Cox 方向一致率最高(10/15)。

### Test_3 贪婪搜索对照(字段轴链主体)

- **数据集**:manifest 主集(数据集分档协议≥100 档,14 个);低事件档仅定性。
- **搜索**:池 = landmark_0 field bank(模板 33/33 已填齐);算法 = 前向贪婪(A2_greedy),早停 sig_stop = gain < 0.005 且 paired Wilcoxon p ≥ 0.05 连续 3 步(D4 已确认)。
- **两臂**(同 field bank 基座,同编码器/模型/划分/seed;臂 = {F,T} 二元组,见 arm_registry):`deleak` = work × lm0(去泄露值,方案 `work_lm0_{work}_{ds}`,与 Test_2b 臂 B 同一产物);`reach` = greedy × lm0(可达值,方案 `greedy_lm0_{ds}`,字段 = 搜索 result.json)。头条 Δc = reach − deleak。字段名单训练时解析(2026-10-13),论文方案仅保留 fields.json 字段登记。
- **评估器**:`mlp_clinic_flatten`(E2 唯一搜索目标模型)。
- **轮数 / 协议**:5 折 val c-index × seed 0(默认;E2 规格支持逗号列表多 seed,跨 seed 报均值 ± std)。产物 `results/greedy_lm0/`(search/、cache.sqlite、compare/、two_arm.csv)。

### Test_4 四档对照表(非实验,收口)

- **数据集**:14 主集(纯消费:生产方 = paper/greedy × {raw, lm0} 四配置,均为 14 主集;低档无生产方 → 表中无低档行)。
- **评估器**:不新增训练——报告值 = report 臂(paper_raw)/ 去泄露值 = deleak 臂、可达值 = reach 臂(缺臂时回退搜索 best_cv_c_mean,std 记 n/a)/ 原始可达值 = greedy × raw(未训 = pending),口径见 arm_registry 磁盘落点映射。
- **轮数 / 协议**:纯汇总;每 (dataset, work) 一行四档 + 档间 Δ(Δ1 报告−去泄露、Δ2 去泄露−可达、Δ3 报告−原始可达、Δ4 原始可达−可达),并列 n_event / 每折事件数。产物 `results_display/Test_4_four_tiers/`。

### Test_5 不变性

- **命题**:两条链(时间轴/字段轴)的结论在换编码(E)、换分析器(M)、换指标(Q)后依然成立。
- **数据集**:14 主集;多模态(M 轴 snn / survgc_f)仅 BRCA/LIHC/KIRC。
- **三轴**:
1. **编码**E = prompt(CONCH 文本 = field bank prompt 变体,基线)/ onehot_ordinary(临床值按 GDC 字典定型 = field bank onehot 变体,全局共享词表;原 baseline 物化线已退役 2026-10-13)/ hgcn_clinic(全连接图节点,**编码先落地、评估臂待 HGCN 模型接入后补跑**);
2. **模型**M = mlp_clinic_flatten(基线)/ snn_clinic_flatten / clinic_cox / survgc_f+survpgc_f(多模态,仅 BRCA/LIHC/KIRC,本轮不含 HGCN 模型);
3. **指标**Q = cv_c_mean(基线)+ IBS(1–60 月)+ AUC@24/60 + IPCW(Q 层先修复 Clinic_Analyzer 指标实现再统一重算)。
- **四个子检查 = 轴 × 链对照**:`E_time` / `E_field`(换编码,本轮只跑 onehot_ordinary 臂)、`M_time` / `M_field`(换分析器),臂对映射见 arm_registry「Test_5 子检查 = 轴 × 臂对」;`E_time`/`M_time` 的历史产物基于已删 apipe 编码,重建批次待排期;本轮约 436 新 confs(hgcn 评估臂 ≈190 待模型接入,全量 ≈626);锁定基线(landmark_0、5 折 seed 0、14 主集)不变;数据轴(CPTAC/MMRF)另行。
- **HGCN**(用户指令 2026-10-03):编码先落地(P5:任意 scheme + landmark,pkl 格式不变 + L0-L5 等价性回归),模型暂不接入(用户移植的训练器为独立工作);既有 `outputs/*/A_manual/HGCN_clinic/`(9 数据集)冻结,已备份仓库外。
- **产物**:`results/Test_5_invariance/{E_time,E_field,M_time,M_field}/`、`results_display/Test_5_invariance/`(q_metrics.csv)。

### Test_6 搜索算法选型(字段轴链选型)

- **命题**:在相同逻辑预算下,哪个搜索算法能在 TCGA 上找到最好的字段组合;GT = 对比算法中表现最好者的结果(**比较性 GT**,诚实声明非全局最优,不做 ANCHOR 穷举)。
- **数据集**:试点 GBM(p=19)/ LGG(p=30)/ PAAD(p=38),landmark_0;胜者推广 14 主集生产搜索。
- **搜索**:池 = landmark_0 field bank;算法 = A1 随机 / A2 前向贪婪(gain_only)/ A3 beam / A4 模拟退火 / A5 遗传 / A6 蚁群 / SEAS;参考线 A0 全字段、A0b 单变量 top-k(不参与 GT)。
- **预算 / 评估器**:预算上限 = min(p(p+1)/2, cap),cap 可配置(当前 500,`--budget_cap`);`mlp_clinic_flatten`,5 折 × seed 0。
- **判定**:平均 rank 排名(平局按 anytime AUC);无算法对贪心平均优势 ≥ 0.005 → 贪心胜出(生产零新增成本);优势为正但 < 0.005 且交错 → 升级 6 数据集;SEAS 进前 2 → 补跑三消融。
- **投队列前闸门**:`scripts/check_search_labels.py`(label 文件无已知 gt≤0 患者)。
- **产物**:configs `Clinic_Analyzer/configs/`(四桶)、`results/Test_6_search/`、`results_display/Test_6_search/`(gap_table / win_rate / ranks / anytime / decision.json,汇总脚本 `scripts/run_bakeoff_report.py`)。
- **投递模板**(每 (dataset, algo) 一次 queue 调用,`--out` 含 dataset+algo 防串目录):

```bash
for ds in TCGA-GBM TCGA-LGG TCGA-PAAD; do
  for algo in A1_random A3_beam A4_anneal A5_genetic A6_aco SEAS A0_full A0b_topk; do
    python scripts/run_selection_queue.py --dataset $ds --landmark_time 0 --algo $algo \
      --stop_mode gain_only --seed 0 --budget_cap 500 \
      --queue_root Clinic_Analyzer/configs \
      --out results/Test_6_search/prompt/landmark_0/$ds/$algo
  done
done
```

### 协议与规范

经典 landmark 三要件(A_pipeline `--landmark_time` 扩展)、方案 × 数据集绑定、数据集分档协议、执行日志/规格/逐步提交——是上述所有实验的前提,本身无独立数据集/评估器/轮数协议。
**主线全部定量实验(Test_1a / 1b / 2a / 2b / 3 / 5 / 6 生产)数据集范围统一 14 主集**。

"唯一不同只有实验配置"要精确成"臂":每个实验的不同之处 = 臂(实验条件) = 已登记在 arm_registry 的条件元组:
- F 字段组合:单字段(univariate)/ 论文方案组合 / 贪婪搜索组合;
- T 时间口径:默认 landmark_0,365/730 作敏感性;
- 模型与编码轴只在 Test_5(不变性)里换(cox / snn / survpgc_f;E 轴 prompt / onehot_ordinary / hgcn_clinic)。

1. 数据管线(编码)——完全统一 ✓
- T34 收尾后编码只有一条活路:统一 field bank(同一编码器、同模板、同 mask 逻辑、同患者名单),所有臂的嵌入都是从 bank 按字段切片装配,零重编码;
- 评估时三份输入(字段向量 / 结局表 / split)对所有臂同一套:协议固定 5 折、seed 0、label 派生同口径;
- 已知的编码噪声本底已解决(T32):off/t0 两臂 batch_size 差异的 GEMM 舍入(~7e-7),通过对齐 batch_size + merged 变体(未改动单元格直接复用 off 臂行)归零。

2. 评估器——统一 ✓
- 主线评估器 = mlp_clinic_flatten,5 折 val c-index,cv_c_mean;训练配置全链统一(max_epochs=12,2026-10-09 拍板,搜索/单变量/cindex 三链同源);
- 同 seed 重跑逐位一致(历史自检证实);
- Test_2b 跑 cox + mlp 两个评估器是设计(双评估器稳健性,都报告),不是偏差;Test_5 换评估器/编码是有意的不变性实验。

