# HGCN Clinic PKL 实现方案

给后续 Codex 落地用。这是新研究里的消融基线，不是论文 clinic 字段的复现。

**字段、类型、缺失判定全部锁死 A_pipeline 现有 L0-L5 / D0-D5。** HGCN 只改两件事：把每个字段做成一个图节点，以及把 D 组 nominal 的 one-hot 改成整数编码。连续/有序字段的取值规则不要另起一套。

本方案只做 clinic 图节点。不切 WSI，不做 RNA，不封装 `all_data.pkl`。

---

## 0. 先读这些

- 本文件
- [README.md](README.md)
- [templates/L0/fields.json](templates/L0/fields.json) 到 [templates/L5/fields.json](templates/L5/fields.json)（L0-L5 字段列表）
- [src/baseline.py](src/baseline.py)（D0-D5 字段列表、连续/有序/名义划分、ordinary 编码、缺失判定）
- [src/extract.py](src/extract.py)
- [src/missingness.py](src/missingness.py)
- [src/clinical_io.py](src/clinical_io.py)
- [src/cli.py](src/cli.py)
- [src/datasets.py](src/datasets.py)
- SurvPGC：`models/missing_modality_baselines/third_party/HGCN/gendata.ipynb` 的 clinic 两格（只抄 pipeline，不抄字段表）

不要对照 HGCN Supplementary 的 Race/BMI/Radiation 表。那是另一篇论文的字段，不是这次实验的字段。

---

## 1. 一句话

对已经明确的 **数据集 × L0-L5 字段组合**，用 HGCN 原文的 clinic 处理风格编码：

```text
同一批 GDC JSON
  -- extract_values / build_patient_rows（已有）-->  每个字段一个原始值
  -- 连续保持标量，有序/名义变成整数，缺失保持 None -->  ttt_cli_feas.pkl
  -- 队列内、只对观测值做对称 min-max 到 [-1, 1] -->  t_cli_feas.pkl
  -- 每个字段一个节点，对角放入 1024 维 -->  x_cli.pkl
  -- 全连接无自环 -->  edge_index_cli.pkl
```

不要换字段。不要填补缺失。不要把所有字段拼成一条 D 组向量。

---

## 2. 和 L / D 的关系

| 通路 | 字段 | 每个字段怎么编码 | 产物形态 |
|---|---|---|---|
| L0-L5 | `templates/{scheme}/fields.json` 的 fields | 模板句子 → CONCH | `(n_fields, 512).pt` |
| D0-D5 | 与 L 完全同一套字段 | 连续 `[0,1]` min-max（缺失填中位数）；有序整数（缺失当 0）；名义 one-hot（缺失是 `__MISSING__` 维） | 变长拼接向量 `.pt` |
| **HGCN_clinic / L0-L5** | **还是这套字段，一个字段也不许改** | 连续保持标量；有序/名义都是一个整数；**缺失保持 None**；再按 HGCN 做对称 min-max + 对角 pad | **pkl 图节点** |

L0 和 D0、L1 和 D1、…、L5 和 D5 字段列表已经对齐。HGCN 按 L 方案名建目录，类型划分直接用 D 组那三张表。

三者并列，目录不要互相覆盖。

---

## 3. 字段列表（锁死，按 L/D 抄）

从 `SCHEME_FIELDS` / `templates/{scheme}/fields.json` 原样复制，顺序就是节点顺序。禁止重排，禁止增删。

