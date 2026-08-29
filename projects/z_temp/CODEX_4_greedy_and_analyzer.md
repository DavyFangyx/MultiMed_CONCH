# Codex 4：Task — greedy 双编码 + Analyzer 路径

把 greedy 接到 prompt/onehot 两套 Field Bank，并把 Clinic_Analyzer 的默认 clinic 路径从 A_manual 改到 field_bank。不要改搜索算法、停点、worker、模型结构。

前置：CODEX_2、CODEX_3 已完成。`outputs/{dataset}/field_bank/{prompt|onehot}/embeddings/pt/*.pt` 的布局已经固定。

工作目录：`CONCH-main`。

---

## 目标

greedy 对两种编码各跑各的。Analyzer 只认：

```text
outputs/{dataset}/field_bank/{encoding}/embeddings/pt
outputs/{dataset}/greedy/{encoding}/subsets/{scheme}/embeddings/pt
```

不再出现 `A_manual` / `B_scan`。

---

## greedy

改 `src/greedy/cli.py`：

- `--encoding {prompt,onehot}`，默认 `prompt`
- Field Bank 输入：`dataset_field_bank_dir(dataset, encoding)`
- 运行产物：`dataset_greedy_dir(dataset, encoding)`

`src/greedy/data.py` 的 `load_field_bank` 必须能读两种目录。判别方式：

1. 优先读 `field_index.json` 的 `encoding`
2. 否则看目录名是 `prompt` 还是 `onehot`
3. 不要用 tensor 最后一维是不是 512 当唯一依据（onehot 的 max_width 也可能碰巧是 512，虽然几乎不会）

`src/greedy/embeddings.py` 的 `subset_embedding_dir` 改为：

```text
outputs/{dataset}/greedy/{encoding}/subsets/{scheme}/embeddings/pt
```

不要再写 `B_scan/greedy`。

`materialize_subset_embeddings` 保持“按行切片”。prompt 是 `[n_fields, 512]`，onehot 是 `[n_fields, max_width]`。切片后仍是 2D tensor，直接 `torch.save`。不要对 onehot 再 mean / flatten / 改成 1D。Analyzer 的 `mlp_clinic_mean` / `mlp_clinic_flatten` 自己做 pooling。

如果当前 `field_bank` 的 `.pt` 还是 dict payload（旧 prompt 格式），prompt 路径继续按现有 `_as_matrix` 解开；onehot 新产物应直接是 tensor。两种都要能切。

`run_config.json` 必须记录 `encoding`。

inner/outer modality 默认值不变：

- inner：`mlp_clinic_flatten`
- outer：`mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten`
- 多模态数据集额外允许 `survgc_f,survpgc_f`

onehot 不要另开一套模型名。token 数 = 字段数，feat_dim = max_width。Analyzer 已有 `_infer_clinic_shape`，会从 `.pt` 推断，不要写死 512 或 6。

后台脚本 `Clinic_Analyzer/bg_greedy.sh` 如果写死了旧路径，改成透传 `--encoding`。不要改调度语义。

---

## Clinic_Analyzer 路径

`Clinic_Analyzer/dataset_deployment/registry.py`：

- `DEFAULT_CLINIC_EXPERIMENT` 从 `"L4"` 改成 `"prompt"`
- `clinic_embedding_dir(study, clinic_experiment=...)` 默认指向：

```text
outputs/{display_name}/field_bank/prompt/embeddings/pt
```

- `resolve_clinic_eval_job` 现在认 `A_manual` 和 `B_scan`。改成认：

```text
.../{dataset}/field_bank/{encoding}/embeddings/pt
.../{dataset}/greedy/{encoding}/subsets/{scheme}/embeddings/pt
```

解析规则写死：

1. 路径必须以 `embeddings/pt` 结尾
2. 若包含 `field_bank`：`display_name` 是它左边那段，`scheme` 用 `field_bank` 右边的 encoding 目录名（`prompt` 或 `onehot`）
3. 若包含 `greedy`：`display_name` 是它左边那段，`scheme` 用 `subsets` 右边的目录名（`G{k}_{hash}`）
4. 其它路径直接报错，列出期望格式。不要再 fallback 到 `A_manual` / `B_scan`

