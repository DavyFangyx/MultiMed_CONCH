# Codex 2：Task — 去掉 A/B 目录，Field Bank 接上 --encoding

Audience: 另一个 Codex。只做路径、CLI 开关、CONCH 输出目录。不要实现 onehot，不要改 greedy 调度，不要改 Analyzer。

前置：`DELETE_A_PATHWAY.md` 已执行。`src/schemes/`、`templates/A_manual/`、`scripts/run_pipeline.py`、`scripts/run_prompt_stats.py` 必须已经不存在。

工作目录：`CONCH-main`，命令形如 `python projects/scripts/...`。

---

## 目标

人工 L0-L5 / D0-D5 已经删掉。剩下一条链：scan → stats → filter → Field Bank → greedy。

目录不再叫 `A_manual` / `B_scan`。两种编码走同一个 `--encoding`：

- `prompt`：现有 CONCH 句向量，默认
- `onehot`：本步只接 CLI 和空壳，真正编码在 CODEX_3

---

## 路径（写死）

改 `src/common/paths.py`：

| 旧 | 新 |
| --- | --- |
| `templates/A_manual` | 删掉相关常量 |
| `templates/B_scan/{dataset}/` | `templates/field_bank/{dataset}/` |
| `outputs/{dataset}/A_manual/` | 删掉 |
| `outputs/{dataset}/B_scan/FIELD_BANK/` | `outputs/{dataset}/field_bank/{encoding}/` |
| `outputs/{dataset}/B_scan/greedy/` | `outputs/{dataset}/greedy/{encoding}/` |
| `outputs/_shared/A_manual/baseline_onehot_mapping_tables/` | 删掉常量 |

函数约定：

- `dataset_field_bank_template_dir(dataset)` → `PROJECT_ROOT / "templates" / "field_bank" / dataset`
- `dataset_field_bank_dir(dataset, encoding="prompt")` → `PROJECT_ROOT / "outputs" / dataset / "field_bank" / encoding`
- `dataset_greedy_dir(dataset, encoding="prompt")` → `PROJECT_ROOT / "outputs" / dataset / "greedy" / encoding`
- 删掉 `dataset_manual_dir`、`dataset_scheme_dir`、`dataset_prompt_dir`、`dataset_embedding_dir`、`dataset_baseline_embedding_dir`、`global_mapping_dir`、`DEFAULT_TEMPLATE_DIR`、`DEFAULT_PROMPT_DIR`、`DEFAULT_OUT_DIR`、`DEFAULT_BASELINE_OUT_ROOT`、`DEFAULT_FIELD_BANK_TEMPLATE_DIR`

合法 encoding 只允许 `prompt`、`onehot`。其它值立刻报错。

把现有磁盘上的 `templates/B_scan/` **改名为** `templates/field_bank/`。33 个数据集子目录和里面的 `FIELD_BANK.csv` 一起搬走，不要复制一份再留旧目录。`templates/B_scan/转换.md` 一并搬走。

更新所有引用这些 path helper 的文件：`src/discovery/field_bank.py`、`src/discovery/filter.py`、`src/discovery/cli.py`、`src/greedy/data.py`、`src/greedy/cli.py`。本步 **不要** 改 `Clinic_Analyzer/`。`src/greedy/embeddings.py` 里的 `B_scan/greedy` 字符串留给 CODEX_4。

---

## CLI

`scripts/run_field_bank.py` / `src/discovery/cli.py` 的 `field_bank_main` 增加：

```text
--encoding {prompt,onehot}   默认 prompt
```

`prompt`：现有行为。读 `templates/field_bank/{dataset}/FIELD_BANK.csv`，写

```text
outputs/{dataset}/field_bank/prompt/prompts.csv
outputs/{dataset}/field_bank/prompt/field_index.json
outputs/{dataset}/field_bank/prompt/embeddings/pt/{patient_id}.pt
```

`--prompts_only` 只对 `prompt` 有效。`onehot` 加 `--prompts_only` 直接报错。

