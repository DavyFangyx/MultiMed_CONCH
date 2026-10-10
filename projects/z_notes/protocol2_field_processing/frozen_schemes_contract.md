# 冻结方案契约(PGC 线 / SurvPGC 侧稳定)

本文档定义"冻结方案"的边界:哪些产物被冻结、谁在消费、什么会破坏冻结、如何重生成。权威时间轴协议见 [`../1_landmark/time_axis.md`](../1_landmark/time_axis.md)。

## 1. 冻结清单与理由

- **L0-L5**(文本编码,字段列表抓取)与 **D0-D5**(同字段 baseline 向量,经 `D_SCHEME_BY_TEXT_SCHEME` 映射到 L0-L5),外加 **HGCN_clinic 的 L0-L5 图节点 pkl**。
- 理由:这批产物是 SurvPGC(MosaicSurv)论文训练的唯一 Clinic 输入——论文结果依赖它们逐字节稳定。PGC 线不套 landmark/时间轴协议,按 fields.json 字段列表抓取即可。

## 2. 产物与消费

- 产物根:`projects/outputs_pgc/{TCGA-XX}/A_manual/{scheme}/`(11 个 lizhe 数据集:BRCA/LIHC/COAD/PRAD/READ/STAD/KICH/KIRC/KIRP/LUAD/LUSC;前 9 个 2026-10-06 自 `outputs/` 迁移;LUAD/LUSC 于 2026-10-08 登记,数据源 `/data/lizhe/Medteam_projects/Lung/clinical/clinical.cart.2026-06-01.json`,同文件按 project_ids 拆分)。
- 编码入口:`projects/A_pipeline_pgc/run.py`(独立子项目:自包含内核 + common 快照,不 import projects/src 与 A_pipeline;无 landmark、无 cindex)。**默认拒绝运行,须 `--force`**。
- 下游消费(外部仓库 `SurvPGC_github_init`,只读):
  - `SurvPGC_Workspace/{study}/C/{L0..L5,D0..D5}` 软链 → 本产物根(46,848 条,由 `build_workspace.sh` 维护,源根已改 outputs_pgc);
  - `SurvPGC_Workspace/hgcn data/{study}/C/{L0-L5}` 为**普通拷贝**(非软链),重生成前须先改 `models/missing_modality_baselines/hgcn_graph_build.py` 的 `A_PIPELINE_OUTPUT_ROOT`(见 SurvPGC_Workspace/Readme.md §7)。
- 输入数据源:`/data/lizhe/Medteam_projects/**` 的 clinical.cart(外部只读,见 `A_pipeline_pgc/datasets.json`)。

## 3. 什么会破坏冻结

1. `A_pipeline_pgc/templates/{L0..L5}/fields.json` 或 `template.csv` 改动;
2. 提取/编码内核(`A_pipeline_pgc/src/` 或 `A_pipeline_pgc/common/`)改动;
3. CONCH 权重(`WORKSPACE_ROOT/CONCH/pytorch_model.bin`)更换;
4. 共享 nominal 词表(`baseline_onehot_mapping_tables/*.json`)重拟合。

已知口径(2026-10-06 独立化时发现,属冻结产物与现内核的差异,不是错误):
- **D1-D5 重生成会多 6 维**:冻结产物按 17 个占位符键名义字段生成;现内核按 GDC 路径键出 22 个字段(93→99、112→118、171→177、173→179、181→187)。重生成前须先决策词表口径;
- L0-L5 仅 COAD 患者 `TCGA-A6-2681` 因 D13(主诊断时间锚点修正,已提交)与冻结产物不一致——重生成时该例会按新口径变化,属预期。

## 4. 重生成 SOP

1. 明确动机(词表口径决策 / lizhe cart 更新 / 内核 bug 修复)并在 `Test_series_execution_log.md` 登记;
2. `python A_pipeline_pgc/run.py <subcommand> ... --force`(无 --force 会被冻结闸门拒绝);
3. 验证:与冻结备份逐文件 diff=0(无预期差异时);有预期差异时逐条说明(如 D13 一例);
4. 重建下游:SurvPGC 侧 `build_workspace.sh`(C 软链)/ hgcn data 拷贝(见 §2);
5. 在 `Test_series_execution_log.md` 登记产物变化与下游同步。

## 5. 同步提示

SurvPGC_Workspace/Readme.md 的路径说明已随独立化更新(build_workspace.sh 源根 = outputs_pgc)。若 SurvPGC 仓库另有引用旧 `projects/outputs` 的文档/脚本,需在那边同步(跨仓库,由用户维护)。
