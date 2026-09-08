# A Pipeline 使用

日常跑实验看这份。字段绑定、队列、产物树看 [README.md](README.md)。

默认读 `A_pipeline/datasets.json` 的 9 个 lizhe 癌种，不走 Field Bank / greedy。

## 参数

所有命令共用同一套 flag。

| 参数 | 取值 | 常用 |
|---|---|---|
| `--dataset` | `all`，或下列 9 个名称（逗号分隔） | `all` |
| `--scheme` | `manual`=L0-L5，`paper`=论文方案，`all`=两组，或单个如 `L0` / `MULTISURV` | `manual` / `paper` |
| `--encoding` | `text`=CONCH，`baseline`=D 向量，`all`=两种 | `text` / `baseline` |
| `--modality` | 评估模型，逗号分隔；默认 `mlp_clinic_flatten` | `mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten` |

L0-L5 / D0-D5 的 9 个 dataset：`TCGA-BRCA`、`TCGA_LIHC`、`TCGA-COAD`、`TCGA-PRAD`、`TCGA-READ`、`TCGA-STAD`、`TCGA-KICH`、`TCGA-KIRC`、`TCGA-KIRP`。
论文方案的 dataset：官方 33 个 TCGA 队列。

`hgcn_clinic` 只接 L0-L5。L0-L5 的 `source` 是 lizhe，论文方案是 gdc。`--dataset all` 按方案来源展开：lizhe 跑上面 9 个；论文方案跑官方 GDC JSON，并绑定全部 33 个 TCGA。不必再传 `--datasets_config`。

## 编码

```bash
conda activate conch
# L0-5生成
python A_pipeline/run.py pipeline --dataset all --scheme manual
# D0-5生成
python A_pipeline/run.py baseline --dataset all --scheme manual
# 论文字段生成
python A_pipeline/run.py pipeline --dataset all --scheme paper

# HCGN的pkl数据
python A_pipeline/run.py hgcn_clinic --dataset all --scheme manual
```

`pipeline` 是 json2prompt + encode。只出句子或只编码时分别用 `json2prompt` / `encode`。

## 评估

```bash
conda activate SurvPGC
# L0-5测试
CUDA_VISIBLE_DEVICES=2 bash A_pipeline/run.sh --workers 16 --dataset all --scheme manual --encoding text --modality mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten,clinic_cox
# D0-5测试
CUDA_VISIBLE_DEVICES=2 bash A_pipeline/bg.sh AGPU2.log --workers 16 --dataset all --scheme manual --encoding baseline --modality mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten,clinic_cox
# 论文字段组合测试
CUDA_VISIBLE_DEVICES=6 bash A_pipeline/bg.sh AGPU6.log --workers 16 --dataset all --scheme paper --encoding text --modality mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten,clinic_cox
```

`run.sh` 等于 `python A_pipeline/run.py cindex ...`。多卡再开一个终端跑同一条命令。

## 产物

```text
# L0-5 6组基础实验
outputs/{dataset}/A_manual/L{0-5}/
outputs/{dataset}/A_manual/D{0-5}/

# 实际论文中字段组合复现
outputs/{dataset}/A_manual/{paper_scheme}/
outputs/{dataset}/A_manual/baseline/{paper_scheme}/

results/A_manual/{dataset}/cindex.csv
```
