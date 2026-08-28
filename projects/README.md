# Projects

临床 JSON 相关流程都在 `projects/`，和上游 `conch/` 分开。

`A_manual` 是人工定义的 L0-L5 / D0-D5。扫描、筛选、Field Bank、贪心是同一条自动链的多个阶段，不要再写成并列的 B / C。

```text
datasets.json + clinical JSON
        |
        +-- rawdata_stats/     JSON 字典、三态缺失、时间、筛选
        |
        +-- A_manual           人工 L0-L5 prompt/embedding，D0-D5 数值编码
        |
        +-- B_scan             筛后 Field Bank -> greedy
```

## Layout

- `datasets.json`：33 个 TCGA 数据集的 clinical JSON 路径，全部指向 `ClinicDatasets/gdc_clinical/raw_json/{project}.json`
- `src/common/`：两边共用的数据集注册、JSON 读取、字段路径、缺失三态
- `src/schemes/`：人工 L0-L5 / D0-D5
- `src/discovery/`：扫描、统计、筛选、Field Bank
- `src/time_stats.py`：生存/随访时间统计
- `src/greedy/`：Field Bank 之后的贪心调度
- `scripts/`：命令行入口
- `templates/field_labels.json`：扫 JSON 时的候选字段路径和中文释义
- `templates/A_manual/`：人工句模和 `schemes.json`
- `templates/B_scan/{dataset}/`：筛完后待填的 Field Bank 长表
- `rawdata_stats/`：JSON 测量和筛选结果，不进 `outputs/`
- `outputs/`：只放 prompt 和 embedding
- `Clinic_Analyzer/`：clinic embedding 评估

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
- L0-L5 模板：`projects/templates/A_manual`
- CONCH 权重：`/data/fangyuxuan/projects/medical_dl/trident_project/CONCH/pytorch_model.bin`

`--dataset all` 覆盖 33 个 TCGA project：ACC, BLCA, BRCA, CESC, CHOL, COAD, DLBC, ESCA, GBM, HNSC, KICH, KIRC, KIRP, LAML, LGG, LIHC, LUAD, LUSC, MESO, OV, PAAD, PCPG, PRAD, READ, SARC, SKCM, STAD, TGCT, THCA, THYM, UCEC, UCS, UVM。其中 LIHC 在 pipeline 里仍写作 `TCGA_LIHC`，对应 `TCGA-LIHC.json`。

---

## JSON 预处理：字典 / 三态缺失 / 时间 / 筛选

统计表只有 `null` / `sentinel` / `valid`。路径抽不到值记入 `null`。`missing = null + sentinel`。

```bash
# B组 step1 JSON -> template
python projects/scripts/run_scan_fields.py --dataset all
python projects/scripts/run_field_stats.py --dataset all
python scripts/run_field_filter.py --dataset all --write_templates
# 字段采集更新时间
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
rawdata_stats/{dataset}/time/
  patient_time_stats.csv
  patient_time_stats.png
  normalized_update_time.csv
  normalized_update_time.png
  normalized_update_time_boxplot.png
  sequences/
    {family}.csv
    {family}.png
rawdata_stats/_shared/
  field_stats.csv
  kept_fields.json
  patient_time_stats_all.png
```

Dead 用 `demographic.days_to_death`；非死亡用 `diagnoses[].days_to_last_follow_up`。

---

## A_manual：人工方案 L0-L5 / D0-D5

字段已知，模板固定。详细字段说明见 `pipeline.md`（L0-L5）和 `pipeline copy.md`（D0-D5）。

### 1. JSON -> prompt -> CONCH embedding

```bash
# 全流程
python projects/scripts/run_pipeline.py pipeline --dataset all --scheme all
# step1 JSON -> prompt
python projects/scripts/run_pipeline.py json2prompt --dataset TCGA-READ --scheme all
# step2 prompt -> CONCH embedding
python projects/scripts/run_pipeline.py encode --dataset TCGA-READ --scheme all

```

产物：

```text
outputs/{dataset}/A_manual/L{0-5}/prompts.csv
outputs/{dataset}/A_manual/L{0-5}/embeddings/pt/{patient_id}.pt
```

`json2prompt` 只写 prompt CSV；`encode` 读已有 CSV 做 CONCH 编码；`pipeline` 是两者串联。`--scheme all` 只跑 L0-L5，不会带上 Field Bank。

### 2. D0-D5 baseline

D 组没有 prompt，直接用字段数值编码。

```bash
python projects/scripts/run_pipeline.py baseline --dataset all --scheme all
```

产物：

```text
outputs/{dataset}/A_manual/D{0-5}/embeddings/pt/{patient_id}.pt
outputs/{dataset}/A_manual/metadata/
outputs/_shared/A_manual/baseline_onehot_mapping_tables/
```

连续值 Min-Max，序数字段整数编码，名义字段 one-hot。多数据集一起跑时，名义词表按全部选中数据集拟合一份。

### 3. Prompt 层占位率对照（通常不用——目标是各个数据集的字段统计不相同）

