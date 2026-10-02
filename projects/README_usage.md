# Projects 使用

日常运行按本文步骤执行。目录和实现细节见 [README.md](README.md)，E2 口径见 [z_notes/E2_Selection_Gain_Algorithm/E2_selection_algorithm_design.md](z_notes/E2_Selection_Gain_Algorithm/E2_selection_algorithm_design.md)，人工方案通路见 [A_pipeline/README_usage.md](A_pipeline/README_usage.md)。

## 通用参数

- `--dataset`：`all`、单个名称或逗号列表；名称以 `datasets.json` 为准。
- `--landmark_time`：天数、`none`、逗号列表或 `all`。E2 使用 `0,365,730,none`。
- `--encoding`：`prompt`（CONCH）或 `onehot`；E2 固定使用 `prompt`。
- `--seed`：普通评估接收一个整数；E2 接收一个整数或逗号分隔列表。

## 1. 扫描、统计与筛选

```bash
conda activate conch

python scripts/run_scan_fields.py --dataset all
python scripts/run_field_stats.py --dataset all
python scripts/run_time_stats.py --dataset all
python scripts/run_event_stats.py --dataset all
python scripts/run_field_filter.py \
    --dataset all \
    --landmark_time all \
    --write_templates \
    --R3_coverage 0.30 \
    --R4_n_unique 2 \
    --R4_mode_share 0.95
```

筛选结果位于 `rawdata_stats/{dataset}/{landmark_tag}/`，模板位于 `templates/field_bank/{dataset}/{landmark_tag}/FIELD_BANK.csv`。

`run_time_stats.py` 的产物：患者级 `rawdata_stats/{dataset}/time_record/patient_time_stats.csv`，每行一名患者，`event` 列为 1（死亡事件）/ 0（删失）/ 空（vital_status 未知）。

`run_event_stats.py` 读取各数据集的 `patient_time_stats.csv`：

- 每个数据集写出患者级事件表 `rawdata_stats/{dataset}/event_stats.csv`（`event` 归一为 1 / 0 / 空，只保留事件相关核心列）；`--dataset` 控制写出范围；
- 汇总写出 `rawdata_stats/_shared/event_summary.csv`（每行一个数据集，含 `n_patients`、`n_event`、`n_censored`、`n_unknown`、`event_rate` 以及缺时间的 `n_event_no_time` / `n_censored_no_time`），并打印表格。

模板可按共享规则补全已有字段；默认保留非空的人工模板：

```bash
python scripts/fill_field_bank_templates.py
```

运行编码前检查每张 `FIELD_BANK.csv` 的 `example`、`convert`、`unit` 和 `template`。

## 2. 生成 Field Bank

```bash
conda activate conch

python scripts/run_field_bank.py \
    --dataset all \
    --encoding prompt \
    --landmark_time all
```

只生成 prompt CSV、不运行 CONCH 时加 `--prompts_only`。主要产物为：

```text
outputs/{dataset}/field_bank/prompt/{landmark_tag}/
  prompts.csv
  field_index.json
  embeddings/pt/{patient_id}.pt
```

L2/L3/L5 组成方案是独立实验，不是 E2 的前置步骤：

```bash
python scripts/run_schemes.py --dataset all --scheme all --landmark_time all
```

## 3. Test_1b 单字段 Cindex 先验

E2 的 `A6_aco`、`SEAS`、三个 SEAS 消融和 `ANCHOR` 需要同一 `(dataset, landmark, seed)` 的单字段结果。A1 至 A5 不需要这一步。

E2 只使用 33 个 TCGA 队列；通用的 `--dataset all` 还包含 MMRF 和 CPTAC，因此先定义队列列表：

