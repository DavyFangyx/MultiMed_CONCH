# A Pipeline

给实现 / 排错用。日常命令看 [README_usage.md](README_usage.md)。

从 clinical JSON 生成三类临床编码。默认读 `A_pipeline/datasets.json` 里的 9 个 lizhe 癌种：BRCA、LIHC、COAD、PRAD、READ、STAD，以及共用一份肾癌 JSON、再按 `project_id` 拆开的 KICH / KIRC / KIRP。不走 Field Bank / greedy。

所有命令共用同一套 `--dataset` / `--scheme` / `--encoding`。`--scheme manual` 是 L0-L5，`--scheme paper` 是论文方案，`--scheme all` 是两组都跑。`--encoding text` 是 CONCH embedding，`--encoding baseline` 是 D 向量。论文方案：`MULTISURV`、`SURVPGC`、`MMSURV`、`INTEGRATIVE_DNN`、`HGCN_KIRC`、`HGCN_LIHC`、`HGCN_ESCA`、`HGCN_LUSC`、`HGCN_LUAD`、`HGCN_UCEC`。`hgcn_clinic` 不接论文方案。每个方案在 `templates/{scheme}/fields.json` 写 `source`：L0-L5 是 `lizhe`，论文方案是 `gdc`。`--dataset all` 按方案来源展开：L0-L5 / D0-D5 只走 `A_pipeline/datasets.json` 的 9 个 clinical.cart；论文方案走 `projects/datasets.json` 的官方 JSON，并绑定全部 33 个 TCGA 队列。

## 三类编码

| 通路 | 命令 | 方案 | 编码方式 | 产物 |
|---|---|---|---|---|
| L | `pipeline` / `json2prompt` / `encode` | L0-L5，以及论文方案 | 每字段一句模板 → CONCH | `(n_fields, 512).pt` |
| D | `baseline` | D0-D5，以及论文方案 | 连续 min-max + 名义 onehot 拼接 | 变长向量 `.pt` |
| HGCN clinic | `hgcn_clinic` | 仅 L0-L5 | 一字段一节点，对角 pad | `x_cli.pkl` 等 |

L 和 D 的字段列表对齐：L0 对应 D0，以此类推。每个方案的字段列表在 `templates/{scheme}/fields.json`，句子模板在 `templates/{scheme}/template.csv`。HGCN clinic 用的是 L0-L5 字段，不是 HGCN 论文那套癌种字段。

## 编码

```bash
conda activate conch
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects
```

### L：prompt + CONCH

`pipeline` = json2prompt + encode。`--scheme` / `--dataset` 取值见上文，不必按组合各写一遍。

```bash
python A_pipeline/run.py pipeline --dataset all --scheme manual
python A_pipeline/run.py json2prompt --dataset all --scheme paper
python A_pipeline/run.py encode --dataset all --scheme manual
```

### D：baseline 向量

```bash
python A_pipeline/run.py baseline --dataset all --scheme manual
```

### HGCN clinic：图节点 pkl

只接 L0-L5。`--scheme L4` 只是把 `manual` 换成单个方案。

```bash
python A_pipeline/run.py hgcn_clinic --dataset all --scheme manual
```


## 评估

### cindex：5-fold val c-index

cindex 先把每条 `(dataset, scheme, modality)` 写成 `Clinic_Analyzer/configs/A_manual/queue/*.conf`，再用 atomic `link`+`unlink` 抢到 `running/`，最后交给 `Clinic_Analyzer/run.sh`。同一条命令开多个终端就会并行抢活；本终端也可用 `--workers` 同时 claim 多条。GPU 用各终端自己的 `CUDA_VISIBLE_DEVICES`。成功进 `done/`，失败进 `failed/`；再跑同一条命令会把 `failed/` 里的任务重新入队。已有 fold CSV 时默认 reuse，不会再调 Analyzer 的 `run.sh`。调度日志用 `A_pipeline/bg.sh` 落到 `A_pipeline/*.log`；每个任务的训练日志仍在 `results/A_manual/runs/{study}__{scheme}/{modality}/run.log`。

推荐入口和 greedy 一样：前台 `bash A_pipeline/run.sh`，后台 `bash A_pipeline/bg.sh <log>`。`run.sh` 等于 `python A_pipeline/run.py cindex ...`。`--workers` / `--modality` 换取值即可，不必各写一遍。

标注实验：

```bash
# L0-5测试
python A_pipeline/run.py cindex --dataset all --scheme manual --encoding text
# D0-5测试
python A_pipeline/run.py cindex --dataset all --scheme manual --encoding baseline
# 论文字段组合测试
python A_pipeline/run.py cindex --dataset all --scheme paper --encoding text
```

调度包装：

```bash
conda activate SurvPGC
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects

# 前台：调度输出打到当前终端
CUDA_VISIBLE_DEVICES=2 bash A_pipeline/run.sh \
    --workers 16 \
    --dataset all \
    --scheme manual \
    --encoding text \
    --modality mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten

# 后台：调度日志落到 A_pipeline/AGPU2.log
CUDA_VISIBLE_DEVICES=2 bash A_pipeline/bg.sh AGPU2.log \
    --workers 16 \
    --dataset all \
    --scheme manual \
    --encoding text \
    --modality mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten
```

和编码命令一样：`--scheme all` 是 L0-L5+论文方案，`--scheme manual` 是 L0-L5，`--scheme paper` 是论文方案。`--encoding text` 评 CONCH embedding，`--encoding baseline` 评 D 向量。L0-L5 / D0-D5 只评 lizhe 那 9 个；论文方案绑了全部 33 个 TCGA，`--dataset all` 会把这些队列都评上。评估没有内外层，只看 `--modality`。默认 `mlp_clinic_flatten`；可逗号分隔：`mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten,survgc_f,survpgc_f`。`survgc_f` / `survpgc_f` 只在 BRCA、COAD、KIRC、KIRP、LIHC 上跑。`--workers` 是本终端同时抢活的数量。