读的是已经生成的 L0-L5 prompt CSV，不读原始 JSON 全字段。

```bash
python projects/scripts/run_prompt_stats.py --dataset all --scheme all
python projects/scripts/run_prompt_stats.py --dataset TCGA-READ --scheme L0
```

产物：

```text
outputs/{dataset}/A_manual/L{0-5}/prompt_stats.csv
```

---

## B_scan：Field Bank / greedy

先完成上面的扫描、统计、筛选。筛选后按数据集填写 Field Bank 长表，再编码；greedy 是 Field Bank 之后的阶段。

```bash
# 人工填写 templates/B_scan/{dataset}/FIELD_BANK.csv
# 先看 example 的原始取值，再裁定 convert/unit，最后填 template。
# convert 允许：空（不换算）、days_to_years、int。

# JSON -> prompt.csv -> CONCH emb
python projects/scripts/run_field_bank.py --dataset TCGA_LIHC

# step1 JSON -> prompt.csv
python projects/scripts/run_field_bank.py --dataset TCGA_LIHC --prompts_only

# greedy 必须串行，不能拆成 A 组那种 conf 队列。后台跑：
conda activate SurvPGC
cd CONCH-main
CUDA_VISIBLE_DEVICES=6 bash projects/Clinic_Analyzer/bg_greedy.sh GreedyGPU6.log \
    --workers 8 \
    --dataset TCGA_LIHC \
    --inner_modality mlp_clinic_flatten \
    --outer_modalities mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
    --init_field '{demographic.ethnicity,demographic.sex_at_birth,demographic.gender,demographic.race}' \
    --splits_source external \
    --seed 0
```

产物：

```text
templates/B_scan/{dataset}/FIELD_BANK.csv
templates/B_scan/{dataset}/FIELD_BANK_columns.json
outputs/{dataset}/B_scan/FIELD_BANK/prompts.csv
outputs/{dataset}/B_scan/FIELD_BANK/field_index.json
outputs/{dataset}/B_scan/FIELD_BANK/embeddings/pt/{patient_id}.pt
outputs/{dataset}/B_scan/greedy/
  run_config.json
  selection_freq.csv
  selection_freq.png
  analyzer_splits/splits_{0-4}.csv
  jobs/{scheme}.json
  subsets/G{k}_{hash}/embeddings/pt/{patient_id}.pt
```

`FIELD_BANK.csv` 按数据集各自填写。`example` 是原始取值，只给人判断单位；看完后再填 `convert` / `unit` / `template`。`convert` 为空则原样填 `{}`。`example`、`unit` 不进入 prompts / embedding。

---

## 评估

A 组是离线评估：embedding 已经全部生成，先扫目录写出 conf，再后台串行跑 queue。

```bash
conda activate SurvPGC
cd CONCH-main/projects/Clinic_Analyzer

bash configs/z_exp_gen/gen_D0_6_L0_6_clinic_unimodal.sh
CUDA_VISIBLE_DEVICES=N bash bg.sh GPUN.log
```

B 组 greedy 是在线评估：Field Bank embedding 先编好，然后后台串行跑调度器。它会当场切子集 embedding，并调用 `Clinic_Analyzer/evaluate.py`。不能拆成 A 组那种 conf 队列，因为下一步字段取决于当前 5-fold mean c-index。

`survgc_f` / `survpgc_f` 只允许 BRCA、COAD、KIRC、KIRP、LIHC。KICH、PRAD、READ、STAD 以及其余 ClinicDatasets 都按 clinic 单模态评估；选多模态模型会直接报错。

多模态模型：

- `survgc_f`
- `survpgc_f`

单模态模型：

- `mlp_clinic_mean`
- `mlp_clinic_flatten`
- `snn_clinic_mean`
- `snn_clinic_flatten`

```bash
conda activate conch
cd CONCH-main

conda activate SurvPGC
cd CONCH-main
CUDA_VISIBLE_DEVICES=6 bash projects/Clinic_Analyzer/bg_greedy.sh GreedyGPU6.log \
    --workers 8 \
    --dataset TCGA_LIHC \
    --inner_modality mlp_clinic_flatten \
    --outer_modalities mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
    --init_field '{demographic.ethnicity,demographic.sex_at_birth,demographic.gender,demographic.race}' \
    --splits_source external \
    --seed 0
```

单数据集把 `--dataset all` 换成 `TCGA-READ`。`run.sh` 会接入 config 快照并调用 `evaluate.py`，不再走 `main.py`。详见 [Clinic_Analyzer/TEST_main_and_runsh.md](Clinic_Analyzer/TEST_main_and_runsh.md)。

## 还要注意

- Field Bank embedding 目前只有 `TCGA_LIHC`。其余 32 个数据集能选、能解析、能读 5-fold，但 greedy 切子集 embedding 时会缺文件。
- `Clinic_Analyzer/data/splits/5foldcv/summary.csv` 只记了 LIHC，没有 33 套 split 的完整清单。
- `--splits_source internal` 仍要 `split_eligibility.csv`，新 split 目录里没有。默认 `external` 不受影响。