```bash
E2_DATASETS=TCGA-ACC,TCGA-BLCA,TCGA-BRCA,TCGA-CESC,TCGA-CHOL,TCGA-COAD,TCGA-DLBC,TCGA-ESCA,TCGA-GBM,TCGA-HNSC,TCGA-KICH,TCGA-KIRC,TCGA-KIRP,TCGA-LAML,TCGA-LGG,TCGA_LIHC,TCGA-LUAD,TCGA-LUSC,TCGA-MESO,TCGA-OV,TCGA-PAAD,TCGA-PCPG,TCGA-PRAD,TCGA-READ,TCGA-SARC,TCGA-SKCM,TCGA-STAD,TCGA-TGCT,TCGA-THCA,TCGA-THYM,TCGA-UCEC,TCGA-UCS,TCGA-UVM
```

seed 0 可批量运行：

```bash
conda activate SurvPGC

CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_univariate.sh \
    --dataset "$E2_DATASETS" \
    --encoding prompt \
    --landmark_time all \
    --analyzer mlp_clinic_flatten,clinic_cox \
    --workers 16 \
    --seed 0
```

`--analyzer` 支持逗号分隔列表（如 `--analyzer mlp_clinic_mean,mlp_clinic_flatten`）；队列层按 analyzer 展开 conf，多 GPU 可并行认领不同 analyzer。

默认产物（每个 analyzer 一份）：

```text
results/univariate/prompt/{landmark_tag}/{dataset}/{analyzer}/
  field_cindex.csv
  run_config.json
```

## 3. E2 选择实验

前人固定字段集（T、N、M、age、sex）:

```bash
# 论文字段组合测试
CUDA_VISIBLE_DEVICES=6 bash A_pipeline/bg.sh AGPU6.log --workers 16 --dataset all --scheme paper --encoding text --analyzer mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten,clinic_cox
```


## 4. 运行 E2

当前可运行算法：

- 基线模型
| 名称 | 方法 |
|---|---|
| `A1_random` | 随机搜索 |
| `A2_greedy` | 前向贪婪 |
| `A3_beam` | Beam search |
| `A4_anneal` | 模拟退火 |
| `A5_genetic` | 遗传算法 |
| `A6_aco` | 蚁群算法 |

- 本工作方法
| `SEAS` | 完整方法 |
| `SEAS-no-sem` | 去语义消融 |
| `SEAS-no-int` | 去交互项消融 |
| `SEAS-no-ei` | 去 EI 消融 |

- 穷举锚点
| `ANCHOR_TIMING` | ANCHOR 计时探针 |
| `ANCHOR` | 受限字段空间穷举 |

单实例后台运行：

```bash
conda activate SurvPGC

CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset TCGA-BRCA \
    --landmark_time 0 \
    --algo A2_greedy \
    --seed 0,1,2,3,4 \
    --workers 16 \
    --inner_analyzer mlp_clinic_mean
```

E2 内层 Clinic Analyzer 默认使用 `mlp_clinic_flatten`。`--inner_analyzer` 支持逗号分隔列表（如 `--inner_analyzer mlp_clinic_flatten,clinic_cox`）：队列层按 analyzer 展开 conf，每个 analyzer 的结果写入独立目录，多 GPU 可并行认领不同 analyzer。

```bash
CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset TCGA-BRCA --landmark_time 0 --algo A2_greedy \
    --seed 0,1,2,3,4 --workers 16 --inner_analyzer mlp_clinic_flatten,clinic_cox
```

analyzer 会进入任务配置和缓存键，因此不同内层测评器不会复用彼此的评估结果。使用需要单字段先验的算法（`A6_aco`、`SEAS` 系列、`ANCHOR`）时，应先用相同 analyzer 运行对应的 univariate 评估（`--analyzer clinic_cox`）。

批量任务使用队列入口。`--dataset`、`--landmark_time` 和 `--algo` 均可展开，多个进程会原子认领任务：