```text
L0 / 4 节点:
  demographic.age_at_index, demographic.sex_at_birth, demographic.race, demographic.ethnicity

L1 / 10 节点:
  L0 + diagnoses[].primary_diagnosis, diagnoses[].morphology, diagnoses[].tissue_or_organ_of_origin,
       diagnoses[].laterality, diagnoses[].year_of_diagnosis, diagnoses[].age_at_diagnosis

L2 / 14 节点:
  L1 + diagnoses[].tumor_grade, diagnoses[].prior_malignancy, diagnoses[].synchronous_malignancy, diagnoses[].prior_treatment

L3 / 19 节点:
  L2 + diagnoses[].ajcc_pathologic_t, diagnoses[].ajcc_pathologic_n, diagnoses[].ajcc_pathologic_m,
       diagnoses[].ajcc_pathologic_stage, diagnoses[].ajcc_staging_system_edition

L4 / 21 节点:
  L3 + diagnoses[].pathology_details[].lymph_nodes_tested, diagnoses[].pathology_details[].lymph_nodes_positive

L5 / 23 节点:
  L4 + follow_ups[].ecog_performance_status, follow_ups[].other_clinical_attributes[].bmi
```

代码里不要再维护一份字段表。直接：

```python
from src.config import SCHEME_FIELDS

HGCN_SCHEME_FIELDS = {
    "L0": SCHEME_FIELDS["L0"],
    "L1": SCHEME_FIELDS["L1"],
    "L2": SCHEME_FIELDS["L2"],
    "L3": SCHEME_FIELDS["L3"],
    "L4": SCHEME_FIELDS["L4"],
    "L5": SCHEME_FIELDS["L5"],
}
```

`N_cli = len(fields)`。L0=4，L1=10，L2=14，L3=19，L4=21，L5=23。**禁止抄 notebook 的 `for i in range(10)`。**

### 3.1 明确不要做的字段改动

- 不要改用 `demographic.gender`。L/D 用的是 `demographic.sex_at_birth`
- 不要加入 Radiation / Pharmaceutical / Pack_years_smoked / Years_smoked / Alcohol
- 不要按癌种换字段表。9 个数据集都跑同一套 L0-L5
- 不要用 L4 的 21 句当唯一方案；L0 到 L5 都要出

---

## 4. 连续 / 有序 / 名义（锁死 D 组划分）

从 `src/baseline.py` 原样用，不要重新分类：

```text
连续 BASELINE_CONTINUOUS_FIELDS:
  demographic.age_at_index, diagnoses[].year_of_diagnosis, diagnoses[].age_at_diagnosis,
  diagnoses[].pathology_details[].lymph_nodes_tested, diagnoses[].pathology_details[].lymph_nodes_positive, follow_ups[].other_clinical_attributes[].bmi

有序 BASELINE_ORDINAL_FIELDS:
  diagnoses[].tumor_grade, diagnoses[].ajcc_pathologic_t, diagnoses[].ajcc_pathologic_n,
  diagnoses[].ajcc_pathologic_m, diagnoses[].ajcc_pathologic_stage, follow_ups[].ecog_performance_status

名义 BASELINE_NOMINAL_FIELDS:
  demographic.sex_at_birth, demographic.race, demographic.ethnicity, diagnoses[].primary_diagnosis, diagnoses[].morphology,
  diagnoses[].tissue_or_organ_of_origin, diagnoses[].laterality, diagnoses[].prior_malignancy,
  diagnoses[].synchronous_malignancy, diagnoses[].prior_treatment, diagnoses[].ajcc_staging_system_edition
```

这就是 one-hot 通路已经告诉你的类型信息。HGCN 不要另发明一套。

---

## 5. 取值：复用现有抽取，不要新写 JSON 路径

输入沿用 A_pipeline：

- `datasets.json` + `load_clinical_cases(json_paths, project_ids)`
- 病人 key：`submitter_id`
- 肾癌三队列按已有 `project_ids` 过滤
- 值：`build_patient_rows(cases)` / `extract_values(case)`

字段语义保持 D 组已有规则，包括：

- `diagnoses[].age_at_diagnosis`：数值 `> 365` 时按天除以 365.25（`_aggregate_continuous_value` 已有）
- 连续字段多值取中位数（这是同一病人多条记录的聚合，不是跨病人填补）
- 有序字段用现有 `_encode_tumor_grade` / `_encode_t_stage` / `_encode_n_stage` / `_encode_m_stage` / `_encode_overall_stage` / `_encode_ecog`
- 名义字段用现有 `_canonical_nominal_value`（小写、去空、多值 ` | ` 连接）
- 缺失判定用现有 `is_missing_token` + `BASELINE_EXTRA_MISSING`（`stage x` / `tx` / `nx` / `mx`）

