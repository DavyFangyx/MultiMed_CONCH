# 命名公约:配置口径(2026-10-14 用户拍板)

本文档是实验目录命名的**唯一公约来源**。配置语义模型(配置=因子元组、实验=配置组)
见同目录 [experiment_list.md](experiment_list.md)「配置口径架构」节;**臂(实验条件)命名的唯一来源 =
[arm_registry.md](arm_registry.md)**(语义名 + 短标签 + 条件元组;字母代号 A/B/Bp/C 已退役)。
本页只回答「某个配置/实验的产物在三处叫什么」。

> 原「Test 编号为主键」口径已于 2026-10-14 退役,旧对照表与迁移记录留档于文末「历史口径」节。

## 公约(三句话)

1. **results/ 按配置(F×T)命名**:`paper_raw` / `paper_lm0` / `greedy_lm0` /
   `single_lm0` / `single_raw`。配置本身不含 Test 编号——它是「条件」,不是「实验」。
2. **实验 = 配置组**:Test 只声明需要哪些配置(enqueue 模板生成 conf);conf 名自带
   家族区分,`Clinic_Analyzer/configs` 统一四桶 `queue/ running/ done/ failed/`
   (不按实验拆目录,`parked/`、`retry_state.json` 按需)。
3. **results_display/ 按 Test 编号**:展示层是配置的**消费者**,每个 Test 只挑它
   声明的配置组做对比/画图,不互相读对方中间产物。

## 现行对照表(配置口径)

| 处 | 命名 | 说明 |
|---|---|---|
| `results/` | `paper_raw` | F=paper × T=raw(report 臂,报告值;旧 `Test_2b/arm_A`) |
| `results/` | `paper_lm0` | F=paper × T=lm0(deleak 臂,去泄露值;旧 `Test_2b/arm_B`,共享 Test_3 deleak 臂) |
| `results/` | `greedy_lm0` | F=greedy × T=lm0(reach 臂,可达值;旧 `Test_3_greedy_vs_works` + `Test_3_search`) |
| `results/` | `single_lm0` | F=single × T=lm0(Test_1a t0 臂;内部 `univariate/prompt/...` 层) |
| `results/` | `single_raw` | F=single × T=raw(Test_1a off 臂;内部 `univariate/prompt/no_mask/...` 层) |
| `results/` | `leak_audit` | Test_2a 泄露审计 |
| `results/` | `labels` / `logs` / `backup` | landmark 结局共享资产 / exp_queue 日志 / 迁移前旧树(只读冻结) |
| `Clinic_Analyzer/configs/` | 四桶 + conf 名 | 全部实验共享;家族目录不拆(flat 布局) |
| `results_display/` | `Test_N` | 保持不变(消费者侧;`Test_1a_field_level` 等) |

保持不变:`outputs/`(按 dataset 组织的编码侧,field bank 基座)、`rawdata_stats/`。

## 过渡规则

- 历史 run_config.json 里写死的旧 results 路径字面量由 `src/common/paths.py` 的
  `LEGACY_TO_TEST_RESULTS` 改写兜底(展示脚本 remap),正常路径不再依赖回退。
- 旧名字符串只允许出现在 `paths.py` 的 LEGACY 常量与本文档「历史口径」节。
- `z_notes/Test_series_execution_log.md` 只追加,不修改历史条目。

## 历史口径(Test 编号,2026-10-14 退役,只读留档)

旧对照表(旧名 → 旧新名)与迁移状态见迁移期 commit(c08bf04 / 60148c6);要点:

| 处 | 旧名 | 迁移期新名 | 配置口径现名 |
|---|---|---|---|
| `Clinic_Analyzer/configs/` | `univariate` | `Test_1a_t0` | 四桶 + conf 名 |
| `Clinic_Analyzer/configs/` | `univariate_raw` | `Test_1a_off` | 四桶 + conf 名 |
| `Clinic_Analyzer/configs/` | `A_manual` | `Test_2b_arms` + `Test_3_arms` | 四桶 + conf 名 |
| `Clinic_Analyzer/configs/` | `E2_selection` | `Test_3_search` | 四桶 + conf 名 |
| `results/` | `univariate` | `Test_1a/arm_t0/univariate` | `single_lm0/univariate` |
| `results/` | `univariate_raw` | `Test_1a/arm_off` | `single_raw` |
| `results/` | `leak_audit` | `Test_2a_leak_audit` | `leak_audit` |
| `results/` | `A_manual` | `Test_2b/arm_A` | `paper_raw` |
| `results/` | `A_manual_landmark` | `Test_2b/arm_B` | `paper_lm0` |
| `results/` | `E2_selection` | `Test_3_search` | `greedy_lm0` |
| `results/` | `greedy` `Test_2_selection` | `results/_archive/` | 已删 |
| `results_display/` | `leak_audit` | `Test_2a_leak_audit` | 不变 |
| `Clinic_Analyzer/results_display/` | 遗留脚本 | `results_display/_archive/` | — |
