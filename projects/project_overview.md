# 项目总览:问题、数据与实验

本文是 `projects/` 目录的口径总览。实现细节见 [README.md](../README.md),日常命令见 [README_usage.md](../README_usage.md),E2 完整规格见 [E2_Selection_Gain_Algorithm/E2_selection_algorithm_design.md](E2_Selection_Gain_Algorithm/E2_selection_algorithm_design.md),人工方案通路见 [A_pipeline/README.md](../A_pipeline/README.md)。

---

## 1. 问题与口径

### 1.1 研究问题

**生存分析问题**:用癌症患者的临床字段(临床 JSON / 电子病历)预测总生存期(OS),评价指标为 concordance index(c-index)。围绕临床字段做三件事:

1. **编码**:把临床字段编码成可学习的表示(字段 → 自然语言句子模板 → CONCH 512 维向量等);
2. **评估**:评估单个字段与字段组合的生存预测力(5 折 c-index);
3. **选字段**:研究"选哪些字段"——在相同评估协议与逻辑预算下比较字段子集搜索算法(E2),并验证本工作方法 SEAS。

### 1.2 生存终点与评估口径

- **终点**:总生存期 OS;**事件** = 死亡。
- **时间**:死亡患者取 `demographic.days_to_death`;删失患者取 `diagnoses[].days_to_last_follow_up`;由此得到患者级 `last_time`(天)。
- **评价**:5 折交叉验证的 val c-index。现有 split 的 val 与 test 是同一批患者,**不是独立测试集**;统一只报 `cv_c_mean`(5 折均值),不用 test / held-out 字样。
- **空集**固定 `cv_c_mean = 0.5`,不训练、不消耗预算。

### 1.3 缺失与时间口径

- **三态缺失**:`null`(路径抽不到值)/ `sentinel`(哨兵值)/ `valid`;`missing = null + sentinel`。
- **landmark 与时间泄露**:字段扫描 / 统计阶段用 landmark 规则对时间泄露做了明确定义与处理——取值 mask 的时点 `T ∈ {0, 365, 730, none}`,槽位状态为 `point` / `bounded` 且时间上界 `t_hi <= T` 的取值才可用,`t_hi > T` 的取值属于"未来信息"被 mask(防泄露);`none` 关闭 mask,且筛选 R0 整层删除 `diagnoses` / `follow_ups` 字段。R0 另删纯结局字段与日历 / 时间点泄漏字段(`year_of_diagnosis`、`year_of_follow_up`、`timepoint_category`)。
- **筛选规则**:R0 删结局字段与日历/时间泄漏;R3 覆盖率 ≥ 0.30;R4 非空唯一值 ≥ 2 且众数占比 ≤ 0.95。

### 1.4 编码口径

| 编码 | 做法 |
|---|---|
| `prompt`(默认) | 每字段一句自然语言模板 → CONCH 文本编码器 → 512 维行向量 |
| `onehot` | 名义字段 one-hot,短字段右侧 0 pad |
| D 向量(A 通路) | 连续 min-max + 名义 onehot 拼接 |
| L2 / L3 / L5 | 字段句子的组成编码:全部拼接 / 按 ≤127 token 切窗 pad / 语义组(`l5_semantic_groups.csv`) |

### 1.5 模型口径

- **单模态分析器**:`mlp_clinic_mean`、`mlp_clinic_flatten`、`snn_clinic_mean`、`snn_clinic_flatten`、`clinic_cox`。
- **多模态模型**:`survgc_f`、`survpgc_f`,仅允许 BRCA、COAD、KIRC、KIRP、LIHC(其 fold 只收临床 + 病理 + 组学齐全的患者);其余队列按 clinic 单模态评估。

### 1.6 E2 专项口径

- **逻辑预算** `B = p(p+1)/2`(p = Field Bank 字段数);全局缓存命中仍消耗逻辑预算,保证算法运行顺序不改变可搜索范围。
- `DELTA = 0.005`,`PATIENCE = 3`;`--seed` 支持单个或逗号列表,同一个 seed 同时传给模型训练与随机搜索。
- **sig_stop**(仅 A2 前向贪婪在线执行):`gain(k) < 0.005` 且 paired Wilcoxon `p >= 0.05` 连续 3 步即停,推荐 `k_sig = k - 3` 的前缀。
- 主实验固定:33 个 TCGA × `prompt` × `mlp_clinic_flatten` × `{landmark_0, landmark_365, landmark_730, landmark_none}`。