不要为 HGCN 再写一套 demographic/treatments 抽取。

---

## 6. 缺失：保持 None，禁止填补

D 组为了拼成一条 dense 向量，做了这些填补，**HGCN 一律不要做**：

| 类型 | D 组现在怎么做 | HGCN 怎么做 |
|---|---|---|
| 连续 | 缺失用队列中位数填，再 `[0,1]` min-max | 缺失就是 `None`，不填中位数 |
| 有序 | 解析不到就当 `0` | 解析不到 / 缺失 → `None`，不要把 0 当成“缺失类” |
| 名义 | one-hot 的第 0 维 `__MISSING__` | 不建缺失类，该位置 `None` |

判定缺失（sentinel、空字符串、`None`）可以沿用 D 组，这是识别缺失，不是改数据。识别之后停在 `None`。

`ttt_cli_feas.pkl` / `t_cli_feas.pkl` 的每个病人是 `list[float | None]`，允许 None。不要为了“像原 notebook 那样全是数字”去填 0 或中位数。那是篡改。

覆盖率只统计观测 vs 缺失，写入 `coverage.json`。不要出现 `n_imputed`。

`x_cli` 是 float 矩阵，缺观测的对角位置保持 `0.0`，含义是“这个节点没有写入观测值”，**不是**“把缺失编码成类别 0 / 数值 0”。`field_schema.json` 和 `summary.md` 必须写明这一点。

---

## 7. 离散怎么变成一个整数（这是相对 D 组唯一的编码改动）

D 组名义字段是 one-hot，有序字段已经是整数。HGCN 要求每个节点一个标量，所以：

### 7.1 有序

直接复用 D 组 encoder，得到正整数。只有 encoder 产出有效 code（`> 0`）才写入；否则 `None`。

不要改 grade / T / N / M / stage / ECOG 的映射函数。

### 7.2 名义：one-hot 改成该维的整数下标

复用 D 组已经拟合好的词表，不要另排序：

1. 优先读 `A_pipeline/baseline_onehot_mapping_tables/category_mapping.json`
2. 没有现成表时，用 D 组同一套 `fit_nominal_mappings`（多数据集则全局词表，`min_count` 默认 5，低频进 `__OTHER__`）
3. 对每个名义字段：观测值 → `mapping[value]` 那个整数；`__MISSING__` → `None`；未见过的值 → `mapping[__OTHER__]`（这是词表里的 other，不是缺失填补）

这样 L/D/HGCN 三组看到的类别编号一致，只是 D 写成 one-hot，HGCN 写成一个整数。

映射写入该方案目录的 `encoding_table.json`。禁止运行时按病人出现顺序漂。

### 7.3 连续

保持 float。缺失 `None`。不要在这一步做 `[0,1]` 归一化。

---

## 8. HGCN 必须严格抄的 pipeline（原文风格只在这里）

字段不是原文的，**这两步是原文的**。

### 8.1 对称 min-max

不要用 D 组的 `(x-min)/(max-min)`。

对每个数据集、每个方案、每个字段 `i`，只用该字段 **非 None** 的 `ttt_cli_feas` 值算 min/max：

```text
x' = (x - (max + min) / 2) / (max - min) * 2
```

映到约 `[-1, 1]`。

- `None` 不参与 min/max，变换后仍是 `None`
- `max == min`：该字段所有观测值记 `0.0`，缺失仍是 `None`，不要除零
- 某字段全队列都缺失：没有尺度，全是 `None`

连续、有序、名义编码后的整数都走这步。原 notebook 对 gender 这种 0/1 也做了 min-max。

### 8.2 对角 pad 1024

