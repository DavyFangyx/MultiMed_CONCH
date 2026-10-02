# 编码噪声本底记录(CONCH 全局 padding 长度敏感性)

- **来源**:S5b(Test_1a off 臂)执行报告,2026-10-02;执行日志 S5b 条目;commit `1d3b9bb`。
- **状态**:📦 存档——用户决定"不用管,先记录,留存档案"(不重建 embedding,不做消除处理)。

## 现象

CONCH 文本编码对**全局 padding 长度不完全不变**:同一字段、同一取值的句子,在"整批较长"与"整批较短"的 field bank 里编码出的 512 维向量有极微小差异(transformer 位置编码/注意力随 padding 位置变化)。

Test_1a 两臂 bank 独立构建:

- 臂 off:所有取值都在 → 整批总体更长;
- 臂 t0:部分未来取值被 mask 成缺失占位句 → 整批总体更短。

因此两臂之间存在一个**与 mask 无关的意外差异**(全局 padding 长度),导致"取值未被 mask 改动"的字段也有非零 Δc。

## 数据(首批 3 数据集,97 字段对)

| 组 | Δc 均值 | 中位 | 说明 |
|---|---|---|---|
| mask_affected(取值被 mask 改动的字段) | **+0.0609** | +0.0308 | 真实信号;GBM treatments 前 5 名 +0.151~+0.195 |
| mask_unaffected(取值未改动的字段,对照组) | +0.0017 | +0.0007 | 噪声本底;p90 \|Δc\| = 0.0107,**无一超过 0.05** |

## 判定规则(已固化进 Test_1a 报表)

Δc 归因于 mask 以**显著超过本底(mask_unaffected 分布)**为准;Δc ≥ 0.05 的字段必须同时是 mask_affected。首批数据中 Δc ≥ 0.05 的 17 个字段全部为 mask_affected,满足该规则。

## 备选方案(存档,未执行)

两臂共用同一 tokenizer/padding 上下文重建 embedding,使两臂真正只剩 mask 一个差异——需重跑部分批跑,更干净但耗时。用户决定不执行。

## 关联

- 报表:`results_display/Test_1a_field_level/`(`Test_1a_metrics.json` 含对照组数值)
- 审计:`results/univariate_raw/_audit_pairs.json`、S5b 执行日志条目
