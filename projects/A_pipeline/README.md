# A Pipeline

从 clinical JSON 生成三类临床编码。默认读 `A_pipeline/datasets.json` 里的 9 个 lizhe 癌种：BRCA、LIHC、COAD、PRAD、READ、STAD，以及共用一份肾癌 JSON、再按 `project_id` 拆开的 KICH / KIRC / KIRP。不走 Field Bank / greedy。

`--scheme all` 只跑 L0-L5 或 D0-D5。论文方案必须显式指定：`MULTISURV`、`SURVPGC`、`MMSURV`、`INTEGRATIVE_DNN`、`HGCN_KIRC`、`HGCN_LIHC`、`HGCN_ESCA`、`HGCN_LUSC`、`HGCN_LUAD`、`HGCN_UCEC`。`hgcn_clinic` 不接论文方案。论文方案可在 `templates/{scheme}/fields.json` 里用 `datasets` 绑定队列；`--dataset all` 也只在绑定交集上跑。

## 三类编码

| 通路 | 命令 | 方案 | 编码方式 | 产物 |
|---|---|---|---|---|
| L | `pipeline` / `json2prompt` / `encode` | L0-L5，以及论文方案 | 每字段一句模板 → CONCH | `(n_fields, 512).pt` |
| D | `baseline` | D0-D5，以及论文方案 | 连续 min-max + 名义 onehot 拼接 | 变长向量 `.pt` |
| HGCN clinic | `hgcn_clinic` | 仅 L0-L5 | 一字段一节点，对角 pad | `x_cli.pkl` 等 |

L 和 D 的字段列表对齐：L0 对应 D0，以此类推。每个方案的字段列表在 `templates/{scheme}/fields.json`，句子模板在 `templates/{scheme}/template.csv`。HGCN clinic 用的是 L0-L5 字段，不是 HGCN 论文那套癌种字段。

## 使用

```bash
conda activate conch
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects
```

### L：prompt + CONCH

```bash
python A_pipeline/run.py json2prompt --dataset TCGA-READ --scheme L0
python A_pipeline/run.py encode --dataset TCGA-READ --scheme L0

python A_pipeline/run.py pipeline --dataset all --scheme all
```
```
```
--scheme L0
 MULTISURV,SURVPGC,MMSURV,INTEGRATIVE_DNN,HGCN_KIRC,HGCN_LIHC,HGCN_ESCA，HGCN_LUSC，HGCN_LUAD，HGCN_UCEC
```


### D：baseline 向量

```bash
python A_pipeline/run.py baseline --dataset TCGA-READ --scheme all
python A_pipeline/run.py baseline --dataset TCGA-READ --scheme HGCN_UCEC
python A_pipeline/run.py baseline --dataset all --scheme all
```

### HGCN clinic：图节点 pkl

```bash
python A_pipeline/run.py hgcn_clinic --dataset TCGA-KIRC --scheme L4
python A_pipeline/run.py hgcn_clinic --dataset all --scheme all
```

不传 `--dataset` 时走 `--json_path` 单 JSON，默认是 lizhe 肾癌 cart，产物写到 `outputs/custom/A_manual/`。需要 33 份官方 GDC JSON 时：

```bash
python A_pipeline/run.py pipeline --dataset all --scheme all --datasets_config datasets.json
```

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

论文方案可以在 `templates/{scheme}/fields.json` 增加 `datasets`。没有这个字段的方案（L0-L5）对所有队列都跑。有绑定的方案，即使 `--dataset all` 也只在交集上生成产物。

当前绑定：

- `MULTISURV` / `INTEGRATIVE_DNN`：官方 33 个 TCGA 队列
- `MMSURV`：BRCA、ESCA、LIHC、LUAD、COAD、STAD
- `SURVPGC`：LIHC、COAD、READ、BRCA
- `HGCN_KIRC` / `HGCN_LIHC` / `HGCN_ESCA` / `HGCN_LUSC` / `HGCN_LUAD` / `HGCN_UCEC`：各自对应一个队列

所以 `pipeline --dataset all --scheme HGCN_KIRC` 只会写 `TCGA-KIRC`。默认 lizhe 9 个癌种里没有 ESCA / LUAD / LUSC / UCEC 时，对应 HGCN 方案会被跳过；需要这些队列时改用 `--datasets_config datasets.json`。

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

### 其他

```text
outputs/{dataset}/A_manual/metadata/
A_pipeline/baseline_onehot_mapping_tables/
```

字段对照见 `paper_tcga_field_mapping.md`。
