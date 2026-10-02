# Results Directory Guide

`results/` 只放评测表和 run_config,不放 embedding / jobs。目录命名公约(Test 编号为主键)见 `z_notes/experiment_list/naming_convention.md`。

```text
results/
  Test_0_dataset_availability/          # Test_0 manifest.csv + 各数据集 profile
  Test_1a/
    arm_t0/                              # Test_1a t0 臂(S5 univariate,prompt/landmark_0/{ds}/mlp_clinic_flatten/field_cindex.csv)
    arm_off/                             # Test_1a off 臂(mask off;内部 univariate/prompt/landmark_none/... 层由写入方构造)
  Test_2a_leak_audit/                    # Test_2a 逐字段审计(leak_audit_summary.csv、{ds}/G1_*.json)
  Test_2b/
    arm_A/                               # Test_2b 臂 A = 报告值(含历史 A_manual 结果;Test_4 三档来源)
    arm_B/                               # Test_2b 臂 B = 去泄露值(landmark_0;含 Test_3 臂 B' 合并行)
  Test_3_greedy_vs_works/                # Test_3 搜索 + 三臂(search/ compare/ three_arm.csv missed_fields.csv)
  Test_3_search/                         # Test_3 搜索缓存(cache.sqlite)
  _archive/                              # 遗留目录归档(greedy、Test_2_selection 等)
```

> 物理迁移进行中:旧名(`univariate`、`univariate_raw`、`leak_audit`、`A_manual`、`A_manual_landmark`、`E2_selection`)在迁移完成前仍存在,新旧对照见 `z_notes/experiment_list/naming_convention.md`。

各 Test 产物明细(行数、验收口径)见 `z_notes/Test_series_spec.md` 与 `z_notes/experiment_list/experiment_list.md`。
