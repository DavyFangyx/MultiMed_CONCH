# E2 字段子集选择算法：实现规格

本文档是实现依据。若本文档与仓库现状冲突，以本文档明确写出的兼容规则为准；不要另建数据划分、编码流程或 Clinic Analyzer。

## 1. 目标与范围

E2 比较字段子集搜索方法在相同评估协议和逻辑预算下的表现，并实现 SEAS。

主实验范围：

| 项目 | 固定值 |
|---|---|
| 队列 | `datasets.json` 注册的 33 个 TCGA 队列，包含别名 `TCGA_LIHC`；排除 MMRF、CPTAC |
| 编码 | `prompt` |
| landmark | `landmark_0`、`landmark_365`、`landmark_730`、`landmark_none` |
| 搜索目标模型 | `mlp_clinic_flatten`（多个功能还是保留，但是我在这个实验中就只用这一个评测model |
| split | `Clinic_Analyzer/data/splits/5foldcv/{study}/splits_0.csv` 至 `splits_4.csv` |
| folds | 5 |
| 最小实际差异 | `DELTA = 0.005` |
| 停止耐心 | `PATIENCE = 3` |
| 默认 seed | `0` |

不在 E2 主实验范围内：

- 不生成或修改患者 split。
- 不重新实现 Field Bank、prompt 编码或 Clinic Analyzer。
- 不使用 `onehot`、`survpgc_f` 或不存在的 `hgcn` 作为主实验模型。
- 不把结果称为独立测试集性能。
- 不实现 1-SE 和 best 两种额外停点。
- 不对 c-index 子集函数声明单调性、次模性、curvature 或贪婪理论保证。

## 2. 仓库事实与复用边界

必须复用以下现有组件：

- `src/greedy/splits.py`：读取现有 5 折 CSV。
- `src/greedy/clinic_evaluator.py`：物化子集并调用 Clinic Analyzer。
- `src/greedy/embeddings.py`：按字段索引切分患者 Field Bank embedding。
- `src/greedy/clinic.py`：读取每折 c-index 和复用已有训练结果。
- `results/univariate/prompt/{landmark_tag}/{dataset}/field_cindex.csv`：单字段结果。

现有 split 的 `val` 和 `test` 是同一批患者。E2 直接使用这 5 折搜索，因此统一术语如下：

- `cv_c_mean`：5 个 fold 验证 c-index 的均值。
- `cv_folds`：长度为 5 的 fold c-index。
- 禁止在 E2 schema、表格和图中使用 `test_c` 或“held-out test”字样。
- Clinic Analyzer 调用使用 `prefer_val=True`。

现有单字段结果覆盖四个目标 landmark。每次读取前必须校验：

- `run_config.json` 中 encoding 为 `prompt`。
- modality 为 `mlp_clinic_flatten`。
- split 目录与当前队列一致。
- `field_cindex.csv` 的字段集合和当前 `field_index.json` 完全一致。
- seed 一致；现有无 seed 子目录的结果视为 seed 0。

## 3. 重复实验与 seed

CLI 保留参数名 `--seed`，同时支持单个整数和逗号分隔整数：

```bash
# 与当前行为相同，只运行一次
python -m selection.runner ... --seed 0

# 运行 5 次
python -m selection.runner ... --seed 0,1,2,3,4
```

规则：

1. 不传 `--seed` 等价于 `--seed 0`。
2. 单个整数只运行一次，不创建“重复实验”。
3. 多个整数按输入顺序去重后分别运行。
4. 小数、空项和非整数直接报错，不做隐式转换。
5. 同一个 seed 同时传给模型训练和随机搜索算法。
6. 每个 seed 是独立 run；缓存键和结果路径必须包含 seed。
7. seed 0 的现有单字段结果直接复用；其他 seed 缺少单字段结果时，只补跑该 seed 的单字段评估。

确定性算法也按多个 seed 重复，因为 MLP 训练受 seed 影响。

