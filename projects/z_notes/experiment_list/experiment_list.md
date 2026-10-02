# 实验清单与协议速查

口径唯一来源:`z_notes/Test_series_spec.md`(规格)与 `z_notes/Test_series_execution_log.md`(执行日志)。本文件只是一页速查,冲突时以规格为准。三处目录命名(configs/results/results_display)的唯一公约见 [naming_convention.md](naming_convention.md)。

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
   2b 去泄露对照(Δc = 报告−去泄露)            三臂对照(Δc = 可达−工作组合)
        ↓                                        ↓
        └─────────── Test_4 三档汇总表收口 ───────────┘
        报告值 − 去泄露值 = 时间轴链收口(高估量)
        去泄露值 − 可达值  = 字段轴链收口(低估量)
```

## 核心口径(全系列共用)

- **评估**:5 折交叉验证的 val c-index(`cv_c_mean` 5 折均值),不伪造独立测试集。
- **landmark = 经典三要件**(t0 = 诊断日):① 风险集只留 `ground_truth_time > T`;② 终点平移到 `gt − T`;③ 协变量只取 `t_hi ≤ T` 的槽位。默认 `landmark_0`。
- **数据协议 A(n_event 四档)**:≥100 主图干净集;70–100 主图带 CI 不排名;30–70 补充材料;<30 低事件组定性。
- **执行口径(训练 vs 报告)**:训练范围(R13,2026-10-02)= **n_event ≥ 100 的 15 个数据集**;70–100 / 30–70 / <30 档**不新增训练**(其已有结果——Test_2b 552 confs、S5 t0 臂 33 队列——保留磁盘,报告按协议 A 四档分层:≥100 主图定量,70–100 带 CI 不排名,30–70 补充,<30 定性)。Test_3 主集即这 15 个。
- **方案 × 数据集绑定(138 组合)**:泛癌种 4 方案(MULTISURV / SURVPGC / MMSURV / INTEGRATIVE_DNN)× 33 TCGA;HGCN_* 6 方案各绑定本癌种(KIRC / LIHC / ESCA / LUSC / LUAD / UCEC)。

## 实验清单总表

| 实验 | 内容 | 数据集 | 产物 |
|---|---|---|---|
| **Test_0** 可用数据集评估 | 按 n_event 把 33 TCGA 分四档(协议 A);两链准入前提 | 33 TCGA | `results/Test_0_dataset_availability/manifest.csv` |
| **Test_1a** 单字段泄露对照(时间轴链动机) | per-field c(mask off) vs c(t0),与 leak_rate 交叉 | 15 个主集(n_event ≥100)× landmark_0 kept 字段 | `results/Test_1a/{arm_t0,arm_off}/`、`results_display/Test_1a_field_level/` |
| **Test_1b** 各数据集 Cindex 情况(字段轴链动机) | 单字段 c-index 分布 + 跨数据集分布 + top-k 重叠 | 33 TCGA | `results_display/Test_1b_dataset_cindex/` |
| **Test_2a** 泄露审计(时间轴链主体) | 138 组合逐字段量化 leak_rate(新口径) | 33 TCGA × 10 方案按绑定(138 组合) | `results/Test_2a_leak_audit/` |
| **Test_2b** 去泄露对照(时间轴链主体) | 同字段集两臂(含泄露 vs landmark_0),Δc = A−B | 33 TCGA × 10 方案按绑定(138 组合) | `results/Test_2b/arm_B`、`results_display/Test_2b_delta/` |
| **Test_3** 贪婪搜索对照(字段轴链主体) | 前向贪婪(sig_stop 0.005)最优组合 vs 各工作组合 → 低估证据,三臂 | 主集 15 个(协议 A ≥100 档) | `results/Test_3_greedy_vs_works/` |
| **Test_4 三档汇总表**(非实验) | 报告值 / 去泄露值 / 可达值,两链收口 | 33 TCGA(报告按协议 A 四档分层) | `results_display/Test_4_three_tiers/` |
| **Test_5** 不变性 | 编码/模型/数据轴重复 Test_2b 与 Test_3 | 待定 | 待定 |
| ~~旧 Test_3b / H3b~~ | 单字段排序对照 | — | ❌ 已取消 |

## 各实验协议

### Test_0 可用数据集评估

- **数据集**:33 TCGA(全部;本阶段不纳入 CPTAC / MMRF)。
- **评估器**:无(不训练,纯统计:患者级事件表 + 5 折 split 的每折事件数)。
- **轮数 / 协议**:单次运行;验收 = 同输入重跑 diff=0 + 与 event_impact_analysis 原型计数一致。产物 `results/Test_0_dataset_availability/manifest.csv`。

### Test_1a 单字段泄露对照(时间轴链动机)

- **数据集**:33 TCGA × landmark_0 kept 字段集(逐字段)。
- **两臂**:臂 off = 取值 mask 关闭(`raw` 变体);臂 t0 = mask 开(= S5 univariate 已完成);**两臂同患者集**(S4 派生 label,gt≤0 排除)。
- **评估器**:`mlp_clinic_flatten`(univariate 单字段,与 S5 一致)。
- **轮数 / 协议**:5 折 × seed 0 × 2 臂,逐字段;Δc_field = c(off) − c(t0) 与 Test_2a 的 leak_rate 交叉(leak_rate 列后填,依赖用户接手的新审计)。产物 `results_display/Test_1a_field_level/`。

### Test_1b 各数据集 Cindex 情况(字段轴链动机)

- **数据集**:33 TCGA(报告按协议 A 四档分层)。
- **评估器**:不新增训练——数据源 = S5 univariate 结果 `results/Test_1a/arm_t0/prompt/landmark_0/{ds}/mlp_clinic_flatten/field_cindex.csv`(33/33 已完成)。
- **轮数 / 协议**:三个量化指标:① 各数据集单字段 c-index 分布(原 E1 Fig2 升级);② 同一字段跨数据集 c-index 分布;③ top-k 字段重叠度(k ∈ {5,10,20},决策点 S5c)。验收:重跑 diff=0 + 抽查 3 个 (dataset, field)。产物 `results_display/Test_1b_dataset_cindex/`。

### Test_2a 泄露审计(时间轴链主体)

- **数据集**:33 TCGA × 10 方案按绑定 = **138 组合**(4 泛癌种 × 33 + 6 HGCN × 本癌种)。
- **评估器**:无(描述性统计,不训练)。直接跑论文管线(A_pipeline,不做泄露处理)逐字段追溯每个值来源槽位的 t_hi;新口径 leak_rate = 值来自 t_hi>0 槽位的患者比例。
- **轮数 / 协议**:单次全量 + 重跑 diff=0;抽查 ≥3 个 (dataset, scheme, field) 与手工核对。**纠错由用户接手**。产物 `results/Test_2a_leak_audit/`。

### Test_2b 去泄露对照(时间轴链主体,已跑完)

- **数据集**:33 TCGA × 10 方案按绑定(138 组合)。
- **两臂**:臂 A = 原字段集 × mask 关闭(报告值对照);臂 B = 同字段集 × landmark_0 三要件(去泄露值)。**唯一差异 = mask**。
- **评估器**:`clinic_cox` + `mlp_clinic_flatten`(2 个)。
- **轮数 / 协议**:5 折 × seed 0 × 2 臂 × 2 评估器 = **552 confs**;控制变量审计、按模态一致性判据验收。产物 `results/Test_2b/arm_B`、`results_display/Test_2b_delta/`。
- **结论**:无数据集级系统性高估;MULTISURV × Cox 方向一致率最高(10/15)。

### Test_3 贪婪搜索对照(字段轴链主体)

- **数据集**:manifest 主集(协议 A ≥100 档,15 个);低事件档仅定性。
- **搜索**:池 = landmark_0 field bank(模板 33/33 已填齐);算法 = 前向贪婪(A2_greedy),早停 sig_stop = gain < 0.005 且 paired Wilcoxon p ≥ 0.05 连续 3 步(D4 已确认)。
- **三臂**(全走 A_pipeline,同编码器/模型/划分/seed):B = 工作组合 × scheme 模板 × lm0;B′ = 工作组合 × bank 模板 × lm0;C = 贪婪最优 × bank 模板 × lm0。头条 Δc = C − B′。
- **评估器**:`mlp_clinic_flatten`(E2 唯一搜索目标模型)。
- **轮数 / 协议**:5 折 val c-index × seed 0(默认;E2 规格支持逗号列表多 seed,跨 seed 报均值 ± std)。产物 `results/Test_3_greedy_vs_works/`。

### Test_4 三档汇总表(非实验,收口)

- **数据集**:33 TCGA(报告按协议 A 四档分层)。
- **评估器**:不新增训练——报告值 / 去泄露值来自 Test_2b 两臂(`clinic_cox` + `mlp_clinic_flatten`),可达值来自 Test_3(`mlp_clinic_flatten`)。
- **轮数 / 协议**:纯汇总;每 (dataset, work) 一行三档 + 档间 Δ,并列 n_event / 每折事件数。产物 `results_display/Test_4_three_tiers/`。

### Test_5 不变性(占位)

- 编码轴(编码方式)/ 模型轴(分析器)/ 数据轴(外部数据集 CPTAC、MMRF 等)重复 Test_2b 与 Test_3。协议待 Test_1–Test_3 完成后另出规格。

### 基础建设(非单一命题,已落地)

经典 landmark 三要件(A_pipeline `--landmark_time` 扩展)、方案 × 数据集绑定、数据协议 A、执行日志/规格/逐步提交——是上述所有实验的前提,本身无独立数据集/评估器/轮数协议。



1. 每个实验只有一个命题、一个主体维度;另一个维度只做"稳健性"

┌──────┬──────────────────────┬─────────────────────────┬──────────────────────────┐
│ 实验 │  命题(它要证明什么)  │        主体维度         │ 另一个维度(数据集/字段)  │
│      │                      │                         │          的作用          │
├──────┼──────────────────────┼─────────────────────────┼──────────────────────────┤
│ Test │ 时间口径(t0)会实质改 │ 字段("哪些字段被 mask   │ 数据集 =                 │
│ _1a  │ 变单字段评估值       │ 动了、动多少")          │ 稳健性:这个效应是普遍的  │
│      │                      │                         │ 还是个别数据集特有       │
├──────┼──────────────────────┼─────────────────────────┼──────────────────────────┤
│ Test │ 每个数据集有自己的最 │ 数据集("每个数据集的最  │ 字段 =                   │
│ _1b  │ 优字段组合           │ 优字段是谁、top-k       │ 反证"通吃字段"不存在     │
│      │                      │ 互不重叠")              │                          │
└──────┴──────────────────────┴─────────────────────────┴──────────────────────────┘