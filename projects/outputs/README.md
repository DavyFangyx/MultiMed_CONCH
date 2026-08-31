# Outputs Directory Guide

`outputs/` 只放 prompt 和 embedding。JSON 字典、三态缺失、时间和筛选在 `rawdata_stats/`。

## Layout

```text
outputs/{dataset}/
  A_manual/
    L{0-5}/prompts.csv
    L{0-5}/embeddings/pt/{patient_id}.pt
    L{0-5}/prompt_stats.csv
    D{0-5}/embeddings/pt/{patient_id}.pt
    metadata/
  B_scan/
    FIELD_BANK/prompts.csv
    FIELD_BANK/field_index.json
    FIELD_BANK/embeddings/pt/{patient_id}.pt
    greedy/

A_pipeline/baseline_onehot_mapping_tables/
```

预处理：

```text
rawdata_stats/{dataset}/scanned_fields.json
rawdata_stats/{dataset}/field_stats.csv
rawdata_stats/{dataset}/kept_fields.json
rawdata_stats/{dataset}/time/
rawdata_stats/_shared/
```

模板：

```text
templates/field_labels.json
A_pipeline/templates/{schemes.json, L0.csv ... L5.csv}
templates/field_bank/{dataset}/FIELD_BANK.csv
```