```python
x_cli = np.zeros((N_cli, 1024), dtype=np.float32)
for i, value in enumerate(normalized_row):
    if value is not None:
        x_cli[i, i] = value
```

pad 维度就是 1024，不要改成 512。

### 8.3 全连接无自环

边方向按 `gendata.ipynb` 的 `get_edge_index_cli` 抄：

```python
start, end = [], []
for i in range(N_cli):
    for j in range(N_cli):
        if i != j:
            start.append(j)
            end.append(i)
edge_index_cli = np.array([start, end], dtype=np.int64)  # (2, N_cli*(N_cli-1))
```

节点集合由方案字段决定，不因某个病人缺字段而变。同一方案边只算一次。

---

## 9. 产物

```text
projects/outputs/{dataset}/A_manual/HGCN_clinic/L0/
projects/outputs/{dataset}/A_manual/HGCN_clinic/L1/
...
projects/outputs/{dataset}/A_manual/HGCN_clinic/L5/
  ttt_cli_feas.pkl      # dict[str, list[float|None]] 编码后、min-max 前，缺失为 None
  t_cli_feas.pkl        # dict[str, list[float|None]] 对称 min-max 后，缺失仍为 None
  x_cli.pkl             # dict[str, ndarray(N_cli, 1024)] float32
  edge_index_cli.pkl    # ndarray(2, N_cli*(N_cli-1)) int64
  encoding_table.json   # 名义整数词表 + 有序 encoder 名
  coverage.json         # 每字段 n_observed / n_missing / percent_observed
  field_schema.json
  summary.md
```

pkl 用 `joblib.dump`。不要写 `.pt`。不要占用 `L0/`-`L5/` 文本目录或 `D0/`-`D5/` 向量目录。

`field_schema.json` 至少包含：

```json
{
  "dataset": "TCGA-KIRC",
  "scheme": "L4",
  "n_cli": 21,
  "fields": ["demographic.age_at_index", "demographic.sex_at_birth", "..."],
  "field_types": {"demographic.age_at_index": "continuous", "demographic.sex_at_birth": "nominal", "diagnoses[].tumor_grade": "ordinal"},
  "pad_dim": 1024,
  "minmax": "symmetric_to_unit",
  "missing_policy": "keep_none",
  "nominal_encoding": "integer_index_from_d_series_mapping",
  "patient_id_field": "submitter_id",
  "n_patients": 513
}
```

不要输出完整 `Data(x_img, x_rna, x_cli, ...)`。

---

## 10. CLI

在 `src/cli.py` 增加子命令 `hgcn_clinic`。`--scheme` 用 L0-L5（`all` 表示六个都跑），`--dataset` 复用现有。

```bash
conda activate conch
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main

python projects/A_pipeline/run.py hgcn_clinic --dataset TCGA-KIRC --scheme L4
python projects/A_pipeline/run.py hgcn_clinic --dataset TCGA_LIHC --scheme all
python projects/A_pipeline/run.py hgcn_clinic --dataset all --scheme all
```

不传 `--dataset` 时走 `--json_path`，写到 `outputs/custom/A_manual/HGCN_clinic/{scheme}/`。

打印：数据集、方案、病人数、`N_cli`、每字段观测百分比、输出目录。

README 补命令，写明：字段等于 L0-L5，编码风格等于 HGCN clinic，不是 D 组拼接向量。

---

## 11. 代码怎么放

```text
A_pipeline/
  src/hgcn_clinic.py
  tests/test_hgcn_clinic.py
  HGCN_clinic_pkl_实现方案.md   # 本文件
```

允许的小改：

- `src/cli.py`：加 subparser
- `src/paths.py`：加 `dataset_hgcn_clinic_dir(dataset_name, scheme)`
- `README.md`：加用法

不要改 L 模板，不要改 D 组 one-hot 逻辑，不要把 HGCN 塞进 `src/baseline.py`。可以 import D 组的字段表、encoder、mapping、`build_patient_rows`。

