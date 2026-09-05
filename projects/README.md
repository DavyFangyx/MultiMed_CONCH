# Projects

临床 JSON 相关流程都在本目录，和上游 `conch/` 分开。

剩下一条链：scan → stats → filter → Field Bank → greedy。两种编码走同一个 `--encoding`：`prompt`（CONCH 句向量，默认）和 `onehot`。Field Bank prompt 句子还可以组成 L2 / L3 / L5 clinic embedding。纵向实验把同一套 Field Bank 字段按 follow-up 记录展开，产物写到 `outputs/{dataset}/longitudinal/...`。

```text
datasets.json + clinical JSON
        |
        +-- rawdata_stats/     JSON 字典、三态缺失、时间、筛选
        |
        +-- templates/field_bank/{dataset}/
        |
        +-- outputs/{dataset}/field_bank/{prompt|onehot}/
        |
        +-- outputs/{dataset}/schemes/{landmark_tag}_{L2|L3|L5}/
        |
        +-- outputs/{dataset}/greedy/{prompt|onehot}/
```

## Layout

- `datasets.json`：33 个 TCGA 数据集的 clinical JSON 路径，全部指向 `ClinicDatasets/gdc_clinical/raw_json/{project}.json`
- `src/common/`：共用的数据集注册、JSON 读取、字段路径、缺失三态
- `src/discovery/`：扫描、统计、筛选、Field Bank、L2/L3/L5 组成编码
- `src/time_stats.py`：生存/随访时间统计
- `src/greedy/`：Field Bank 之后的贪心调度
- `scripts/`：命令行入口
- `templates/field_labels.json`：旧人工释义表，已停用；扫描默认读 GDC clinical dictionary
- `templates/field_bank/{dataset}/`：筛完后待填的 Field Bank 长表
- `rawdata_stats/`：JSON 测量和筛选结果，不进 `outputs/`
- `outputs/`：Field Bank prompt / embedding、L2/L3/L5 scheme embedding，以及 greedy 产物
- `Clinic_Analyzer/`：clinic embedding 评估

独立的人工方案通路在 `A_pipeline/`，不走上面这条链。它默认读 `A_pipeline/datasets.json` 里 lizhe 的 9 个 `clinical.cart`，不是 B 的 33 份 ClinicDatasets。L0-L5 / D0-D5 入口：

```bash
python A_pipeline/run.py json2prompt --dataset TCGA-READ --scheme L0
python A_pipeline/run.py pipeline --dataset TCGA-READ --scheme all
python A_pipeline/run.py baseline --dataset TCGA-READ --scheme all
```

产物写到 `outputs/{dataset}/A_manual/`，详见 [A_pipeline/README.md](A_pipeline/README.md)。

## 公共约定

```bash
conda activate conch
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects
```

- `--dataset all` 跑 `datasets.json` 里全部 33 个 TCGA 数据集
- 也可以写 `--dataset TCGA-READ` 或 `--dataset TCGA-BRCA,TCGA-READ`
- 肝细胞癌历史目录名仍是 `TCGA_LIHC`；`--dataset TCGA-LIHC` 会解析到同一份配置
- 不传 `--dataset` 时，走 `--json_path` 单 JSON 模式
- 患者级 `.pt` 统一命名为 `TCGA-XX-XXXX.pt`

默认路径：

- 数据集配置：`datasets.json`
- clinic JSON：`ClinicDatasets/gdc_clinical/raw_json/{TCGA-XXXX}.json`
- Field Bank 模板：`templates/field_bank/{dataset}`
- CONCH 权重：`/data/fangyuxuan/projects/medical_dl/trident_project/CONCH/pytorch_model.bin`

`--dataset all` 覆盖 33 个 TCGA project：ACC, BLCA, BRCA, CESC, CHOL, COAD, DLBC, ESCA, GBM, HNSC, KICH, KIRC, KIRP, LAML, LGG, LIHC, LUAD, LUSC, MESO, OV, PAAD, PCPG, PRAD, READ, SARC, SKCM, STAD, TGCT, THCA, THYM, UCEC, UCS, UVM。其中 LIHC 在 pipeline 里仍写作 `TCGA_LIHC`，对应 `TCGA-LIHC.json`。

