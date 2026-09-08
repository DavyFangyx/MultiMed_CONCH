# Results Directory Guide

`results/` 只放评测表和 run_config，不放 embedding / jobs。

```text
results/{experiment}/{encoding}/{landmark_tag}/{dataset}/
```

`experiment` 取值：`greedy`、`univariate`、`linear_probe`、`longitudinal_greedy`、`longitudinal_univariate`、`schemes`、`A_manual`。

- greedy：`cindex_by_n_fields.csv/.png`、`selection_freq.csv/.png`、`path.json`、`run_config.json`
- univariate：`field_cindex.csv`、`run_config.json`
- linear_probe：`numeric_r2.csv`、`predictions.csv`、`run_config.json`
- A_manual：`cindex.csv`、`run_config.json`；Clinic_Analyzer fold CSV 和 `run.log` 在 `results/A_manual/runs/{study}__{scheme}/{modality}/`

跨数据集汇总写到 `results_display/{experiment}/{encoding}/{landmark_tag}/`。
