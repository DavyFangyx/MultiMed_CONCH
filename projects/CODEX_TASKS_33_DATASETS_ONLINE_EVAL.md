# 33 个数据集接入 greedy 在线评估

根代理只负责任务拆解和最终查验。下面 4 个 Codex 并行改代码 / 组织数据，互不抢同一文件。

## 目标

`datasets.json` 里 33 个 TCGA 都能做 **clinic 单模态** greedy 在线评估。

`survgc_f` / `survpgc_f` 只允许 BRCA、COAD、KIRC、KIRP、LIHC。KICH、PRAD、READ、STAD 以及其余 ClinicDatasets 都按 clinic 单模态评估；选多模态模型会直接报错。

多模态数据集：BRCA、COAD、KIRC、KIRP、LIHC
单模态数据集：ACC、BLCA、CESC、CHOL、DLBC、ESCA、GBM、HNSC、KICH、LAML、LGG、LUAD、LUSC、MESO、OV、PAAD、PCPG、PRAD、READ、SARC、SKCM、STAD、TGCT、THCA、THYM、UCEC、UCS、UVM

多模态模型：`survgc_f`、`survpgc_f`
单模态模型：`mlp_clinic_mean`、`mlp_clinic_flatten`、`snn_clinic_mean`、`snn_clinic_flatten`

这 5 个多模态数据集按 P、C、G 齐全处理；其余 28 个只跑单模态模型。

Clinic_Analyzer 是从 `/data/fangyuxuan/projects/medical_dl/SurvPGC_github_init/` 迁过来的。split 源目录：

`/data/fangyuxuan/projects/medical_dl/SurvPGC_github_init/splits`

同仓库里已有 split 生成 pipeline 的 md，Codex 2 按那份文档做，不要另起一套格式。

## 不要改

- 不要改 SurvPGC 本体训练逻辑
- 不要把 28 个单模态数据集接进 G/P
- 不要回退已有的多模态白名单
- 不要互相覆盖别人负责的文件

## Codex 1：Analyzer 认出 33 个数据集

负责让 `Clinic_Analyzer/evaluate.py` 能从 `clinic_dir` 解析出全部 33 个 study。

改这些文件：

- `Clinic_Analyzer/dataset_deployment/registry.py`
- 如需导出，再动 `Clinic_Analyzer/dataset_deployment/__init__.py`

要求：

1. `DATASET_CONFIGS` 覆盖 33 个 TCGA，display name 与 `datasets.json` / outputs 目录一致（LIHC 仍是 `TCGA_LIHC`）。
2. `resolve_clinic_eval_job()` 对 33 个都不报 `Unknown clinic dataset`。
3. `--study` 能选这 33 个。
4. 多模态白名单保持现状：只有 BRCA / COAD / KIRC / KIRP / LIHC 能用 `survgc_f` / `survpgc_f`。
5. 新数据集的 csv / workspace 路径按 SurvPGC 现有命名习惯写全；缺文件不在这一步补。

完成后自检：对 `TCGA-ACC`、`TCGA-READ`、`TCGA_LIHC` 各解析一次 clinic_dir，前两个只能走单模态。

## Codex 2：组织 33 个数据集的 splits

这是数据组织任务，不是改 greedy 调度器。

源目录：

`/data/fangyuxuan/projects/medical_dl/SurvPGC_github_init/splits`

先读该仓库里现有的 split 生成 pipeline md，按原格式扩到 33 个。

规则：

1. BRCA、COAD、KIRC、KIRP、LIHC：多模态 split。患者必须 P、C、G 都齐全，才能进 5-fold。
2. 其余 28 个：单模态 split。只按 clinic / 生存标签划 fold，不要求 WSI 或 gene。
3. 每个数据集都要有 `splits/5foldcv/{study}/splits_{0-4}.csv`，列格式与现有 9 个一致，Clinic_Analyzer 能直接读。
4. 已有 9 个 split 不要无故重划。KICH / PRAD / READ / STAD 若当前是按 P+C+G 齐全筛的，改成单模态资格后重生成，并写清和旧 split 的差异。
5. 产出一份清单：每个数据集是 multimodal 还是 unimodal、患者数、fold 大小、缺的上游文件。

