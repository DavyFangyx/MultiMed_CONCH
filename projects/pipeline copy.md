# One-Hot / Ordinary Baseline Pipeline

本文档只描述临床字段 baseline，不经过 CONCH、prompt 或文本 embedding。

整体流程：

```text
clinical JSON
    -> 患者级字段抽取
    -> 缺失值和类别清洗
    -> 字段分类与编码
    -> 按固定顺序拼接
    -> D0-D5 患者特征向量
```

## 1. 数据处理

1. 以 `submitter_id` 作为患者 ID。
2. 按 `project.project_id` 过滤目标 TCGA 数据集。
3. 相同患者去重，保留第一条记录。
4. 从 `demographic`、`diagnoses`、`treatments`、`pathology_details` 和 `follow_ups` 抽取字段。
5. 空值、`unknown`、`not applicable`、`--` 等统一为缺失值。
6. 类别词表、数值统计量和编码映射只使用训练集拟合，验证集和测试集复用同一套映射，避免数据泄漏。

最终得到患者级字段字典，例如：

```text
AGE=63
SEX_AT_BIRTH=female
RACE=white
ETHNICITY=not hispanic or latino
PRIMARY_DIAGNOSIS=Adenocarcinoma
MORPHOLOGY=8140/3
...
```

## 2. 字段分类与编码策略

### 2.1 连续数值字段

字段：

```text
AGE
YEAR_OF_DIAGNOSIS
AGE_AT_DIAGNOSIS
LYMPH_NODES_TESTED
LYMPH_NODES_POSITIVE
BMI
```

策略：

- 转换为数值类型。
- 缺失值使用训练集的中位数填充。
- 使用训练集统计量做 `Min-Max` 归一化。
- `AGE_AT_DIAGNOSIS` 如果原始单位是天，先换算为年，再归一化。
- 每个连续字段占 `1` 个维度。

### 2.2 有序等级字段

字段：

```text
TUMOR_GRADE
AJCC_PATHOLOGIC_T
AJCC_PATHOLOGIC_N
AJCC_PATHOLOGIC_M
AJCC_PATHOLOGIC_STAGE
ECOG_PERFORMANCE_STATUS
```

策略：

- 按临床顺序转换为 ordinal integer，例如 `G1 < G2 < G3 < G4`、`T1 < T2 < T3 < T4`。
- 缺失或无法识别的值使用固定缺失编码。
- 编码后可按训练集范围归一化。
- 每个字段占 `1` 个维度。

### 2.3 名义类别字段

字段：

```text
SEX_AT_BIRTH
RACE
ETHNICITY
PRIMARY_DIAGNOSIS
MORPHOLOGY
TISSUE_OR_ORGAN_OF_ORIGIN
LATERALITY
PRIOR_MALIGNANCY
SYNCHRONOUS_MALIGNANCY
PRIOR_TREATMENT
AJCC_STAGING_SYSTEM_EDITION
```

策略：

| Baseline | 编码方式 | 输出维度 |
| --- | --- | --- |
| `onehot` | 每个类别对应一个位置；低频类别可合并为 `OTHER`；缺失单独保留为 `MISSING` | `K_f`，其中 `K_f` 为字段 `f` 的类别数 |
| `ordinary` | 使用固定的 label/integer mapping，例如 `MISSING=0`，其余类别映射为整数 | `1` |

`ordinary` 是简单数值 baseline，不表示类别之间存在真实的大小关系；类别映射必须在所有 split 中保持一致。

## 3. 向量拼接规则

每个 `D_i` 内部严格按照字段列表顺序拼接，不能因样本缺失或类别不存在而改变位置。

定义：

- 连续数值字段或 ordinal 字段：`dim(f) = 1`
- `onehot` 名义类别字段：`dim(f) = K_f`
- `ordinary` 名义类别字段：`dim(f) = 1`

因此：

```text
onehot_dim(Di) = 所有字段 dim(f) 之和
ordinary_dim(Di) = Di 中字段数量
```

缺失字段仍然保留对应位置：

- 连续字段使用缺失填充值后进入该字段的 `1` 个位置。
- one-hot 字段激活 `MISSING` 位置。
- ordinary 字段使用缺失编码，例如 `0`。

## 4. D0-D5 字段组与输出向量

`D0-D5` 与当前文本 pipeline 的 `L0-L5` 字段范围对应，但输出从 prompt/embedding 改为一个患者级一维向量。

### D0（对应 L0）

字段列表：

```text
[AGE, SEX_AT_BIRTH, RACE, ETHNICITY]
```

向量组成：

| 位置 | 内容 | onehot 维度 | ordinary 维度 | 编码 |
| --- | --- | ---: | ---: | --- |
| `0` | `AGE` | `1` | `1` | 连续值，归一化 |
| `1-?` | `SEX_AT_BIRTH` | `K_SEX` | `1` | One-Hot / integer |
| `...` | `RACE` | `K_RACE` | `1` | One-Hot / integer |
| `...` | `ETHNICITY` | `K_ETHNICITY` | `1` | One-Hot / integer |

输出形状：

```text
onehot:   [1 + K_SEX + K_RACE + K_ETHNICITY]
ordinary: [4]
```

如果类别数为 `SEX=2`、`RACE=6`、`ETHNICITY=2`，则 one-hot 维度约为 `11`。

### D1（对应 L1）

字段列表：

```text
[AGE, SEX_AT_BIRTH, RACE, ETHNICITY,
 PRIMARY_DIAGNOSIS, MORPHOLOGY, TISSUE_OR_ORGAN_OF_ORIGIN,
 LATERALITY, YEAR_OF_DIAGNOSIS, AGE_AT_DIAGNOSIS]
```

