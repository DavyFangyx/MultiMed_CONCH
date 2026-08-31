# 混合编码基线改动说明

## 这次已经改好的部分

- `CONCH-main/projects/src/pipeline.py` 里的 baseline 现在固定使用一种混合编码策略：
  - continuous 字段归一化后保留标量
  - ordinal 字段做有序整数映射
  - nominal 字段做 one-hot
- nominal 字段统一规则：
  - `MISSING` 单独保留为一个类别
  - 出现次数 `>= threshold` 的类别保留
  - 出现次数 `< threshold` 的类别合并到 `OTHER`
- 新增参数：
  - `--baseline_nominal_min_count 5`
  - 也可以改成 `10`
- 多数据集运行 baseline 时，会先合并所选数据集患者，生成一份共享的 `category_mapping.json` 和 `feature_schema.json`，再给每个数据集复用。

## 共享 mapping 现在怎么落地

- 全局混合编码 mapping 保存到：
  - `CONCH-main/projects/outputs/baseline_onehot_mapping_tables/category_mapping.json`
- 全局特征布局保存到：
  - `CONCH-main/projects/outputs/baseline_onehot_mapping_tables/feature_schema.json`
- 每个数据集本地 metadata 不再重复保存同一份 nominal mapping。
- 每个数据集只保留：
  - `normalization_stats.json`
  - `global_metadata_ref.json`

## 和原规划不完全一致的地方

- 当前仓库里没有现成的 train/val/test split 文件或 train patient 清单配置。
- 所以现在的“多数据集共享全局映射”统计范围，实际是：
  - 当前命令里选中的数据集全部患者
  - 不是“所有数据集训练集患者”
- 这个偏差不是编码规则问题，是仓库里缺少 split 来源导致的。
- 如果后面补了 train patient 清单，就应该把全局映射统计范围改成“只统计 train patients”。

## 目前保留的字段口径

- 为了不破坏现有 D0-D5 的 23 字段结构，当前仍保留：
  - `YEAR_OF_DIAGNOSIS`
  - `AJCC_PATHOLOGIC_STAGE`
- 当前实现里：
  - `YEAR_OF_DIAGNOSIS` 仍按连续值处理
  - `AJCC_PATHOLOGIC_STAGE` 仍按 ordinal 处理
- 这两个点和设计讨论里“可作为普通类别或直接剔除”的提议还没完全统一。
- 如果后面决定正式剔除它们，需要同步改：
  - `BASELINE_CONTINUOUS_FIELDS`
  - `BASELINE_ORDINAL_FIELDS`
  - `BASELINE_SCHEME_FIELDS`
  - 以及已有输出维度说明

## 建议使用方式

- 单数据集：
  - `python projects/scripts/run_pipeline.py baseline --dataset TCGA-READ --scheme all --baseline_nominal_min_count 5`
- 多数据集共享全局 metadata：
  - `python projects/scripts/run_pipeline.py baseline --dataset all --scheme all --baseline_nominal_min_count 5`
