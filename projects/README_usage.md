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
python scripts/run_field_filter.py \
    --dataset all \
    --landmark_time all \
    --write_templates \
    --R3_coverage 0.30 \
    --R4_n_unique 2 \
    --R4_mode_share 0.95
```

筛选结果位于 `rawdata_stats/{dataset}/{landmark_tag}/`，模板位于 `templates/field_bank/{dataset}/{landmark_tag}/FIELD_BANK.csv`。

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

## 3. E1 单字段 Cindex 先验

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
    --modality mlp_clinic_flatten \
    --workers 8 \
    --seed 0
```

默认产物：

```text
results/univariate/prompt/{landmark_tag}/{dataset}/
  field_cindex.csv
  run_config.json
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
    --workers 8
```

批量任务使用队列入口。`--dataset`、`--landmark_time` 和 `--algo` 均可展开，多个进程会原子认领任务：

```bash
CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset "$E2_DATASETS" \
    --landmark_time 0 \
    --algo A1_random,A2_greedy,A3_beam,A4_anneal,A5_genetic,A6_aco,SEAS,SEAS-no-sem,SEAS-no-int,SEAS-no-ei \
    --seed 0 \
    --workers 8
```

另一张卡运行相同命令时只需修改 `CUDA_VISIBLE_DEVICES`。队列位于 `Clinic_Analyzer/configs/E2_selection/{queue,running,done,failed}/`；同配置的已存在任务不会重复创建。

E2 默认读取：

- Field Bank：`outputs/{dataset}/field_bank/prompt/{landmark_tag}`
- split：`Clinic_Analyzer/data/splits/5foldcv/{study}`
- 单字段先验：`results/univariate/prompt/{landmark_tag}/{dataset}`；非零 seed 再加 `seed_{seed}`

默认输出：

```text
results/E2_selection/prompt/{landmark_tag}/{dataset}/{algorithm}/
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
CUDA_VISIBLE_DEVICES=4 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset TCGA-BRCA --landmark_time 0 --algo ANCHOR_TIMING --seed 0

CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset TCGA-LGG --landmark_time 0 --algo ANCHOR_TIMING --seed 0

CUDA_VISIBLE_DEVICES=6 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset TCGA-CHOL --landmark_time 0 --algo ANCHOR_TIMING --seed 0

CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_e2_selection.sh \
    --dataset TCGA-BRCA \
    --landmark_time 0 \
    --algo ANCHOR \
    --anchor_p 12 \
    --seed 0
```

四个后台脚本都会根据 `CUDA_VISIBLE_DEVICES` 自动将日志写入 `Clinic_Analyzer/GPU{N}_任务.log`（例如 `GPU5_e2_selection.log`），无需再提供日志文件名。每个 GPU 上同一任务类型只能运行一个实例；重复启动会报错返回。查看日志可用 `tail -f Clinic_Analyzer/GPU5_e2_selection.log`。

`ANCHOR` 只表示单字段 top-p 受限空间中的精确最优，不是完整 Field Bank 的全局最优。A0/A0b 的内部组件尚未接入 CLI，A0c 尚未实现，因此当前不要把它们写进运行命令。

## 5. 汇总 E2

```bash
conda activate SurvPGC
python -m src.selection.report
```

汇总结果写入：

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
    --inner_modality mlp_clinic_flatten \
    --outer_modalities mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
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
