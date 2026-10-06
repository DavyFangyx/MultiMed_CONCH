# 改动登记

- 编号系列：**D** = TCGA 数据相关，**T** = 实验相关，**P** = 管线与工程，**G** = 文档与治理；各系列从 1 递增，一行一号；（决策点）= 用户拍板/口径确认。
- 每行 = 一次改动（一个 git 提交，或同一件事合并的多次提交）；**只有明确的决策点才成为提交**（spec §9），脚本小改 / 改名 / 单步实现随所属决策点提交。git 提交名保持原样，本表编号为准。
- 旧长篇执行日志（2026-09-29–10-05，含旧编号 D0-D9 / R1-R13 / S 系列的结论明细）已归档：`backup/execution_log_legacy_20261005.md`；历史细节以 git 为准。
- 口径规格：`Test_series_spec.md`；时间轴协议：`time_axis/time_axis.md`；实验速查：`experiment_list/experiment_list.md`。

## 待决事项

| 编号 | 事项 | 状态 |
|---|---|---|
| D9 | 数据集降级/剔除逐项确认（manifest v2） | 待确认 |
| T29 | Test_5 报告与 Test_4 三档衔接 | 待执行 |
| T30 | gt≤0 剔除 + landmark-first 扶正后的重跑范围：field bank（35 数据集）+ Test_1a 两臂 + Test_1b 重出 + Test_2b / Test_3 搜索与三臂 / Test_5 | 待用户拍板 |
| D10 | 现行 kept_fields 是否切换 landmark-first（选项 C） | ✅ 已拍板（2026-10-05）：切换，见 D13 |
| D11 | 泛癌种方案是否继续全 33 TCGA | 未解决 |
| D12 | 门槛锚点（U1，效应量先验反推） | 未解决 |
| D14 | 365/730 的 landmark 统计缺失时 `run_field_filter` 的行为（回退 raw 统计 vs 直接报错） | 待用户拍板 |

## 改动登记（最新在前）

