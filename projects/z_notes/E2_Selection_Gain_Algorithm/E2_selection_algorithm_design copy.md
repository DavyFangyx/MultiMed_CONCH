# E2 选择算法对比实验设计文档
---

## 0. 全局常量（唯一定义处：`config.py`）

任何数字在别处出现都视为bug。

| 常量 | 值 | 说明 |
|---|---|---|
| `COHORTS` | 33个TCGA队列 | 完整列表写死在config |
| `LANDMARKS` | `[0, 30, 90, 365]` | 4档时点。`None`作为第5档对照单列，不计入这4档 |
| `ENCODING_E2` | `"survpgc"` | E2全程锁定单一编码，编码轴的比较归E6 |
| `INNER_MODEL` | `"cox_clinical"` | 选择过程用的廉价模型，仅临床模态 |
| `OUTER_MODELS` | `["survpgc", "hgcn"]` | 昂贵的多模态模型，只评最终推荐子集 |
| `K_FOLD` | 5 | 分层依据为event指示变量 |
| `TEST_FRAC` | 0.20 | 每个队列一次性切出，`SPLIT_SEED=2026`，永不参与选择 |
| `REPEATS` | 5 | repeat编号r，固定`fold_seed=r`且`algo_seed=r` |
| `BUDGET_FORMULA` | `B = 5 * p * (p+1) // 2` | p为该实例field bank大小，即5倍贪婪全路径开销 |
| `BANK_MISS_MAX` | 0.40 | 缺失率超此值的字段不进field bank |
| `ALPHA` | 0.05 | Wilcoxon显著性水平 |
| `PATIENCE` | 3 | sig_stop的连续不显著步数 |

`LANDMARKS`若与实际口径不符，只改这一行，其余代码不含任何时点字面量。

---

## 1. 实验要证明什么（可证伪陈述）

**H1（选择有效）**：存在字段子集，其性能显著高于全字段。
判据：在至少2/3的`(cohort, T)`实例上，贪婪1-SE停点的test c-index减去全字段test c-index，既大于等于该实例的δ\*，又通过折级配对Wilcoxon检验（p<0.05）。

**H2（方法有差异）**：在同一预算B下，不同搜索算法的anytime曲线存在有意义差异。
判据：同上口径下，SEAS对"最强基线"的胜率大于等于60%，且在锚点实例上SEAS的optimality gap显著小于贪婪。

**H2的证伪预案**（已定，不是备选）：若第一步随机搜索与Lasso-Cox和贪婪之间无显著差异，则E2/E3的论断整体改写为"选择方法本身不重要，时点约束才重要"，本文档第4节的A4至A7与第5节的SEAS全部降级为附录横评，工程时间转入E4。这一预案写进论文提纲，不等实验结果再临时决定。

---

## 2. 统一评估协议

这一节是全文可比性的地基，所有算法只允许通过这里的接口触碰数据。

### 2.1 评估单元

一次评估 = 一个子集S在一个实例上的完整5折交叉验证。

```python
# evaluator.py
class Evaluator:
    def __init__(self, cohort, T, enc, inner_model, fold_seed, budget, record_path): ...
    def evaluate(self, S: frozenset[str]) -> EvalResult: ...
    # 预算耗尽时抛 BudgetExhausted
```

`EvalResult`字段：`val_c`（5折验证集c-index均值）、`val_folds`（长度5的列表，配对检验与SE的唯一来源）、`test_c`、`k`、`cache_hit`。

`test_c`的算法：在80%训练全量上用S重训一次，在固定held-out test上评。test集在任何搜索决策中都不可见，只在记录里写下来供事后画图。

### 2.2 缓存

key = `sha1(f"{cohort}|{T}|{enc}|{inner_model}|{fold_seed}|{','.join(sorted(S))}")`

缓存跨算法、跨进程共享，落在单个sqlite文件里，写入加锁。这意味着后跑的算法可以免费复用先跑算法的评估结果，这正是设计意图。