---

## JSON 预处理：字典 / 三态缺失 / 时间 / 筛选

统计表只有 `null` / `sentinel` / `valid`。路径抽不到值记入 `null`。`missing = null + sentinel`。

```bash
python scripts/run_scan_fields.py --dataset all
python scripts/run_field_stats.py --dataset all
python scripts/run_field_filter.py --dataset all --write_templates --R3_coverage 0.30 --R4_n_unique 2 --R4_mode_share 0.95 --landmark_time 730
python scripts/run_field_filter.py --dataset all --write_templates --landmark_time 0,365,730,none

python scripts/run_time_stats.py --dataset all
```

产物：

```text
rawdata_stats/{dataset}/scanned_fields.json
rawdata_stats/{dataset}/field_stats.csv
rawdata_stats/{dataset}/{landmark_none|landmark_T}/kept_fields.json
rawdata_stats/{dataset}/{landmark_none|landmark_T}/fliter_log/
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
  {landmark_none|landmark_T}/kept_fields.json
  patient_time_stats_all.png
rawdata_stats/TIME_CRITERIA.md
```

Dead 用 `demographic.days_to_death`；非死亡用 `diagnoses[].days_to_last_follow_up`。这个值是生存统计里的患者级 `last_time`（天），不再当作 Field Bank landmark 起点。`t_write` / `t_record` 两张实现表见 `rawdata_stats/TIME_CRITERIA.md`。R0 只删真正结局字段和日历/时间点泄漏（`year_of_diagnosis`、`year_of_follow_up`、`timepoint_category`）。`--landmark_time T` 时，diagnoses / follow_ups 整层留给 Field Bank 按外部起点 `T` 做取值 mask；`--landmark_time none` 时 R0 整层删除路径含 `diagnoses` / `follow_ups` 的字段。

---

## Field Bank / greedy

先完成上面的扫描、统计、筛选。筛选后按数据集填写 Field Bank 长表，再编码；greedy 是 Field Bank 之后的阶段。

