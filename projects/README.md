# Projects

This layer keeps clinical workflows separate from the upstream `conch/` code.

## Layout

- `datasets.json`: clinical JSON paths for each TCGA dataset
- `src/`: reusable Python logic for the clinical workflow
- `scripts/`: thin command-line entry points
- `templates/l0_l5/`: current `L0-L5` templates and scheme config
- `templates/v1/`: legacy `O/A/B/C/D` templates and scheme config
- `outputs/`: generated prompts, embeddings, and statistics
- `pipeline.md`: `L0-L5` prompt / CONCH embedding pipeline 说明
- `pipeline copy.md`: `D0-D5` baseline pipeline 说明

## Defaults

- datasets_config: `CONCH-main/projects/datasets.json`
- template_dir: `CONCH-main/projects/templates/l0_l5`
- ckpt: `/data/fangyuxuan/projects/medical_dl/trident_project/CONCH/pytorch_model.bin`
- dataset output root: `CONCH-main/projects/outputs/{dataset}/`
- kidney TCGA split from one shared JSON: `TCGA-KICH`, `TCGA-KIRC`, `TCGA-KIRP`

## Entry points

```bash
conda activate conch
cd CONCH-main
python projects/scripts/run_pipeline.py pipeline --dataset all --scheme all

# 0、详细流程说明
# L0-L5 文本 prompt -> CONCH embedding：见 projects/pipeline.md
# D0-D5 baseline mixed encoding：见 projects/pipeline copy.md

python projects/scripts/run_pipeline.py baseline --dataset all --scheme all

# 1、Embedding一共两步 原始数据 clinical JSON -> 结构化病历 prompt CSV -> embeddings

# Step 1 only: generate prompt CSV files from clinical JSON for one dataset
python projects/scripts/run_pipeline.py json2prompt --dataset TCGA-READ --scheme all

# Step 2 only: encode existing prompt CSV files into embeddings for one dataset
python projects/scripts/run_pipeline.py encode --dataset TCGA-READ --scheme all

# Full pipeline for all datasets in datasets.json
python projects/scripts/run_pipeline.py pipeline --dataset all --scheme all

# Full pipeline for one dataset: JSON -> prompt CSV -> embeddings
python projects/scripts/run_pipeline.py pipeline --dataset TCGA-READ --scheme all

# Full pipeline for selected datasets
python projects/scripts/run_pipeline.py pipeline --dataset TCGA-BRCA,TCGA-READ --scheme all

# Kidney TCGA is split into 3 datasets from one shared clinical JSON
python projects/scripts/run_pipeline.py pipeline --dataset TCGA-KICH,TCGA-KIRC,TCGA-KIRP --scheme all

# 2、Analysis 统计原始数据各数据集 clinical JSON 字段删失情况
conda activate conch
cd CONCH-main
python projects/scripts/run_missing_rate_analysis.py --dataset all --scheme all --json_all_fields true

# Analysis only: missing rate / placeholder rate / JSON field stats
python projects/scripts/run_missing_rate_analysis.py --dataset TCGA-READ --scheme all --json_all_fields true

# Analysis for all datasets in datasets.json
python projects/scripts/run_missing_rate_analysis.py --dataset all --scheme all --json_all_fields true

# Legacy v1 templates if needed
python projects/scripts/run_pipeline.py json2prompt --scheme O_simple --template_dir projects/templates/v1 --prompt_dir projects/outputs/prompts/v1
```

## Command Notes

- `json2prompt`
  Reads clinical JSON and writes prompt CSV files for the selected schemes.
- `encode`
  Reads existing prompt CSV files and generates CONCH text embeddings.
- `pipeline`
  Runs `json2prompt` first, then `encode`.
- `baseline`
  Reads clinical JSON directly and writes fixed-width `D0-D5` patient baselines.
  `--scheme` 在 baseline 流程中对应 `D0-D5`；`all` 表示运行全部 `D0-D5`。
- `run_missing_rate_analysis.py`
  Runs statistics only. It does not create embeddings.
  With `--dataset all` or a dataset list, it still writes per-dataset stats under `projects/outputs/{dataset}/stats/`,
  and also writes cross-dataset JSON summary tables under `projects/outputs/stats/`.
  In multi-dataset runs, it also writes `json_layer_stats_by_dataset.png`.

## Notes

- The clinical workflow is now self-contained under `projects/`.
- Generated files under `projects/outputs/` are ignored by `projects/.gitignore`.
- `--dataset all` runs every dataset listed in `projects/datasets.json`; use comma-separated names when you only want a subset.
- `TCGA-KICH`, `TCGA-KIRC`, and `TCGA-KIRP` all read the same kidney clinical JSON and are split by `project.project_id`.
- Without `--dataset`, the scripts still support single-JSON mode via `--json_path`, `--prompt_dir`, and `--out`.
- Baseline uses one fixed mixed encoding strategy: continuous fields are normalized scalars, ordinal fields use ordinal integer mapping, and nominal fields use one-hot.
- Baseline writes to `projects/outputs/{dataset}/embeddings/D{i}/pt/{patient_id}.pt`.
- In multi-dataset runs, shared global `category_mapping.json` and `feature_schema.json` are written under `projects/outputs/baseline_onehot_mapping_tables/`; each dataset keeps local `normalization_stats.json` and a `global_metadata_ref.json`.
- The default path set is for the current `L0-L5` workflow. Use `--template_dir projects/templates/v1` when you need the legacy scheme family.
- For detailed `L0-L5` prompt/embedding processing, see `projects/pipeline.md`.
- For detailed `D0-D5` baseline vector processing, see `projects/pipeline copy.md`.

## C pt文件统一命名格式

### 推荐最终格式

Clinic 患者级特征统一命名为：

```text
TCGA-XX-XXXX.pt
```

示例：

```text
TCGA-3L-AA1B.pt
TCGA-KL-8323.pt
TCGA-BC-A10Q.pt
```

### 命名原则

- 一个 `.pt` 对应一个患者 `case_id`
- 文件名必须能直接包含患者 ID
- 最终训练读取应按患者级而不是 sample UUID 读取