| 编号 | 改动名称 | git 提交 | 时间 | 简单描述 |
|---|---|---|---|---|
| P14 | 接口整理 D3：脚本接口顺手清理 | `8d107c0` | 2026-10-06 | 提交 s5_univariate_queue.sh 工作区已有修复（manifest 派生 DS_LIST/EXPECTED、QUEUE_ROOT=Test_1a_t0）；check_search_labels 闸门 FAIL 补 sys.exit(1)（编排判据依赖退出码）；s5b 注释修正报告路径为 results/Test_1a/arm_off |
| P13 | 接口整理 B3：slide 级 label 本地派生 | `a62e4c0` | 2026-10-06 | 新增 scripts/build_slide_metadata.py：P 特征文件名枚举 slide 清单（slide_id=stem+.svs、case_id=前 12 位，等价 PGC pipeline.py 做法），左连接本地 case 级 label；输出与 case 级表分离的 metadata_slide/{study}.csv（避免 clinic-only 链路的缓存哈希/闸门被 slide 行数波及，多模态 conf 解 park 时经 LABEL_FILE_PATH 显式指向）；已生成 5 个多模态 study（brca 1100/coad 417/kirc 350/kirp 278/lihc 360 行，kirc 丢弃 168 = P 目录增量，与调研一致） |
| P12 | 接口整理 B1/B2/B4：label/clinical/split 解耦去 PGC 回退 | `3a21acd` | 2026-10-06 | landmark_labels.resolve_label_file 与 greedy.data（load_survival_table/default_label_file_for）删 PGC 回退——仅本地、缺失即报错；test_survival_metrics 对照源改为 tests/_vendored 快照（122 行原版 vendored），不再读 PGC 仓库，SurvPGC env 下 21 测试全过；Clinic_Analyzer 不入库（P3 裁定）：run.sh（删 prefer_existing_path）、registry.py、defaults.conf 同步去回退、SURVPGC_ROOT 语义收窄为外部特征根（P/G/omics/HGCN），仅盘上生效 |
| P11 | 接口整理 A2：死分支删除 | `f324753` | 2026-10-06 | linear_probe 旧 mask 口径（t_record_le_last_time，以 gt 为 last_time，CLI 无路径可达）整支删除，landmark_policy 参数随死分支移除；check_search_labels 死常量 MONTHS_TO_DAYS（30.44）删除、月空间比较注释修正（该文件首次入库） |
| P10 | 接口整理 A1：协议数值常量集中 | `b8c851d` | 2026-10-06 | 新增 src/common/constants.py：DAYS_PER_MONTH（月→天反推）、LABEL_MONTHS_TO_DAYS（30.44，仅登记为 PGC 外部标签除数）、DAYS_PER_YEAR、LANDMARK_TIMES；landmark_labels/baseline/onehot/converters 与测试内联 365.25 全部改引用 |
| P9 | 收尾：R2 移除 + legacy 回退映射删除 + static_only 更名 + 术语修订（决策点） | `4fac584` `5afccf3` | 2026-10-05 | R2（timepoint 标记）移除——无下游消费者，时点语义由 landmark-first R3 承载；paths.py 三组 \*\_LEGACY 目录回退映射删除（旧名目录已不存在），LEGACY_TO_TEST_RESULTS 保留（历史 run_config 字面量仍被 Test_2b 展示消费）；landmark_none → static_only 全量更名（36 rawdata_stats + 35 outputs bank 目录，代码/测试同步，Clinic_Analyzer registry 盘上同步）；「官方」称谓废弃（唯一官方 = TCGA GDC 词典），kept_fields 等一律称「现行」 |
| D13 | landmark-first 扶正 + 旧 raw-first 运行清理（决策点，选项 C） | `3b1570d` | 2026-10-05 | t0stats 产物扶正为现行 `landmark_0/kept_fields.json`（36 数据集）；`run_field_filter` 默认消费 landmark 统计；删除旧口径下游 23G（field bank 921M + `outputs/_raw` 17G + `results/Test_1a` 5.2G），旧 kept_fields 与两臂 field_cindex 移走 `z_notes/backup/landmark_first_promotion_20261005/`；清理清单 `z_notes/cleaned_runs_landmark_first_20261005.md` |
| G6 | TCGA 处理流程一页地图 | `8b87e45` | 2026-10-05 | `z_notes/tcga_pipeline/README.md`：八阶段流程（扫描→统计→筛选→Field Bank→schemes→label→评估→报表）+ 两条筛选链对照（raw-first vs landmark-first）+ 关键口径一句话版 |
| D13 | 主诊断时间锚点修正（决策点） | `94f3da9` | 2026-10-06 | get_primary_diagnosis 改为 days 锚定（flag 仅 tie-break）；修掉 SKCM 型「随访记录被当主诊断 → 真实 t0 分期被占位符覆盖」；修后 MMSURV 两臂取值全库一致（0/470）；受影响数据集 arm A 工件需重编码 |
| T28 | 论文字段存在性审计 | `b5681fc` | 2026-10-05 | 论文字段缺失被静默占位符化：29 项根本不存在 + 60 项近零（`z_notes/temp/field_existence_audit.md`，字段轴链低估论据） |
| T27 | Test_1a 存在性头条图 | `e9fc79f` | 2026-10-05 | 新增 Main_field_existence 图（coverage 崩塌散点 + 逐数据集准入构成）；头条命题改为「时间口径决定单字段是否存在」，172/468 在 t0 下不存在或退化 |
| G5 | 文档体系整理（决策点） | `7b46233` `90df0eb` `7b6e664` | 2026-10-05 | 删 9 个遗物文档；登记表统一为 D/T/P/G 编号；spec §9 提交协议修订（只有决策点才提交）；README 合一导航；旧日志归档 backup/ |
| D8 | landmark-first 字段准入（决策点） | `1443af6` | 2026-10-05 | t0 口径字段统计 + R0-R6 重跑；172/468 字段排除；Test_1a 报表准入集 296 字段 |
| D7 | gt≤0 全局剔除（决策点） | `2a1ee01` | 2026-10-05 | 训练/评估全局过滤 gt≤0 占位坑患者（label 层、splits 不动）；rawdata_stats 分类计数 + 排除清单；MMSURV 132 confs 重跑：59/66 对 Δ 逐位归零，7 对残差根因 = 特征工件不一致 |
| T26 | Test_3 局部预览 + 搜索修复提速 | `a50dedc` `ae630bd` `b2c7ade` | 2026-10-04 | 三臂表局部预览；conf 分裂修复、按 GPU 配置 drainer |
| T25 | Test_3 停止标准修订（决策点） | `08aaa36` | 2026-10-04 | gain-only δ=0.005 替代 sig_stop |
| T24 | 头条图重设计 + 修订 | `eda5c36` `d94a445` | 2026-10-04 | Test_1a/1b 头条图重设计（密度分组图 + 山脊图），指标口径不变 |
| T23 | Test_4 三档表预览 + 柱图 | `44898f5` `47f2707` | 2026-10-04 | 三档汇总表局部预览（64 行）+ 均值柱状图 |
| T22 | Test_5 批跑基建（决策点） | `977a273` | 2026-10-04 | 批跑基建 + diff=0 小样验证关闭 + GPU0-3 投放 |
| P8 | baseline 编码批产 | `a444c56` | 2026-10-03 | 188 编码产物，幂等验证通过 |
| P7 | cox 自检修复 + 补记 | `7cfd516` `a6dde93` | 2026-10-03 | tie 翻转根因修复；arm_A cox 时代差异记录；训练限 GPU0-3 |
| P6 | HGCN 等价放行确认（决策点） | `b525f76` | 2026-10-03 | HGCN L0-L5 等价 → 放行；产物维持冻结 |
| P5 | HGCN 编码落地 | `3f57887` | 2026-10-03 | 任意 scheme + landmark 编码，等价性回归通过 |
| P4 | Q 离线重算 | `1507cba` | 2026-10-03 | 离线重算脚本 + 训练侧 metrics-input 落盘 |
| T21 | Test_5 方案修订（决策点） | `0be1511` `37b49ca` | 2026-10-03 | HGCN 不纳入 → 编码先落地、模型暂不接入 |
| P3 | Q 指标修复 + 补记 | `830efd6` `bf804c5` | 2026-10-03 | survival_metrics 移植 + cox Breslow；Clinic_Analyzer 不入库裁定 |
| T20 | Test_5 规格落地（决策点） | `b8f4f28` | 2026-10-03 | E/M/Q 三轴不变性规格 + HGCN 产物备份 |
| T19 | Test_3 链恢复（4 连） | `546ed9b` `556eae1` `0d502c7` `f4e1a5f` | 2026-10-03 | 臂 B 陈旧行修复、早停语义核对、搜索与臂 C 链恢复、遗留归档 |
| T18 | Test_2a 新口径重跑 | `027673b` | 2026-10-03 | 值来源槽位 t_hi 判定的泄露审计重跑 |
| T17 | Test_1b 主图拆分 | `e0a7228` | 2026-10-03 | topk 重叠拆两张 Main |
| T16 | Test_2b 主图改版 | `1f5fd04` | 2026-10-02 | 两档值直画（橙=论文报告值，蓝=去泄露值） |
| G4 | 结果前缀规范 + 目录 README | `41a3617` `e2ec56c` | 2026-10-02 | Main/Appx/Raw/Meta 前缀重组 + 结果目录 README 入库 |
| P2 | 命名统一迁移（决策点） | `c08bf04` `60148c6` `b698cb7` `e66828e` `1ca3f45` | 2026-10-02 | 三处目录 Test 编号主键统一：文档层 → 路径登记中心 → configs/results 物理迁移（基线归档先行） |
| T15 | Test_3 批跑终止归档 | `9dc0c5b` | 2026-10-02 | 批跑停止、进度留盘 |
| D6 | 编码噪声本底存档 | `2ebcc58` | 2026-10-02 | CONCH 全局 padding 长度敏感性记录（文档已随遗物删除） |
| T14 | Test_3 字段轴链落地 | `1bb2a36` `c035a17` `479518f` `14aa395` | 2026-10-02 | 搜索队列 + 三臂 B′ 全量 + 臂 C 自动接力 + 比较脚本与 Δc 图；missed_fields 遗漏字段清单产出于此 |
| T13 | Test_1a off 臂落地 | `1d3b9bb` | 2026-10-02 | off 臂（raw 变体）落地 + Δc 报表 |
| T12 | 训练范围限定（决策点） | `5594e0b` | 2026-10-02 | 训练限 n_event ≥ 100 的 15 主集 |
| T11 | Test_1b 落地 | `8db193a` | 2026-10-02 | 三指标 + 四档分层 + top-k 重叠 |
| G3 | 实验编号重组（决策点） | `0c3a3a7` `bb1495b` `27e0bf4` | 2026-10-02 | Test_1 动机 / Test_2 高估 / Test_3 低估 / Test_4 三档表；清单改列与执行口径说明 |
| T10 | H3b 取消 | `82da8d2` | 2026-09-30 | 单字段排序对照取消 |
| G2 | 实验命题总表（3 迭代） | `eb00fbe` `2813dad` `049aea4` | 2026-09-30 | 命题总表补写 / 改写 / 补全 |
| T9 | H2 步骤1（冒烟中止） | `2c492dd` | 2026-09-30 | 自定义方案生成与三臂对照脚本 |
| T8 | leak_rate 口径纠错（决策点） | `d93a0f3` | 2026-09-30 | 改为追踪论文管线实际输入的时间槽 |
| T7 | 单字段泄露对照 | `fd2dc3e` | 2026-09-30 | 串联 H1a 与 H1b（Test_1a 前身） |
| T6 | Δc 对照报表 | `0c256dd` | 2026-09-30 | 报告值 vs 去泄露值 |
| T5 | 贪婪停止标准确认（决策点） | `eef900e` | 2026-09-30 | sig_stop 阈值早停 0.005 |
| T4 | Test_2b 批跑完成 | `e4178e0` `5bcb33d` `96ecde7` `ee3ba89` `02f4100` | 2026-09-30 | 138 组合×2 臂×2 分析器放量，552/552 confs 完成；期间 watch 判活修复、GPU 迁移与 drainer 重启 |
| D5 | n_event 判据补全 | `854de4e` | 2026-09-30 | 70-100 带 CI 不排名；33 TCGA 计数校正 |
| P1 | landmark 管线扩展（决策点） | `c5f1e9e` `ee8d688` | 2026-09-30 | A_pipeline --landmark_time 扩展与冒烟自检；放量确认 |
| D4 | 数据协议 A 判据（决策点） | `f787410` `4c0aeaf` `a9a051a` | 2026-09-30 | n_event 四档：≥100 / 70-100 / 30-70 / <30；全部按 A 判据执行，B/C 存档不执行 |
| D3 | 门槛锚点 + HGCN 绑定 | `9937ba9` | 2026-09-30 | 门槛锚点改由效应量先验反推（未解决）；HGCN 按癌种绑定 |
| D2 | 范围纠正（决策点） | `84c68a3` | 2026-09-29 | 仅 33 TCGA；外部数据集暂不纳入；未确认事项先报告 |
| T3 | 删除 E 系列结果（决策点） | `2144102` | 2026-09-29 | 按方案 B 删除 E 系列结果，释放约 200GB |
| T2 | 泄露审计初版 | `2f4e0c1` `5dd455a` | 2026-09-29–30 | 审计模块与全数据集审计；按新绑定重跑（HGCN 仅本癌种，剔除 CPTAC/MMRF） |
| D1 | 时间口径变更（决策点） | `9ff280d` `fc019b3` | 2026-09-29 | 经典 landmark 三要件确立；默认 landmark_0，landmark_none 更名 static_only |
| T1 | 可用数据集评估 | `6b04cc0` | 2026-09-29 | 评估脚本 + 初版 manifest（Test_0 前身） |
| G1 | 规格与日志建立 | `a14e01a` | 2026-09-29 | H 系列规格与执行日志（Test_ 系列前身） |
| — | 前史（19 提交） | `21bf422` … `9f64feb` | 2026-07-27–09-12 | 仓库初始化 → 多数据集集成 → 贪婪部署 → A/B 管线演变与 A 清理 → GDC/CHC 数据接入 → E1/E2 实验组织 |
