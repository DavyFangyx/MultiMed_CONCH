# results_display

把各数据集 greedy 产物抽到这里做展示，不改 `outputs/`。

当前只汇总 prompt greedy 的 `cindex_by_n_fields.png` / `cindex_by_n_fields.csv`。

```bash
python results_display/scripts/collect_greedy_cindex.py --dataset all --landmark_time 0
python results_display/scripts/collect_greedy_cindex.py --dataset TCGA-STAD,TCGA-BRCA --landmark_time none
```

产物写到 `results_display/greedy/{encoding}/{landmark_tag}/`：

- `cindex_by_n_fields.png`：按 `datasets.json` 顺序拼成 6 列网格，每格顶部写数据集名
- `cindex_by_n_fields.csv`：原 greedy 步级明细纵向拼接，并加 `dataset,encoding,landmark_tag`
- `field_gain_matrix.png` / `field_gain_matrix.csv`：后续 greedy 步里真正抬升 c-index 的字段 × 数据集；格子颜色是该字段带来的 Δ c-index，空白表示没有增长

`--dataset` 默认 `all`；`--landmark_time` 必填，和 greedy CLI 一样写成天数或 `none`。
