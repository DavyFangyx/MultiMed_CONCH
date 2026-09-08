# Outputs Directory Guide

`outputs/` 只放 prompt、embedding，以及 greedy / univariate 的 jobs 和 subset embedding。评测表在 `results/`。JSON 字典、三态缺失、时间和筛选在 `rawdata_stats/`。

## Layout

```text
outputs/{dataset}/
  field_bank/{prompt|onehot}/{landmark_tag}/
    prompts.csv
    field_index.json
    embeddings/pt/{patient_id}.pt
  schemes/{landmark_tag}_{L2|L3|L5}/
    prompts.csv
    field_index.json
    embeddings/pt/{patient_id}.pt
  greedy/{prompt|onehot}/{landmark_tag}/
    jobs/
    subsets/{scheme}/embeddings/pt/{patient_id}.pt
  univariate/{prompt|onehot}/{landmark_tag}/
    jobs/
  A_manual/
```

评测表：

```text
results/{greedy|univariate|linear_probe|longitudinal_greedy|longitudinal_univariate}/{encoding}/{landmark_tag}/{dataset}/
```

预处理：

```text
rawdata_stats/{dataset}/scanned_fields.json
rawdata_stats/{dataset}/field_stats.csv
rawdata_stats/{dataset}/{landmark_tag}/kept_fields.json
rawdata_stats/_shared/
```