## 4. 统一评估器

### 4.1 接口

新增通用选择模块 `src/selection/`，但评估器只能适配现有 `ClinicSubsetEvaluator`，不得复制数据读取和模型训练代码。

```python
@dataclass(frozen=True)
class EvalResult:
    subset: tuple[str, ...]
    subset_idx: tuple[int, ...]
    k: int
    cv_c_mean: float | None
    cv_folds: tuple[float, ...]  # 成功时固定长度 5
    logical_eval_idx: int
    physical_cache_hit: bool
    wall_ms: int
    status: Literal["ok", "error"]
    error: str | None

class BudgetExhausted(RuntimeError):
    pass

class Evaluator:
    def evaluate(self, subset: frozenset[str]) -> EvalResult:
        ...

@dataclass(frozen=True)
class SearchResult:
    algorithm: str
    seed: int
    best_subset: tuple[str, ...]
    best_cv_c_mean: float
    recommended_subset: tuple[str, ...]
    stop_reason: str
    logical_evals: int
    physical_trains: int
    proposal_count: int
```

`evaluate()` 必须满足：

- 子集按当前 `field_index.json` 转成稳定索引。
- 空集不训练，固定返回 `cv_c_mean=0.5`、`cv_folds=[0.5]*5`，且不消耗预算。
- 成功的非空子集必须返回恰好 5 个有限数；缺 fold、NaN 或训练失败返回 `status="error"`，不参与最优候选竞争。
- 相同配置和字段集合的结果与输入字段顺序无关。
- 候选并行可以改变完成顺序，但不能改变逻辑评估序号、选择结果和 JSONL 顺序。

### 4.2 内层产物

当前 Clinic Analyzer 会为每个子集保存 checkpoint 和 pickle，不能直接用于大规模搜索。为 E2 增加 `summary_only` 模式：

- 搜索阶段只保留每折 c-index、训练配置、运行日志和必要的失败信息。
- 不保留 checkpoint、逐患者 pickle 和重复的 split CSV。
- 各算法最终推荐子集可再以完整模式训练并保存模型产物。
- 不得删除已有结果；清理由 E2 新任务产生的临时文件时，只操作本 run 的明确目录。

## 5. 缓存、预算与记录

### 5.1 逻辑预算

一个逻辑评估等于当前算法 run 首次请求一个非空字段集合。一次逻辑评估内部已经包含 5 个 fold，因此预算不再额外乘 5。

```python
B = p * (p + 1) // 2
```

其中 `p` 是当前 `(dataset, landmark)` 的 Field Bank 字段数。

规则：

- A1 至 A6 和 SEAS 使用同一个 B。
- 全局物理缓存命中仍消耗当前 run 的一个逻辑预算，避免算法运行顺序改变可搜索范围。
- 同一 run 内的重复提议不重新评估、不增加逻辑评估数，但增加 `proposal_count`；Searcher 必须剔除已提议子集，不能依靠重复提议无限运行。
- A6 和 SEAS 使用单字段先验，run 开始时预扣 p 个逻辑评估；其可继续搜索预算为 `B-p`。
- A0、A0b、A0c 和 ANCHOR 不参加 A1 至 A6 的预算竞争。
- 预算只能由 Evaluator 计数。耗尽时抛出 `BudgetExhausted`，Searcher 返回当前合法状态。

### 5.2 物理缓存

使用 SQLite WAL 缓存，并提供进程级写锁。缓存键必须覆盖：

```text
dataset
landmark_tag
encoding
modality
seed
sorted field names
field_index.json content hash
five split CSV content hashes
effective Clinic Analyzer training args hash
code/cache schema version
```

字段索引不能单独作为缓存身份。配置指纹不同必须 cache miss。

### 5.3 JSONL

每个候选完成后写一行，字段固定为：

