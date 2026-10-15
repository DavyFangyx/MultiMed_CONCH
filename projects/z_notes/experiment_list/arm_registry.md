# 臂注册表:臂 = 实验条件元组(单一权威来源)

> 本文档是**臂(实验条件)定义的唯一口径来源**。命题层(Test_N)与条件层(臂)分离:
> Test_N 管"要证明什么",臂管"在什么条件下做"。任何文档/代码里的臂名必须能回溯到本表;
> 字母代号(A/B/Bp/C)已退役,只允许出现在历史条目与遗留对照表中。

## 核心模型:先编码,后实验

**编码是一次性的统一基座,不是实验条件。** 全部实验共用同一个 **field bank**——
33 数据集逐字段的 CONCH 文本嵌入矩阵(landmark_0 口径;raw 变体同字段集、mask 关)。
任何方案级嵌入(论文组合、贪婪最优、单字段)都是**从 field bank 按字段索引切片**装配
出来的(零重编码)。因此:

- 臂(实验条件)= **{F 字段组合, T 时间口径} 二元组 + 语义名**;
- "bank 切片"是装配操作,不是条件因子——所有臂天然在同一个编码基座上;
- 历史的 apipe 全量编码之所以是"另一条路径",正因为它**不在** field bank 基座上;
  该路径已整体删除(T31 + 2026-10-09 收尾),遗留产物退役冻结。

## 定义格式

```
语义名: 去泄露值
短标签: deleak
F 字段组合: work(论文方案组合)
T 时间口径: lm0(landmark_0 三要件)
编码基座: field bank 切片(统一基座,所有臂相同,非条件因子)
服务对象: Test_3 臂 B(原 B′)、Test_4 档 2、Test_5 {E_field,M_field} 的 deleak 臂
────────────────────────────────────────
```

两个条件因子:

| 因子 | 取值 | 含义 |
|---|---|---|
| F 字段组合 | `work` / `greedy` / `single` | 论文方案组合 / 贪婪搜索最优 / 单字段 |
| T 时间口径 | `raw` / `lm0` | mask 关(含泄露)/ landmark_0 三要件(去泄露) |

Test_5 换 E 轴时,编码器被 E 轴值覆盖(如 baseline D-向量)——那是 Test_5 的不变性轴,
不是臂的条件因子;M/Q 轴同理。

## 现行臂表(field bank 基座,唯一编码)

**报告值**
- 短标签: `report`
- F: work
- T: raw(mask 关)
- 编码基座: field bank(raw 变体)切片
- 服务对象: Test_2b 臂对的 raw 侧、Test_4 档 1、Test_5 {E_time,M_time} 的 report 臂
- 状态: **已重建(bank 基座)**——`results/paper_raw/` 14 主集 × 4 方案
  (60 runs `.done` 全齐,2026-10-14);Test_4 档 1 已补齐(四档表 report_c 实值)
────────────────────────────────────────

**去泄露值**
- 短标签: `deleak`
- F: work
- T: lm0
- 编码基座: field bank(landmark_0 变体)切片
- 服务对象: Test_2b 臂 B / Test_3 deleak 臂、Test_4 档 2、Test_5 {E_field,M_field} 的 deleak 臂
- 方案名(F×T): `work_lm0_{work}_{ds}`(与 Test_2b 臂 B 同一产物)
- 状态: 现行(字段名单训练时解析,无切片文件;见 runbook 阶段 2)
────────────────────────────────────────

**可达值**
- 短标签: `reach`
- F: greedy
- T: lm0
- 编码基座: field bank(landmark_0 变体)切片
- 服务对象: Test_3 reach 臂、Test_4 档 3、Test_5 {E_field,M_field} 的 reach 臂
- 方案名(F×T): `greedy_lm0_{ds}`(字段 = 搜索 result.json recommended_subset)
- 状态: 现行
────────────────────────────────────────

**原始可达值**
- 短标签: `reach_raw`
- F: greedy
- T: raw(mask 关)
- 编码基座: field bank(raw 变体)切片
- 服务对象: Test_4 档 4(四档对照新增;字段与 reach 同一名单 = 搜索 recommended_subset)
- 方案名(F×T): `greedy_raw_{ds}`(行落 paper_raw 表,与 report 臂同表)
- 状态: 待训(2026-10-14 新增配置,enqueue --arm test_4 生成 conf)
────────────────────────────────────────

