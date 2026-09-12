# 先删这些：A 通路（L0-L5 / D0-D5）

你来删。删完再开 `CODEX_2`。不要先跑测试，`src/schemes` 一删，`tests/test_common_and_filter.py` 会暂时 import 失败，这是预期的。

工作目录：`CONCH-main/projects`。

---

## 必须删

代码：

```text
src/schemes/                      # 整目录
scripts/run_pipeline.py
scripts/run_prompt_stats.py
```

模板：

```text
templates/A_manual/               # L0.csv … L5.csv, schemes.json
```

A 组离线评估脚本（只扫 L/D embedding 写 conf）：

```text
Clinic_Analyzer/configs/z_exp_gen/gen_D0_6_L0_6_clinic_unimodal.sh
Clinic_Analyzer/configs/z_exp_gen/gen_FigB_clinical_prompt_test.sh
Clinic_Analyzer/configs/z_exp_gen/gen_Clinictest_Li.sh
```

---

## 建议一起删的生成物

不删也能改代码，只是占盘、路径马上会作废：

```text
outputs/*/A_manual/
outputs/_shared/A_manual/
```

如果 `Clinic_Analyzer/configs/queue/` 里还有这些 conf，一并清掉：

```text
clinictest_li__*
encode_eval_d0-6_l0-6__*
FigB / Clinical_Prompt_Test 相关
```

---

## 不要删

- `src/discovery/` `src/greedy/` `src/common/` `src/time_stats.py`
- `templates/B_scan/`（TASK 2 会改名为 `templates/field_bank/`）
- `templates/field_labels.json`
- `rawdata_stats/`
- `scripts/run_scan_fields.py` `run_field_stats.py` `run_field_filter.py` `run_field_presence.py` `run_field_bank.py` `run_greedy_search.py` `run_time_stats.py` `run_missing_rate_analysis.py`
- `Clinic_Analyzer/` 主体：`evaluate.py` `run.sh` `dataset_deployment/registry.py` 由 TASK 4 改，不要先删

---

## 删完后仍会留下的 A/B 字符串

这些交给后面的 TASK，不要手改：

| 位置 | 谁改 |
| --- | --- |
| `src/common/paths.py` 的 `A_manual` / `B_scan` | CODEX_2 |
| `tests/test_common_and_filter.py` 的 `schemes.config` | CODEX_2 |
| `README.md` A_manual / L0-L5 / D0-D5 | CODEX_2 |
| `Clinic_Analyzer/evaluate.py` `run.sh` `registry.py` | CODEX_4 |
| `src/greedy/embeddings.py` 的 `B_scan/greedy` | CODEX_4 |
| `src/discovery/cli.py` help 里的 `B_scan` | CODEX_2 |

---

## 建议删除命令

```bash
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects
rm -rf src/schemes templates/A_manual
rm -f scripts/run_pipeline.py scripts/run_prompt_stats.py
rm -f Clinic_Analyzer/configs/z_exp_gen/gen_D0_6_L0_6_clinic_unimodal.sh
rm -f Clinic_Analyzer/configs/z_exp_gen/gen_FigB_clinical_prompt_test.sh
rm -f Clinic_Analyzer/configs/z_exp_gen/gen_Clinictest_Li.sh
```

生成物可选：

```bash
rm -rf outputs/*/A_manual outputs/_shared/A_manual
```

---

## 删完怎么验收

```bash
test ! -e src/schemes
test ! -e templates/A_manual
test ! -e scripts/run_pipeline.py
test ! -e scripts/run_prompt_stats.py
ls src/discovery src/greedy scripts/run_field_bank.py templates/B_scan
```

四条 `test` 都应静默成功。然后把 `CODEX_2_paths_and_encoding_switch.md` 交给 Codex。