```bash
# 人工填写 templates/field_bank/{dataset}/{landmark_none|landmark_T}/FIELD_BANK.csv
# 先看 example 的原始取值，再裁定 convert/unit，最后填 template。
# convert 允许：空（不换算）、days_to_years、int。

# JSON -> prompt.csv -> CONCH emb；必须给 --landmark_time T（天）或 none
python scripts/run_field_bank.py --dataset all --encoding prompt --landmark_time none
python scripts/run_field_bank.py --dataset all --encoding onehot --landmark_time 365
python scripts/run_field_bank.py --dataset all --encoding prompt --landmark_time 0,365,730,none
python scripts/run_field_bank.py --dataset all --encoding prompt --landmark_time all

# 纵向 Field Bank：按 follow-up 记录编码，并加入 days_since / ECOG/Karnofsky/BMI/weight 变化列
python scripts/run_longitudinal_field_bank.py --dataset all --encoding prompt --landmark_time none
python scripts/run_longitudinal_field_bank.py --dataset all --encoding onehot --landmark_time 365

# step1 JSON -> prompt.csv（仅 prompt）
python scripts/run_field_bank.py --dataset all --encoding prompt --prompts_only --landmark_time 365

# Field Bank 完成后再做范式转换。--dataset 与 --landmark_time 指定已完成的 prompt 基座。
# 产物目录：outputs/{dataset}/schemes/landmark_730_L2 等。
# L2：全部有效句子拼成 1 段
# L3：按 CONCH tokenizer 贪心切 <=127 token 的完整句窗口，不足窗口 pad 成同形状
# L5：按 templates/field_bank/_shared/l5_semantic_groups.csv 把字段合成语义组；缺组用占位句，mask=False
python scripts/run_schemes.py --dataset all --scheme all --prompts_only --landmark_time 730
python scripts/run_schemes.py --dataset all --scheme all --landmark_time 730
python scripts/run_schemes.py --dataset TCGA-READ --scheme L5 --landmark_time 365
python scripts/run_schemes.py --dataset all --scheme all --landmark_time all

# 关闭 landmark 用 --landmark_time none；筛选同样传 none，R0 会整层去掉 diagnoses / follow_ups
python scripts/run_field_filter.py --dataset all --landmark_time none --write_templates
python scripts/run_field_bank.py --dataset all --encoding prompt --landmark_time none

# greedy / univariate 按 (dataset, landmark) 排队。调度器根据 --dataset 与 --landmark_time 自动生成 conf，不用手写。
# --landmark_time 支持 365、none、0,365,none，或 all（扫描该 dataset 已有 landmark_* 目录）。
# 多卡共用同一队列：GPU5 正在跑的 (dataset, landmark)，GPU6 认领不到。
conda activate SurvPGC
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects
CUDA_VISIBLE_DEVICES=7 bash Clinic_Analyzer/bg_greedy.sh GreedyGPU7.log \
    --workers 16 \
    --dataset all \
    --encoding prompt \
    --landmark_time 0 \
    --init_field '{demographic.}' \
    --inner_modality mlp_clinic_flatten \
    --outer_modalities mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
    --seed 0 \
    --min_delta 0.01

CUDA_VISIBLE_DEVICES=6 bash Clinic_Analyzer/bg_greedy.sh GreedyGPU6.log \
    --workers 16 \
    --dataset all \
    --encoding prompt \
    --inner_modality mlp_clinic_flatten \
    --outer_modalities mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
    --init_field '{demographic.}' \
    --landmark_time none \
    --seed 0 \
    --min_delta 0.01

# 纵向 greedy / univariate 走同一套入口，产物写到 outputs/{dataset}/longitudinal/...
python scripts/run_longitudinal_greedy.py --dataset TCGA-BRCA --encoding prompt --landmark_time none --init_field '{demographic.}'
python scripts/run_longitudinal_univariate_cindex.py --dataset TCGA-BRCA --encoding prompt --landmark_time none
python scripts/run_numeric_linear_probe.py --dataset all --encoding prompt --landmark_time 730
```

产物：

```text
templates/field_bank/{dataset}/{landmark_none|landmark_T}/FIELD_BANK.csv
templates/field_bank/{dataset}/{landmark_none|landmark_T}/FIELD_BANK_columns.json
outputs/{dataset}/field_bank/prompt/{landmark_none|landmark_T}/prompts.csv
outputs/{dataset}/field_bank/prompt/{landmark_none|landmark_T}/field_index.json
outputs/{dataset}/field_bank/prompt/{landmark_none|landmark_T}/embeddings/pt/{patient_id}.pt
outputs/{dataset}/field_bank/onehot/{landmark_none|landmark_T}/field_index.json
outputs/{dataset}/field_bank/onehot/{landmark_none|landmark_T}/embeddings/pt/{patient_id}.pt
outputs/{dataset}/field_bank/onehot/{landmark_none|landmark_T}/metadata/
outputs/{dataset}/schemes/{landmark_none|landmark_T}_{L2|L3|L5}/prompts.csv
outputs/{dataset}/schemes/{landmark_none|landmark_T}_{L2|L3|L5}/field_index.json
outputs/{dataset}/schemes/{landmark_none|landmark_T}_{L2|L3|L5}/embeddings/pt/{patient_id}.pt
outputs/{dataset}/greedy/{prompt|onehot}/{landmark_none|landmark_T}/
  run_config.json
  selection_freq.csv
  selection_freq.png
  jobs/{scheme}.json
  subsets/G{k}_{hash}/embeddings/pt/{patient_id}.pt
outputs/{dataset}/longitudinal/field_bank/{prompt|onehot}/{landmark_none|landmark_T}/
  prompts.csv
  field_index.json
  embeddings/pt/{patient_id}.pt
outputs/{dataset}/longitudinal/greedy/{prompt|onehot}/{landmark_none|landmark_T}/
  run_config.json
  subsets/G{k}_{hash}/embeddings/pt/{patient_id}.pt
```

