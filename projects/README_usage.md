# Projects 使用

日常跑实验看这份。目录、产物、landmark / 队列实现看 [README.md](README.md)。人工方案通路看 [A_pipeline/README_usage.md](A_pipeline/README_usage.md)。

## 参数

同一套 flag，换取值即可，不必按组合各写一遍。

| 参数 | 取值 | 常用 |
|---|---|---|
| `--dataset` | `all`，或下列 35 个名称（逗号分隔） | `all` |
| `--encoding` | `prompt`（CONCH，默认），`onehot` | `prompt` |
| `--landmark_time` | 天数，`none`，逗号列表，或 `all` | `0,365,730,none` |
| `--scheme` | 仅 `run_schemes`。主流程组成方案：`L2` 全句拼接、`L3` token 窗、`L5` 语义组、`all`。不是 A 通路的 L0-L5。 | `all` |

全部 dataset：`TCGA-ACC`、`TCGA-BLCA`、`TCGA-BRCA`、`TCGA-CESC`、`TCGA-CHOL`、`TCGA-COAD`、`TCGA-DLBC`、`TCGA-ESCA`、`TCGA-GBM`、`TCGA-HNSC`、`TCGA-KICH`、`TCGA-KIRC`、`TCGA-KIRP`、`TCGA-LAML`、`TCGA-LGG`、`TCGA-LIHC`、`TCGA-LUAD`、`TCGA-LUSC`、`TCGA-MESO`、`TCGA-OV`、`TCGA-PAAD`、`TCGA-PCPG`、`TCGA-PRAD`、`TCGA-READ`、`TCGA-SARC`、`TCGA-SKCM`、`TCGA-STAD`、`TCGA-TGCT`、`TCGA-THCA`、`TCGA-THYM`、`TCGA-UCEC`、`TCGA-UCS`、`TCGA-UVM`、`MMRF`、`CPTAC`。

## 预处理

```bash
conda activate conch
python scripts/run_scan_fields.py --dataset all
python scripts/run_field_stats.py --dataset all
python scripts/run_field_filter.py --dataset all --write_templates --R3_coverage 0.30 --R4_n_unique 2 --R4_mode_share 0.95 --landmark_time 730
python scripts/run_time_stats.py --dataset all
```

筛完后填写 `templates/field_bank/{dataset}/{landmark_*}/FIELD_BANK.csv`。

## 编码

```bash
conda activate conch
python scripts/run_field_bank.py --dataset all --encoding prompt --landmark_time none
python scripts/run_schemes.py --dataset all --scheme all --landmark_time 730
python scripts/run_longitudinal_field_bank.py --dataset all --encoding prompt --landmark_time none
```

只出 prompt CSV：加 `--prompts_only`。

## 评估

```bash
conda activate SurvPGC
CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_greedy.sh GreedyGPU5.log \
    --workers 8 \
    --dataset all \
    --encoding prompt \
    --inner_modality mlp_clinic_flatten \
    --outer_modalities mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
    --init_field '{demographic.}' \
    --landmark_time 730 \
    --seed 0 \
    --min_delta 0.01

CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_univariate.sh UniGPU5.log \
    --workers 8 \
    --dataset all \
    --encoding prompt \
    --modality mlp_clinic_flatten \
    --landmark_time none \
    --seed 0

python scripts/run_numeric_linear_probe.py --dataset TCGA_LIHC --encoding prompt --landmark_time none --seed 0
python scripts/run_longitudinal_greedy.py --dataset TCGA-BRCA --encoding prompt --landmark_time none --init_field '{demographic.}'
python scripts/run_longitudinal_univariate_cindex.py --dataset TCGA-BRCA --encoding prompt --landmark_time none
```

汇总：

```bash
conda activate SurvPGC
python results_display/scripts/collect_greedy_cindex.py --dataset all --landmark_time 0
python results_display/scripts/collect_univariate_cindex.py --dataset all --landmark_time 0
python results_display/scripts/collect_linear_probe_r2.py --dataset all --landmark_time 730
```
