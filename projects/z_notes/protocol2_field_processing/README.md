# 规则2:字段处理(权威)

字段准入与编码基座的规则本体。执行层流程一图流见 [`../tcga_pipeline/tcga_pipeline.md`](../tcga_pipeline/tcga_pipeline.md)
(阶段 ①–⑤,执行层文档;冲突时以本目录为准)。

| 内容 | 权威细节 |
|---|---|
| 字段筛选 R0–R6(R2 编号保留不复用;landmark-first 已扶正) | [`field_filter.md`](field_filter.md)(本目录) |
| 编码基座:先编码后实验、统一 field bank、bank 切片零重编码、臂 = {F 字段组合, T 时间口径} | [`../experiment_list/arm_registry.md`](../experiment_list/arm_registry.md)(臂注册表) |
| 方案 × 数据集绑定:泛癌种 4 方案 × 全部数据集;HGCN_* 6 方案各绑本癌种 | 执行层引用见 spec §2.4(绑定名单由各方案 fields.json 承载,不硬编码) |
| PGC 线冻结契约(L0–L5 / D0–D5,外部 SurvPGC 线,与时间轴无关) | [`frozen_schemes_contract.md`](frozen_schemes_contract.md)(本目录) |
| 探查附录:R4 豁免 / R5 别名的决策依据(2026-10-08,只读探查记录) | [`probe_paper_scheme_interception_20261008.md`](probe_paper_scheme_interception_20261008.md)、[`probe_r5_alias_and_units_20261008.md`](probe_r5_alias_and_units_20261008.md) |
| 未决:365/730 landmark 统计缺失时 `run_field_filter` 回退 raw 统计 vs 直接报错 | 执行日志 **D14** 待拍板(执行状态,非规则) |
