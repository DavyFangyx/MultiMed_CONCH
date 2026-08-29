# Codex 3：Task — Field Bank onehot 编码

Audience: 另一个 Codex。只实现 `--encoding onehot`。不要改 greedy 调度，不要改 Analyzer，不要改 prompt 编码。

`src/schemes/` 不存在。`templates/field_bank/` 已就位。`run_field_bank.py --encoding onehot` 现在应报 not implemented。

工作目录：`CONCH-main`。

---

## 目标

给 Field Bank 增加数值编码，和 CONCH prompt 并列。每个字段一行 token，Analyzer 继续用现有 flatten / mean。

输出：

```text
outputs/{dataset}/field_bank/onehot/embeddings/pt/{patient_id}.pt
outputs/{dataset}/field_bank/onehot/field_index.json
outputs/{dataset}/field_bank/onehot/metadata/
  field_types.json
  normalization_stats.json
  category_mapping.json
  feature_schema.json
```

每个 `.pt` 形状：`[n_fields, max_width]`，dtype float32。

- `n_fields` 与 prompt 的 Field Bank 行数、顺序完全一致
- `max_width = max(field_widths)`，短字段右侧 0 pad
- 连续字段 width=1
- 名义/枚举字段 width=该字段 one-hot 维（含 `__MISSING__`、`__OTHER__`）

不要把所有字段拼成一条长向量。不要写 prompts.csv。

---

## 字段顺序

必须和 prompt Field Bank 同一份长表：

```text
templates/field_bank/{dataset}/FIELD_BANK.csv
```

列：`field,example,convert,unit,template`。onehot **不读** `template`。`example` / `unit` 仍不进向量。

`convert` 仍走现有 `src/discovery/converters.py`：空、`days_to_years`、`int`。取值抽取必须复用 Field Bank 现有逻辑（`load_clinical_cases` + 现有 path extract + convert），不要另写 JSON 遍历。

某个字段在该患者缺失：该行全 0 之外，名义字段点亮 `__MISSING__`；连续字段用训练集中位数再 min-max（见下）。

---

## 类型判定（按这个顺序，写死）

对每个 field 单独判定，不要沿用 D0-D5 的人工字段名单。

1. 用 GDC dictionary 的 `type`，按 `(entity, leaf)` join。
   - dictionary：`ClinicDatasets/gdc_clinical/field_tables/gdc_clinical_dictionary.csv`
   - entity 用现有 `ClinicDatasets/gdc_field_tables.py` 的 `mapping_entity(field)`。不要复制一份映射表。把 `gdc_field_tables.py` 的导入路径接好即可；不要重跑 API。
   - 路径去 `[]` 再取 leaf。`diagnoses[].age_at_diagnosis` → entity `diagnosis`，leaf `age_at_diagnosis`。
   - dictionary `type` 可能是 `integer`、`number`、`enum`、`string`、`boolean`，也可能是 `integer|null`、`enum|enum`。判定前先按 `|` 切开，去掉 `null`，剩下的 unique type：
     - 只含 `integer` / `number` → 连续
     - 含 `enum` 或 `boolean` → 名义
     - 只含 `string` → 还不能定，进入下一步
     - join 不上 → 进入下一步
2. 回退 `src/common/types.py` 的 `infer_type(field_name, valid_values, unique_count)`。
   - `numeric` → 连续
   - `ordinal_stage` / `ordinal_class` / `text` / `empty` → 名义
   - **不要**把 stage 做成 1 维整数。全部名义字段都 one-hot。用户不要 D 组那种 ordinal 整数编码。
3. `valid_values` 来自该数据集纳入病例、经过 convert 之后的非缺失值。缺失判定用 `src/common/missingness.py`。

把最终类型写入 `metadata/field_types.json`：每个 field 一行，包含 `field`、`gdc_entity`、`gdc_type`、`final_type`（`continuous` 或 `nominal`）、`source`（`gdc_dictionary` 或 `infer_type`）。

---

## 连续字段

- 同一患者多值：中位数。`AGE_AT_DIAGNOSIS` / `age_at_diagnosis` 如果值 > 365，先 `x / 365.25` 再聚合（与旧 baseline 一致）。
- 拟合：该数据集所有纳入患者的非缺失值，min / max / median。
- 变换：minmax 到 `[0, 1]`。缺失填 median 再 minmax。`max == min` 则写 0。
- 写出 `normalization_stats.json`，字段级 min/max/median。