`FIELD_BANK.csv` 按数据集各自填写。`example` 是原始取值，只给人判断单位；看完后再填 `convert` / `unit` / `template`。`convert` 为空则原样填 `{}`。`example`、`unit` 不进入 prompts / embedding。默认 Field Bank：prompt 是 `[n_fields, 512]`；onehot 是 `[n_fields, max_width]`，短字段右侧 0 pad。纵向实验按记录展开：prompt / onehot 都是 `[n_fields * n_records, D]`，同一字段的多次 follow-up 连续排在一起；缺记录用 missing prompt / 空 onehot 行 pad 到该数据集最大记录数。

Landmark 发生在 Field Bank 取值。必须传 `--landmark_time T`、`--landmark_time none`、逗号列表，或 `--landmark_time all`。`none` 关闭取值 mask，且筛选阶段 R0 会整层删除 diagnoses / follow_ups。产物目录统一为 `landmark_{T}` 或 `landmark_none`。门控变量是记录区间上界：槽位自己的有限 `t_hi` 对外部起点 `T`。通过条件是状态为 `point` / `bounded` 且 `t_hi <= T`。`t_write` / `updated_datetime` 不参与。无时间实体不 mask；缺有限 `t_hi` 时该槽按缺失处理，不删列。`field_index.json` 里 `landmark_policy` 为 `t_hi_le_landmark_time` 或 `off`，并记录 `landmark_time`。

---

## 评估

只保留 greedy 在线评估：Field Bank embedding 先编好，然后后台跑调度器。调度器按 `--dataset` 与 `--landmark_time` 自动生成 `Clinic_Analyzer/configs/greedy/{queue,running,done,failed}` 里的 conf 快照，一张卡一次只认领一个 (dataset, landmark)。单卡和多卡走同一条队列，后加的卡会接着认领。dataset 内部的字段选择仍必须串行，因为下一步字段取决于当前 5-fold mean c-index。内层 `greedy_forward` 每一步只加增益最大的字段；如果最好候选的 c-index 增益小于 `--min_delta`（默认 0），则不加该字段并早停。`patience` 仍只用于事后 Wilcoxon 停点，不打断搜索。`--workers` 只并行当前 greedy 步的候选评估。`GreedyGPU5.log` 只记队列认领和 greedy 步，Clinic_Analyzer 训练刷屏不写进去。

`survgc_f` / `survpgc_f` 只允许 BRCA、COAD、KIRC、KIRP、LIHC。KICH、PRAD、READ、STAD 以及其余 ClinicDatasets 都按 clinic 单模态评估；选多模态模型会直接报错。

多模态数据集：BRCA、COAD、KIRC、KIRP、LIHC
单模态数据集：ACC、BLCA、CESC、CHOL、DLBC、ESCA、GBM、HNSC、KICH、LAML、LGG、LUAD、LUSC、MESO、OV、PAAD、PCPG、PRAD、READ、SARC、SKCM、STAD、TGCT、THCA、THYM、UCEC、UCS、UVM

多模态模型：`survgc_f`、`survpgc_f`
单模态模型：`mlp_clinic_mean`、`mlp_clinic_flatten`、`snn_clinic_mean`、`snn_clinic_flatten`

```bash
conda activate SurvPGC
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects
CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_greedy.sh GreedyGPU5.log \
    --workers 8 \
    --dataset all \
    --encoding prompt \
    --inner_modality mlp_clinic_flatten \
    --outer_modalities mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
    --init_field '{demographic.ethnicity,demographic.sex_at_birth,demographic.gender,demographic.race}' \
    --landmark_time 730 \
    --seed 0 \
    --min_delta 0.01
CUDA_VISIBLE_DEVICES=6 bash Clinic_Analyzer/bg_greedy.sh GreedyGPU6.log \
    --workers 8 \
    --dataset all \
    --encoding prompt \
    --inner_modality mlp_clinic_flatten \
    --outer_modalities mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
    --init_field '{demographic.ethnicity,demographic.sex_at_birth,demographic.gender,demographic.race}' \
    --landmark_time 730 \
    --seed 0 \
    --min_delta 0.01
```

