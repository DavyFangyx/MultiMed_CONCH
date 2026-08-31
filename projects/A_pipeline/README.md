# A Pipeline

独立的人工方案通路：lizhe `clinical.cart` JSON → L0-L5 prompt / CONCH embedding，以及 JSON → D0-D5 baseline 向量。不依赖 `projects/src`，也不走 Field Bank / greedy。

默认数据集是 `A_pipeline/datasets.json` 里的 9 个癌种，全部指向 `/data/lizhe/Medteam_projects/` 下的 `clinical.cart*.json`：BRCA、LIHC、COAD、PRAD、READ、STAD，以及共用一份肾癌 JSON、再按 `project_id` 拆开的 KICH / KIRC / KIRP。字段对照表在 `templates/json_field_dictionary.json`。

工作目录是 `CONCH-main`。

```bash
conda activate conch
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main

python projects/A_pipeline/run.py json2prompt --dataset TCGA-READ --scheme L0
python projects/A_pipeline/run.py encode --dataset TCGA-READ --scheme L0
python projects/A_pipeline/run.py pipeline --dataset TCGA-READ --scheme all
python projects/A_pipeline/run.py baseline --dataset TCGA-READ --scheme all
python projects/A_pipeline/run.py pipeline --dataset all --scheme all
```

不传 `--dataset` 时走 `--json_path` 单 JSON，默认是 lizhe 肾癌 cart，产物写到 `outputs/custom/A_manual/`。需要 33 份官方 GDC JSON 时，显式传 `--datasets_config projects/datasets.json`。

产物：

```text
outputs/{dataset}/A_manual/L{0-5}/prompts.csv
outputs/{dataset}/A_manual/L{0-5}/embeddings/pt/{patient_id}.pt
outputs/{dataset}/A_manual/D{0-5}/embeddings/pt/{patient_id}.pt
outputs/{dataset}/A_manual/metadata/
A_pipeline/baseline_onehot_mapping_tables/
```

模板在 `projects/A_pipeline/templates/`。Field Bank / greedy 不走这里。
