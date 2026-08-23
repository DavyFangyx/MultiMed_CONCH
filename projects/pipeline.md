# Pipeline

本项目把 TCGA clinical JSON 转成 CONCH 可用的患者级文本嵌入。整体数据流如下：

`clinical JSON -> prompt CSV -> CONCH embedding -> per-patient .pt`

这里的关键点不是“把一个病人直接编码成一个 `[768]` 向量”，而是：

- 先把一个病人的多个临床字段拆成多个 prompt 片段
- 每个 prompt 片段单独过一次 CONCH 文本编码器
- 最终每个病人保存为一个二维张量 `[nc, 768]`
- 其中 `nc` 是该 scheme 的 prompt 片段数

## 1. 输入

- 输入是一个或多个 `clinical.cart*.json`
- 数据集映射由 `datasets.json` 管理
- 同一个临床 JSON 可能对应多个 TCGA 项目，必要时按 `project.project_id` 再过滤
- 单条记录的患者主键使用 `submitter_id`

一个原始 clinical JSON 记录通常是这种结构：

```json
{
  "submitter_id": "TCGA-AB-1234",
  "project": {
    "project_id": "TCGA-READ"
  },
  "primary_site": "Rectum",
  "demographic": {
    "race": "white",
    "ethnicity": "not hispanic or latino",
    "gender": "female",
    "sex_at_birth": "female",
    "age_at_index": 63
  },
  "diagnoses": [
    {
      "primary_diagnosis": "Adenocarcinoma",
      "morphology": "8140/3",
      "tissue_or_organ_of_origin": "Rectum",
      "laterality": "not reported",
      "year_of_diagnosis": 2018,
      "age_at_diagnosis": 23011,
      "tumor_grade": "G2",
      "prior_malignancy": "no",
      "synchronous_malignancy": "no",
      "prior_treatment": "no",
      "ajcc_pathologic_t": "T3",
      "ajcc_pathologic_n": "N1",
      "ajcc_pathologic_m": "M0",
      "ajcc_pathologic_stage": "Stage IIIB",
      "ajcc_staging_system_edition": "8th",
      "treatments": [
        {
          "treatment_type": "Pharmaceutical Therapy, NOS",
          "treatment_or_therapy": "yes",
          "treatment_intent_type": "Adjuvant"
        }
      ],
      "pathology_details": [
        {
          "lymph_nodes_tested": 18,
          "lymph_nodes_positive": 3
        }
      ]
    }
  ],
  "follow_ups": [
    {
      "ecog_performance_status": "0",
      "other_clinical_attributes": [
        {
          "bmi": 22.4
        }
      ]
    }
  ]
}
```

说明：

- 实际 JSON 往往比这个更长，这里只保留 pipeline 会读取的核心字段
- 某些值可能不存在，代码会把空值、`unknown`、`not reported`、`not applicable`、`--` 等统一视为缺失
- 缺失后会替换成固定占位文本，例如 `not reported`、`unknown`、`Stage X`、`TX`

## 2. JSON 处理

代码行为以 `projects/src/pipeline.py` 为准，处理逻辑如下：

- 以 `submitter_id` 作为患者主键
- 去掉缺少 `submitter_id` 的记录
- 按 `submitter_id` 去重，重复时保留第一次出现的病例
- 如果数据集配置了 `project_ids`，则按 `case["project"]["project_id"]` 过滤
- 从不同层级抽取并汇总字段：
  - `demographic`
  - `diagnoses`
  - `diagnoses[].treatments`
  - `diagnoses[].pathology_details`
  - `follow_ups`
  - `follow_ups[].other_clinical_attributes`
- 多条治疗、病理、随访记录中的同名字段会去重后拼接

例如最终会抽取出一组患者级字段值：

