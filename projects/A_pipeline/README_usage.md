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
| `--analyzer` | 测评器（analyzer），逗号分隔；默认 `mlp_clinic_flatten` | `mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten` |

L0-L5 / D0-D5 的 9 个 dataset：`TCGA-BRCA`、`TCGA_LIHC`、`TCGA-COAD`、`TCGA-PRAD`、`TCGA-READ`、`TCGA-STAD`、`TCGA-KICH`、`TCGA-KIRC`、`TCGA-KIRP`。
论文方案的 dataset：官方 33 个 TCGA 队列。

L0-L5 的 `source` 是 lizhe，论文方案是 gdc。`--dataset all` 按方案来源展开：lizhe 跑上面 9 个；论文方案跑官方 GDC JSON，并绑定全部 33 个 TCGA。不必再传 `--datasets_config`。

`hgcn_clinic` 与其它命令同一个方案装载路径：`manual` / `all` 只展开 L0-L5（旧产物树不变），论文方案与 `templates/{scheme}` 自定义方案（如 `--scheme MULTISURV` / `--scheme Test_3_greedy_TCGA-LAML`）显式点名即可编码。节点类型先查 L0-L5 冻结三分法，其余字段按 D 向量同一份 GDC dictionary 分类（enum/boolean→nominal，integer/number→continuous）；提取器没有值的字段记 `keep_none`（对角 0 行、coverage 0%），不报错。L0-L5 产物节点名沿用占位符（`AGE`/`SEX_AT_BIRTH`/…），其它方案用 `fields.json` 的字段路径。

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

# HCGN 图节点：论文方案 / 自定义方案
python A_pipeline/run.py hgcn_clinic --dataset TCGA-LAML --scheme MULTISURV
python A_pipeline/run.py hgcn_clinic --dataset TCGA-LAML --scheme Test_3_greedy_TCGA-LAML

# HCGN 图节点 + landmark（值级 mask 与 prompt / baseline 一致）
python A_pipeline/run.py hgcn_clinic --dataset all --scheme manual --landmark_time 0

# 试跑 / 等价性回归：输出根目录改到别处，不碰 outputs/
python A_pipeline/run.py hgcn_clinic --dataset TCGA-KICH --scheme manual --hgcn_out_root /tmp/s11_hgcn_regress
```

`pipeline` 是 json2prompt + encode。只出句子或只编码时分别用 `json2prompt` / `encode`。

`hgcn_clinic` 专用 flag：`--landmark_time {0,365,730}`（不传=旧布局；传了落 `{scheme}/landmark_{T}/`）与 `--hgcn_out_root`（默认 `outputs`，即 `{root}/{dataset}/A_manual/HGCN_clinic`）。

## 评估

```bash
conda activate SurvPGC
# L0-5测试
CUDA_VISIBLE_DEVICES=2 bash A_pipeline/run.sh --workers 16 --dataset all --scheme manual --encoding text --analyzer mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten,clinic_cox
# D0-5测试
CUDA_VISIBLE_DEVICES=2 bash A_pipeline/bg.sh AGPU2.log --workers 16 --dataset all --scheme manual --encoding baseline --analyzer mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten,clinic_cox
# 论文字段组合测试
CUDA_VISIBLE_DEVICES=6 bash A_pipeline/bg.sh AGPU6.log --workers 16 --dataset all --scheme paper --encoding text --analyzer mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten,clinic_cox
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

# HGCN 图节点：L0-L5 与其它方案同一个根目录；landmark 臂多一层 landmark_{T}
outputs/{dataset}/A_manual/HGCN_clinic/L{0-5}/
outputs/{dataset}/A_manual/HGCN_clinic/{scheme}/
outputs/{dataset}/A_manual/HGCN_clinic/{scheme}/landmark_{T}/

results/A_manual/{dataset}/cindex.csv
```