### 2.3 预算计数规则（消歧关键）

1. 预算按**唯一评估次数**计，即cache miss数。cache hit不消耗预算。
2. 理由：缓存是共享基础设施，重复提议不产生真实算力开销。
3. 但每个算法必须额外报告**重复提议率**（`proposals / unique_evals - 1`），作为诊断指标进主表。GA与ACO这类重复率高的算法不会因缓存而被不当奖励，重复率本身就是它们的缺陷证据。
4. **单字段先验预扣**：单变量c-index表在实验开始时统一算一次（p次评估）。任何使用该表的算法（ACO的η、SEAS的先验μ、单变量top-k参考线）在其预算里预扣p次，即实际可用搜索预算为`B - p`。贪婪与随机搜索不使用该表，预算为完整B。这条规则消除"谁白嫖了先验"的争议。
5. 预算耗尽由Evaluator抛异常，算法内部**不允许**自己数预算。所有Searcher的`run()`必须能被异常中断且中断后状态合法。

### 2.4 重复与随机性

所有算法统一跑5个repeat，repeat r使用`fold_seed=r`且`algo_seed=r`。确定性算法（贪婪、beam、枚举、Lasso路径）在不同repeat间因fold划分不同而产生差异，因此和随机算法拥有同分布的误差条，可直接比较。报告均值与标准差。

### 2.5 记录格式（jsonl，每次唯一评估一行）

```json
{"run_id": "...", "cohort": "BRCA", "T": 90, "enc": "survpgc",
 "inner_model": "cox_clinical", "algo": "greedy", "repeat": 3,
 "eval_idx": 47, "wall_ms": 82, "subset": ["age","stage_t","..."],
 "k": 7, "val_c": 0.6841, "val_folds": [0.67,0.69,0.68,0.70,0.68],
 "test_c": 0.6712, "cache_hit": false, "meta": {}}
```

绘图代码只读这个文件，不依赖任何算法内部结构。`meta`供算法写自有诊断量（如SA的当前温度、GA的代数），但绘图不得读取`meta`。

### 2.6 Anytime曲线定义（防作弊）

横轴：已消耗唯一评估数。
纵轴两条线：
- **val线**：截至当前的`max(val_c)`。
- **test线**：**val线当前最优子集所对应的test\_c**。

test线绝不是test上的历史最大值。这一条必须在绘图代码里以断言形式固化。

---

## 3. "有意义的差异"δ\*与统计口径

### 3.1 δ\*的测定（预实验，一次性）

对每个`(cohort, T)`实例：

1. 随机抽30个子集（size-uniform采样，见4.2）。
2. 每个子集在5个不同`fold_seed`下各评一次，得到5个`val_c`。
3. 取这30个子集各自的标准差，求中位数σ̃。
4. **δ\*(cohort, T) = max(0.005, 2σ̃)**。

结果写入`config/delta_star.json`，全文所有比较统一引用，不允许任何脚本另设阈值。

### 3.2 显著性判据

称A优于B，当且仅当同时满足：
1. `mean(val_c_A) - mean(val_c_B) >= δ*`
2. 折级配对Wilcoxon signed-rank检验p<0.05，配对样本为25对（5 repeat × 5 fold）

两个条件缺一不可。只满足其一的一律写成"无有意义差异"。

### 3.3 Optimality gap与curvature（仅锚点实例）

```
gap(alg, B) = f(S*_exhaustive) - f(S_alg_at_B)
```

Conforti-Cornuéjols总曲率，直接从枚举结果算，不额外评估：

```
c = 1 - min_j [ f(V) - f(V \ {j}) ] / [ f({j}) - f(∅) ],   f(∅) := 0.5
```

贪婪的理论保证由1−1/e退化为(1/c)(1−e^{−c})。把这个数报出来，"贪婪为什么不够"就成为可核对的量。

---

## 4. 基线算法规格

所有类继承`search/base.py`的`Searcher`，只实现`run(self, ev, bank, budget, rng)`。

