# A_pipeline_pgc —— PGC（SurvPGC）专用编码线

独立子项目，与 `A_pipeline/`（gdc 线）平级、**完全自包含**。

## 这条线是干什么的

只服务 **SurvPGC** 论文训练：把 lizhe 的 `clinical.cart.*.json` 按固定字段列表
（L0-L5）抽成 prompt 句子 → CONCH 文本 embedding，并派生同字段的 D0-D5 baseline
向量、L0-L5 的 HGCN clinic 图节点。

- **无 landmark 协议**：没有 `--landmark_time` / `--landmark_shift`，没有
  `landmark_{T}` 子目录，没有 cindex 评测通路。
- **单一数据源**：`datasets.json` 的 9 个 lizhe 癌种，没有 gdc 分支。
- **冻结**：产物是 SurvPGC 训练的输入。重生成需用户显式决定；日常只读。

## 目录

```text
A_pipeline_pgc/
├── run.py                       # CLI 入口：python run.py <cmd> ...
├── datasets.json                # 9 个 lizhe 数据集的 clinic_files 清单
├── src/                         # 内核（从 A_pipeline/src 独立复制）
│   ├── cli.py                   # json2prompt / encode / pipeline / baseline / hgcn_clinic
│   ├── config.py                # 只注册 L0-L5（templates/schemes.json 的 _schemes）
│   ├── datasets.py              # 单源 dataset job 展开
│   ├── paths.py                 # 产物根 = projects/outputs_pgc/
│   ├── extract.py               # 32 字段取值（无 landmark mask）
│   ├── json2prompt.py           # JSON → prompts.csv
│   ├── encode.py                # prompts.csv → CONCH embedding（需 GPU）
│   ├── baseline.py              # D0-D5 onehot/ordinary 向量
│   └── hgcn_clinic.py           # L0-L5 HGCN 图节点 pkl
├── common/                      # 基础库快照（从 projects/src/common 复制并裁剪）
├── gdc_dictionary/              # GDC 字段类型词典快照（baseline/hgcn 分类用）
├── templates/{L0..L5}/          # fields.json + template.csv（冻结）
└── baseline_onehot_mapping_tables/   # 共享名义词表（category_mapping.json 等）
```

产物根：`projects/outputs_pgc/{TCGA-XX}/A_manual/{L0..L5,D0..D5}/`，
结构与原 `projects/outputs/{TCGA-XX}/A_manual/` 逐字一致。

## 与 A_pipeline（gdc 线）的差异（复制的取舍）

内核是 A_pipeline 的**忠实副本**，只动了下面这些必要处：

| 文件 | 差异 | 原因 |
|---|---|---|
| `paths.py` | 产物根改 `outputs_pgc/`；`global_mapping_dir()` 无 source 分支 | 彻底分离，词表只有一份 |
| `config.py` | 删 scheme source 机制、paper / Test_3 方案、`ALL_TCGA_DATASETS` | 单源 + 只注册 L0-L5 |
| `datasets.py` | `expand_source_jobs` 去掉双源分组（源恒为 lizhe） | 单源 |
| `extract.py` | 删 `mask_case` 调用；`extract_values(case)` 少两个参数 | 无 landmark |
| `json2prompt.py` / `encode.py` / `baseline.py` / `hgcn_clinic.py` | 删所有 landmark 参数与 `landmark_{T}` 目录逻辑 | 无 landmark |
| `baseline.py` | 删 paper 方案注册；`discovery.onehot` → 本地 `common.gdc_types` | 零外部 import |
| `cli.py` | 只留 5 个子命令；删 `--landmark_time` / `--landmark_shift` / cindex；`--encoding` 现在真的会跳过另一条编码通路 | 无评测通路 |
| `templates/L0..L5/fields.json` | 删 `"source": "lizhe"` 键（代码也不再读） | 单源，字段已无意义 |
| `templates/schemes.json` | `_schemes` 只留 L0-L5 | 无 paper / Test_3 |

`extract_values` 的删参是**逐字等价**的：上游 `mask_case(case, None)` 原样返回
`case`，所以取值与旧线完全一致（已用 prompts.csv 逐字节回归验证）。

## 用法

```bash
PY=/data/fangyuxuan/miniconda3/envs/trident/bin/python
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects/A_pipeline_pgc

# prompt（不需要 GPU）
$PY run.py json2prompt --dataset TCGA-COAD --scheme L0

# CONCH embedding（需要 GPU）
$PY run.py pipeline --dataset all --scheme all --encoding text

# D0-D5 baseline 向量
$PY run.py baseline --dataset all --scheme all

# HGCN clinic 图节点 pkl（喂 SurvPGC_Workspace/hgcn data）
$PY run.py hgcn_clinic --dataset all --scheme all
```

`--dataset` 不传时走 `--json_path` 单 JSON 模式，产物落
`outputs_pgc/custom/A_manual/`。

## 消费方

`SurvPGC_github_init/SurvPGC_Workspace/build_workspace.sh` 把
`outputs_pgc/{TCGA-XX}/A_manual/{L|D}{0-5}/embeddings/pt/*.pt` 软链到
`{study}/C/{L|D}{0-5}/`；`SurvPGC_Workspace/hgcn data` 的 clinic 分支来自
`outputs_pgc/{TCGA-XX}/A_manual/HGCN_clinic/L{k}/`。