完成后自检：5 个多模态目录存在且资格是三模态齐全；抽查 `TCGA-ACC` / `TCGA-READ` 能读 5 个 fold csv，且不依赖 G/P。

## Codex 3：clinic 单模态评估不再绑 G/P

负责让 28 个单模态数据集过了 registry 之后，不会因为缺 omics / WSI 而失败。

改这些文件：

- `Clinic_Analyzer/datasets/dataset_survival.py`
- `Clinic_Analyzer/utils/process_args.py`
- 如有必要：`Clinic_Analyzer/evaluate.py`、`Clinic_Analyzer/main.py`

要求：

1. `mlp_clinic_*` / `snn_clinic_*` 只依赖 clinic embedding、label、clinical csv、splits。
2. 单模态路径不要强制读 `omics_dir`、不要按 WSI `data_dir` 过滤患者。
3. `survgc_f` / `survpgc_f` 仍读 G、P，且只允许那 5 个数据集。
4. 不要改模型结构，只改数据装配和缺模态时的失败方式。

完成后自检：单模态 study 在没有 WSI/gene 时能完成一次 factory 初始化；多模态 study 缺 G 或 P 时仍失败。

## Codex 4：greedy 在线评估接到 33 个

负责 greedy 选数据集之后，真的能切子集 embedding 并调用 Analyzer。

改这些文件0：

- `src/greedy/data.py`
- `src/greedy/cli.py`
- 如有必要：`src/greedy/clinic.py`、`src/greedy/clinic_evaluator.py`

要求：

1. `STUDY_BY_DISPLAY` / study 解析覆盖 33 个，和 Codex 1 的 display name 一致。
2. 默认 split 能指向 Codex 2 组织好的 `5foldcv/{study}`；没有外部 split 时走 internal，或明确报错。
3. 患者宇宙、label、events 对单模态数据集不要再要求 SurvPGC 三模态齐全。
4. inner/outer modality 继续走现有白名单：那 5 个才能选 `survgc_f` / `survpgc_f`。
5. `--dataset all` 对 33 个都能进入评估链路；只是单模态数据集评估的只有单模态的模型。
    "mlp_clinic_mean",
    "mlp_clinic_flatten",
    "snn_clinic_mean",
    "snn_clinic_flatten",
    而多模态的数据集可以评估多有模型。
完成后自检：`TCGA-ACC` + `mlp_clinic_flatten` 能走到调用 Analyzer；`TCGA-READ --inner_modality survgc_f` 启动前报错；`TCGA_LIHC` 仍可走原路径。

## 根代理查验

四个 Codex 都交卷后再查，不提前改他们的文件。

1. 33 个 display name 在 greedy 和 Analyzer 里能对上。
2. 5 个多模态：split 按 P+C+G 齐全；可跑 `survgc_f` / `survpgc_f`。
3. 28 个单模态：能选、能解析、能读 5-fold；选多模态模型立即失败。
4. clinic 单模态不读 G/P；缺 Field Bank 时报文件缺失，不再报 Unknown clinic dataset。
5. 现有 `TCGA_LIHC` greedy 路径没有被改坏。

## 建议顺序

Codex 1、2、3 可并行。Codex 4 依赖 1 的命名和 2 的 split 路径，可先写映射和 CLI，等 split 落地后再对外部 split 做最终接通。

## 当前状态

四个 Codex 任务已落地。33 个 display name 能对上；clinic 单模态不再绑 G/P；greedy 默认读 `Clinic_Analyzer/data/splits/5foldcv`。多模态 5 个已排除模态缺失。

## 还要注意

- Field Bank embedding 目前只有 `TCGA_LIHC`。其余 32 个数据集能选、能解析、能读 5-fold，但 greedy 切子集 embedding 时会缺文件。
- `Clinic_Analyzer/data/splits/5foldcv/summary.csv` 只记了 LIHC，没有 33 套 split 的完整清单。
- `--splits_source internal` 仍要 `split_eligibility.csv`，新 split 目录里没有。默认 `external` 不受影响。
