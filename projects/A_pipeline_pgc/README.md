# A_pipeline_pgc —— PGC（SurvPGC）专用编码线

独立子项目，与 `A_pipeline/`（gdc 线）平级、**完全自包含**。

## 这条线是干什么的

只服务 **SurvPGC** 论文训练：把 lizhe 的 `clinical.cart.*.json` 按固定字段列表
（L0-L5）抽成 prompt 句子 → CONCH 文本 embedding，并派生同字段的 D0-D5 baseline
向量、L0-L5 的 HGCN clinic 图节点。

- **无 landmark 协议**：没有 `--landmark_time` / `--landmark_shift`，没有
  `landmark_{T}` 子目录，没有 cindex 评测通路。
- **单一数据源**：`datasets.json` 的 11 个 lizhe 癌种，没有 gdc 分支。
- **冻结**：产物是 SurvPGC 训练的输入。重生成需用户显式决定；日常只读。

## 目录

```text
A_pipeline_pgc/
├── run.py                       # CLI 入口：python run.py <cmd> ...
├── datasets.json                # 11 个 lizhe 数据集的 clinic_files 清单
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
PY=/data/fangyuxuan/miniconda3/envs/conch/bin/python
cd /data/fangyuxuan/projects/medical_dl/trident_project/CONCH-main/projects/A_pipeline_pgc

# prompt（不需要 GPU）
$PY run.py json2prompt --dataset all --scheme manual --force
# CONCH embedding（需要 GPU）
$PY run.py pipeline --dataset all --scheme all --encoding text --force

# D0-D5 baseline 向量（也会重建词表 该词表 HGCN 编码同样需要）
$PY run.py baseline --dataset all --scheme all --force

# HGCN clinic 图节点 pkl（喂 SurvPGC_Workspace/hgcn data）
$PY run.py hgcn_clinic --dataset all --scheme all --force
```

`--dataset` 不传时走 `--json_path` 单 JSON 模式，产物落
`outputs_pgc/custom/A_manual/`。

## 消费方

`SurvPGC_github_init/SurvPGC_Workspace/build_workspace.sh` 把
`outputs_pgc/{TCGA-XX}/A_manual/{L|D}{0-5}/embeddings/pt/*.pt` 软链到
`{study}/C/{L|D}{0-5}/`；`SurvPGC_Workspace/hgcn data` 的 clinic 分支来自
`outputs_pgc/{TCGA-XX}/A_manual/HGCN_clinic/L{k}/`。

## 增加数据集

以 2026-10-08 新增 TCGA-LUAD / TCGA-LUSC(肺癌)为例,步骤:

1. **datasets.json 登记**(同文件按 `project_ids` 拆分,与肾癌三集同模式):
   `clinic_files` = `/data/lizhe/Medteam_projects/Lung/clinical/clinical.cart.2026-06-01.json`(956 例),
   `project_ids` = `["TCGA-LUAD"]` / `["TCGA-LUSC"]`(各 478 例)。
2. **环境固定为 conch**(transformers 5.3.0);trident 环境分词行为不同、产物会全量漂移,禁用。
3. **按顺序运行**(先 L0-L5,再 baseline,最后 hgcn_clinic):
   ```bash
   $PY run.py pipeline --force --dataset TCGA-LUAD,TCGA-LUSC --scheme manual   # 新集 L0-L5(GPU,~10 分钟)
   $PY run.py baseline --force --dataset all --scheme all                     # 11 集同跑:共享名义词表重构
   $PY run.py hgcn_clinic --force --dataset all --scheme all                  # 复用新词表
   ```
4. **契约与下游同步**:`z_notes/time_axis/frozen_schemes_contract.md` 数据集名单、执行日志 D 系列登记、下游 SurvPGC `build_workspace.sh` 软链 + hgcn 数据拷贝。

影响口径(2026-10-08 实测):新数据集对旧集 **D0 与 HGCN L0 零影响**(demographic 字段词表未变);词表重建后旧集 **D1-D5 全部重算、维度 +24~29**(预期内,以 BRCA 为例):

| | 旧 | 新 | 增长 |
|---|---|---|---|
| D1 | 93 | 117 | +24 |
| D2 | 112 | 136 | +24 |
| D3 | 171 | 196 | +25 |
| D4 | 173 | 198 | +25 |
| D5 | 181 | 210 | +29 |

- 新词表:22 字段、245 类别,scope = 11 数据集、4860 患者(3904 + 956)。
- 维度增长不止契约预估的 +6(17→22 字段):肺的 956 例把一批原本 <5 频次被合并进 OTHER 的类别顶过了 `min_count=5` 阈值,契约 §3「已知口径」那段(+6 维)可顺带更新。
- HGCN L1–L5:每集 3 个 pkl(x_cli / ttt_cli_feas / t_cli_feas)随新词表变化。