### 1.7 命名口径

- `TCGA_LIHC` 是历史目录名,与 `TCGA-LIHC` 解析到同一份配置;`CPTAC` / `MMRF` 是 pipeline 名,原始 JSON 为 `CPTAC-3.json` / `MMRF-COMMPASS.json`。
- 患者级 `.pt` 按 `submitter_id` 命名;E2 报告按 5 折 val,不伪造独立测试集。

---

## 2. 数据

### 2.1 主数据:33 个 TCGA 队列

`projects/datasets.json` 注册 33 个 TCGA 队列的 GDC clinical JSON(`ClinicDatasets/gdc_clinical/raw_json/TCGA-XXXX.json`),是 B 通路(扫描/筛选/Field Bank/E1/E2/greedy 等)与论文方案复现的数据来源。

ACC、BLCA、BRCA、CESC、CHOL、COAD、DLBC、ESCA、GBM、HNSC、KICH、KIRC、KIRP、LAML、LGG、LIHC、LUAD、LUSC、MESO、OV、PAAD、PCPG、PRAD、READ、SARC、SKCM、STAD、TGCT、THCA、THYM、UCEC、UCS、UVM

### 2.2 外部数据集

| 数据集 | 状态 |
|---|---|
| MMRF(MMRF-COMMPASS) | **已接入** `datasets.json`,未使用(E2 明确排除) |
| CPTAC(CPTAC-3) | **已接入** `datasets.json`,未使用(E2 明确排除) |
| MSK-CHORD 2024 | **未接入**(仅放在 `ClinicDatasets/msk_chord_2024/`,不在任何 `datasets.json`),未使用 |

### 2.3 lizhe 数据(A 通路)

`A_pipeline/datasets.json` 指向 `/data/lizhe/Medteam_projects/` 下 9 个癌种的 `clinical.cart`:BRCA、LIHC、COAD、PRAD、READ、STAD,以及共用一份肾癌 JSON、按 `project_id` 拆开的 KICH、KIRC、KIRP。人工方案 L0-L5 / D0-D5 只在这 9 个队列上跑。

### 2.4 多模态数据

**BRCA、COAD、KIRC、KIRP、LIHC** 五个癌种在 `/data/lizhe` 下具有**三种模态**的数据(临床 + 病理 WSI + 组学)。当前项目只使用其中的临床 JSON;多模态的体现是:这 5 个队列的 5 折 split 只收三模态齐全的患者,且多模态模型 `survgc_f` / `survpgc_f` 仅在这 5 个队列上可用。

### 2.5 数据划分

5 折 split 位于 `Clinic_Analyzer/data/splits/5foldcv/{study}/splits_0.csv` ~ `splits_4.csv`,本地生成,不覆盖 SurvPGC 原划分。

---

## 3. 执行分析(实验与目标)

公共处理链:scan(扫描)→ stats(统计)→ filter(筛选)→ Field Bank(长表**人工填写** + 编码)→ 各评估实验。

### 3.1 E1:单字段 c-index 实验

- **实验目标**:对 Field Bank 筛后的每个字段单独评估生存预测力,得到字段级基线;其结果同时是 E2 中 A6_aco、SEAS 系列、ANCHOR 所需的**单字段先验**。
- **做法**:每个字段切 `[1, D]` embedding,用同一分析器报 5 折 val c-index(不是 greedy 的一步,不改选字段)。
- **产物**:`results/univariate/prompt/{landmark_tag}/{dataset}/{analyzer}/field_cindex.csv`;可视化脚本 `Test_1b_dataset_cindex.py`。

### 3.2 复现实验:论文字段复现与人工字段工作

