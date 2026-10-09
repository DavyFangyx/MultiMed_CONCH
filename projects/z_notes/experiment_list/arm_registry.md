# 臂注册表:臂 = 实验条件元组(单一权威来源)

> 本文档是**臂(实验条件)定义的唯一口径来源**。命题层(Test_N)与条件层(臂)分离:
> Test_N 管"要证明什么",臂管"在什么条件下做"。任何文档/代码里的臂名必须能回溯到本表;
> 字母代号(A/B/Bp/C)已退役,只允许出现在历史条目与遗留对照表中。

## 定义格式

```
语义名: 去泄露值
短标签: deleak
F 字段组合: work(论文方案组合)
T 时间口径: lm0(landmark_0 三要件)
P 编码路径: bank 切片(零重编码)
服务对象: Test_3 臂 B(原 B′)、Test_4 档 2、Test_5 {5E_3,5M_3} 的 deleak 臂
────────────────────────────────────────
```

一个臂 = **{F, T, P} 条件元组 + 语义名**。三个因子:

| 因子 | 取值 | 含义 |
|---|---|---|
| F 字段组合 | `work` / `greedy` / `single` | 论文方案组合 / 贪婪搜索最优 / 单字段 |
| T 时间口径 | `raw` / `lm0` | mask 关(含泄露)/ landmark_0 三要件(去泄露) |
| P 编码路径 | `bank 切片` / `field bank` | 现行唯一编码 = field bank 嵌入矩阵切片,零重编码 |

**编码统一(2026-10-07 T31 + 2026-10-09 收尾)**:apipe 全量 CONCH 编码路径已整体删除
(`json2prompt.py`/`encode.py` 及 cli 三子命令);bank 切片是唯一存活的文本编码方式。
Test_5 换 E 轴时 P 被 E 轴值覆盖(如 baseline D-向量),其余因子不变。

## 现行臂表(bank-only)

**报告值**
- 短标签: `report`
- F: work
- T: raw(mask 关)
- P: bank 切片(raw bank 源,`variant="raw"`)
- 服务对象: Test_2b 臂对的 raw 侧、Test_4 档 1、Test_5 {5E_2b,5M_2b} 的 report 臂
- 状态: **待重建**——raw 切片零成本(raw bank 33/33 已齐),训练批次待排期;
  现 Test_4 档 1 仍读冻结历史 apipe 行(见退役臂表),重建后替换
────────────────────────────────────────

**去泄露值**
- 短标签: `deleak`
- F: work
- T: lm0
- P: bank 切片(landmark_0 bank 源)
- 服务对象: Test_3 臂 B(原 B′,scheme = `Test_3_{work}_{dataset}`)、Test_4 档 2、
  Test_5 {5E_3,5M_3} 的 deleak 臂
- 状态: 现行(60 个切片方案登记齐,编码产物 T31 清理后按需 `Test_3_arms.py encode` 重切)
────────────────────────────────────────

**可达值**
- 短标签: `reach`
- F: greedy
- T: lm0
- P: bank 切片
- 服务对象: Test_3 臂 C(scheme = `Test_3_greedy_{dataset}`)、Test_4 档 3、
  Test_5 {5E_3,5M_3} 的 reach 臂
- 状态: 现行
────────────────────────────────────────

**单字段·raw**
- 短标签: `field_raw`
- F: single
- T: raw
- P: field bank 逐字段(raw bank,`outputs/_raw/`)
- 服务对象: Test_1a off 臂
- 状态: 现行
────────────────────────────────────────

**单字段·lm0**
- 短标签: `field_lm0`
- F: single
- T: lm0
- P: field bank 逐字段(landmark_0 bank)
- 服务对象: Test_1a t0 臂、Test_1b 数据源
- 状态: 现行
────────────────────────────────────────

## 退役臂表(冻结历史,只读)

**去泄露值·apipe**
- 短标签: `deleak_apipe`(历史文档中亦作"Test_2b 臂 B")
- F: work
- T: lm0
- P: apipe 全量 CONCH 编码(**已删除**)
- 服务对象: Test_2b 臂 B(历史 552 confs)、Test_2b_delta 的 A−B 对照
- 状态: 退役——底层编码产物已删除,结果表(`results/Test_2b/arm_B` 非 Test_3_* 行)冻结为
  历史口径,仅供历史对照,不再参与现行链路
────────────────────────────────────────

**报告值·apipe**
- 短标签: `report_apipe`(历史文档中亦作"Test_2b 臂 A"、"旧 A_manual")
- F: work
- T: raw
- P: apipe 全量 CONCH 编码(**已删除**)
- 服务对象: Test_2b 臂 A(历史)、Test_4 档 1(现行读这里,**待 report 臂重建后替换**)
- 状态: 退役——结果表(`results/Test_2b/arm_A`)冻结为历史口径
────────────────────────────────────────

## Test_5 子检查 = 轴 × 臂对

| 子检查 | 换的轴 | 重复的臂对 | 备注 |
|---|---|---|---|
| 5E_2b | E→baseline | {`report`, `deleak`}(work 方案集 × baseline 编码) | 历史产物基于已删 apipe 编码,重建批次见下 |
| 5E_3 | E→baseline | {`deleak`, `reach`} | |
| 5M_2b | M→snn / survgc_f / survpgc_f | {`report`, `deleak`}(work 方案集 × text) | 历史产物同上 |
| 5M_3 | M→clinic_cox | {`deleak`, `reach`} | |

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
| `report`(重建后) | 待定(重建批次定) | 待定 |
| `report_apipe`(冻结) | `results/Test_2b/arm_A/{ds}[gdc]/cindex.csv` | `{work}__landmark_none` |
| `deleak` | `results/Test_2b/arm_B/{ds}[gdc]/cindex.csv`(T31 合并行) | `Test_3_{work}_{ds}__landmark_0` |
| `deleak_apipe`(冻结) | 同上表 | `{work}__landmark_0` |
| `reach` | `results/Test_3_greedy_vs_works/two_arm.csv` 的 C_c | `Test_3_greedy_{ds}` |
| `field_raw` | `results/Test_1a/arm_off/` | per-field |
| `field_lm0` | `results/Test_1a/arm_t0/` | per-field |