```json
{
  "run_id": "...",
  "dataset": "TCGA-BRCA",
  "landmark_tag": "landmark_365",
  "encoding": "prompt",
  "modality": "mlp_clinic_flatten",
  "algo": "A2_greedy",
  "seed": 0,
  "proposal_idx": 42,
  "logical_eval_idx": 37,
  "subset": ["field.a", "field.b"],
  "k": 2,
  "cv_c_mean": 0.681,
  "cv_folds": [0.67, 0.69, 0.68, 0.70, 0.675],
  "physical_cache_hit": false,
  "wall_ms": 1234,
  "status": "ok",
  "meta": {}
}
```

失败行使用 `status="error"` 和简短 `error` 字段。runner 是唯一 JSONL writer；worker 不直接写文件。

Anytime 曲线：

- 横轴为 `logical_eval_idx`。
- 纵轴为截至当前的最大 `cv_c_mean`。
- 全局缓存命中仍推进横轴。
- 算法因 sig_stop、字段空间耗尽或候选池耗尽而在 B 前正常结束时，画图和预算终点比较将其最后最佳值水平延伸至 B，但不得伪造 JSONL 评估记录。
- 不绘制 test 曲线。

## 6. 三个参考方法

参考方法不参加预算竞争。A0 和 A0b 使用统一 MLP Evaluator；A0c 使用自己的 Lasso-Cox，但必须使用相同字段库、患者 folds 和 seed。

### A0 全字段

评估完整 Field Bank 一次，报告 `cv_c_mean` 和 5 个 fold 值。

### A0b 单变量 top-k

1. 读取当前 dataset、landmark、seed 的 `field_cindex.csv`。
2. 按 `c_index_mean` 降序、`field_idx` 升序打破平局。
3. k 网格定义为：

```python
K_GRID = sorted(set(min(k, p) for k in [1, 3, 5, 8, 12, 20, p]))
```

4. 对每个 k 的累计 top-k 子集调用统一 Evaluator。
5. 报告完整 k 路径；参考水平线取其中 `cv_c_mean` 最大者，平局取更小 k。

单字段表只用于排序，不能把单字段 c-index 求和或平均当作 top-k 子集性能。

### A0c Lasso-Cox 路径

Lasso-Cox 是预测参考，不通过子集 Evaluator 二次选择：

- 输入是每个字段对应的 512 维 prompt embedding，按字段形成特征块。
- 每个 fold 只在该 fold 的 train 患者上完成标准化、lambda 路径拟合和所有参数估计。
- lambda 为从 `lambda_max` 到 `0.001 * lambda_max` 的 100 点对数网格。
- 每个 lambda 直接在该 fold 的 val 患者上计算 c-index，然后跨 5 折取均值。
- 最优 lambda 按均值最大选择，平局取更强正则。
- 字段被选中定义为该字段 512 维系数块中至少一个系数非零；只报告每折字段数和字段选择频率，不先合并稳定子集再用同一 folds 重评。

主图仅画最优 lambda 的水平线；完整 lambda 路径写入表格。

## 7. 六个预算基线

所有 Searcher 实现统一接口：

```python
class Searcher(ABC):
    name: str
    is_stochastic: bool
    uses_univariate_prior: bool

    @abstractmethod
    def run(self, evaluator, bank: tuple[str, ...], rng) -> SearchResult:
        ...
```

### A1 随机搜索

- 先采样 `k ~ Uniform{1,...,p}`，再均匀无放回采样 k 个字段。
- 剔除已提议子集，直到预算耗尽。
- 禁止直接均匀采样二进制向量。

### A2 前向贪婪

- 从空集开始；E2 不使用 `init_field`。
- 每一步评估 `S union {f}` 的全部未选字段。
- 选择 `cv_c_mean` 最大候选；平局按字段名升序。
- 每一步完成后执行第 9 节的在线 `sig_stop`。
- 触发停止、字段耗尽或预算耗尽后返回。
- 当前步全部候选均写 JSONL，不能只记录胜出者。

### A3 Beam search

