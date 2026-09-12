# Numeric Linear-Probe R2

Audience: 后续实现 `scripts/run_numeric_linear_probe.py` 或复核产物。规则已锁死，不要再发明连续字段名单、目标值或回归口径。
本轮只检查 **prompt / CONCH embedding** 能不能线性还原连续字段的原始数值。不改 Field Bank 编码，不跑 Clinic_Analyzer。

入口：

```bash
conda activate SurvPGC
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects
python scripts/run_numeric_linear_probe.py \
    --dataset TCGA_LIHC \
    --encoding prompt \
    --seed 0
```

默认数据集冒烟用 `TCGA_LIHC`。`--dataset all` / 逗号列表与 greedy 相同。
默认 encoding 是 `prompt`。若显式传入 `--encoding onehot`，直接报错退出：onehot 连续列已经是数值本身，本检查无意义。

---

## 需求

对每个 `final_type == continuous` 的字段：

1. 取出该患者 Field Bank prompt embedding 的对应行，形状 `[512]`。
2. 用和 onehot 相同的转换/聚合规则还原原始数值 y。
3. 在现成 5-fold split 上做 Ridge linear probe：train 拟合，val 算 R2。

R2 很低，说明文本编码器对量级不敏感，连续字段不该走 CONCH。本表是证据，不设硬失败阈值。

---

## 目录

```text
outputs/{dataset}/linear_probe/{encoding}/
  numeric_r2.csv
  predictions.csv
  run_config.json
```

新增路径函数：`src/common/paths.py` 增加 `dataset_linear_probe_dir(dataset, encoding)`。
不要写 PNG。不要写进 univariate / greedy / field_bank 根目录。

---

## CLI

`python scripts/run_numeric_linear_probe.py`

薄入口，`src` 进 `sys.path`，主逻辑放 `src/discovery/linear_probe.py` 或 `src/greedy/linear_probe.py` 之一；推荐 `src/discovery/linear_probe.py`，因为它复用 onehot 的连续字段定义。

| 参数 | 默认 | 规则 |
| --- | --- | --- |
| `--dataset` | 必填 | 支持 `all` 或逗号列表 |
| `--datasets_config` | `datasets.json` | 同 greedy |
| `--encoding` | `prompt` | 只接受 `prompt`；`onehot` 报错 |
| `--field_bank_dir` | `outputs/{dataset}/field_bank/prompt` | 必须已有 `.pt` 和 `field_index.json` |
| `--splits` | `Clinic_Analyzer/data/splits/5foldcv/{study}` | 现成 split，不生成 |
| `--out` | `outputs/{dataset}/linear_probe/prompt` | 覆盖输出根目录 |
| `--alpha` | `1.0` | Ridge L2 |
| `--min_valid` | `10` | 有效患者数少于此值则跳过该字段 |
| `--seed` | `0` | 只写入 run_config，不重切 split |
| `--landmark` | 开 | 与 Field Bank 默认一致；`--landmark_time none` 关闭 |

不要调用 Clinic_Analyzer，不要训练 MLP/SNN。

---

## 连续字段

必须复用 `src/discovery/onehot.py`：

1. 从 Field Bank 模板读字段和 `convert`。
2. `collect_patient_field_values(cases, fields, converts, landmark=...)`
3. `infer_field_types(...)`
4. 只保留 `final_type == "continuous"`

不要用 age/BMI/weight/pack_years 关键字匹配。GDC dictionary 判成 continuous 的字段，即使名字不像数值，也要进表。

有效患者：`aggregate_continuous(tokens, field)` 得到有限浮点数。`n_valid < min_valid` 的字段写 `status=skipped`，不算 error。

---

## 目标值 y

和 onehot 连续列同一套数，只是**不要 min-max**：

- 原始 JSON 取值
- `convert_value` / `extract_converted_tokens`
- landmark 过滤与 Field Bank 相同：`t_record <= last_time`
- `aggregate_continuous`：多值取 median；`age_at_diagnosis` 且 `>365` 时先 `/365.25`，单位是年
- 缺失患者直接丢掉，不要用 median 填补

X 是 prompt Field Bank `.pt` 里该 `field_idx` 的一行，`float32 -> float64`，形状 `[512]`。患者 ID 用 `.pt` stem，必须能对上 split CSV 和 JSON `submitter_id`。

---

## Linear probe

模型：`sklearn.linear_model.Ridge(alpha=1.0, fit_intercept=True)`。
特征：只对该连续字段的 512-d 向量做标准化；scaler 只在当前 fold 的 train 上 fit。
不要 PCA，不要 MLP，不要把别的字段拼进去。

Split 与 univariate / greedy 相同：`load_analyzer_split_dir`。每个 fold：

- 只用该字段 y 有限的患者
- train = split.train 交集有效患者
- val = split.val 交集有效患者
- val 有效点数 `< 3` 的 fold 不进均值，`per_fold` 写 `null`
- 至少 1 个有效 fold 才算 `status=ok`；否则 `status=skipped`

`r2_mean` / `r2_std` 是有效 fold 的 val R2。R2 用 sklearn `r2_score(y_val, y_hat)`。

同时写出 pooled val 预测：每个患者在其 val fold 上的 `y_true` / `y_pred`。同一患者若因 5-fold 的 val=test 重复出现，每个 fold 一行，不要去重。

---

## numeric_r2.csv

列必须是：

```text
field,field_idx,n_valid,r2_mean,r2_std,per_fold,status,error
```

- 成功：`status=ok`
- 有效患者不足或有效 fold 不足：`status=skipped`，R2 列空
- 读 embedding / 拟合失败：`status=error`，继续其他字段
- 成功行按 `r2_mean` 降序；skipped / error 放后面，按 `field_idx` 升序

---

## predictions.csv

列必须是：

```text
field,field_idx,fold,patient_id,y_true,y_pred
```

只写 `status=ok` 且该 fold 实际评了的 val 患者。

---

## run_config.json

至少包含：

```json
{
  "dataset": "TCGA_LIHC",
  "encoding": "prompt",
  "alpha": 1.0,
  "min_valid": 10,
  "n_continuous_fields": 6,
  "n_ok": 5,
  "n_skipped": 1,
  "n_error": 0,
  "landmark": true,
  "target": "onehot_aggregate_continuous_unscaled",
  "model": "ridge",
  "standardize_x": true,
  "split_dir": "...",
  "field_bank_dir": "...",
  "out_dir": "..."
}
```

---

## 测试

加 `tests/test_numeric_linear_probe.py`：

1. toy `.pt`：某一行 embedding = `[y, 0, 0, ...]`，y 为已知连续值；5-fold 后该字段 `r2_mean > 0.95`。
2. 常数或纯噪声行：`r2_mean < 0.2`。
3. 名义字段（`final_type=nominal`）不出现在 CSV。
4. `n_valid < 10` 的连续字段 `status=skipped`。
5. `--encoding onehot` 直接 SystemExit / ValueError。
6. 路径：`dataset_linear_probe_dir("TCGA_LIHC", "prompt")` 指向 `outputs/TCGA_LIHC/linear_probe/prompt`。

单测用临时目录和 stub cases，不要读完整 TCGA JSON 跑 CONCH。

---

## README

紧挨 univariate 命令加一段：连续字段 linear probe R2，指向本 CLI 和产物路径。写明这是 prompt 可恢复性检查，不是生存预测。

---

## 不要做

- 不 min-max y
- 不用 cosine 近似代替 R2
- 不把 BMI/age 写死成字段名单
- 不训练 Clinic_Analyzer
- 不设 R2 硬阈值让流水线失败