```json
{
  "AGE": "63",
  "SEX_AT_BIRTH": "female",
  "RACE": "white",
  "ETHNICITY": "not hispanic or latino",
  "PRIMARY_DIAGNOSIS": "Adenocarcinoma",
  "MORPHOLOGY": "8140/3",
  "TISSUE_OR_ORGAN_OF_ORIGIN": "Rectum",
  "LATERALITY": "not reported",
  "YEAR_OF_DIAGNOSIS": "2018",
  "AGE_AT_DIAGNOSIS": "23011",
  "TUMOR_GRADE": "G2",
  "PRIOR_MALIGNANCY": "no",
  "SYNCHRONOUS_MALIGNANCY": "no",
  "PRIOR_TREATMENT": "no",
  "AJCC_PATHOLOGIC_T": "T3",
  "AJCC_PATHOLOGIC_N": "N1",
  "AJCC_PATHOLOGIC_M": "M0",
  "AJCC_PATHOLOGIC_STAGE": "Stage IIIB",
  "AJCC_STAGING_SYSTEM_EDITION": "8th",
  "LYMPH_NODES_TESTED": "18",
  "LYMPH_NODES_POSITIVE": "3",
  "ECOG_PERFORMANCE_STATUS": "0",
  "BMI": "22.4"
}
```

## 3. Prompt 生成

### 3.1 `schemes.json` 是干什么的

每个 scheme 对应一组模板和字段映射，定义在 `templates/A_manual/schemes.json`。

以 `templates/A_manual/schemes.json` 中的 `L0` 为例：

```json
{
  "L0": {
    "description": "L0：age_at_index + sex_at_birth + race + ethnicity",
    "template_file": "L0_template.csv",
    "prompt_file": "prompts.csv",
    "dirname": "L0",
    "template_cols": [
      "AGE_TEMPLATE",
      "SEX_AT_BIRTH_TEMPLATE",
      "RACE_TEMPLATE",
      "ETHNICITY_TEMPLATE"
    ],
    "placeholders": [
      "AGE",
      "SEX_AT_BIRTH",
      "RACE",
      "ETHNICITY"
    ],
    "output_cols": [
      "age_template",
      "sex_at_birth_template",
      "race_template",
      "ethnicity_template"
    ]
  }
}
```

这些字段的含义分别是：

- `template_file`: 读取哪个模板 CSV
- `prompt_file`: 生成的 prompt CSV 文件名
- `dirname`: 编码后 embedding 的输出子目录名
- `template_cols`: 从模板 CSV 中读取哪些模板列
- `placeholders`: 这些模板列里要替换的占位符名
- `output_cols`: 写到 prompt CSV 里的输出列名

约束是：

- `template_cols`、`placeholders`、`output_cols` 三者长度必须完全一致
- 第 `i` 个模板列会用第 `i` 个占位符替换，然后写入第 `i` 个输出列

### 3.2 模板 CSV 长什么样

以 `templates/A_manual/L0.csv` 为例：

```csv
AGE_TEMPLATE,SEX_AT_BIRTH_TEMPLATE,RACE_TEMPLATE,ETHNICITY_TEMPLATE
The patient is AGE years old at index.,Sex at birth is SEX_AT_BIRTH.,Race is RACE.,Ethnicity is ETHNICITY.
```

这里的替换规则很直接：

- `AGE_TEMPLATE` 里的 `AGE` 会被替换成患者的 `AGE`
- `SEX_AT_BIRTH_TEMPLATE` 里的 `SEX_AT_BIRTH` 会被替换成患者的 `SEX_AT_BIRTH`
- 其他列同理

### 3.3 生成后的 prompt CSV 长什么样

如果患者 `TCGA-AB-1234` 的字段值如上，那么 `L0` 生成的一行大致会是：

```csv
patient_id,age_template,sex_at_birth_template,race_template,ethnicity_template
TCGA-AB-1234,The patient is 63 years old at index.,Sex at birth is female.,Race is white.,Ethnicity is not hispanic or latino.
```

关键点：

- CSV 的每一行对应一个患者
- CSV 的每一列对应一个 prompt 片段
- 这里不是先把所有字段拼成一整段长文本，而是保留“多列、多句”的结构

## 4. Embedding 编码

编码逻辑如下：