- **实验目标**:用统一的编码 + 评估通路复现现有论文的字段组合,并按人工规则产生 / 定义字段方案,验证通路一致性,作为后续实验的对照基线。
- **论文字段复现(10 个方案)**:`MULTISURV`、`SURVPGC`、`MMSURV`、`INTEGRATIVE_DNN`、`HGCN_KIRC`、`HGCN_LIHC`、`HGCN_ESCA`、`HGCN_LUSC`、`HGCN_LUAD`、`HGCN_UCEC` —— 字段来自 GDC 官方 JSON,绑全部 33 个 TCGA 队列;编码走 prompt/CONCH 与 D 向量。
- **人工字段工作**:
  - **人工方案** L0-L5(prompt/CONCH)与 D0-D5(baseline 向量)字段列表对齐,按人工设计的层级规则产生,另接 HGCN clinic 图节点 —— 只跑 lizhe 9 个队列;
  - **Field Bank 长表人工填写**(B 通路):看 `example` 原始取值 → 裁定 `convert` / `unit` → 填 `template` 句子模板,是 prompt 编码前的人工字段释义环节。
- **产物**:`results/A_manual/{dataset}/cindex.csv`;与 greedy 增长曲线叠加比较见 `FigA_Other_Paper_Works.py`。

### 3.3 E2:字段子集选择算法实验

- **实验目标**:在相同评估协议与逻辑预算 B 下比较字段子集搜索方法,并验证本工作方法 SEAS 的有效性与消融。

| 类别 | 算法 | 说明 |
|---|---|---|
| 参考(不参加预算竞争) | A0 全字段 | 完整 Field Bank 评一次 |
| | A0b 单变量 top-k | 按单字段 c-index 取 k ∈ {1,3,5,8,12,20,p} |
| | A0c Lasso-Cox | 字段块 Lasso 路径,最优 λ 水平线 |
| 基线 | A1 随机搜索 | size-uniform 采样 k 个字段 |
| | A2 前向贪婪 | 每步加增益最大字段,唯一 sig_stop |
| | A3 beam | W=8 |
| | A4 模拟退火 | 1-flip / swap 邻域,降温重启 |
| | A5 遗传算法 | 种群 20,锦标赛,2 elite |
| | A6 蚁群 | 信息素 + 单字段先验启发式 |
| 本方法 | **SEAS** | 语义表示 + 线性交互代理模型 + EI 采集(q=8) |
| | SEAS-no-sem / -no-int / -no-ei | 三个消融 |
| 锚点 | ANCHOR_TIMING → ANCHOR | 计时探针选 p ∈ [8,15],top-p 受限空间穷举(仅 seed 0) |

- **实验假设**:
  - H1:A2 的 sig_stop 子集相对 A0 全字段,在至少 2/3 实例上平均差值 ≥ 0.005;
  - H2:SEAS 对 A1-A6 中全局最强基线的胜率 ≥ 60%;锚点实例另报 seed 0 的 optimality gap。
- **范围**:33 个 TCGA(排除 MMRF、CPTAC)× 4 个 landmark × `prompt` × `mlp_clinic_flatten`(支持按 analyzer 展开)。
- **当前状态**:A1-A6、SEAS + 3 消融、ANCHOR_TIMING、ANCHOR 可运行;A0/A0b 内部组件尚未接入 CLI,A0c 尚未实现。
- **产物**:`results/E2_selection/prompt/{landmark_tag}/{dataset}/{algorithm}/{analyzer}/seed_*/`;汇总 `results_display/E2_selection/`(main_table、anytime、anchor_gap、landmark)。

### 3.4 其他实验

| 实验 | 目标 |
|---|---|
| 旧 greedy(前向贪心) | Field Bank 上的字段增量选择(内层选字段、外层多分析器,`min_delta` 早停);E2 之前的早期探索,**全数据集扫描已完成** |
| 组成方案 L2 / L3 / L5 | 考察字段句子的不同组成编码方式对生存预测的影响 |
| linear probe(Ridge R²) | 检查 prompt 512 维向量能否线性还原数值字段原始值(可恢复性检查,非生存预测) |
| 纵向实验 | Field Bank 按 follow-up 记录展开并加入 days_since / ECOG / Karnofsky / BMI / weight 变化列,考察纵向随访信息的预测价值 |