**单字段·raw**
- 短标签: `field_raw`
- F: single
- T: raw
- 编码基座: field bank(raw 变体,`outputs/_raw/`)逐字段
- 服务对象: Test_1a off 臂
- 状态: 现行
────────────────────────────────────────

**单字段·lm0**
- 短标签: `field_lm0`
- F: single
- T: lm0
- 编码基座: field bank(landmark_0 变体)逐字段
- 服务对象: Test_1a t0 臂、Test_1b 数据源
- 状态: 现行
────────────────────────────────────────

## 退役臂表(非 field bank 基座的历史产物,冻结只读)

**去泄露值·apipe**
- 短标签: `deleak_apipe`(历史文档中亦作"Test_2b 臂 B")
- F: work
- T: lm0
- 编码: apipe 全量 CONCH 编码(**非 field bank 基座;路径已删除**)
- 服务对象: Test_2b 臂 B(历史 552 confs)、Test_2b_delta 的 A−B 对照
- 状态: 退役——底层编码产物已删除,结果表未留盘(`results/backup/Test_2b/arm_B/` 仅存 labels),
  不再参与现行链路
────────────────────────────────────────

**报告值·apipe**
- 短标签: `report_apipe`(历史文档中亦作"Test_2b 臂 A"、"旧 A_manual")
- F: work
- T: raw
- 编码: apipe 全量 CONCH 编码(**非 field bank 基座;路径已删除**)
- 服务对象: Test_2b 臂 A(历史);Test_4 档 1 **不再读这里**(重跑期间 n/a,待 report 臂重建补齐)
- 状态: 退役——apipe 编码产物已删除,结果表未留盘(`results/backup/` 无 arm_A cindex)
────────────────────────────────────────

## Test_5 子检查 = 轴 × 臂对

| 子检查 | 换的轴 | 重复的臂对 | 备注 |
|---|---|---|---|
| `E_time` | E→onehot_ordinary | {`report`, `deleak`}(时间轴链对照,work 方案集 × onehot bank) | 历史产物基于已删 apipe 编码,重建批次见下 |
| `E_field` | E→onehot_ordinary | {`deleak`, `reach`}(字段轴链对照) | |
| `M_time` | M→snn / survgc_f / survpgc_f | {`report`, `deleak`}(时间轴链对照,work 方案集 × text) | 历史产物同上 |
| `M_field` | M→clinic_cox | {`deleak`, `reach`}(字段轴链对照) | |

Q 轴(IBS / AUC@24/60 / IPCW)不是臂对,是离线指标电池,覆盖全部臂结果。

## 遗留对照表(旧名 → 新名)

| 旧名 | 现名 |
|---|---|
| Test_2b 臂 A | `report`(bank 重建;冻结历史 = `report_apipe`) |
| Test_2b 臂 B | 退役 → `deleak_apipe`;现行同名语义 = `deleak`(bank) |
| Test_3 臂 B(原臂 B′) | `deleak` |
| Test_3 臂 C | `reach` |
| Test_5 代码标签 A / B / Bp / C | `report` / `deleak`(Bp = deleak 的旧标签)/ `reach` |

## 磁盘落点映射(磁盘冻结,不改物理目录)

| 臂 | results 落点 | 行键(scheme 列) |
|---|---|---|
| `report` | `results/paper_raw/{ds}[gdc]/cindex.csv`(runs = `work_raw_*`) | `work_raw_{work}_{ds}` |
| `report_apipe`(冻结) | 已删(apipe 编码产物删除;backup 未留 cindex 表) | `{work}__landmark_none` |
| `deleak` | `results/paper_lm0/{ds}[gdc]/cindex.csv`(T31 合并行) | `work_lm0_{work}_{ds}` |
| `deleak_apipe`(冻结) | 已删(backup/Test_2b/arm_B/ 仅存 labels) | `{work}__landmark_0` |
| `reach` | 训练行与 deleak 同表:`results/paper_lm0/{ds}[gdc]/cindex.csv`(未训时对照回退搜索 best_cv_c_mean);对照表 = `results/greedy_lm0/two_arm.csv` 的 C_c | `greedy_lm0_{ds}` |
| `reach_raw` | 训练行与 report 同表:`results/paper_raw/{ds}[gdc]/cindex.csv` | `greedy_raw_{ds}` |
| `field_raw` | `results/single_raw/univariate/prompt/no_mask/{ds}/` | per-field |
| `field_lm0` | `results/single_lm0/univariate/prompt/landmark_0/{ds}/` | per-field |
