# Univariate Field C-Index

Audience: 后续实现 `scripts/run_univariate_cindex.py` 或复核产物。规则已锁死，不要再发明评估口径、目录或模型。
本轮只评 Field Bank 编码表里的**单字段**。不改 greedy 搜索，不改 Field Bank 编码。

入口：

```bash
conda activate SurvPGC
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects
CUDA_VISIBLE_DEVICES=6 python scripts/run_univariate_cindex.py \
    --dataset TCGA_LIHC \
    --encoding prompt \
    --modality mlp_clinic_flatten \
    --workers 8 \
    --seed 0
```

默认数据集冒烟用 `TCGA_LIHC`。`--dataset all` / 逗号列表与 greedy 相同。其余 32 个数据集允许解析，但缺 Field Bank `.pt` 时该数据集失败并写明原因。

---

## 需求

对 `outputs/{dataset}/field_bank/{encoding}/field_index.json` 里的每一个字段：

1. 从已编好的 Field Bank embedding 切出该字段一行，得到 `[1, D]` 患者级 `.pt`。
2. 用 Clinic_Analyzer 训练同一个 clinic 模型。
3. 在现成 5-fold split 上报告 **val c-index**。

这不是把字段压成标量后直接算 concordance，也不是单变量 Cox。空子集 `[]` 不算一行。

---

## 目录

每个数据集、每种 encoding 一份：

```text
outputs/{dataset}/univariate/{encoding}/
  field_cindex.csv
  run_config.json
  jobs/{scheme}.json
```

切出来的单字段 embedding 仍走 greedy 的 subset 目录，便于和 greedy 共用缓存：

```text
outputs/{dataset}/greedy/{encoding}/subsets/{scheme}/embeddings/pt/{patient_id}.pt
outputs/{dataset}/greedy/{encoding}/subsets/{scheme}/embeddings/fields.json
```

`scheme = subset_scheme_name([field_idx])`，即 `G1_{md5[:10]}`。不要为 univariate 再造一套 subset 目录。
不要写 PNG。不要写进 `outputs/{dataset}/greedy/{encoding}/` 根目录，也不要写进 `field_bank/`。

新增路径函数：`src/common/paths.py` 增加 `dataset_univariate_dir(dataset, encoding)`，返回上面的 univariate 根目录。

---

## CLI

`python scripts/run_univariate_cindex.py`

薄入口，和 `scripts/run_greedy_search.py` 一样把 `src` 加进 `sys.path`，然后调 `greedy.univariate_cli:main`（或同等独立模块，不要把逻辑塞进 `greedy/cli.py` 的 greedy parser）。

| 参数 | 默认 | 规则 |
| --- | --- | --- |
| `--dataset` | 必填 | 支持 `all` 或逗号列表 |
| `--datasets_config` | `datasets.json` | 同 greedy |
| `--encoding` | `prompt` | `prompt` 或 `onehot` |
| `--field_bank_dir` | `outputs/{dataset}/field_bank/{encoding}` | 必须已有 `field_index.json` 和 `embeddings/pt/*.pt` |
| `--field_index` | Field Bank 的 `field_index.json` | 字段名和顺序以它为准 |
| `--splits` | `Clinic_Analyzer/data/splits/5foldcv/{study}` | 现成 `splits_*.csv`，不生成 split |
| `--out` | `outputs/{dataset}/univariate/{encoding}` | 覆盖输出根目录 |
| `--modality` | `mlp_clinic_flatten` | 只允许一个 clinic 模型 |
| `--workers` | `8` | 并行评字段，不是并行 fold |
| `--seed` | `0` | 传给 Clinic_Analyzer |
| `--max_epochs` | `None` | 透传 |
| `--conch_python` | conch env python | 切 embedding 时 fallback |
| `--analyzer_python` | SurvPGC env python | 跑 `Clinic_Analyzer/evaluate.py` |

不要加 `--init_field`、`--outer_modalities`、`--min_delta`、`--patience`、`--max_steps`。

`--modality` 校验复用 `greedy.clinic.parse_one_modality` / `ensure_modalities_allowed`。单模态数据集选 `survgc_f` / `survpgc_f` 直接报错。

---

## 评估

字段列表：`load_candidate_fields(dataset, field_index_path=bank/field_index.json)`。顺序就是 `field_idx`。

split：`load_analyzer_split_dir(default_analyzer_split_dir(dataset))`。val 和 test 在这些 CSV 里是同一批 held-out 患者；本功能只读 **val** 分数。

每个字段调用：

```python
ClinicSubsetEvaluator(..., modality=args.modality, for_test=False, split_dir=split_dir).evaluate([i])
```

必须：

- `prefer_val=True` / `for_test=False`
- 切 embedding 用现有 `materialize_subset_embeddings_with_python`
- 已有 subset `.pt` 且数量对得上时 reuse，不重切
- Analyzer job reuse=True
- 从返回 dict 取 `c_index_mean` / `c_index_std` / `per_fold`；不要用 `test_c_index_*`

空子集 `evaluate([])` 的 0.5 占位不写进 CSV。

并行：默认 8 个字段同时 evaluate。可用 `ThreadPoolExecutor`，和 greedy 一步内并行候选同一套路。不要并行多个数据集。

失败：某个字段训练/切 embedding 失败时，该行 `status=error`，`error` 写简短原因，继续跑其余字段。不要 fail-fast。数据集级前置失败（缺 Field Bank、缺 splits、非法 modality）仍直接退出该数据集。

---

## field_cindex.csv

列必须是：

```text
field,field_idx,n_fields,c_index_mean,c_index_std,per_fold,status,scheme,clinic_dir,error
```

- `n_fields` 恒为 `1`
- `c_index_mean` / `c_index_std` 是 5-fold **val**
- `per_fold` 是 JSON 列表，例如 `[0.61,0.58,...]`
- 成功：`status=ok`，`error` 空
- 失败：`status=error`，c-index 列空，`scheme` / `clinic_dir` 能填则填
- 先按成功行 `c_index_mean` 降序，error 行放最后，error 行内部按 `field_idx` 升序

---

## run_config.json

至少包含：

```json
{
  "dataset": "TCGA_LIHC",
  "encoding": "prompt",
  "modality": "mlp_clinic_flatten",
  "n_fields": 40,
  "n_ok": 39,
  "n_error": 1,
  "workers": 8,
  "seed": 0,
  "prefer_val": true,
  "field_bank_dir": "...",
  "split_dir": "...",
  "out_dir": "..."
}
```

---

## 测试

加 `tests/test_univariate_cindex.py`：

1. Stub evaluator：4 个字段，`evaluate([i])` 返回已知分数；跑完全部 singleton 后 CSV 按 val mean 降序，且每个 `n_fields==1`。
2. CLI/parser：默认 `workers=8`，默认 `modality=mlp_clinic_flatten`，没有 `init_field` / `outer_modalities`。
3. 某个字段 `evaluate` raise：该行 `status=error`，其余行仍写出，进程不退出。
4. 路径：`dataset_univariate_dir("TCGA_LIHC", "prompt")` 指向 `outputs/TCGA_LIHC/univariate/prompt`。

不要在单测里真跑 Clinic_Analyzer。

---

## README

在「评估」节 greedy 命令后面加一段：单字段 val c-index，指向本 CLI，并写产物路径。不要把本功能写成 greedy 的一步。

---

## 不要做

- 不改 greedy 选字段逻辑
- 不报 test c-index
- 不画柱状图
- 不默认跑 4 个 clinic 模型
- 不为缺 embedding 的 32 个数据集补编 Field Bank
