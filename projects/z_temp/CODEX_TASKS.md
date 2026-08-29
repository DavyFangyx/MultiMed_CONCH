# Codex 任务拆分：去掉 A 通路，Field Bank 改成 prompt / onehot

先自己按 `DELETE_A_PATHWAY.md` 删文件。然后按 2 → 3 → 4 串行交给 Codex。不要并行。

| 文件 | 谁做 | 依赖 |
| --- | --- | --- |
| `DELETE_A_PATHWAY.md` | 你 | 无 |
| `CODEX_2_paths_and_encoding_switch.md` | Codex | 删除完成 |
| `CODEX_3_onehot_encoder.md` | Codex | CODEX_2 |
| `CODEX_4_greedy_and_analyzer.md` | Codex | CODEX_3 |
| `CODEX_5_field_bank_convert_unit_template.md` | Codex | 可与 2–4 并行；不要同时改同一份 FIELD_BANK.csv |

不要重跑 33 个 JSON，不要改 R0–R6，不要改 `rawdata_stats/` 口径，不要改 greedy 搜索逻辑。

最终布局：

```text
outputs/{dataset}/field_bank/{prompt|onehot}/
  prompts.csv                  # 仅 prompt
  field_index.json
  embeddings/pt/{patient}.pt
  metadata/                    # 仅 onehot

outputs/{dataset}/greedy/{prompt|onehot}/
  run_config.json
  jobs/{scheme}.json
  subsets/G{k}_{hash}/embeddings/pt/{patient}.pt
```

Analyzer 继续吃 `.../{scheme}/embeddings/pt/*.pt`。prompt 是 `[n_fields, 512]`；onehot 是 `[n_fields, max_width]`，短字段右侧 0 pad。