- beam width `W=8`。
- 第 k 层扩展 beam 中全部状态的一字段邻域，先按字段集合去重，再评估。
- 按 `cv_c_mean` 降序、字段名字典序保留 top-W。
- 字段耗尽或预算耗尽后返回最佳已评估子集。

### A4 模拟退火

- 初态按 size-uniform 随机采样。
- 邻域：概率 0.8 做 1-flip，概率 0.2 做 swap；无合法 swap 时退化为 1-flip。
- 前 50 个有效移动的 `abs(delta)` 中位数除以 `ln(2)` 作为初温；若中位数为 0，初温取 `1e-3`。
- 每个逻辑评估后温度乘 `0.995`。
- 连续 200 个逻辑评估无改进时，从历史最佳做最多 3 个合法 flip 后重启。
- 跑至预算耗尽。

### A5 遗传算法

- population size `20`，二进制编码，size-uniform 初始化。
- tournament size `3`，uniform crossover `p_c=0.8`。
- 每位 mutation `p_m=1/p`，保留 2 个 elite。
- 空集 fitness 固定为 0.5，不消耗预算。
- 每代候选去重；候选池耗尽时正常结束。

### A6 蚁群

- 10 只蚂蚁，字段信息素初值 1，范围 `[0.01, 10]`。
- 启发式来自当前 seed 的单字段 c-index：`max(c_i-0.5, 0)` 后 min-max 归一化；全相等时全部设为 1。
- 每只蚂蚁先 size-uniform 采 k，再按 `tau_i^1 * eta_i^2` 无放回采字段。
- 每轮蒸发率 `rho=0.1`，仅轮内最优解沉积 `max(cv_c_mean-0.5, 0)`。
- 概率总和为 0 时退化为均匀采样。
- 跑至预算耗尽。

## 8. SEAS

SEAS 与 A1 至 A6 使用相同逻辑预算；预扣 p 个单字段评估。

### 8.1 字段语义表示

- 对每个字段构造固定文本：字段路径 + GDC 字段描述 + Field Bank 模板。
- 使用项目现有 CONCH text encoder 编码一次，得到字段级向量 `E`。
- 不使用患者标签、c-index 或验证集统计构造 E。
- `Sim` 为余弦相似度，对角置 0。
- 文档和代码中不得称其为“SurvPGC 字段编码器”。

### 8.2 代理模型

子集表示为 `z in {0,1}^p`：

```text
y_hat(z) = w0 + sum(w_i*z_i) + sum(v_ij*z_i*z_j for (i,j) in P) + b*|z|
```

- 每个字段取语义相似度 top-3 邻居，去重得到交互集合 P。
- `w_i ~ Normal(c_i-0.5, 0.05^2)`。
- `v_ij ~ Normal(-0.01*Sim_ij, 0.02^2)`。
- `b ~ Normal(0, 0.01^2)`。
- 初始观测噪声为 `DELTA/2`，每 20 个新观测按残差重估，下限 `1e-6`。
- 使用带 jitter 的 Cholesky 求解，不显式求矩阵逆。

### 8.3 初始化与采集

- 初始观测为 p 个缓存中的单字段结果，加 20 个去重的 size-uniform 随机子集。
- 采集函数为 Expected Improvement，batch size `q=8`。
- batch 内使用 fantasy mean；最后不足 8 个预算时只提交剩余数量。
- 每轮候选池合并：当前最佳 5 个子集的全部 1-flip、200 个 size-uniform 随机子集、当前最佳的 100 个合法 2-swap。
- 无合法 2-swap 时跳过该来源。
- 剔除空集、已提议子集和重复子集。

必须实现三个消融，除指定差异外共享全部设置和 seed：

| 名称 | 唯一改动 |
|---|---|
| `SEAS-no-sem` | 先验均值置 0，并删除语义交互项 |
| `SEAS-no-int` | 保留单字段先验，删除交互项 |
| `SEAS-no-ei` | 用后验均值替代 EI 排序 |

## 9. 唯一停止规则：sig_stop