### 4.0 参考线（不参与预算竞争，画成水平虚线）

| 编号 | 名称 | 成本 | 说明 |
|---|---|---|---|
| A0 | 全字段 | 1次评估 | E2的落点对照 |
| A0b | 单变量top-k | k网格`[1,3,5,8,12,20,p]`共7次 | 复用已预扣的单字段表排序 |
A0c Lasso-Cox路径
1. λ网格：`λ_max`到`0.001·λ_max`的对数网格，100点，`λ_max`由标准coxnet规则算出。
2. **变量选择必须在每折训练集内独立进行**，不得先用全量选变量再做CV，那是选择性泄露。
3. 对每个λ，取"跨5折中出现频次大于等于3"的字段构成该λ的稳定子集。
4. 全部λ的稳定子集去重后（通常20到60个），逐个送入统一`score()`。预算消耗等于去重后的子集数。

### 4.1 A1 随机搜索（零假设地板，地板组）

采样方式固定为size-uniform：先`k ~ Uniform{1..p}`，再从bank中均匀取大小为k的子集。**禁止**直接对`{0,1}^p`均匀采样，那会把质量集中在`|S|≈p/2`附近，构成不公平的null。跑满B。

### 4.2 A2 前向贪婪（改造见第6节）

从空集起，每步遍历所有未选字段，评估`S ∪ {f}`，取`val_c`最大者加入。**跑满p步或预算耗尽为止**。全路径开销`p(p+1)/2`。若小于B，曲线在该点终止并向右画水平虚线延长至B。

每步必须把该步**全部候选**写入jsonl，不只是胜出者，否则anytime曲线缺点。

### 4.3 A3 Beam search

beam宽度`W=8`。第k层对beam中每个状态扩展所有未选字段，合并去重后按`val_c`保留top-W。跑满p层或预算耗尽。p=15时理论开销约900次，超过B=600，因此曲线会在B处被截断，这是anytime协议的正常行为，不是bug。

### 4.4 A4 模拟退火

- 初始状态：size-uniform随机采样一个子集
- 邻域：概率0.8做1-flip，概率0.2做swap（一进一出）
- 初温：用前50次邻域移动的`|Δval_c|`中位数除以`ln 2`，使初始接受率约0.5
- 降温：几何`α=0.995`，每次评估后降一次
- 重启：连续200次评估无改进则从当前最优做3-flip扰动重启
- 跑满B，5 seeds

### 4.5 A5 遗传算法

- 种群`N=20`，二进制编码，初始种群size-uniform采样
- 选择：锦标赛，size=3
- 交叉：均匀交叉，`p_c=0.8`
- 变异：逐位翻转，`p_m=1/p`
- 精英：保留2个
- 空集个体直接判为`val_c=0.5`且不消耗预算
- 跑到B耗尽，5 seeds

### 4.6 A6 蚁群

- 二进制ACO，信息素`τ_i`定义在字段上，蚂蚁数`m=10`
- 启发式`η_i` = 单字段c-index减0.5后做min-max归一化（来自预扣的单字段表）
- 选择概率`P_i ∝ τ_i^a · η_i^b`，`a=1, b=2`
- 每只蚂蚁先采`k ~ Uniform{1..p}`，再按上述概率不放回抽k个字段
- 蒸发`ρ=0.1`，仅迭代最优蚂蚁沉积`Δτ = (val_c - 0.5)`
- `τ`裁剪到`[0.01, 10]`
- 跑到B耗尽，5 seeds

### 4.7 ANCHOR 全枚举（锚点，非基线，提供最优解）

枚举`2^p - 1`个非空子集，用`INNER_MODEL`评估。产出全局最优、optimality gap基准、curvature。p由第7节的计时探针确定。

---

## 5. 自研方法 SEAS

**S**urrogate-guided, **E**mbedding-**A**nchored **S**ubset search。

设计动机是攻击真实瓶颈：每次评估都很贵。把笔记里给出的两条方向（语义相似度引导、子集空间代理模型）合成一个方法，而不是留成二选一，因为语义相似度恰好解决了代理模型最难的部分，即交互项的稀疏结构从哪来。