```bash
# 6个基线
CUDA_VISIBLE_DEVICES=7 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset "$E2_DATASETS" \
    --landmark_time 0 \
    --algo A1_random,A2_greedy,A3_beam,A4_anneal,A5_genetic,A6_aco,SEAS,SEAS-no-sem,SEAS-no-int,SEAS-no-ei \
    --seed 0 \
    --workers 16

# 1个主模型 + 3个消融
CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset "$E2_DATASETS" \
    --landmark_time 0 \
    --algo SEAS,SEAS-no-sem,SEAS-no-int,SEAS-no-ei \
    --seed 0 \
    --workers 16

```

另一张卡运行相同命令时只需修改 `CUDA_VISIBLE_DEVICES`。队列位于 `Clinic_Analyzer/configs/E2_selection/{queue,running,done,failed}/`；同配置的已存在任务不会重复创建。

E2 默认读取：

- Field Bank：`outputs/{dataset}/field_bank/prompt/{landmark_tag}`
- split：`Clinic_Analyzer/data/splits/5foldcv/{study}`
- 单字段先验：`results/univariate/prompt/{landmark_tag}/{dataset}/{analyzer}`；非零 seed 再加 `seed_{seed}`

默认输出：

```text
results/E2_selection/prompt/{landmark_tag}/{dataset}/{algorithm}/{analyzer}/
  seed_{seed}/
    evaluations.jsonl
    result.json
    run_config.json
  aggregate.csv
  aggregate.json

results/E2_selection/cache.sqlite
```

缓存命中会减少实际训练，但仍占用当前算法的逻辑预算。E2 报告的是现有 5 折的 `cv_c_mean`；当前 split 中 val 与 test 相同，不能称为独立测试集结果。

### ANCHOR

先对固定的三个队列运行计时探针，再根据计时结果选择 `8 <= p <= 15`：

```bash
# 计时探针:实测单次 5 折评估耗时,为 ANCHOR 选 p。每个 analyzer 各随机采 20 个未命中缓存的子集真实评估,
# 代码强制只用这 3 个队列(规模大小不同,便于按患者数外推)。
CUDA_VISIBLE_DEVICES=4 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset TCGA-BRCA --landmark_time 0 --algo ANCHOR_TIMING --seed 0 --inner_analyzer mlp_clinic_mean,clinic_cox

CUDA_VISIBLE_DEVICES=3 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset TCGA-LGG --landmark_time 0 --algo ANCHOR_TIMING --seed 0 --inner_analyzer mlp_clinic_mean,clinic_cox

CUDA_VISIBLE_DEVICES=2 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset TCGA-CHOL --landmark_time 0 --algo ANCHOR_TIMING --seed 0 --inner_analyzer mlp_clinic_mean,clinic_cox

# 检查单次评估的耗时来源：取该 analyzer 单字段 c-index 前 5 的字段，关闭缓存剖析一次真实 `Evaluator.evaluate(S)`。
# 需要先跑过对应 analyzer 的 univariate 先验（--seed 默认 0）。
CUDA_VISIBLE_DEVICES=6 python scripts/profile_e2_evaluator.py --dataset TCGA-LGG --landmark_time 0 --analyzer mlp_clinic_mean,clinic_cox --seed 0

# 明确时间开销之后选择 anchor_p
CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset TCGA-BRCA \
    --landmark_time 0 \
    --algo ANCHOR \
    --anchor_p 12 \
    --seed 0
```

`--inner_analyzer` 同样支持列表：`ANCHOR_TIMING` 的计时结果按 analyzer 分开（`results/E2_selection/timing/{dataset}/{landmark_tag}/{analyzer}/seed_0/timing.json`），`ANCHOR` 的 top-p 空间按各 analyzer 自己的 univariate 先验计算，`--anchor_p` 应根据同一 analyzer 的计时结果选择。不同 analyzer 训练速度不同，各测各的；下面跑 `ANCHOR` 时也要带上相同的 `--inner_analyzer`（top-p 空间按该 analyzer 的 univariate 先验计算，没有对应先验会直接报错）。