对 Field Bank 里筛完后的每个字段单独切 `[1, D]` embedding，用同一个 clinic 模型报 5-fold **val** c-index。这不是 greedy 的一步，也不改选字段。调度器和 greedy 一样按 `--dataset` 与 `--landmark_time` 生成 conf 快照，但队列在 `Clinic_Analyzer/configs/univariate/{queue,running,done,failed}`，不和 greedy 抢任务。一张卡一次只认领一个 (dataset, landmark)；`--workers` 只并行当前任务的字段。`bg_univariate.sh` 后台启动后打出一个 PID 和一个 log。

```bash
conda activate SurvPGC
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects
CUDA_VISIBLE_DEVICES=5 bash Clinic_Analyzer/bg_univariate.sh UniGPU5.log \
    --workers 8 \
    --dataset all \
    --encoding prompt \
    --modality mlp_clinic_flatten \
    --landmark_time none \
    --seed 0
CUDA_VISIBLE_DEVICES=6 bash Clinic_Analyzer/bg_univariate.sh UniGPU6.log \
    --workers 8 \
    --dataset all \
    --encoding prompt \
    --modality mlp_clinic_flatten \
    --landmark_time none \
    --seed 0
```

产物：

```text
outputs/{dataset}/univariate/{encoding}/{landmark_none|landmark_T}/
  field_cindex.csv
  run_config.json
  jobs/{scheme}.json
outputs/{dataset}/longitudinal/univariate/{encoding}/{landmark_none|landmark_T}/
  field_cindex.csv
  run_config.json
```

单字段 embedding 仍走 greedy 的 subset 目录，便于复用缓存：

```text
outputs/{dataset}/greedy/{encoding}/{landmark_none|landmark_T}/subsets/{scheme}/embeddings/pt/{patient_id}.pt
outputs/{dataset}/longitudinal/greedy/{encoding}/{landmark_none|landmark_T}/subsets/{scheme}/embeddings/pt/{patient_id}.pt
```

对 Field Bank 里、GDC dictionary `type` 为 `number` / `integer` 的字段，用 Ridge 在全部有效患者上一次拟合，检查 prompt / CONCH 512-d 行向量能不能线性还原原始数值。这个数据集里完全没值的字段不进表。这是可恢复性检查，不是生存预测，也不走 5 折。`--encoding onehot` 会直接报错。

```bash
conda activate SurvPGC
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects
python scripts/run_numeric_linear_probe.py \
    --dataset TCGA_LIHC \
    --encoding prompt \
    --landmark_time none \
    --seed 0
```

产物：

```text
outputs/{dataset}/linear_probe/prompt/{landmark_none|landmark_T}/
  numeric_r2.csv
  predictions.csv
  run_config.json
```

单数据集把 `--dataset all` 换成 `TCGA-READ`。`run.sh` 会接入 config 快照并调用 `evaluate.py`，不再走 `main.py`。详见 [Clinic_Analyzer/TEST_main_and_runsh.md](Clinic_Analyzer/TEST_main_and_runsh.md)。

## 还要注意

- Field Bank embedding 目前只有 `TCGA_LIHC`。其余 32 个数据集能选、能解析、能读 5-fold，但 greedy 切子集 embedding 时会缺文件。
- `Clinic_Analyzer/data/splits/5foldcv/summary.csv` 只记了 LIHC，没有 33 套 split 的完整清单。
- 纵向实验默认入口是 `scripts/run_longitudinal_*.py`，它们会把 `--experiment longitudinal` 写进队列和产物路径；普通 Field Bank / greedy 不受影响。
- 纵向 Field Bank 在筛选后的字段上额外加入 `follow_ups[].days_since_last_follow_up` 以及 ECOG / Karnofsky / BMI / weight 的相邻记录差值。没有 follow-up 的患者保留 1 条 missing 记录，不回落到整份病历。