`sig_stop` 只用于 A2 前向贪婪，并且在线执行。其他算法以预算停止，推荐最佳已评估子集。

对贪婪路径的字段数 k，定义：

- `m(k)`：第 k 个贪婪前缀的 `cv_c_mean`。
- `v(k)`：对应的 5 个 fold c-index。
- `k_star`：进入第 k 步前，历史 `m` 最大的字段数；空集 `k=0`、`m(0)=0.5`、`v(0)=[0.5]*5`。
- `gain(k) = m(k) - m(k_star)`。
- `p(k)`：对 `v(k)-v(k_star)` 做单侧 paired Wilcoxon，alternative 为 `greater`。差值全为 0 时 p=1。

当前步为无有意义改进，当且仅当：

```text
gain(k) < 0.005 and p(k) >= 0.05
```

状态更新顺序固定：

1. 用进入当前步前的 `k_star` 计算 gain 和 p。
2. 若 `gain(k) >= 0.005 and p(k) < 0.05`，令 `k_star=k` 并把连续计数清零。
3. 若同时满足无有意义改进条件，连续计数加一。
4. 其余混合情况清零，但不更新 `k_star`。
5. 连续计数达到 3 时立即停止，`k_sig = k - 3`，推荐该前缀；允许 `k_sig=0`。
6. 若从未触发，推荐搜索结束时的 `k_star`。

Wilcoxon 失败或返回 NaN 时将 p 记为 1，并在记录中写 `wilcoxon_fallback=true`。`p>=0.05` 仅用于停止启发式，不表述为统计等效。

## 10. ANCHOR 精确枚举

ANCHOR 只在 seed 0 上运行，并只证明截断字段空间内的精确最优。

1. 在 BRCA、LGG、CHOL 各评估 20 个未缓存随机子集，测量真实五折 `mlp_clinic_flatten` 的单子集中位耗时 `t_med`。
2. 总墙钟预算 `H=30h`，worker 数为实际配置 W。
3. 对指定实例集合，选择满足下式的最大 `p_anchor`，候选范围为 8 至 15：

```text
n_instances * (2^p_anchor - 1) * t_med / W <= H
```

4. 每个实例按 seed 0 单字段 c-index 取前 `min(p_anchor,p)` 个字段并枚举全部非空子集。
5. 若 33 队列 x 4 landmarks 下不存在可行 p，按患者数排序并三等分；每等分取首、中、末 3 个队列，共 9 个锚点队列，再重算 p。
6. 若 9 队列 x 4 landmarks 仍不可行，只保留 `landmark_0` 和 `landmark_365`，再重算 p。
7. 若最后仍不存在 `p_anchor>=8`，停止 ANCHOR 并明确报告计时结果，不伪称获得最优解。

输出全局最佳受限子集，以及每个算法在相同受限字段空间、相同 seed 0 下的：

```text
optimality_gap = anchor_best_cv_c - algorithm_best_cv_c
```

不计算 curvature 和理论近似保证。

## 11. 汇总与统计

### 11.1 seed 级结果

每个 `(dataset, landmark, algorithm, seed)` 输出：

- 最佳或 sig_stop 推荐子集。
- 推荐子集字段数。
- `cv_c_mean` 和 5 个 fold 值。
- logical eval、physical train、cache hit、proposal 和失败数量。
- wall time 和停止原因。

### 11.2 跨 seed 结果

- 对每个 seed 先取 5 folds 的均值，再对 seeds 报告均值和标准差。
- 只有一个 seed 时标准差写 NaN，不伪造为 0。
- 算法配对比较以共同 seed 的 fold 均值为样本；不把 `5 seeds x 5 folds` 当作 25 个独立样本。
- seed 数小于 2 时只报告差值，不做 Wilcoxon。

H1：A2 的 sig_stop 子集相对 A0 全字段，在至少 2/3 实例上平均差值不低于 0.005。显著性结果单独报告，不作为“独立测试集提升”。

