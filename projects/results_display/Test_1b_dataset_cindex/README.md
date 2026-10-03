# Test_1b 各数据集 Cindex 情况(字段轴链动机)

**问题**:字段能力随数据集而异,每个数据集是不是有**各自的最优字段组合**?

**结论**:是。33 个数据集的 top-1 落在 **18 个不同字段**;top-k 重叠度极低(k=5 时 **47.2% 数据集对零共享**;0 个字段进入全部数据集的 top-10)→ 选字段是应该的(Test_3 的存在理由)。

**文件角色**:`Main_` = 头条(回答命题)、`Appx_` = 附录(明细)、`Raw_` = 原始矩阵、`Meta_` = 元数据。

| 文件 | 角色 | 它想表达的含义 |
|---|---|---|
| `Main_per_dataset_profile.png` | 头条图 | 33 个数据集在共享字段轴上的单字段 c-index 全貌(协议 A 四档分层)——各数据集字段能力画像 |
| `Main_topk_overlap_rate.png` | 头条图1 | 逐 k 平均/中位重叠率(k=5/10/20:0.149/0.197/0.327)——**重叠程度有多低** |
| `Main_topk_zero_share.png` | 头条图2 | 逐 k 零共享占比(47.2% / 13.6% / 0%)——**多少数据集对的最优组合完全不重合**;"0 个字段进入全部数据集的 top-k" |
| `Main_topk_overlap.csv` | 头条表 | 重叠度汇总数字(逐 k,含 Jaccard) |
| `Main_dataset_summary.csv` | 头条表 | 逐数据集:top-1 字段与数值、中位 c、字段跨度、n_event、tier |
| `Appx_per_dataset_distribution.png` | 附录图 | 各数据集**内部**字段 c-index 分布——数据集内换字段的收益空间 |
| `Appx_cross_dataset_field_spread.png` | 附录图 | **同一字段**跨数据集的 c-index 分布——字段能力随数据集变化多大(17/37 字段跨度 ≥ 0.25) |
| `Appx_topk_overlap_matrix.png` | 附录图 | 528 对数据集两两 top-k 重叠率热图(k=5/10/20) |
| `Appx_topk_pairwise_distribution.png` | 附录图 | 每对数据集重叠率的散点分布(Q1/Q3/中位;每点 = 一对数据集) |
| `Appx_field_summary.csv` | 附录表 | 逐字段跨数据集汇总(跨度、出现数据集数)——反证"通吃字段"不存在 |
| `Appx_topk_members.csv` | 附录表 | 每数据集的 top-k 成员字段清单(查"某个数据集最优的是谁") |
| `Appx_topk_pairwise_k{5,10,20}.csv` | 附录表 | 两两数据集重叠率明细 |
| `Raw_cindex_matrix.csv` | 原始矩阵 | dataset × field c-index 全矩阵(底层数据) |
| `Meta_metrics.json` | 元数据 | 聚合指标 |

生成脚本:`results_display/scripts/Test_1b_dataset_cindex.py`(可复跑,diff=0)。