- 读取 prompt CSV
- 按 `output_cols` 的列顺序取出同一患者的多个 prompt 片段
- 每个片段单独送入 CONCH 文本编码器
- 每个片段得到一个 `768` 维向量
- 每个片段的向量都会做 L2 归一化
- 最后把同一患者的所有片段堆叠成一个二维张量

所以最终形状不是单个 `[768]`，而是：

`[nc, 768]`

其中：

- `nc` = 当前 scheme 的 prompt 片段数
- `768` = CONCH 文本 embedding 维度

对整个批次来说，中间大张量的形状是：

`[num_patients, nc, 768]`

随后会拆开，按患者分别保存为：

`outputs/{dataset}/A_manual/{scheme}/embeddings/pt/{patient_id}.pt`

### 4.1 L0-L5 对应的 `nc`

- `L0`: `nc = 4`
- `L1`: `nc = 10`
- `L2`: `nc = 14`
- `L3`: `nc = 19`
- `L4`: `nc = 21`
- `L5`: `nc = 23`

因此：

- `L0` 的单患者 `.pt` 是 `[4, 768]`
- `L5` 的单患者 `.pt` 是 `[23, 768]`

如果下游模型需要单个 `[768]` 患者向量，需要在 pipeline 之后自行做 pooling，例如：

- mean pooling over `nc`
- attention pooling
- 只取某些 prompt 片段

当前 `projects/src/pipeline.py` 本身不会在编码阶段把 `[nc, 768]` 再压成 `[768]`。

## 5. 一个完整例子

下面用一条 `L0` 病例把整个过程串起来。

### Step 1. 原始 JSON

```json
{
  "submitter_id": "TCGA-AB-1234",
  "project": { "project_id": "TCGA-READ" },
  "demographic": {
    "age_at_index": 63,
    "sex_at_birth": "female",
    "race": "white",
    "ethnicity": "not hispanic or latino"
  },
  "diagnoses": [
    {
      "primary_diagnosis": "Adenocarcinoma"
    }
  ]
}
```

### Step 2. 提取患者级字段

```json
{
  "AGE": "63",
  "SEX_AT_BIRTH": "female",
  "RACE": "white",
  "ETHNICITY": "not hispanic or latino"
}
```

### Step 3. 读取 `L0_template.csv`

```csv
AGE_TEMPLATE,SEX_AT_BIRTH_TEMPLATE,RACE_TEMPLATE,ETHNICITY_TEMPLATE
The patient is AGE years old at index.,Sex at birth is SEX_AT_BIRTH.,Race is RACE.,Ethnicity is ETHNICITY.
```

### Step 4. 占位符替换后得到 prompt CSV 一行

```csv
patient_id,age_template,sex_at_birth_template,race_template,ethnicity_template
TCGA-AB-1234,The patient is 63 years old at index.,Sex at birth is female.,Race is white.,Ethnicity is not hispanic or latino.
```

### Step 5. 编码时按列顺序组成 prompt 序列

```text
[
  "The patient is 63 years old at index.",
  "Sex at birth is female.",
  "Race is white.",
  "Ethnicity is not hispanic or latino."
]
```

### Step 6. 每句单独编码

得到 4 个向量：

```text
[e1, e2, e3, e4], each ei in R^768
```

堆叠后：

```text
embedding(TCGA-AB-1234) in L0 = [4, 768]
```

### Step 7. 保存为单患者 `.pt`

保存路径类似：

```text
outputs/TCGA-READ/A_manual/L0/embeddings/pt/TCGA-AB-1234.pt
```

这个 `.pt` 文件里保存的是一个二维张量：

```text
torch.FloatTensor of shape [4, 768]
```

如果换成 `L5`，同样的保存方式不变，只是形状会变成：

```text
torch.FloatTensor of shape [23, 768]
```

## 6. 一句话总结

这个 clinic pipeline 不是“一个病人 -> 一个 prompt -> 一个 `[768]` 向量”，而是：

`一个病人 -> 多个结构化 prompt 片段 -> 每片段一个 768 维向量 -> 保存为单患者 [nc, 768]`