不传 `--dataset` 时走 `--json_path` 单 JSON，默认是 lizhe 肾癌 cart，产物写到 `outputs/custom/A_manual/`。`--dataset all --scheme all` 会同时跑 lizhe 的 L0-L5 和 GDC 的论文方案，不必再传 `--datasets_config`。

## 改字段

每个方案一个目录：

```text
A_pipeline/templates/schemes.json              # 方案名单 + 可用字段
A_pipeline/templates/{scheme}/fields.json      # 该方案字段列表
A_pipeline/templates/{scheme}/template.csv     # 该方案句子模板
```

可用字段见 `templates/schemes.json` 的 `_available_fields`。

### 改 L0

1. 编辑 `templates/L0/fields.json` 的 `fields`。
2. 同步改 `templates/L0/template.csv` 的列。列名是字段名把 `.` 和 `[]` 换成下划线，再加 `_template`，例如 `demographic.age_at_index` → `demographic_age_at_index_template`。单元格必须带 `{}`。
3. D0 和 `hgcn_clinic --scheme L0` 会跟着 L0 走，不用再维护一份字段表。

### 改论文方案，例如 `HGCN_KIRC` 或 `MULTISURV`

1. 编辑 `templates/HGCN_KIRC/fields.json` 或 `templates/MULTISURV/fields.json`。
2. 同步改对应目录里的 `template.csv`。
3. 这条字段表同时作用于 L（prompt/CONCH）和 D（baseline 向量）。
4. `hgcn_clinic` 不会读这些论文方案。论文 HGCN 字段目前只走 `pipeline` 和 `baseline`。

### 方案绑定数据集

每个方案必须写 `source`。`lizhe` 只展开 `A_pipeline/datasets.json` 的 9 个队列；`gdc` 只展开 `projects/datasets.json` 的官方队列。论文方案再写 `datasets` 绑定全部 33 个 TCGA；`--dataset all` 只在该来源和绑定的交集上生成产物。BRCA 这类两边都有的队列会各跑一次：L0-L5 用 lizhe JSON，论文方案用 GDC JSON。

当前绑定：

- L0-L5 / D0-D5：lizhe 的 9 个队列（BRCA、LIHC、COAD、PRAD、READ、STAD、KICH、KIRC、KIRP）
- 全部论文方案（`MULTISURV`、`SURVPGC`、`MMSURV`、`INTEGRATIVE_DNN`、`HGCN_KIRC`、`HGCN_LIHC`、`HGCN_ESCA`、`HGCN_LUSC`、`HGCN_LUAD`、`HGCN_UCEC`）：官方 33 个 TCGA 队列

所以 `pipeline --dataset all --scheme paper` 会给 33 个 TCGA 都写 GDC 产物。lizhe 9 个里没有的 ESCA / LUAD / LUSC / UCEC / GBM 等，也会从 GDC JSON 展开，不必再传 `--datasets_config`。`pipeline --dataset all --scheme manual` 仍然只跑 lizhe 那 9 个。

### 改 HGCN clinic 的图节点字段

- 只能改 L0-L5。例如改 `hgcn_clinic --scheme L4`，就去改 `templates/L4/fields.json`。
- 不要去改 `templates/HGCN_KIRC/` 那些论文方案，它们不会进入 `x_cli.pkl`。

如果新字段已经在 `_available_fields` 里，改对应方案的 `fields.json` + `template.csv` 即可。如果要加一个当前抽不出来的字段，还要改 `src/extract.py`；若它要进 HGCN clinic，还要把它加进 `src/baseline.py` 的 continuous / ordinal / nominal 三张表。

## 产物

### L prompt / CONCH

```text
# L0-5 6组基础实验
outputs/{dataset}/A_manual/L{0-5}/prompts.csv
outputs/{dataset}/A_manual/L{0-5}/embeddings/pt/{patient_id}.pt

# 实际论文中字段组合复现
outputs/{dataset}/A_manual/{paper_scheme}/prompts.csv
outputs/{dataset}/A_manual/{paper_scheme}/embeddings/pt/{patient_id}.pt
```

### D baseline 向量

```text
outputs/{dataset}/A_manual/D{0-5}/embeddings/pt/{patient_id}.pt

# 实际论文中字段组合复现
outputs/{dataset}/A_manual/baseline/{paper_scheme}/embeddings/pt/{patient_id}.pt
```

### HGCN pkl 产物

```text
outputs/{dataset}/A_manual/HGCN_clinic/L{0-5}/ttt_cli_feas.pkl
outputs/{dataset}/A_manual/HGCN_clinic/L{0-5}/t_cli_feas.pkl
outputs/{dataset}/A_manual/HGCN_clinic/L{0-5}/x_cli.pkl
outputs/{dataset}/A_manual/HGCN_clinic/L{0-5}/edge_index_cli.pkl
```

### cindex

```text
results/A_manual/{dataset}/cindex.csv
results/A_manual/{dataset}/run_config.json
results/A_manual/runs/{study}__{scheme}/{modality}/val_result_fold*.csv
results/A_manual/runs/{study}__{scheme}/{modality}/run.log
```

### 其他

```text
outputs/{dataset}/A_manual/metadata/
A_pipeline/baseline_onehot_mapping_tables/
```

字段对照见 `paper_tcga_field_mapping.md`。
