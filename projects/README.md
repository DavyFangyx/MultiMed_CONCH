# Projects

临床 JSON 相关流程都在 `projects/`，和上游 `conch/` 分开。

剩下一条链：scan → stats → filter → Field Bank → greedy。两种编码走同一个 `--encoding`：`prompt`（CONCH 句向量，默认）和 `onehot`。

```text
datasets.json + clinical JSON
        |
        +-- rawdata_stats/     JSON 字典、三态缺失、时间、筛选
        |
        +-- templates/field_bank/{dataset}/
        |
        +-- outputs/{dataset}/field_bank/{prompt|onehot}/
        |
        +-- outputs/{dataset}/greedy/{prompt|onehot}/
```

## Layout

- `datasets.json`：33 个 TCGA 数据集的 clinical JSON 路径，全部指向 `ClinicDatasets/gdc_clinical/raw_json/{project}.json`
- `src/common/`：共用的数据集注册、JSON 读取、字段路径、缺失三态
- `src/discovery/`：扫描、统计、筛选、Field Bank
- `src/time_stats.py`：生存/随访时间统计
- `src/greedy/`：Field Bank 之后的贪心调度
- `scripts/`：命令行入口
- `templates/field_labels.json`：扫 JSON 时的候选字段路径和中文释义
- `templates/field_bank/{dataset}/`：筛完后待填的 Field Bank 长表
- `rawdata_stats/`：JSON 测量和筛选结果，不进 `outputs/`
- `outputs/`：只放 Field Bank prompt / embedding 和 greedy 产物
- `Clinic_Analyzer/`：clinic embedding 评估

独立的人工方案通路在 `A_pipeline/`，不走上面这条链。它默认读 `A_pipeline/datasets.json` 里 lizhe 的 9 个 `clinical.cart`，不是 B 的 33 份 ClinicDatasets。L0-L5 / D0-D5 入口：

```bash
python projects/A_pipeline/run.py json2prompt --dataset TCGA-READ --scheme L0
python projects/A_pipeline/run.py pipeline --dataset TCGA-READ --scheme all
python projects/A_pipeline/run.py baseline --dataset TCGA-READ --scheme all
```

产物写到 `outputs/{dataset}/A_manual/`，详见 [A_pipeline/README.md](A_pipeline/README.md)。

## 公共约定

```bash
conda activate conch
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main
```

- `--dataset all` 跑 `datasets.json` 里全部 33 个 TCGA 数据集
- 也可以写 `--dataset TCGA-READ` 或 `--dataset TCGA-BRCA,TCGA-READ`
- 肝细胞癌历史目录名仍是 `TCGA_LIHC`；`--dataset TCGA-LIHC` 会解析到同一份配置
- 不传 `--dataset` 时，走 `--json_path` 单 JSON 模式
- 患者级 `.pt` 统一命名为 `TCGA-XX-XXXX.pt`

默认路径：

- 数据集配置：`projects/datasets.json`
- clinic JSON：`projects/ClinicDatasets/gdc_clinical/raw_json/{TCGA-XXXX}.json`
- Field Bank 模板：`projects/templates/field_bank/{dataset}`
- CONCH 权重：`/data/fangyuxuan/projects/medical_dl/trident_project/CONCH/pytorch_model.bin`

`--dataset all` 覆盖 33 个 TCGA project：ACC, BLCA, BRCA, CESC, CHOL, COAD, DLBC, ESCA, GBM, HNSC, KICH, KIRC, KIRP, LAML, LGG, LIHC, LUAD, LUSC, MESO, OV, PAAD, PCPG, PRAD, READ, SARC, SKCM, STAD, TGCT, THCA, THYM, UCEC, UCS, UVM。其中 LIHC 在 pipeline 里仍写作 `TCGA_LIHC`，对应 `TCGA-LIHC.json`。

---

## JSON 预处理：字典 / 三态缺失 / 时间 / 筛选

统计表只有 `null` / `sentinel` / `valid`。路径抽不到值记入 `null`。`missing = null + sentinel`。

```bash
python projects/scripts/run_scan_fields.py --dataset all
python projects/scripts/run_field_stats.py --dataset all
python projects/scripts/run_field_filter.py --dataset all --write_templates --R3_coverage 0.30 --R4_n_unique 2 --R4_mode_share 0.95
python projects/scripts/run_time_stats.py --dataset all
```

产物：

```text
rawdata_stats/{dataset}/scanned_fields.json
rawdata_stats/{dataset}/field_stats.csv
rawdata_stats/{dataset}/kept_fields.json
rawdata_stats/{dataset}/fliter_log/
  exclusion_log.csv
  field_registry.csv
rawdata_stats/{dataset}/time_write/ and time_record/
  patient_time_stats.csv
  patient_time_stats.png
  normalized_update_time.csv
  normalized_update_time.png
  normalized_update_time_boxplot.png
  sequences/{family}.csv
  sequences/{family}.png
  missing/{family}.csv
  missing/{family}.png
rawdata_stats/_shared/
  field_stats.csv
  kept_fields.json
  patient_time_stats_all.png
rawdata_stats/TIME_CRITERIA.md
```

Dead 用 `demographic.days_to_death`；非死亡用 `diagnoses[].days_to_last_follow_up`。`t_write` / `t_record` 两张实现表见 `rawdata_stats/TIME_CRITERIA.md`。