`onehot`：本步只做目录和失败信息，不要假装编完。调用编码函数时：

1. 先 `try` import 一个新模块，例如 `discovery.onehot_encode` 或 `common.onehot`（名字自定，CODEX_3 会填实现）
2. 如果模块/函数不存在，raise 带明确信息：`onehot encoding is not implemented yet; finish CODEX_3`
3. 不要写空 `.pt`，不要写假 `field_index.json`

`run_field_filter.py --write_templates` 的输出改到 `templates/field_bank/{dataset}/FIELD_BANK.csv`。help 文本里的 `templates/B_scan` 全部改掉。

greedy CLI 本步只改默认 Field Bank 路径读取，使 `dataset_field_bank_dir(dataset, encoding)` 能被传入。给 `src/greedy/cli.py` 加 `--encoding`，默认 `prompt`，用来解析 Field Bank 目录。子集物化输出目录先不要改文件内容到 Analyzer；如果当前代码写死 `B_scan/greedy`，先改成调用 `dataset_greedy_dir(dataset, encoding)`，但不要改 Analyzer。若改动会迫使你改 `embeddings.py` 的输出布局，把输出布局留给 CODEX_4，本步只把 helper 接上、旧默认值改成新 helper。

---

## 测试债

`tests/test_common_and_filter.py` 现在 import `schemes.config`。`src/schemes` 已删，这个测试会挂。

删掉 `test_scheme_loader_skips_field_bank` 整段，以及文件顶部的 `from schemes.config import ...`。

保留：

- `test_extract_path_and_primary_diagnosis`
- `test_missingness_three_state`
- `test_filter_rules`
- `test_infer_type_stage_vs_class`

加最小测试：

1. `dataset_field_bank_dir("TCGA-BRCA")` → `.../outputs/TCGA-BRCA/field_bank/prompt`
2. `dataset_field_bank_dir("TCGA-BRCA", "onehot")` → `.../outputs/TCGA-BRCA/field_bank/onehot`
3. `dataset_greedy_dir("TCGA-BRCA", "onehot")` → `.../outputs/TCGA-BRCA/greedy/onehot`
4. 非法 encoding 报错
5. `field_bank_main` 对未知 encoding 报错（可用 `pytest.raises` / 直接调 parser）

不要为 onehot 编码写测试，那是 CODEX_3。

---

## README

改 `projects/README.md`：

- 删掉 A_manual / L0-L5 / D0-D5 / `run_pipeline.py` / `run_prompt_stats.py` 整节
- 布局改成 scan/stats/filter → Field Bank → greedy
- Field Bank 命令改成：

```bash
python projects/scripts/run_field_bank.py --dataset TCGA_LIHC --encoding prompt
python projects/scripts/run_field_bank.py --dataset TCGA_LIHC --encoding onehot
```

- 产物路径改成上面的新目录
- 评估节里“A 组离线评估 / B 组 greedy”改成：只保留 greedy 在线评估。A 组 conf 生成脚本已删，不要再写 `gen_D0_6_L0_6_clinic_unimodal.sh`
- `templates/B_scan` 全部改成 `templates/field_bank`

不要改 `Clinic_Analyzer/README.md`，那是 CODEX_4。

---

## 明确不要做

- 不要实现 onehot 数值编码
- 不要改 Clinic_Analyzer 的 `A_manual` 默认路径
- 不要改 greedy 搜索、停点、worker
- 不要改 R0–R6、`rawdata_stats/`、`field_presence`
- 不要重跑 CONCH
- 不要保留 `A_manual` / `B_scan` 兼容读

---

## 完成后怎么交审计

最终回复只需要：

1. 改了哪些文件
2. `templates/B_scan` 是否已经变成 `templates/field_bank`
3. 新 path helper 的三个例子
4. `run_field_bank.py --help` 里能看到 `--encoding`
5. 测试命令和结果
6. 调用 `--encoding onehot` 时是否按设计报 `not implemented yet`（CODEX_3 完成前这是正确行为）