H2：先在全部实例上按平均 rank 选出 A1 至 A6 中唯一的全局最强基线，再计算 SEAS 在各实例预算终点对该基线的胜率；目标胜率不低于 60%。锚点实例另报 seed 0 的 optimality gap。

### 11.3 图表

- 主表：A0/A0b/A0c、A1-A6、SEAS 和三个消融的 seed 聚合性能、字段数、逻辑预算、物理训练数、缓存率和失败率。
- 主图 1：anytime CV 曲线；A0、A0b 最优 k、A0c 最优 lambda 为水平参考线。
- 主图 2：锚点实例的 optimality gap。
- 主图 3：四个 landmark 的同算法对照。
- A2 图中标记唯一的 `k_sig`；不标记 best 或 1-SE 停点。

## 12. 模块与实现顺序

新增代码放在 `src/selection/`，入口脚本为 `scripts/run_e2_selection.py`。不得创建第二套数据预处理或 Clinic Analyzer。

```text
src/selection/
  config.py          # 本文常量、队列和 landmark
  types.py           # EvalResult、SearchResult、BudgetExhausted
  evaluator.py       # 现有 ClinicSubsetEvaluator 的统一适配和预算
  cache.py           # SQLite 物理缓存和配置指纹
  stopping.py        # 仅 sig_stop
  references.py      # A0、A0b、A0c
  search/
    base.py
    random_search.py
    greedy.py
    beam.py
    anneal.py
    genetic.py
    aco.py
    seas.py
    exhaustive.py
  runner.py          # 单实例、seed 展开、JSONL 单写者
  report.py          # 聚合、统计和绘图
```

实现顺序：

1. `types/config/cache/evaluator` 和 summary-only 评估。
2. A0、A0b、A1、A2、预算和 sig_stop。
3. A3-A6 与 A0c。
4. SEAS 和三个消融。
5. 计时探针、ANCHOR、汇总和绘图。

多个 Codex 并行时，先由一个任务固定 `types.py`、缓存 schema 和 JSONL schema；其他任务只依赖这些接口，不得各自定义变体。

## 13. CLI 与输出目录

示例：

```bash
python scripts/run_e2_selection.py \
  --dataset TCGA-BRCA \
  --landmark_time 365 \
  --algo A2_greedy \
  --seed 0,1,2,3,4 \
  --workers 8
```

默认输出：

```text
results/E2_selection/prompt/{landmark_tag}/{dataset}/{algorithm}/
  seed_{seed}/
    evaluations.jsonl
    result.json
    run_config.json
  aggregate.csv
  aggregate.json

results_display/E2_selection/prompt/
  main_table.csv
  anytime/
  anchor_gap/
  landmark/
```

单字段补跑仍写现有 `results/univariate/...` 体系，并增加 seed 子目录；不得覆盖 seed 0 的已有文件。

## 14. 验收标准

- 33 个 TCGA 队列均只读取现有 5 折 split，且运行元数据明确记录 `val_equals_test=true`。
- 不传 seed、单 seed、多个整数 seed 均符合第 3 节；非法小数会失败。
- 同一子集在串行和并行下得到相同选择结果与有序 JSONL。
- 全局缓存命中不增加物理训练，但仍消耗当前算法逻辑预算。
- A0b 对 `p<20` 不产生重复 k，且所有 top-k 子集经过统一评估。
- A2 每步记录全部候选，并严格按第 9 节在线停止。
- 任何 E2 输出均不包含伪独立的 `test_c` 或 test anytime 曲线。
- 多 seed 汇总不把 folds 和 seeds 当作 25 个独立样本。
- 内层批量搜索不保存 checkpoint 和逐患者 pickle；最终推荐子集可以完整复评。
- ANCHOR 只报告受限字段空间的 seed 0 精确最优，且通过实际计时公式决定是否运行。
- 原有 greedy、univariate CLI 的单 seed 用法和既有结果不被破坏。
