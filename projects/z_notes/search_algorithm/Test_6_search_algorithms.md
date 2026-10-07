# Test_6 搜索算法说明(字段轴链选型)

一句话:**Test_6 在相同逻辑预算下对比 7 个搜索算法(A1–A6 + SEAS)找最优字段组合,判定贪心能否守住生产席位**。口径来源:`experiment_list.md` §Test_6;实现规格(更长、以兼容规则为准)见 `z_notes/E2_Selection_Gain_Algorithm/E2_selection_algorithm_design.md`。代码:`src/selection/`。

## 1. 共同口径(所有算法一致)

| 项目 | 值 |
|---|---|
| 搜索池 | landmark_0 field bank;试点 GBM(p=19)/ LGG(p=30)/ PAAD(p=38) |
| 评估器 | `mlp_clinic_flatten`,5 折 val c-index × seed 0(`cv_c_mean` + 5 个 `cv_folds`) |
| 逻辑预算 | 上限 = min(p(p+1)/2, cap=500) → GBM 190 / LGG 465 / PAAD 500。**每次提案评估计 1 个逻辑预算(缓存命中也计)**;同 run 内重复提案直接回放、不计 |
| 缓存 | 全局 SQLite(`Test_3_search/cache.sqlite`),key 含 dataset / landmark / encoding / modality / seed / 字段索引 hash / split hash / 训练参数 hash / label hash → **跨算法共享,同一子集不重训** |
| 单字段先验 | Test_1a arm_t0 的 `field_cindex.csv`(5 折 mean+folds)。A6 / SEAS / A0b 使用;`precharge` 占用 p 个逻辑预算 |
| 随机 | 统一 `np.random.default_rng(seed)` |

## 2. 算法一览

| 算法 | 类型 | 核心机制 |
|---|---|---|
| **A0_full** | 参考线(不参与预算竞争/GT) | 全字段集评 1 次 |
| **A0b_topk** | 参考线 | 按单字段 c-index 排序取累计 top-k(k∈{1,3,5,8,12,20,p}),报最优 k |
| **A1_random** | 随机 | 随机大小 k∈[1,p] 的随机子集,去重,烧完预算为止 |
| **A2_greedy** | 前向贪婪(**当前生产算法**) | 每步评估所有单字段扩展取最优加入;SigStop 早停(§3) |
| **A3_beam** | 束搜索 | width=8:每轮扩展束内所有状态(各加 1 字段),保留 top-8 |
| **A4_anneal** | 模拟退火 | 1-flip 加/减 + swap(20%)邻域;Metropolis 接受 exp(Δ/T);T 由前 50 次 |Δ| 中位数/ln2 自适应,×0.995 降温;200 步无改善回跳至历史最优 |
| **A5_genetic** | 遗传算法 | pop=20;top-2 精英保留;均匀交叉(父代取自 top-3..pop)+ 每字段 1/p 概率变异;烧完预算为止 |
| **A6_aco** | 蚁群 | 10 ants,ρ=0.1;信息素 τ(冠军子集更新,clip [0.01,10])× 单字段先验启发 η²(归一化 max(c−0.5,0))引导构造;随机大小子集 |
| **SEAS** | 贝叶斯代理 + EI(§4) | 用单字段先验 + 字段语义相似度建代理,期望改进批量采集 |
| **ANCHOR** | 穷举(非 GT) | 仅受限空间:top-univariate p∈[8,15] 字段穷举 2^p−1,供最优差距参考与时间规划 |

竞争算法 = {A1..A6, SEAS};A0 系参考线、ANCHOR、SEAS 消融均不参与 GT 与排名。

## 3. A2 贪心早停(SigStop,`src/selection/stopping.py`)

- 参数:δ(gain)= 0.005,patience = 3。
- **sig 模式**(原口径,Test_3 用):增益 ≥ δ **且** 5 折配对 Wilcoxon p < 0.05 记"进步";gain < δ 且 p ≥ 0.05 计数;连续 3 步停。
- **gain_only 模式**(D4 修订 2026-10-04,**Test_6 采用**):只看增益,不看 Wilcoxon——n=5 时 p<0.05 要求 5/5 折全正,过严。
- 停止时**推荐子集 = 最后进步步数 k_sig 的前缀**(`prefixes[k − patience]`),不是历史最优子集。
- 预算耗尽时推荐 `k_star` 前缀,reason = budget_exhausted。

## 4. SEAS 要点(最复杂,`src/selection/search/seas.py`)

- **语义相似度**:每字段描述文本(GDC 字典 + Field Bank 模板)经 CONCH ViT-B-16 `encode_text` 编码(npy 缓存),取每字段 top-3 语义邻居为交互对。
- **代理**:贝叶斯线性回归,特征 = [1, 子集指示 z, 交互对 z_i·z_j, |z|];先验均值 = 0.5 + (单字段 c−0.5) − 0.01·sim;噪声初值 δ/2,每 20 次新观测用残差 RMSE 更新。
- **采集**:期望改进 EI,batch q=8,fantasy 更新;候选池 = top-5 的 1-flip 邻域 + 最优解 swap(≤100)+ 200 随机子集;先随机采 20 个点初始化。
- **消融**:SEAS-no-sem(无语义)/ SEAS-no-int(无交互)/ SEAS-no-ei(纯均值采集)。

## 5. 判定规则(`src/selection/bakeoff.py` decide)

- **GT = 比较性 GT**:同 instance 内竞争算法预算内历史最优 cv_c_mean(跨 seed 均值)——诚实声明非全局最优,不做 ANCHOR 穷举。
- **排名**:instance 内按 mean best 排名(平局平均名次)→ 跨 instance 平均 rank;**rank 平局按 anytime AUC**(anytime 曲线归一化梯形面积)。
- **决策**(δ = 0.005):
  1. 最佳竞争者相对贪心的平均优势 ≥ δ → **换胜者**,胜者推广生产搜索;
  2. 优势 > 0 但 < δ 且实例间交错 → **ambiguous**,升级 6 数据集再判;
  3. 否则 → **贪心胜出**(生产零新增成本,Test_3 已用贪心);
  4. SEAS 平均 rank ≤ 2 → 补跑三消融。
- 产物:`gap_table / win_rate / ranks / anytime / decision.json`,汇总脚本 `scripts/run_bakeoff_report.py`。

## 6. 代码指路

| 内容 | 位置 |
|---|---|
| 各算法实现 | `src/selection/search/{random_search,greedy,beam,anneal,genetic,aco,seas,exhaustive}.py` |
| CLI 注册与预算 | `src/selection/runner.py`(`--algo / --stop_mode / --budget_cap`) |
| 评估器(预算/缓存/先验) | `src/selection/evaluator.py` |
| 早停 | `src/selection/stopping.py` |
| 常量与预算公式 | `src/selection/config.py`(DELTA=0.005, PATIENCE=3, budget_cap_for) |
| 参考线 | `src/selection/references.py`(A0_full / A0b_topk) |
| GT 与判定 | `src/selection/bakeoff.py` |
| 投递队列 | `scripts/run_e2_selection_queue.py`;投递前闸门 `scripts/check_search_labels.py` + `scripts/cache_status.py` |
| 产物目录 | `Clinic_Analyzer/configs/Test_6_search`、`results/Test_6_search/`、`results_display/Test_6_search/` |
