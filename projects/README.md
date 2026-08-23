# Projects

临床 JSON 相关流程都在 `projects/`，和上游 `conch/` 分开。

这里有两条互不混用的通路，公共层只负责读数据集和取字段：

```text
datasets.json + clinical JSON
        |
        +-- 通路 A  人工方案（字段已知）
        |     L0-L5 文本方案  /  D0-D5 baseline
        |
        +-- 通路 B  扫描字段（字段未知）
              扫字典 -> 全字段统计 -> R0-R6 筛选 -> Field Bank
```

`L0-L5` / `D0-D5` 的字段清单写死在模板里。Field Bank 的字段来自 JSON 扫描和筛选，不要再把 `FIELD_BANK` 当成第七套 scheme。

## Layout

- `datasets.json`：每个数据集的 clinical JSON 路径；肾癌三套数据共用一份 JSON，靠 `project_ids` 切开
- `src/common/`：两边共用的数据集注册、JSON 读取、字段路径、缺失四态
- `src/schemes/`：通路 A，L0-L5 / D0-D5
- `src/discovery/`：通路 B，扫描、统计、筛选、Field Bank
- `src/time_stats.py`：生存/随访时间统计，独立脚本
- `src/greedy/`：通路 C，嵌套 CV 贪心调度器（先不依赖 Clinic_Analyzer）
- `scripts/`：命令行入口
- `templates/l0_l5/`：L0-L5 句子模板和 `custom_schemes.json`
- `templates/common/json_field_dictionary.json`：扫描时继承的中文释义
- `templates/field_bank/`：通路 B 生成的空模板，第二行需要人工填句子
- `Clinic_Analyzer/`：clinic embedding 评估
- `outputs/`：所有运行产物

## 公共约定

```bash
conda activate conch
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main
```

- `--dataset all` 跑 `datasets.json` 里全部数据集
- 也可以写 `--dataset TCGA-READ` 或 `--dataset TCGA-BRCA,TCGA-READ`
- 肾癌：`--dataset TCGA-KICH,TCGA-KIRC,TCGA-KIRP`
- 不传 `--dataset` 时，走 `--json_path` 单 JSON 模式
- 患者级 `.pt` 统一命名为 `TCGA-XX-XXXX.pt`

默认路径：

- 数据集配置：`projects/datasets.json`
- L0-L5 模板：`projects/templates/l0_l5`
- CONCH 权重：`/data/fangyuxuan/projects/medical_dl/trident_project/CONCH/pytorch_model.bin`

---

## 通路 A：人工方案 L0-L5 / D0-D5

字段已知，模板固定。详细字段说明见 `pipeline.md`（L0-L5）和 `pipeline copy.md`（D0-D5）。

### 1. JSON -> prompt -> CONCH embedding

```bash
# 一步跑完
python projects/scripts/run_pipeline.py pipeline --dataset TCGA-READ --scheme all
python projects/scripts/run_pipeline.py pipeline --dataset all --scheme all

# 拆开跑
python projects/scripts/run_pipeline.py json2prompt --dataset TCGA-READ --scheme all
python projects/scripts/run_pipeline.py encode --dataset TCGA-READ --scheme all

# 只跑某一个 L 方案
python projects/scripts/run_pipeline.py pipeline --dataset TCGA-READ --scheme L3
```

产物：使用 Conch 编码的emb

```text
outputs/{dataset}/prompts/tcga_ki_prompt_L{0-5}.csv
outputs/{dataset}/embeddings/L{0-5}/pt/{patient_id}.pt
```

`json2prompt` 只写 prompt CSV；`encode` 读已有 CSV 做 CONCH 编码；`pipeline` 是两者串联。`--scheme all` 只跑 L0-L5，不会带上 Field Bank。

### 2. D0-D5 baseline

```bash
python projects/scripts/run_pipeline.py baseline --dataset TCGA-READ --scheme all
python projects/scripts/run_pipeline.py baseline --dataset all --scheme all
```

产物：

```text
outputs/{dataset}/embeddings/D{0-5}/pt/{patient_id}.pt
outputs/{dataset}/embeddings/metadata/
outputs/baseline_onehot_mapping_tables/     # 多数据集时的共享 one-hot 词表
```

连续值 Min-Max，序数字段整数编码，名义字段 one-hot。多数据集一起跑时，名义词表按全部选中数据集拟合一份。

### 3. Prompt 层占位率对照

读的是已经生成的 L0-L5 prompt CSV，不读原始 JSON 全字段。

```bash
python projects/scripts/run_prompt_stats.py --dataset all --scheme all
python projects/scripts/run_prompt_stats.py --dataset TCGA-READ --scheme L0
```

产物：

```text
outputs/{dataset}/stats/l0_5/prompt_layer_L{0-5}.csv
outputs/{dataset}/stats/l0_5/prompt_layer_all_schemes.csv
outputs/{dataset}/stats/l0_5/prompt_layer_stats.csv
```

