# Projects

This layer keeps clinical workflows separate from the upstream `conch/` code.

## Layout

- `datasets.json`: clinical JSON paths for each TCGA dataset
- `src/`: reusable Python logic for the clinical workflow
- `scripts/`: thin command-line entry points
- `templates/l0_l5/`: current `L0-L5` templates and scheme config
- `templates/v1/`: legacy `O/A/B/C/D` templates and scheme config
- `outputs/`: generated prompts, embeddings, and statistics

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

# 一共两步 原始数据 clinical JSON -> 结构化病历 prompt CSV -> embeddings

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

# Analysis only: missing rate / placeholder rate / JSON field stats
python projects/scripts/run_missing_rate_analysis.py --dataset TCGA-READ --scheme all --json_all_fields true

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
- `run_missing_rate_analysis.py`
  Runs statistics only. It does not create embeddings.

## Notes

- The clinical workflow is now self-contained under `projects/`.
- Generated files under `projects/outputs/` are ignored by `projects/.gitignore`.
- `--dataset all` runs every dataset listed in `projects/datasets.json`; use comma-separated names when you only want a subset.
- `TCGA-KICH`, `TCGA-KIRC`, and `TCGA-KIRP` all read the same kidney clinical JSON and are split by `project.project_id`.
- Without `--dataset`, the scripts still support single-JSON mode via `--json_path`, `--prompt_dir`, and `--out`.
- The default path set is for the current `L0-L5` workflow. Use `--template_dir projects/templates/v1` when you need the legacy scheme family.

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