拟合范围：当前 `--dataset` 列出的每个数据集各自拟合一份。不要做 33 数据集全局词表。`--dataset all` 也是每数据集各写各的 metadata。

---

## 名义字段

对齐旧 D 组口径，但作用在 Field Bank 字段上：

- 缺失 token：`__MISSING__`
- 低频合并：该数据集内频次 `< 5` 的类别合并为 `__OTHER__`
- 多值：先按现有 convert/抽取得到 token 列表，小写 strip，去缺失，排序去重，用 `" | "` join 成一个复合类别，再 one-hot。不要 multi-hot。
- 每个名义字段的 one-hot 必须包含 `__MISSING__` 和 `__OTHER__`
- 写出 `category_mapping.json`：字段 → {category: index}

不要复用 `outputs/_shared/A_manual/baseline_onehot_mapping_tables/`。那是已删除的 A 通路产物。

---

## 向量布局

对患者 P、字段 i：

- 连续：`row[i, 0] = scaled`，`row[i, 1:] = 0`
- 名义：`row[i, code] = 1`，其余 0；如果该字段 width < max_width，右边 pad 0

`feature_schema.json` 必须能从向量还原：

```json
{
  "encoding": "onehot",
  "n_fields": 80,
  "max_width": 17,
  "fields": [
    {"index": 0, "field": "demographic.age_at_index", "type": "continuous", "width": 1},
    {"index": 1, "field": "demographic.race", "type": "nominal", "width": 6, "categories": ["__MISSING__", "__OTHER__", "..."]}
  ]
}
```

`field_index.json` 与 prompt 侧对齐，至少包含 `fields` 列表（顺序与 CSV 一致）和 `encoding: "onehot"`、`n_fields`、`feat_dim`（= max_width）。

Analyzer 读到的是 2D tensor。`mlp_clinic_flatten` 会把 `[n_fields, max_width]` 当 n_fields 个 token、每个 token dim=max_width。这是预期。

---

## CLI 接线

把 CODEX_2 的 onehot 空壳换成真实现。

```bash
python projects/scripts/run_field_bank.py --dataset TCGA-READ --encoding onehot
python projects/scripts/run_field_bank.py --dataset all --encoding onehot
```

不要调用 CONCH，不要读 ckpt。`--ckpt` / `--batch_size` 在 onehot 下忽略即可，不必报错。

`--prompts_only` + `onehot` 继续报错。

代码位置建议：`src/discovery/onehot.py`（或同等模块），由 `src/discovery/field_bank.py` 在 encoding=onehot 时调用。不要把实现塞回已删除的 `src/schemes/baseline.py`。

可参考已删除的 baseline 思路（minmax、`__MISSING__`、`__OTHER__`、频次 5），但必须按 Field Bank 字段动态做，不能写死 AGE/RACE 那张表。

---

## 测试

用很小的假病例，不要读 33 个 JSON。

1. 连续字段：两个值 0 和 10，第三个缺失 → 向量是 0 / 1 / 0.5（median=5）
2. 名义字段：`white` 出现 5 次以上、`unknown_rare` 出现 1 次、缺失 1 次 → rare 进 `__OTHER__`，缺失进 `__MISSING__`
3. 两个字段 width 不同：连续 width=1 + 名义 width=4 → 每个 `.pt` 都是 `[2, 4]`，连续行只有第 0 列非零
4. 字段顺序与传入 fields 列表一致
5. dictionary `integer|null` 被当成连续；`enum` 被当成名义
6. `infer_type` 得到 `ordinal_stage` 的字段仍然 one-hot，不是 1 维整数

跑现有 `tests/test_common_and_filter.py`，确认没被破坏。

---

## 明确不要做

- 不要改 prompt 编码
- 不要改 greedy
- 不要改 Clinic_Analyzer
- 不要全局 33 数据集拟合词表
- 不要输出 1D 拼接向量
- 不要把 ordinal 做成整数等级
- 不要重跑 CONCH / 不要写 GPU 代码

---

## 完成后怎么交审计

最终回复只需要：

1. 改了哪些文件
2. 怎么跑 onehot
3. 用 `TCGA-READ` 或假数据跑出的一个 `.pt` 的 shape
4. `max_width` 怎么来的
5. 测试命令和结果
6. 若没跑真实数据集，明确说只用了单测