---

## Field Bank / greedy

先完成上面的扫描、统计、筛选。筛选后按数据集填写 Field Bank 长表，再编码；greedy 是 Field Bank 之后的阶段。

```bash
# 人工填写 templates/field_bank/{dataset}/FIELD_BANK.csv
# 先看 example 的原始取值，再裁定 convert/unit，最后填 template。
# convert 允许：空（不换算）、days_to_years、int。

# JSON -> prompt.csv -> CONCH emb
python projects/scripts/run_field_bank.py --dataset TCGA_LIHC --encoding prompt
python projects/scripts/run_field_bank.py --dataset TCGA_LIHC --encoding onehot

# step1 JSON -> prompt.csv（仅 prompt）
python projects/scripts/run_field_bank.py --dataset TCGA_LIHC --encoding prompt --prompts_only

# greedy 必须串行。后台跑：
conda activate SurvPGC
cd CONCH-main
CUDA_VISIBLE_DEVICES=6 bash projects/Clinic_Analyzer/bg_greedy.sh GreedyGPU6.log \
    --workers 8 \
    --dataset TCGA_LIHC \
    --encoding prompt \
    --inner_modality mlp_clinic_flatten \
    --outer_modalities mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
    --init_field '{demographic.ethnicity,demographic.sex_at_birth,demographic.gender,demographic.race}' \
    --seed 0 \
    --min_delta 0.01
```

产物：

```text
templates/field_bank/{dataset}/FIELD_BANK.csv
templates/field_bank/{dataset}/FIELD_BANK_columns.json
outputs/{dataset}/field_bank/prompt/prompts.csv
outputs/{dataset}/field_bank/prompt/field_index.json
outputs/{dataset}/field_bank/prompt/embeddings/pt/{patient_id}.pt
outputs/{dataset}/field_bank/onehot/field_index.json
outputs/{dataset}/field_bank/onehot/embeddings/pt/{patient_id}.pt
outputs/{dataset}/field_bank/onehot/metadata/
outputs/{dataset}/greedy/{prompt|onehot}/
  run_config.json
  selection_freq.csv
  selection_freq.png
  jobs/{scheme}.json
  subsets/G{k}_{hash}/embeddings/pt/{patient_id}.pt
```

`FIELD_BANK.csv` 按数据集各自填写。`example` 是原始取值，只给人判断单位；看完后再填 `convert` / `unit` / `template`。`convert` 为空则原样填 `{}`。`example`、`unit` 不进入 prompts / embedding。prompt 是 `[n_fields, 512]`；onehot 是 `[n_fields, max_width]`，短字段右侧 0 pad。

---

## 评估

只保留 greedy 在线评估：Field Bank embedding 先编好，然后后台串行跑调度器。它会当场切子集 embedding，并调用 `Clinic_Analyzer/evaluate.py`。不能拆成 conf 队列，因为下一步字段取决于当前 5-fold mean c-index。内层 `greedy_forward` 每一步只加增益最大的字段；如果最好候选的 c-index 增益小于 `--min_delta`（默认 0），则不加该字段并早停。`patience` 仍只用于事后 Wilcoxon 停点，不打断搜索。

`survgc_f` / `survpgc_f` 只允许 BRCA、COAD、KIRC、KIRP、LIHC。KICH、PRAD、READ、STAD 以及其余 ClinicDatasets 都按 clinic 单模态评估；选多模态模型会直接报错。

多模态数据集：BRCA、COAD、KIRC、KIRP、LIHC
单模态数据集：ACC、BLCA、CESC、CHOL、DLBC、ESCA、GBM、HNSC、KICH、LAML、LGG、LUAD、LUSC、MESO、OV、PAAD、PCPG、PRAD、READ、SARC、SKCM、STAD、TGCT、THCA、THYM、UCEC、UCS、UVM

多模态模型：`survgc_f`、`survpgc_f`
单模态模型：`mlp_clinic_mean`、`mlp_clinic_flatten`、`snn_clinic_mean`、`snn_clinic_flatten`

```bash
conda activate SurvPGC
cd CONCH-main
CUDA_VISIBLE_DEVICES=6 bash projects/Clinic_Analyzer/bg_greedy.sh GreedyGPU6.log \
    --workers 8 \
    --dataset TCGA_LIHC \
    --encoding prompt \
    --inner_modality mlp_clinic_flatten \
    --outer_modalities mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
    --init_field '{demographic.ethnicity,demographic.sex_at_birth,demographic.gender,demographic.race}' \
    --seed 0 \
    --min_delta 0.01
```

单数据集把 `--dataset all` 换成 `TCGA-READ`。`run.sh` 会接入 config 快照并调用 `evaluate.py`，不再走 `main.py`。详见 [Clinic_Analyzer/TEST_main_and_runsh.md](Clinic_Analyzer/TEST_main_and_runsh.md)。

## 还要注意

- Field Bank embedding 目前只有 `TCGA_LIHC`。其余 32 个数据集能选、能解析、能读 5-fold，但 greedy 切子集 embedding 时会缺文件。
- `Clinic_Analyzer/data/splits/5foldcv/summary.csv` 只记了 LIHC，没有 33 套 split 的完整清单。
