# 实验清单与协议速查

口径唯一来源:`z_notes/Test_series_spec.md`(规格)与 `z_notes/Test_series_execution_log.md`(执行日志)。本文件只是一页速查,冲突时以规格为准。臂(实验条件)定义唯一来源 = [arm_registry.md](arm_registry.md)(臂 = {F 字段组合, T 时间口径, P 编码路径} 条件元组 + 语义名;字母代号已退役)。三处目录命名(configs/results/results_display)的唯一公约见 [naming_convention.md](naming_convention.md)。全量重跑操作手册见 [runbook.md](runbook.md)。

## 背景(一句话)

对 **33 个 TCGA 队列**做生存预测(OS,c-index),临床字段经 CONCH 编码。之前发表的工作在临床字段使用上有两个缺陷:**无时点约束**(混入诊断时点 t0 之后的信息 → 高估)与**无依据选字段**(漏掉有效字段 → 低估)。

## 组织思路(两条论证链 + 动机层)

**Test_1 是动机层**,分别指出"应该做但之前没人做"的两件事;Test_2/Test_3 是两条链的主体;Test_4 三档表是两链的收口产物,**不是实验**。组织原则:**一个 Test = 一个实验(对应一个命题),一个实验对应多张表;表本身不占实验编号**。

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
        └─────────── Test_4 三档汇总表收口 ───────────┘
        报告值 − 去泄露值 = 时间轴链收口(高估量)
        去泄露值 − 可达值  = 字段轴链收口(低估量)
