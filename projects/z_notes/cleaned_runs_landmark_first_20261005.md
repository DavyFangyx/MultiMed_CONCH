# 清理记录 2026-10-05:landmark-first 扶正——旧 raw-first 口径运行产物(用户指令)

**决策**:landmark 必须在 R3/R4 之前(选项 C 拍板)。之前的 raw-first 口径运行归为**错误**:
官方 `landmark_0/kept_fields.json` 及其下游产物全部以 landmark-first(t0stats)替换;
旧运行产物该删除的删除、该移走的移走。重跑范围见待决事项 T30。

## 扶正(替换官方产物)

- `rawdata_stats/{ds}/landmark_0_t0stats/{kept_fields.json, fliter_log/}` →
  官方 `rawdata_stats/{ds}/landmark_0/`(36 数据集:33 TCGA + CPTAC + MMRF + `_shared`);
  `landmark_0/field_stats.csv` 本就是 landmark-first 统计,原位保留;t0stats 目录移除。
- 旧官方 raw-first 产物(`landmark_0/kept_fields.json` + `fliter_log/`)移走至
  `z_notes/backup/landmark_first_promotion_20261005/rawdata_stats_legacy/`。
- 代码扶正:`run_field_filter` 在 landmark 开启且对应 landmark 统计存在时,
  默认消费 landmark-first 统计(显式 `--stats_csv` 仍可覆盖);
  `scripts/run_landmark_first_filter.py` 改为直接写官方目录(去掉 `--out_suffix`);
  Test_1a 报表默认读官方 `landmark_0/fliter_log/`。

## 删除路径(旧 kept_fields 口径的下游,可重跑再生)

- 921M `outputs/{ds}/field_bank/prompt/landmark_0/`(35 数据集:33 TCGA + CPTAC + MMRF)
- 17G  `outputs/_raw/`(Test_1a off 臂 raw bank 变体)
- 5.2G `results/Test_1a/`(arm_t0 + arm_off,43,528 文件;univariate 逐字段 checkpoint/结果)

## 移走路径(小结,供对账)

- `results/Test_1a/{arm_t0,arm_off}/**/field_cindex.csv`(逐数据集)→
  `z_notes/backup/landmark_first_promotion_20261005/{arm_t0,arm_off}_field_cindex/`
- `results/Test_1a/arm_off/_s5b_report.json`、`_audit_pairs.json` → 同上
- 旧官方 `landmark_0/{kept_fields.json, fliter_log/}` → 见"扶正"节

## 未动(有专门归属)

- `results/Test_2a_leak_audit/`:用户接手资产;kept 字段列表缩减后 field_idx 重排,
  G1 审计需按新 kept 列表重跑(待用户)。
- `results_display/Test_1a_field_level/`、`Test_1b_dataset_cindex/`:口径修正后的报表产物
  留在磁盘,待两臂重跑后由脚本重出(重跑前两脚本会报 missing 并 pending 退出)。
- `A_pipeline/templates/`(schemes.json 与 Test_3_greedy_* 模板)、`rawdata_stats/{ds}/landmark_none/`:
  与本次口径无关。
- CPTAC/MMRF 的 `landmark_365/730/none` bank:不同变体,不在本次修正范围。

## 进程

- 无(本轮纯文件操作,无训练进程)
