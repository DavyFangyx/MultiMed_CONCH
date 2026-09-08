# results_display

把各数据集 `results/` 里的评测表抽到这里做展示，不改 `outputs/`。

```bash
python results_display/scripts/collect_greedy_cindex.py --dataset all --landmark_time 730
python results_display/scripts/collect_greedy_cindex.py --dataset TCGA-STAD,TCGA-BRCA --landmark_time none
python results_display/scripts/collect_univariate_cindex.py --dataset all --landmark_time none
python results_display/scripts/collect_linear_probe_r2.py --dataset all --landmark_time 730
python results_display/scripts/FigA_Other_Paper_Works.py --dataset all --landmark_time 730
```

产物写到 `results_display/{experiment}/{encoding}/{landmark_tag}/`：

- greedy：`cindex_by_n_fields.png/.csv`，以及 `field_gain_matrix.png/.csv`
- univariate：`field_cindex.csv`
- linear_probe：`numeric_r2.csv`
- FigA other paper works：`results_display/FigA_Other_Paper_Works/{encoding}/{landmark_tag}/`
  - 分数据集 PNG：`per_dataset/{dataset}.png`
  - 33 宫格：`cindex_by_n_fields.png`
  - 论文参考线表：`paper_reference_cindex.csv`

FigA 只画 TCGA。蓝色实线是 greedy 增长曲线；论文字段组合按绑定癌种画彩色水平参考线。缺 c-index 的绑定方案会写进 CSV，但不画线。默认 modality 是 `mlp_clinic_flatten`。

`--dataset` 默认 `all`；`--landmark_time` 必填，和 CLI 一样写成天数或 `none`。纵向实验加 `--experiment longitudinal`。