建议函数：

- `resolve_hgcn_schemes(scheme) -> list[str]`
- `encode_raw_row(row, fields, nominal_mappings) -> list[float|None]`
- `minmax_symmetric(values_by_patient, n_cli) -> dict[str, list[float|None]]`
- `diagonal_pad(values, dim=1024) -> ndarray`  # None → 对角 0
- `full_connect_edges(n_cli) -> ndarray`
- `run_hgcn_clinic(...)`

不强制 torch。numpy + joblib 足够。

---

## 12. 测试（合成 JSON，不碰 lizhe）

`tests/test_hgcn_clinic.py` 至少覆盖：

1. **字段锁定**：L0 产出 4 维，L5 产出 23 维；字段顺序与 `SCHEME_FIELDS` 一致
2. **不引入论文字段**：结果里没有 `Radiation_Therapy` / `Pack_years_smoked`
3. **名义不是 one-hot**：`demographic.sex_at_birth=male` 是一个整数，不是一段 0/1 向量
4. **有序复用 D 组**：`ajcc_pathologic_t=T2` 的整数与 `_encode_t_stage` 一致
5. **缺失保持 None**：某个名义/连续字段不写或写 `not reported`，`ttt_cli_feas` 对应位置是 `None`，不是中位数，也不是 0 类
6. **连续缺失不填中位数**：队列里 demographic.age_at_index 为 `[50, None, 70]`，缺失那位仍是 `None`
7. **min-max 公式**：某连续字段观测值为 `[0, 10]`，变换后为 `[-1, 1]`；公式是 `(x-(max+min)/2)/(max-min)*2`，不是 D 组 `(x-min)/(max-min)`
8. **None 不进 min/max**：观测 `[0, 10]` 加一个缺失，min/max 仍按 0 和 10 算
9. **对角 pad**：3 个字段 shape `(3,1024)`；有值写在 `x[i,i]`，缺失位对角为 0，其余为 0
10. **边**：`N_cli=3` 时 6 条边，无自环
11. **输出路径**：`.../A_manual/HGCN_clinic/L4/ttt_cli_feas.pkl`，不进 `D4/` 或文本 `L4/`
12. **肾癌 project 过滤**：合成 KIRC/KICH 两条，KIRC job 只留 KIRC
13. **joblib**：能 load；list 长度等于 schema；允许 None

现有 `tests/test_a_pipeline.py` 不要改坏。

---

## 13. 验收

- [ ] `run.py hgcn_clinic --dataset TCGA-KIRC --scheme L4` 能跑通
- [ ] `--scheme all` 写出 L0-L5 六个目录
- [ ] 9 个默认数据集都能跑
- [ ] L0 `n_cli==4`，L4 `n_cli==21`，L5 `n_cli==23`，字段顺序与 D 组一致
- [ ] 没有 Radiation / Pack years 这类论文字段
- [ ] `ttt_cli_feas` 可 joblib.load；缺失位置是 `None`
- [ ] 没有把连续缺失填成中位数
- [ ] `x_cli` shape `(n_cli, 1024)`，非对角接近 0
- [ ] 观测值归一化后落在 `[-1.05, 1.05]`
- [ ] L0-L5 / D0-D5 旧路径不变
- [ ] 新单测通过
- [ ] README 有命令

---

## 14. 硬约束

1. 字段 = L0-L5 = D0-D5，一个都不许换
2. 类型划分 = `BASELINE_CONTINUOUS/ORDINAL/NOMINAL_FIELDS`
3. 取值 = 现有 `extract_values` / `build_patient_rows`
4. 缺失 = None，禁止中位数/众数/0 类填补
5. 相对 D 组只改：名义 one-hot → 整数；拼接向量 → 一字段一节点
6. min-max / 对角 1024 / 全连接无自环 按 HGCN notebook 抄
7. 病人 ID 用 `submitter_id`
8. 不处理生存标签，不写 `all_data.pkl`