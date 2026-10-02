# 命名公约:Test 编号为主键的三处目录统一

本文档是实验目录命名的**唯一公约来源**。实验编号口径见 `z_notes/Test_series_spec.md`;本页只回答「某个 Test 的产物在三处叫什么」。

## 公约(三句话)

1. **主键 = Test 编号**:`Clinic_Analyzer/configs`(实验定义)、`results`(结果)、`results_display`(展示)三处的目录名都以 `Test_N[ab]` 开头,一眼可对应。
2. **角色/臂用后缀**:一个 Test 有多个臂或角色时,用 `_arm_X` / `_search` / `_t0` / `_off` 等后缀区分,不另造家族名。
3. **configs 家族内保留生命周期子目录**:`queue/ running/ done/ failed/`(`parked/`、`retry_state.json` 按需),调度器只在这层移动 conf。

## 对照表(旧名 → 新名)

| 处 | 旧名 | 新名 | 说明 |
|---|---|---|---|
| `Clinic_Analyzer/configs/` | `univariate` | `Test_1a_t0` | S5 t0 臂(Test_1a 的 t0 数据源),33/33 done |
| `Clinic_Analyzer/configs/` | `univariate_raw` | `Test_1a_off` | Test_1a off 臂 |
| `Clinic_Analyzer/configs/` | `A_manual` | `Test_2b_arms` + `Test_3_arms` | 拆分:Test_2b 两臂 conf 归档到 `Test_2b_arms`;Test_3 臂 B′/C conf 归 `Test_3_arms` |
| `Clinic_Analyzer/configs/` | `E2_selection` | `Test_3_search` | Test_3 贪婪搜索队列 |
| `Clinic_Analyzer/configs/` | `queue` `running` `done` `failed` `z_exp_gen` | 删除 | 空遗留 |
| `results/` | `univariate` | `Test_1a/arm_t0` | |
| `results/` | `univariate_raw` | `Test_1a/arm_off` | 内部 `univariate/prompt/...` 层由写入方构造,保留 |
| `results/` | `leak_audit` | `Test_2a_leak_audit` | |
| `results/` | `A_manual` | `Test_2b/arm_A` | 报告值(Test_4 三档来源) |
| `results/` | `A_manual_landmark` | `Test_2b/arm_B` | 去泄露值(含 Test_3 臂 B′ 合并行) |
| `results/` | `E2_selection` | `Test_3_search` | 搜索缓存 cache.sqlite |
| `results/` | `greedy` `Test_2_selection` | `results/_archive/` | 遗留,空则删 |
| `results_display/` | `leak_audit` | `Test_2a_leak_audit` | 含 scripts/audit_leak.py |
| `Clinic_Analyzer/results_display/` | 遗留脚本 | `results_display/_archive/` | |

保持不变:`results/Test_0_dataset_availability`、`results/Test_3_greedy_vs_works`、`results_display/{Test_1a_field_level,Test_1b_dataset_cindex,Test_2b_delta,Test_3_greedy_vs_works}`、`outputs/`(按 dataset 组织的编码侧,spec 锁定 `outputs/*/{A_manual,field_bank}`)、`rawdata_stats/`。Test_4 收口按本公约建 `results_display/Test_4_three_tiers`。

## 迁移状态

| 步 | 内容 | 状态 |
|---|---|---|
| 1 | 公约文档 + README | 本文档 |
| 2 | 代码路径登记(`src/common/paths.py`)+ 新旧兼容 | 待做 |
| 3 | configs 家族物理迁移(drain-gated) | 待做 |
| 4 | results / results_display 物理迁移(drain-gated) | 待做 |

## 过渡规则

- 物理迁移完成前,代码中的**读**路径一律经 `src/common/paths.py` 解析(新名优先、旧名回退),保证迁移前后都能跑。
- **写**路径的默认值切换必须与对应物理 mv 同一步:configs 队列根随步骤 3 切,results 写路径随步骤 4 切。
- 迁移期间旧名字符串只允许出现在 `paths.py` 的 LEGACY 常量与本文档对照表中。
- `z_notes/Test_series_execution_log.md` 只追加,不修改历史条目。
