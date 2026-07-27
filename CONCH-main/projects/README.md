# Projects

This layer keeps clinical workflows separate from the upstream `conch/` code.

## Layout

- `src/`: reusable Python logic for the clinical workflow
- `scripts/`: thin command-line entry points
- `templates/`: project-layer template assets
- `configs/`: project-layer scheme and path configs
- `outputs/`: generated prompts, embeddings, and statistics

## Defaults

- JSON: `/data/lizhe/Medteam_projects/kindey_cancer_TCGA/clinical/clinical.cart.2026-03-17.json`
- template_dir: `CONCH-main/prompt_generate/templates`
- prompt_dir: `CONCH-main/prompt_generate/prompt`
- filtered_csv: `/data/fangyuxuan/projects/medical_dl/SurvPGC/patients_index/filtered_patient_id.csv`
- ckpt: `/data/fangyuxuan/projects/medical_dl/trident_project/CONCH/pytorch_model.bin`
- out: `/data/fangyuxuan/projects/medical_dl/trident_project/TRIDENT_workspace/clinical_embeddings`

## Entry points

```bash
conda activate conch
cd CONCH-main

# 一共两步 原始数据 clinical JSON -> 结构化病历 prompt CSV -> embeddings

# Step 1 only: generate prompt CSV files from clinical JSON
python projects/scripts/run_pipeline.py json2prompt --scheme all

# Step 2 only: encode existing prompt CSV files into embeddings
python projects/scripts/run_pipeline.py encode --scheme all

# Full pipeline: JSON -> prompt CSV -> embeddings
python projects/scripts/run_pipeline.py pipeline --scheme all

# Analysis only: missing rate / placeholder rate / JSON field stats
python projects/scripts/run_missing_rate_analysis.py --scheme all --json_all_fields true
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

- The current working defaults still point to the original root-level paths under `prompt_generate/` and `TRIDENT_workspace/`.
- `outputs/prompts/`, `outputs/embeddings/`, and `outputs/stats/` keep their own `.gitignore` files so generated artifacts stay out of git.
- `templates/` and `configs/` are reserved project-layer locations for later migration of real files.