---

## 通路 B：扫描字段 / Field Bank

字段事先未知。先从 JSON 扫并集，再统计、按 R0-R6 筛选，最后才编码。

```bash
# 1. 扫字段字典
python projects/scripts/run_scan_fields.py --dataset all

# 2. JSON 全字段统计
python projects/scripts/run_field_stats.py --dataset all

# 3. R0-R6 筛选，并生成空的 Field Bank 模板
python projects/scripts/run_field_filter.py --dataset all --write_templates

# 4. 人工填写 templates/field_bank/{dataset}_FIELD_BANK_template.csv 的第二行
#    列名不要改，一列一句，句子里写该列占位符

# 5. 编码 Field Bank（句子没填完不要跑）
python projects/scripts/run_field_bank.py --dataset TCGA-READ
python projects/scripts/run_field_bank.py --dataset TCGA-READ --prompts_only   # 只出 prompt，不调 CONCH
```

产物：

```text
outputs/registry/dicts/{dataset}_json_field_dict.json
outputs/registry/{dataset}/field_stats_raw.csv
outputs/registry/field_stats_raw.csv              # 跨数据集总表
outputs/registry/exclusion_log.csv                # 被剔除字段及规则（R0-R5）
outputs/registry/field_registry.csv               # 人工审阅主表，含 keep / portability
outputs/registry/active_fields.json               # 每个数据集最终使用的字段清单
templates/field_bank/{dataset}_FIELD_BANK_template.csv
outputs/{dataset}/field_bank/prompts.csv
outputs/{dataset}/field_bank/field_index.json
outputs/{dataset}/field_bank/pt/{patient_id}.pt
```

不要再用这些旧命令：

```bash
python projects/scripts/run_pipeline.py --scheme FIELD_BANK          # 已移除
python projects/scripts/run_missing_rate_analysis.py                 # 已拆分，见上面通路 A.3 和通路 B.2 / B.3
```

`run_scan_json_field_dict.py` 仍可用，等价于 `run_scan_fields.py`。

---

## 通路 C：贪心字段选择（调度器）

每个候选子集 `S ∪ {f}` 都会先从 Field Bank 切出一份 clinic embedding，再调度 `Clinic_Analyzer/evaluate.py`，读回 c-index 后继续贪心。默认 `--evaluator clinic`。

划分是一套 5-fold：每折 `val` 与 `test` 相同。内层搜索和外层汇报共用这套 split。每个子集 embedding 在一个模型上跑完整 5-fold。`--model mlp,snn` 会为每个模型各跑一条贪心。

```bash
python projects/scripts/run_greedy_search.py \
    --dataset TCGA-READ --evaluator clinic --model mlp --mode mean \
    --outer_folds 5 --seed 0
```

过程产物：

```text
outputs/{dataset}/embeddings/G{k}_{hash}/pt/{patient}.pt   # 该子集的 clinic embedding
outputs/{dataset}/greedy/analyzer_splits/splits_{0-4}.csv
outputs/{dataset}/greedy/jobs/{scheme}.json
Clinic_Analyzer/results/greedy/{study}__{scheme}/{modality}/
```

汇总产物：

```text
outputs/{dataset}/greedy/selection_freq.csv
outputs/{dataset}/greedy/selection_freq.png
outputs/{dataset}/greedy/run_config.json
```

---

## Json原始文件统计 —— 时间统计

```bash
python projects/scripts/run_time_stats.py --dataset all
python projects/scripts/run_time_stats.py --dataset TCGA_LIHC
python projects/scripts/run_time_stats.py --self_test
```

Dead 用 `demographic.days_to_death`；非死亡用 `diagnoses[].days_to_last_follow_up`。产物在 `outputs/time_stats/{dataset}/`。

---

## 评估

```bash
conda activate SurvPGC
cd CONCH-main/projects/Clinic_Analyzer

# 扫描现成 D0-D6 / L0-L6 embedding，生成 clinic 单模态评估 conf
bash configs/z_exp_gen/gen_D0_6_L0_6_clinic_unimodal.sh
bash run.sh configs/queue/encode_eval_d0-6_l0-6__001__tcga_brca__D0__mlp_clinic_mean.conf

# 直接测单个 embedding 目录
python evaluate.py --clinic_dir .../outputs/TCGA-READ/embeddings/D0/pt --modality mlp_clinic_mean,mlp_clinic_flatten

# 通路 B（句子填完并编码后）
python evaluate.py --clinic_dir .../outputs/TCGA-READ/field_bank/pt --modality mlp_clinic_mean,mlp_clinic_flatten
```

`run.sh` 会接入 config 快照并调用 `evaluate.py`，不再走 `main.py`。详见 [Clinic_Analyzer/TEST_main_and_runsh.md](Clinic_Analyzer/TEST_main_and_runsh.md)。