脚本在每个 `results/E2_selection/profiling/{dataset}/{landmark_tag}/{analyzer}/` 下自动建目录并写出 `profile.txt`（内部 cProfile，按 cumtime 排序）、`subset.json` 和 `result.json`。当前剖析结果显示总耗时约 248 秒，主要时间位于 `evaluate_clinic_dir` 启动的 Clinic Analyzer 子进程；cProfile 只能看到等待子进程输出的调用栈。若环境安装了 `py-spy`，可用同一脚本生成火焰图（py-spy 一次只产出一张图，`--analyzer` 给单个即可；目标目录由脚本运行中自动创建）：

```bash
py-spy record -o results/E2_selection/profiling/TCGA-LGG/landmark_0/mlp_clinic_flatten/prof.svg -- \
    python scripts/profile_e2_evaluator.py --dataset TCGA-LGG --landmark_time 0 --analyzer mlp_clinic_flatten
```

性能剖析后，最终的 E2 计时校验命令为：

```bash
CUDA_VISIBLE_DEVICES=6 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset TCGA-CHOL --landmark_time 0 --algo ANCHOR_TIMING --seed 0
```

四个后台脚本都会根据 `CUDA_VISIBLE_DEVICES` 自动将日志写入 `Clinic_Analyzer/GPU{N}_任务.log`（例如 `GPU5_e2_selection.log`），无需再提供日志文件名。每个 GPU 上同一任务类型只能运行一个实例；重复启动会报错返回。查看日志可用 `tail -f Clinic_Analyzer/GPU5_e2_selection.log`。

`ANCHOR` 只表示单字段 top-p 受限空间中的精确最优，不是完整 Field Bank 的全局最优。A0/A0b 的内部组件尚未接入 CLI，A0c 尚未实现，因此当前不要把它们写进运行命令。

## 5. 汇总 E2

```bash
conda activate SurvPGC
python -m src.selection.report
```

`main_table.csv` 新增 `analyzer` 列（每个 analyzer 一行），`statistics.json`、anytime / anchor_gap / landmark 图与统计均按 analyzer 分开。汇总结果写入：

```text
results_display/E2_selection/prompt/
  main_table.csv
  statistics.json
  anytime/
  anchor_gap/
  landmark/
```

## 其他评估入口

这些入口仍可独立使用，不是 E2 的必需步骤：

```bash
# 旧 greedy
CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_greedy.sh \
    --workers 8 \
    --dataset all \
    --encoding prompt \
    --inner_analyzer mlp_clinic_flatten \
    --outer_analyzers mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
    --init_field '{demographic.}' \
    --landmark_time 730 \
    --seed 0 \
    --min_delta 0.01

# 连续数值恢复
python scripts/run_numeric_linear_probe.py --dataset all --encoding prompt --landmark_time 730 --seed 0

# 纵向实验
python scripts/run_longitudinal_field_bank.py --dataset all --encoding prompt --landmark_time none
python scripts/run_longitudinal_greedy.py --dataset TCGA-BRCA --encoding prompt --landmark_time none --init_field '{demographic.}'
python scripts/run_longitudinal_univariate_cindex.py --dataset TCGA-BRCA --encoding prompt --landmark_time none
```

## 旧目录与旧 conf（可选清理）

多 analyzer 改造后，所有读取端只认带 `{analyzer}` 层的新布局。以下旧数据不再被读取，可自行清理：

- `results/univariate/prompt/{landmark_tag}/{dataset}/field_cindex.csv`、`run_config.json`（无 analyzer 层）
- `results/E2_selection/prompt|timing|anchor/.../{algorithm}/seed_*/`（无 analyzer 层）
- `Clinic_Analyzer/configs/E2_selection/{queue,running,done,failed}/` 中 args 带 `inner_modality` 键的旧 conf

缓存 `results/E2_selection/cache.sqlite` 的 key 已含 analyzer，不受影响，重跑会直接命中。
