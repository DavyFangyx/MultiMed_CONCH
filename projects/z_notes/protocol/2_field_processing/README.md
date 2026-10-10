# 规则2:字段处理(索引页)

字段线全景一图流见 [`../tcga_pipeline/README.md`](../tcga_pipeline/README.md)(阶段 ①–⑤)。本目录内容:

| 内容 | 权威细节 |
|---|---|
| 字段筛选 R0–R6(R2 编号保留不复用;landmark-first 已扶正) | [`field_filter.md`](field_filter.md)(本目录) |
| PGC 线冻结契约(L0–L5 / D0–D5,外部 SurvPGC 线,与时间轴无关) | [`frozen_schemes_contract.md`](frozen_schemes_contract.md)(本目录) |
| 编码基座:先编码后实验、33 数据集统一 field bank、bank 切片零重编码、臂 = {F,T} | `z_notes/experiment_list/arm_registry.md` |
| 方案 × 数据集绑定(138 组合;HGCN 绑本癌种) | `z_notes/Test_series_spec.md` §2.4 |
| 未决:365/730 landmark 统计缺失时 `run_field_filter` 回退 raw 统计 vs 直接报错 | 执行日志 **D14** 待拍板 |