### 5.1 表示

子集表示为`z ∈ {0,1}^p`。字段语义嵌入`E ∈ R^{p×d}`直接复用已复现的SurvPGC编码器对字段名与取值描述的编码，不新增训练。相似度`Sim = cosine(E)`，对角置0。

### 5.2 代理模型

```
ŷ(z) = w₀ + Σᵢ wᵢ zᵢ + Σ_{(i,j)∈P} v_ij zᵢ zⱼ + b·|z|
```

交互项集合P的构造：对每个字段i取`Sim[i]`的top-3邻居，全部字段的邻居对去重，`|P| ≤ 3p`。

贝叶斯线性回归，共轭高斯先验，闭式后验：

- `wᵢ ~ N(μᵢ, σ_w²)`，`μᵢ = (单字段c-index_i - 0.5)`，`σ_w = 0.05`。这是"单字段c-index作为先验"的落点。
- `v_ij ~ N(-λ_red · Sim_ij, σ_v²)`，`λ_red = 0.01`，`σ_v = 0.02`。负均值编码冗余惩罚：语义越近的字段对，同时入选的边际收益越可能被压低。
- `b ~ N(0, 0.01²)`，吸收子集规模的整体趋势。
- 观测噪声`σ_n`用δ\*/2初始化，每20次评估用残差重估一次。

参数维度约`4p+2`，p=40时162维，闭式求逆开销微秒级，代理本身不构成瓶颈。

### 5.3 采集与候选池

采集函数为期望改进EI，基于后验预测均值与方差。

批量`q=8`，用fantasy策略：选出EI最大者后，将其后验预测均值当作已观测值更新后验，再选下一个，重复q次。这样一批候选内部不会全部挤在同一个峰上。

每轮候选池 = 以下三者合并去重并剔除已评估子集：
1. 当前val最优的5个子集的**全部1-flip邻域**
2. 200个size-uniform随机子集
3. 当前最优子集的100个随机2-swap邻域

### 5.4 冷启动

初始设计 = p个单字段子集（已在预扣预算内，从缓存直接读取，不重复计费）+ 20个size-uniform随机子集。冷启动完成后进入EI循环，直到预算耗尽。

### 5.5 消融（E2的必需项，不是可选项）

| 变体 | 改动 | 要回答的问题 |
|---|---|---|
| SEAS−sem | 去掉嵌入先验与交互项，退化为一阶贝叶斯线性+EI | 语义信息是否真的有用 |
| SEAS−int | 保留嵌入先验μ，去掉交互项P | 交互建模是否有用 |
| SEAS−ei | 用后验均值贪婪替代EI | 不确定性建模是否有用 |

三个消融与SEAS共享全部其他设置与同样的B。没有这三条，SEAS就只是横评里的第八个算法。

---

## 6. 停止准则改造（贪婪现状与修改方案）

### 6.1 现状的三个问题

当前实现在`best_gain < min_delta`时直接break。

1. 路径被提前截断，anytime曲线缺右半段，1-SE停点无从计算，因为1-SE需要看到峰值之后的下降。
2. `min_delta=0.01`是绝对值硬编码，与该实例的折间噪声无关。在σ̃大的小队列上过松，在σ̃小的大队列上过紧。
3. break条件与patience、Wilcoxon规则的职责重叠，形成两套并行的停止逻辑。

### 6.2 改造原则：搜索与停止解耦

搜索始终跑满p步或预算B，产出**完整路径**。停止准则在完整路径上**事后**选点，不干预搜索。这条原则同样适用于beam、SEAS等所有能定义"路径"的算法（对无自然路径的SA/GA/ACO，路径定义为anytime最优序列）。

### 6.3 三个停点的精确定义

设路径上第k步的验证性能为`m(k)`，折级值为`v(k) ∈ R^25`（5 repeat × 5 fold）。