`run_name` 默认仍是 `{study}__{scheme}`。例如 `tcga_lihc__prompt`、`tcga_lihc__G12_ab12cd34ef`。

`Clinic_Analyzer/run.sh` 里现在是：

```bash
CLINIC_DIR=.../A_manual/${CLINIC_EXPERIMENT}/embeddings/pt
```

改成：

```bash
CLINIC_DIR=.../${CLINIC_DISPLAY_NAME}/field_bank/${CLINIC_EXPERIMENT}/embeddings/pt
```

这样 `CLINIC_EXPERIMENT=prompt` 或 `onehot` 就能用。greedy 子集评估不走这个默认，走 `evaluate.py --clinic_dir` 的绝对路径（greedy 已经这么干）。

`evaluate.py` 的 help 文本去掉 `A_manual`，改成 field_bank / greedy 两种例子。

不要改模型、loss、fold、`_infer_clinic_shape`。onehot 的 `[n_fields, max_width]` 和 prompt 的 `[n_fields, 512]` 已经都能被现有 2D loader 吃掉。

---

## 文档

改这些文件里残留的 `A_manual` / `B_scan` / `L4` 默认：

- `Clinic_Analyzer/README.md`
- `Clinic_Analyzer/TEST_main_and_runsh.md`
- `projects/README.md` 若 CODEX_2 还留了 Analyzer 旧路径，一并改准

greedy 命令示例改成：

```bash
conda activate SurvPGC
cd CONCH-main
CUDA_VISIBLE_DEVICES=6 bash projects/Clinic_Analyzer/bg_greedy.sh GreedyGPU6.log \
    --workers 8 \
    --dataset TCGA_LIHC \
    --encoding prompt \
    --inner_modality mlp_clinic_flatten \
    --outer_modalities mlp_clinic_mean,mlp_clinic_flatten,snn_clinic_mean,snn_clinic_flatten \
    --init_field '{demographic.ethnicity,demographic.sex_at_birth,demographic.gender,demographic.race}' \
    --seed 0 \
    --min_delta 0.01
```

onehot 把 `--encoding prompt` 换成 `--encoding onehot`。

不要再提 `gen_D0_6_L0_6_clinic_unimodal.sh`、`L0-L5`、`D0-D5`。

---

## 测试

1. `resolve_clinic_eval_job` 对
   `.../TCGA-BRCA/field_bank/prompt/embeddings/pt`
   得到 `display_name=TCGA-BRCA`、`scheme=prompt`、`study=tcga_brca`
2. 对
   `.../TCGA_LIHC/greedy/onehot/subsets/G3_deadbeef12/embeddings/pt`
   得到 `scheme=G3_deadbeef12`
3. 对旧 `A_manual/L4/embeddings/pt` 必须报错
4. `materialize_subset_embeddings`：假 onehot tensor `[4, 7]` 切 `[0, 2]` 后是 `[2, 7]`，不是 `[2]` 或 `[14]`
5. 假 prompt tensor `[4, 512]` 切完仍是 `[2, 512]`
6. 现有 `tests/test_greedy_scheduler.py` 必须继续过（那是搜索逻辑，不要动）

不要真跑 Analyzer 训练。

---

## 明确不要做

- 不要改 greedy_forward / 停点 / Wilcoxon / worker 数
- 不要改 MLPClinic / SNNClinic
- 不要让 onehot 走 1D clinic 输入
- 不要保留 A_manual / B_scan 兼容
- 不要重新实现 Field Bank 编码

---

## 完成后怎么交审计

最终回复只需要：

1. 改了哪些文件
2. 新默认 clinic 路径
3. greedy `--encoding` 怎么传
4. 两种 clinic_dir 的解析例子
5. 测试命令和结果
6. 全仓库再搜一遍 `A_manual` / `B_scan`，列出还剩哪些（`z_temp/` 和本 TASK 文件可以剩）
