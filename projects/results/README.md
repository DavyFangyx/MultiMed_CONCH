# Results Directory Guide

`results/` 按**配置口径**存放评测表与训练产物(配置 = F 字段组合 × T 时间口径,
模型见 `z_notes/experiment_list/experiment_list.md`「配置口径架构」节;臂语义权威 =
`z_notes/experiment_list/arm_registry.md`)。不放 embedding / jobs
(embedding 在 `outputs/`,jobs 在 `Clinic_Analyzer/configs/` 四桶)。

```text
results/
  labels/                  # landmark 派生结局(患者线共享资产;{study}__landmark_0.csv/.json)
  leak_audit/              # Test_2a 逐字段泄露审计(leak_audit_summary.csv、{ds}/G1_*.json)
  paper_raw/               # F=paper × T=raw(report 臂,报告值)
    {ds}[gdc]/cindex.csv   #   评测表(scheme = work_raw_*)
    runs/work_raw_*        #   训练产物(.done = 完成标记,也是 skip 判据)
  paper_lm0/               # F=paper × T=lm0(deleak 臂,去泄露值)
    {ds}[gdc]/cindex.csv   #   scheme = work_lm0_*(T31 合并行)
    runs/work_lm0_*
  greedy_lm0/              # F=greedy × T=lm0(reach 臂,可达值)
    search/                #   搜索落盘({ds}/{modality}/seed_*/result.json;skip 判据)
    cache.sqlite           #   搜索评估缓存
    compare/               #   Test_3_compare per-(dataset, work) JSON
    two_arm.csv            #   两臂表(B=deleak、C=reach)+ missed_fields.csv
  single_lm0/              # F=single × T=lm0(Test_1a t0 臂 field_lm0)
    univariate/prompt/landmark_0/{ds}/mlp_clinic_flatten/field_cindex.csv
  single_raw/              # F=single × T=raw(Test_1a off 臂 field_raw)
    univariate/prompt/no_mask/{ds}/mlp_clinic_flatten/field_cindex.csv
  logs/                    # exp_queue 运行日志
  backup/                  # 迁移前旧 Test 编号目录(只读冻结)
```

- 每个结果归属一个**配置**;Test 编号只活在 `results_display/`(消费者)与队列 conf 侧。
- 历史 run_config.json 里写死的旧路径字面量由 `src/common/paths.py` 的
  `LEGACY_TO_TEST_RESULTS` 改写兜底,随历史产物重生成后退役。
- 各 Test 产物明细(行数、验收口径)见 `z_notes/Test_series_spec.md` 与
  `z_notes/experiment_list/experiment_list.md`。