- **best**：`k_best = argmax_k m(k)`
- **1-SE parsimonious**：`k_1se = min{ k : m(k) >= m(k_best) - SE(k_best) }`，其中`SE = std(v(k_best)) / 5`（25个样本的标准误）
- **sig_stop**：从k=1起递增，记录截至k的最优`m*`。若连续`PATIENCE=3`步同时满足「`m(k) - m* < δ*`」和「`v(k)`对`v(k*)`的配对Wilcoxon检验p≥0.05」，则`k_sig = k - PATIENCE`

三个停点必须在anytime曲线上以垂直标记画出，这是把停止准则当作方法贡献而非工程细节来论述的可视化落点。

### 6.4 代码级修改清单（greedy.py）

1. 删除`if best_gain < min_delta: break`。
2. `min_delta`参数保留但语义变更为δ\*，仅由`stopping.sig_stop()`读取，默认值来自`config/delta_star.json`，不再硬编码。CLI参数名建议改为`--delta_star`并对旧名`--min_delta`保留告警式别名，避免旧脚本静默使用错误语义。
3. `patience`从"辅助确定推荐字段数"提升为`sig_stop`的显式参数。
4. 每步写入**全部候选**的评估记录，不只是胜出者。
5. 移除内部预算计数，改为捕获`BudgetExhausted`后返回已完成路径。
6. `--init_field`保留，其初始评估同样计入预算。
7. 每步内的并行候选评估保留（步间必须串行），预算计数在Evaluator内加锁，与并行度无关。
8. 新增`--record_path`，格式严格按2.5节。

---

## 7. 锚点预算核算与降级阶梯

33队列 × 4时点 × `2^15` = 约433万次评估，这个量级必须先测再定，且降级路径预先写死。

### 7.1 计时探针

在BRCA（大）、LGG（中）、CHOL（小）各随机评200个子集，取单worker下的**中位**耗时t̄（秒）。

### 7.2 p的确定公式

```
p* = max{ p ∈ [12, 15] : 33 × 4 × 2^p × t̄ / W <= H }
```

`W`为并行worker数，`H = 30`小时。p*即枚举所用的field bank截断长度（按单字段c-index降序取前p\*个）。

### 7.3 降级阶梯（按序触发，不留裁量）

1. 若p\*存在，按p\*执行全33队列全4时点枚举。
2. 若p=12仍超H，改为**锚点队列子集**：按样本量三分位，每档取3个队列共9个，在这9个队列 × 4时点上做p=15枚举；其余24个队列只跑B预算的搜索基线，不做枚举。论文中的optimality gap与curvature只在锚点队列上报告，并明确说明覆盖范围。
3. 若9队列 × 4时点仍超H，再降为9队列 × 2时点（`T ∈ {0, 365}`，取扫描的两端）。

### 7.4 内外层成本分离（可行性的关键）

枚举与所有搜索过程**只使用`INNER_MODEL`**（临床模态Cox），单次评估在0.05到0.5秒量级。

昂贵的`OUTER_MODELS`只评估各算法的最终推荐子集：
```
外层评估次数 = 算法数(10) × 停点数(3) × 实例数(33×4=132) × 外层模型数(2) = 7920
```
按单次150秒、16并行计约21小时，可接受。任何把外层模型放进搜索循环的实现都是错的。

---

## 8. 文件清单与接口

```
e2_selection/
  config.py              # 第0节全部常量，含 delta_star.json 的读取
  data.py                # load_cohort(), fixed_test_split(), apply_landmark_mask(T)
  encoders.py            # 5种编码统一接口，E2只用 survpgc
  evaluator.py           # Evaluator, EvalResult, BudgetExhausted, sqlite缓存
  stopping.py            # best(), one_se(), sig_stop()
  stats.py               # estimate_delta_star(), paired_wilcoxon(), curvature(), optimality_gap()
  search/
    base.py              # Searcher 抽象基类
    reference.py         # A0, A0b, A3
    greedy.py            # A1
    random_search.py     # A2
    beam.py              # A4
    anneal.py            # A5
    genetic.py           # A6
    aco.py               # A7
    exhaustive.py        # ANCHOR
    seas.py              # SEAS 及三个消融变体
  runner.py              # CLI：跑一个 (cohort, T, enc, algo, repeat) 单元
  plots.py               # anytime曲线、停点标注、gap条形图、E4落锤图
```