```

## 核心口径(全系列共用)

- **评估**:5 折交叉验证的 val c-index(`cv_c_mean` 5 折均值),不伪造独立测试集。
- **landmark = 经典三要件**(t0 = 诊断日):① 风险集只留 `ground_truth_time > T`;② 终点平移到 `gt − T`;③ 协变量只取 `t_hi ≤ T` 的槽位。默认 `landmark_0`。
- **数据协议 A(n_event 四档)**:≥100 主图干净集;70–100 主图带 CI 不排名;30–70 补充材料;<30 低事件组定性。
- **执行口径(训练 vs 报告)**:训练范围(T12,2026-10-02;2026-10-09 修订口径)= **label 宇宙有效事件 ≥ 100 的 13 个数据集**(原 15 主集 − COAD 90 − KIRC 86);70–100 / 30–70 / <30 档**不新增训练**(其已有结果——Test_2b 552 confs、S5 t0 臂 33 队列——保留磁盘,报告按协议 A 四档分层:≥100 主图定量,70–100 带 CI 不排名,30–70 补充,<30 定性)。Test_3 主集即这 13 个。
- **方案 × 数据集绑定(138 组合)**:泛癌种 4 方案(MULTISURV / SURVPGC / MMSURV / INTEGRATIVE_DNN)× 33 TCGA;HGCN_* 6 方案各绑定本癌种(KIRC / LIHC / ESCA / LUSC / LUAD / UCEC)。

## 实验清单总表

| 实验 | 内容 | 数据集 | 产物 |
|---|---|---|---|
| **Test_0** 可用数据集评估 | 按 n_event 把 33 TCGA 分四档(协议 A);两链准入前提 | 33 TCGA | `results/Test_0_dataset_availability/manifest.csv` |
| **Test_1a** 单字段泄露对照(时间轴链动机) | per-field c(mask off) vs c(t0),与 leak_rate 交叉 | 13 个主集(label 宇宙有效事件 ≥100)× landmark_0 kept 字段 | `results/Test_1a/{arm_t0,arm_off,arm_t0_merged}/`、`results_display/Test_1a_field_level/` |
| **Test_1b** 各数据集 Cindex 情况(字段轴链动机) | 单字段 c-index 分布 + 跨数据集分布 + top-k 重叠 | 33 TCGA | `results_display/Test_1b_dataset_cindex/` |
| **Test_2a** 泄露审计(时间轴链主体) | 138 组合逐字段量化 leak_rate(新口径) | 33 TCGA × 10 方案按绑定(138 组合) | `results/Test_2a_leak_audit/` |
| **Test_2b** 去泄露对照(时间轴链主体) | 同字段集两臂(含泄露 vs landmark_0),Δc = A−B | 33 TCGA × 10 方案按绑定(138 组合) | `results/Test_2b/arm_B`、`results_display/Test_2b_delta/` |
| **Test_3** 贪婪搜索对照(字段轴链主体) | 前向贪婪(gain_only δ=0.005)最优组合 vs 各工作组合 → 低估证据,两臂 | 主集 13 个(协议 A ≥100 档,label 宇宙有效事件) | `results/Test_3_greedy_vs_works/` |
| **Test_4 三档汇总表**(非实验) | 报告值 / 去泄露值 / 可达值,两链收口(档 2 = deleak 臂 bank 行;档 1 现读冻结 apipe 历史行,待 report 臂重建替换,见 arm_registry) | 33 TCGA(报告按协议 A 四档分层) | `results_display/Test_4_three_tiers/` |
| **Test_5** 不变性 | 编码(E)/模型(M)/指标(Q)轴重复 Test_2b 与 Test_3(四子检查 5E_2b/5E_3/5M_2b/5M_3,规格 `Test_series_spec.md` §8bis) | 13 主集(label 宇宙有效事件 ≥100);多模态仅 BRCA/COAD/KIRC/LIHC | `results/Test_5_invariance/`、`results_display/Test_5_invariance/` |
| **Test_6** 搜索算法选型(字段轴链选型) | 同预算 min(B,500) 下 A1–A6 + SEAS 对比,GT = 对比内最好(不做穷举 ANCHOR);试点 3 数据集定胜者,胜者推广生产搜索 | 试点 GBM / LGG / PAAD(landmark_0);生产 = 13 主集 | `Clinic_Analyzer/configs/Test_6_search`、`results/Test_6_search/`、`results_display/Test_6_search/` |
| ~~旧 Test_3b / H3b~~ | 单字段排序对照 | — | ❌ 已取消 |

## 各实验协议

### Test_0 可用数据集评估

- **数据集**:33 TCGA(全部;本阶段不纳入 CPTAC / MMRF)。
- **评估器**:无(不训练,纯统计:患者级事件表 + 5 折 split 的每折事件数)。
- **轮数 / 协议**:单次运行;验收 = 同输入重跑 diff=0 + 与 event_impact_analysis 原型计数一致。产物 `results/Test_0_dataset_availability/manifest.csv`。

### Test_1a 单字段泄露对照(时间轴链动机)

- **数据集**:33 TCGA × landmark_0 kept 字段集(逐字段)。
- **两臂**:臂 off = 取值 mask 关闭(`raw` 变体);臂 t0 = mask 开(= univariate 已完成);**两臂同患者集**(S4 派生 label,gt≤0 排除)。
- **评估器**:`mlp_clinic_flatten`(univariate 单字段,与 t0 臂一致)。
- **轮数 / 协议**:5 折 × seed 0 × 2 臂,逐字段;Δc_field = c(off) − c(t0) 与 Test_2a 的 leak_rate 交叉(leak_rate 列后填,依赖用户接手的新审计)。产物 `results_display/Test_1a_field_level/`。
- **merged t0 臂（噪声本底归零变体，2026-10-08 T32）**:两臂编码 batch_size 差异（64/256）的 GEMM 舍入（~7e-7）是 mask_unaffected Δc 本底的根因；merged 变体把未改动单元格直接复用 off 臂行（`outputs/_merged`，零 CONCH 重编码），两臂输入位同 → mask_unaffected Δc 精确 0（显示脚本 `--strict_noise_floor` 断言）。结果 `results/Test_1a/arm_t0_merged/`，报表 `results_display/Test_1a_field_level_merged/`。BRCA/GBM 待 raw bank 新字段表重建后补跑。

### Test_1b 各数据集 Cindex 情况(字段轴链动机)

- **数据集**:33 TCGA(报告按协议 A 四档分层)。
- **评估器**:不新增训练——数据源 = univariate 结果(Test_1a t0 臂) `results/Test_1a/arm_t0/prompt/landmark_0/{ds}/mlp_clinic_flatten/field_cindex.csv`(33/33 已完成)。
- **轮数 / 协议**:三个量化指标:① 各数据集单字段 c-index 分布(原 E1 Fig2 升级);② 同一字段跨数据集 c-index 分布;③ top-k 字段重叠度(k ∈ {5,10,20},决策点 S5c)。验收:重跑 diff=0 + 抽查 3 个 (dataset, field)。产物 `results_display/Test_1b_dataset_cindex/`。

### Test_2a 泄露审计(时间轴链主体)

- **数据集**:33 TCGA × 10 方案按绑定 = **138 组合**(4 泛癌种 × 33 + 6 HGCN × 本癌种)。
- **评估器**:无(描述性统计,不训练)。直接跑论文管线(A_pipeline,不做泄露处理)逐字段追溯每个值来源槽位的 t_hi;新口径 leak_rate = 值来自 t_hi>0 槽位的患者比例。
- **轮数 / 协议**:单次全量 + 重跑 diff=0;抽查 ≥3 个 (dataset, scheme, field) 与手工核对。**纠错由用户接手**。产物 `results/Test_2a_leak_audit/`。

### Test_2b 去泄露对照(时间轴链主体,已跑完)

- **数据集**:33 TCGA × 10 方案按绑定(138 组合)。
- **两臂**:臂 A = 原字段集 × mask 关闭(报告值对照);臂 B = 同字段集 × landmark_0 三要件(去泄露值)。**唯一差异 = mask**。编码路径 = apipe 全量 CONCH(历史;该路径已退役删除,两臂结果冻结为历史口径,见 arm_registry 退役臂表)。
- **评估器**:`clinic_cox` + `mlp_clinic_flatten`(2 个)。
- **轮数 / 协议**:5 折 × seed 0 × 2 臂 × 2 评估器 = **552 confs**;控制变量审计、按模态一致性判据验收。产物 `results/Test_2b/arm_B`、`results_display/Test_2b_delta/`。
- **结论**:无数据集级系统性高估;MULTISURV × Cox 方向一致率最高(10/15)。

### Test_3 贪婪搜索对照(字段轴链主体)

- **数据集**:manifest 主集(协议 A ≥100 档,15 个);低事件档仅定性。
- **搜索**:池 = landmark_0 field bank(模板 33/33 已填齐);算法 = 前向贪婪(A2_greedy),早停 sig_stop = gain < 0.005 且 paired Wilcoxon p ≥ 0.05 连续 3 步(D4 已确认)。
- **两臂**(同 field bank 基座切片,同编码器/模型/划分/seed;臂 = {F,T} 二元组,见 arm_registry):`deleak` = work × lm0(去泄露值,原"臂 B′"更名而来);`reach` = greedy × lm0(可达值)。头条 Δc = reach − deleak。scheme 模板分支已删除(T31),论文方案仅保留 fields.json 字段登记。
- **评估器**:`mlp_clinic_flatten`(E2 唯一搜索目标模型)。
- **轮数 / 协议**:5 折 val c-index × seed 0(默认;E2 规格支持逗号列表多 seed,跨 seed 报均值 ± std)。产物 `results/Test_3_greedy_vs_works/`。

### Test_4 三档汇总表(非实验,收口)

- **数据集**:33 TCGA(报告按协议 A 四档分层)。
- **评估器**:不新增训练——报告值(冻结 apipe 历史)/ 去泄露值 = deleak 臂(bank 切片)、可达值 = reach 臂,口径见 arm_registry 磁盘落点映射。
- **轮数 / 协议**:纯汇总;每 (dataset, work) 一行三档 + 档间 Δ,并列 n_event / 每折事件数。产物 `results_display/Test_4_three_tiers/`。

### Test_5 不变性(规格已落地 2026-10-03,详见 `Test_series_spec.md` §8bis;臂对定义见 arm_registry)

- **命题**:Test_2b(时间轴链)与 Test_3(字段轴链)的结论在换编码(E)、换分析器(M)、换指标(Q)后依然成立。
- **三轴**:E = prompt(CONCH 文本 = field bank 切片,基线)/ baseline(D-向量)/ hgcn_clinic(全连接图节点,**编码先落地、评估臂待 HGCN 模型接入后补跑**);M = mlp_clinic_flatten(基线)/ snn_clinic_flatten / clinic_cox / survgc_f+survpgc_f(多模态,仅 BRCA/COAD/KIRC/LIHC,本轮不含 HGCN 模型);Q = cv_c_mean(基线)+ IBS(1–60 月)+ AUC@24/60 + IPCW(Q 层先修复 Clinic_Analyzer 指标实现再统一重算)。
- **四个子检查 = 轴 × 臂对**:5E_2b / 5E_3(换编码,本轮只跑 baseline 臂)、5M_2b / 5M_3(换分析器),臂对映射见 arm_registry「Test_5 子检查 = 轴 × 臂对」;5E_2b/5M_2b 的历史产物基于已删 apipe 编码,重建批次待排期;本轮约 388 新 confs(hgcn 评估臂 ≈188 待模型接入,全量 ≈546);锁定基线(landmark_0、5 折 seed 0、13 主集)不变;数据轴(CPTAC/MMRF)另行。
- **HGCN**(用户指令 2026-10-03):编码先落地(P5:任意 scheme + landmark,pkl 格式不变 + L0-L5 等价性回归),模型暂不接入(用户移植的训练器为独立工作);既有 `outputs/*/A_manual/HGCN_clinic/`(9 数据集)冻结,已备份仓库外。

### Test_6 搜索算法选型(字段轴链选型)

- **命题**:在相同逻辑预算下,哪个搜索算法能在 TCGA 上找到最好的字段组合;GT = 对比算法中表现最好者的结果(**比较性 GT**,诚实声明非全局最优,不做 ANCHOR 穷举)。
- **数据集**:试点 GBM(p=19)/ LGG(p=30)/ PAAD(p=38),landmark_0;胜者推广 13 主集生产搜索。
- **搜索**:池 = landmark_0 field bank;算法 = A1 随机 / A2 前向贪婪(gain_only)/ A3 beam / A4 模拟退火 / A5 遗传 / A6 蚁群 / SEAS;参考线 A0 全字段、A0b 单变量 top-k(不参与 GT)。
- **预算 / 评估器**:预算上限 = min(p(p+1)/2, cap),cap 可配置(当前 500,`--budget_cap`);`mlp_clinic_flatten`,5 折 × seed 0。
- **判定**:平均 rank 排名(平局按 anytime AUC);无算法对贪心平均优势 ≥ 0.005 → 贪心胜出(生产零新增成本);优势为正但 < 0.005 且交错 → 升级 6 数据集;SEAS 进前 2 → 补跑三消融。
- **投队列前闸门**:`scripts/check_search_labels.py`(label 文件无已知 gt≤0 患者)与 `scripts/cache_status.py`(旧 e2-v1 缓存行盘点)。
- **产物**:configs `Clinic_Analyzer/configs/Test_6_search`、`results/Test_6_search/`、`results_display/Test_6_search/`(gap_table / win_rate / ranks / anytime / decision.json,汇总脚本 `scripts/run_bakeoff_report.py`)。
- **投递模板**(每 (dataset, algo) 一次 queue 调用,`--out` 含 dataset+algo 防串目录):

```bash
for ds in TCGA-GBM TCGA-LGG TCGA-PAAD; do
  for algo in A1_random A3_beam A4_anneal A5_genetic A6_aco SEAS A0_full A0b_topk; do
    python scripts/run_e2_selection_queue.py --dataset $ds --landmark_time 0 --algo $algo \
      --stop_mode gain_only --seed 0 --budget_cap 500 \
      --queue_root Clinic_Analyzer/configs/Test_6_search \
      --out results/Test_6_search/prompt/landmark_0/$ds/$algo
  done
done
```

### 基础建设(非单一命题,已落地)

经典 landmark 三要件(A_pipeline `--landmark_time` 扩展)、方案 × 数据集绑定、数据协议 A、执行日志/规格/逐步提交——是上述所有实验的前提,本身无独立数据集/评估器/轮数协议。
