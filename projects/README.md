# Projects

This layer keeps clinical workflows separate from the upstream `conch/` code.

## Layout

- `src/`: reusable Python logic for the clinical workflow
- `scripts/`: thin command-line entry points
- `templates/l0_l5/`: current `L0-L5` templates and scheme config
- `templates/v1/`: legacy `O/A/B/C/D` templates and scheme config
- `outputs/`: generated prompts, embeddings, and statistics
- `archive/legacy_v1/`: old backup scripts moved in from the previous layout

## Defaults

- JSON: `/data/lizhe/Medteam_projects/kindey_cancer_TCGA/clinical/clinical.cart.2026-03-17.json`
- template_dir: `CONCH-main/projects/templates/l0_l5`
- prompt_dir: `CONCH-main/projects/outputs/prompts`
- filtered_csv: `/data/fangyuxuan/projects/medical_dl/SurvPGC/patients_index/filtered_patient_id.csv`
- ckpt: `/data/fangyuxuan/projects/medical_dl/trident_project/CONCH/pytorch_model.bin`
- out: `CONCH-main/projects/outputs/embeddings`

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
- The default path set is for the current `L0-L5` workflow. Use `--template_dir projects/templates/v1` when you need the legacy scheme family.