`base.py`的契约：

```python
class Searcher:
    name: str
    is_stochastic: bool
    uses_univariate_prior: bool   # True 则预算预扣 p 次
    def run(self, ev: Evaluator, bank: list[str], budget: int, rng) -> None:
        """只允许通过 ev.evaluate(S) 触碰数据。
        预算耗尽时 ev 抛 BudgetExhausted，由基类捕获，run 内不得捕获。"""
```

`runner.py`的CLI：

```
python -m e2_selection.runner \
  --cohort BRCA --landmark 90 --enc survpgc \
  --algo greedy --repeat 3 \
  --workers 16 --record_path runs/brca_T90_greedy_r3.jsonl
```

`--landmark none`表示无时点约束。所有实验单元互相独立，可任意并行调度。

---

## 9. 依赖关系与编码/运行顺序

代码可以一次性全部写完，运行必须按序。下表的"可并行编码"列指编码阶段的独立性。

| 阶段 | 模块 | 依赖 | 可并行编码 | 对应实验步骤 |
|---|---|---|---|---|
| 0 | config, data, encoders, evaluator, stats, stopping, plots骨架 | 无 | 是 | 预实验：测δ\*与计时探针 |
| 1 | greedy改造, random_search, reference | 阶段0 | 是 | 第一步：贪婪 vs 随机 vs Lasso |
| 2 | exhaustive | 阶段0 | 是 | 第二步：optimality gap与curvature |
| 3 | beam, anneal, genetic, aco | 阶段0 | 是 | 第三步：扩基线，anytime图已就位 |
| 4 | seas及消融 | 阶段0，且需阶段1的缓存做冷启动加速 | 是 | 第四步：接自研方法 |
| 5 | plots完整实现 | 阶段0的记录schema | 是 | 贯穿 |

运行顺序上的两条硬约束：

1. δ\*的预实验必须先于所有正式跑，否则stopping与stats无法工作。
2. 单字段c-index表必须先于ACO与SEAS生成，因为二者的先验依赖它。这一步归入阶段0的预实验。

阶段2的枚举可以与阶段3并行运行，二者共享缓存且互不阻塞。第四步的SEAS带mask参数扫`LANDMARKS`全部4档时，直接就是E4的数据，不需要另写脚本。

---

## 10. 主表与主图（论文里长什么样）

**主表**（每个`(cohort, T)`一行块）：算法名、B预算下val\_c均值±sd、对应test\_c、三停点的k、重复提议率、对全字段的Δ与Wilcoxon p值。

**主图1**：anytime曲线，横轴唯一评估数，纵轴val与test双线，10条算法线加2条参考水平线，锚点实例上再加一条全局最优水平线。三个停点以垂直标记标出。

**主图2**：optimality gap条形图，横轴算法，纵轴gap，按curvature分组的多个锚点实例并列。

**主图3（落锤图，属E4但绘图代码同源）**：同一批字段集在`T=none`与4档landmark下的性能对照。

---

## 11. 验收清单

- [ ] `delta_star.json`已生成，覆盖全部132个实例
- [ ] 计时探针跑完，p\*已确定并写入config
- [ ] Evaluator的预算计数在16并行下与串行结果完全一致（单测）
- [ ] anytime绘图代码含"test线取val最优对应值"的断言
- [ ] 贪婪跑满全路径，jsonl中每步候选数等于`p-k`
- [ ] 所有随机算法5个repeat齐全，缺一不进主表
- [ ] SEAS三个消融与主方法共享同一B与同一缓存
- [ ] 枚举结果中`f(∅)=0.5`的约定与curvature计算一致

---