向量组成：

| 位置范围 | 内容 | 维度 | 说明 |
| --- | --- | ---: | --- |
| `0` | `AGE` | `1` | 连续值，归一化 |
| `1-?` | `SEX_AT_BIRTH` | `K_SEX`，常见为 `2` | One-Hot |
| `...` | `RACE` | `K_RACE`，示例为 `6` | One-Hot |
| `...` | `ETHNICITY` | `K_ETHNICITY`，示例为 `2` | One-Hot |
| `...` | `PRIMARY_DIAGNOSIS` | `K_DIAGNOSIS`，约 `30` | One-Hot，低频类可压缩 |
| `...` | `MORPHOLOGY` | `K_MORPHOLOGY`，约 `20` | One-Hot，低频类可压缩 |
| `...` | `TISSUE_OR_ORGAN_OF_ORIGIN` | `K_TISSUE`，约 `20` | One-Hot，低频类可压缩 |
| `...` | `LATERALITY` | `K_LATERALITY`，常见为 `4` | One-Hot |
| `末尾-2` | `YEAR_OF_DIAGNOSIS` | `1` | 连续值，归一化 |
| `末尾-1` | `AGE_AT_DIAGNOSIS` | `1` | 连续值，归一化 |

当类别数采用示例值时：

```text
onehot_dim(D1) ~= 1 + 2 + 6 + 2 + 30 + 20 + 20 + 4 + 1 + 1 = 87
ordinary_dim(D1) = 10
```

输出形状：

```text
onehot:   [约 87]，具体维度取决于训练集类别词表
ordinary: [10]
```

### D2（对应 L2）

字段列表：

```text
D1 + [TUMOR_GRADE, PRIOR_MALIGNANCY,
      SYNCHRONOUS_MALIGNANCY, PRIOR_TREATMENT]
```

新增向量位置：

| 内容 | onehot 维度 | ordinary 维度 | 编码 |
| --- | ---: | ---: | --- |
| `TUMOR_GRADE` | `1` | `1` | ordinal |
| `PRIOR_MALIGNANCY` | `K_PRIOR` | `1` | One-Hot / integer |
| `SYNCHRONOUS_MALIGNANCY` | `K_SYNCHRONOUS` | `1` | One-Hot / integer |
| `PRIOR_TREATMENT` | `K_TREATMENT` | `1` | One-Hot / integer |

输出形状：

```text
onehot:   [onehot_dim(D1) + 1 + K_PRIOR + K_SYNCHRONOUS + K_TREATMENT]
ordinary: [14]
```

### D3（对应 L3）

字段列表：

```text
D2 + [AJCC_PATHOLOGIC_T, AJCC_PATHOLOGIC_N,
      AJCC_PATHOLOGIC_M, AJCC_PATHOLOGIC_STAGE,
      AJCC_STAGING_SYSTEM_EDITION]
```

新增向量位置：

| 内容 | onehot 维度 | ordinary 维度 | 编码 |
| --- | ---: | ---: | --- |
| `AJCC_PATHOLOGIC_T` | `1` | `1` | ordinal |
| `AJCC_PATHOLOGIC_N` | `1` | `1` | ordinal |
| `AJCC_PATHOLOGIC_M` | `1` | `1` | ordinal |
| `AJCC_PATHOLOGIC_STAGE` | `1` | `1` | ordinal |
| `AJCC_STAGING_SYSTEM_EDITION` | `K_EDITION` | `1` | 名义类别 |

输出形状：

```text
onehot:   [onehot_dim(D2) + 4 + K_EDITION]
ordinary: [19]
```

### D4（对应 L4）

字段列表：

```text
D3 + [LYMPH_NODES_TESTED, LYMPH_NODES_POSITIVE]
```

向量组成：

| 内容 | 维度 | 说明 |
| --- | ---: | --- |
| `LYMPH_NODES_TESTED` | `1` | 连续值，归一化 |
| `LYMPH_NODES_POSITIVE` | `1` | 连续值，归一化 |

输出形状：

```text
onehot:   [onehot_dim(D3) + 2]
ordinary: [21]
```

### D5（对应 L5）

字段列表：

```text
D4 + [ECOG_PERFORMANCE_STATUS, BMI]
```

向量组成：

| 内容 | 维度 | 说明 |
| --- | ---: | --- |
| `ECOG_PERFORMANCE_STATUS` | `1` | ordinal，可归一化 |
| `BMI` | `1` | 连续值，归一化 |

输出形状：

```text
onehot:   [onehot_dim(D4) + 2]
ordinary: [23]
```

## 5. 输出

每个患者输出一个一维向量：

```text
onehot baseline:   [d_onehot]
ordinary baseline: [d_ordinary]
```

其中：

```text
d_ordinary(D0-D5) = [4, 10, 14, 19, 21, 23]
```

`d_onehot` 由训练集类别数量决定。以 D1 为例，若采用示例类别数，输出约为 `[87]`；实际维度可能因类别合并、缺失类别和词表配置而变化。

当前实现默认保存格式（`ordinary` baseline）：

```text
outputs/{dataset}/A_manual/D0/embeddings/pt/TCGA-XX-XXXX.pt
outputs/{dataset}/A_manual/D1/embeddings/pt/TCGA-XX-XXXX.pt
...
outputs/{dataset}/A_manual/D5/embeddings/pt/TCGA-XX-XXXX.pt
```

同时保存对应的 `metadata/category_mapping.json`、`metadata/normalization_stats.json` 和 `metadata/feature_schema.json`，保证训练、验证和测试阶段的向量位置完全一致。
