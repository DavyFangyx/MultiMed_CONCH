# 实验全链路速查(usage)
> **在 `projects/` 根目录执行**。环境三分:训练 = conda env **SurvPGC**,编码 = conda env **conch**,投递/监控 = **base python 3.13**(速查表见 runbook.md §env 变量速查)。
> **结果在哪看**:训练落 `results/`、报表落 `results_display/`(各 Test 对应目录见 runbook.md「结果在哪看(总览)」表)。
> **队列纪律**:上一步判据满足再走下一步(唯一并行例外:阶段 4 时间轴链 与 阶段 5 字段轴链);长序列运行,关键节点须人工核查审计(runbook.md 各阶段判据)。

## 分步手动(按阶段自己跑;每个阶段的完整子命令见 runbook.md 对应小节)
### 阶段 0:前置闸门
```bash
# 闸门 1:搜索链路 label 无 gt≤0 患者(FAIL → 先修 label,再投任何队列)
python scripts/check_search_labels.py
# 闸门 2:评估缓存盘点(全新重跑应为空或仅 e2-v2 行;旧 v1 行永不命中)
python scripts/cache_status.py
# 判据:两条均退出码 0
```
### 阶段 1:原始文件审查
```bash
# 字段字典扫描:字段路径 + GDC 字典释义(失败 → 检查 gdc_clinical/raw_json/ 原始文件是否齐)
python scripts/run_scan_fields.py --dataset all
# 现行 landmark-first 链:t0 统计(重算 landmark_0 mask 口径,写 _shared/landmark_0/)
python scripts/run_field_stats.py --dataset all --landmark_time 0
# R0-R6 筛选(R3/R4 阈值可改;自动消费上一步 landmark 统计,生成 kept_fields.json)
python scripts/run_field_filter.py --dataset all --landmark_time 0 \
    --R3_coverage 0.30 --R4_n_unique 2 --R4_mode_share 0.95

# 判据:退出码 0 且 rawdata_stats/*/landmark_0/kept_fields.json 齐备(36 数据集;存在性审计 field_presence / 时间统计 time_stats 见 runbook.md 阶段 1)
```
### 阶段 2:编码(一律 conch env;换卡改行首 env,默认卡 7)
```bash
# Field Bank 文本基座(Test_1a t0 臂 / Test_3 字段基座;失败 → 先补阶段 1;换卡改 FIELD_BANK_GPU)
FIELD_BANK_GPU=7 conda run -n conch python scripts/run_field_bank.py --dataset all --landmark_time 0 --encoding prompt
# 论文方案 gdc 线:方案拼句 + 编码(换卡改 A_PIPELINE_GPU 或加 --gpu N;随后补 baseline / hgcn_clinic 子命令)
A_PIPELINE_GPU=7 conda run -n conch python scripts/run_a_manual.py pipeline --dataset all --scheme paper
# off 臂 raw Field Bank(mask off;唯一差异 = 取值 mask;产物 outputs/_raw/;换卡改行首 S5B_ENC_GPU)
S5B_ENC_GPU=7 bash scripts/s5b_univariate_queue.sh bank
# 判据:退出码 0;bash scripts/s5b_univariate_queue.sh check 通过(raw bank 15/15)+ run_schemes.py 方案组合(见 runbook.md 阶段 2);15 主集 field_index.json 存在
```
### 阶段 3:Test_1a 单字段泄露对照
```bash
# t0 臂:预投放 15 主集 conf(幂等)
bash scripts/s5_univariate_queue.sh enqueue
# t0 臂:后台自愈循环(训练;换卡/换并发改行首 S5_GPUS / S5_WORKERS,全完成 report 退出)
S5_GPUS=2,3,4 S5_WORKERS=8 bash scripts/s5_univariate_queue.sh watch
# off 臂:预投放主集 conf(幂等;raw bank 已在阶段 2 建好)
bash scripts/s5b_univariate_queue.sh enqueue
# off 臂:每 GPU 起一个后台 drainer(换卡/换并发改行首 S5B_GPUS / S5B_WORKERS)
S5B_GPUS=7 S5B_WORKERS=8 bash scripts/s5b_univariate_queue.sh drain
# 判据:两家族 queue 空 && running 空 && done ≥ 15(off 臂 watch 自愈见 runbook.md 阶段 3)
```
### 阶段 4:Test_2 时间轴链(2a 审计 → 2b 训练)
```bash
# 2a 审计:逐字段 leak_rate(描述性,不训练)
python scripts/run_leak_audit.py
# 2b 编码:补齐缺失 embeddings(conch env;换卡改行首 A_PIPELINE_GPU;已存在的跳过)
A_PIPELINE_GPU=7 bash scripts/s4_Test_2b_queue.sh encode
# 2b 训练:后台自愈(换卡/换并发改行首 S4_GPU_TRAIN / S4_WORKERS;自动分波投放 + drainer 续跑)
S4_GPU_TRAIN=5 S4_WORKERS=8 bash scripts/s4_Test_2b_queue.sh watch
# 判据:Test_2b_arms queue 空 && running 空 && done ≥ 256;再跑 bash scripts/s4_Test_2b_queue.sh validate(退出码 0)
```
### 阶段 5:Test_3 字段轴链(搜索 → 三臂 → Test_4)
```bash
# 搜索:预投放 15 主集搜索 conf(幂等)
bash scripts/Test_3_queue.sh search_enqueue
# 搜索:后台 watch 自愈(换卡改行首 T3_SEARCH_GPUS;全 done 自动 report 退出)
T3_SEARCH_GPUS=1,0,3,4,5,6 bash scripts/Test_3_queue.sh search_watch
# 三臂:生成臂 B′ 自定义方案(注册进 schemes.json)
bash scripts/Test_3_queue.sh arms_generate
# 三臂:臂 B′ 后台训练(换卡/换并发改行首 T3_GPU / T3_WORKERS;前置 arms_encode_bg + arms_enqueue 投放见 runbook.md 阶段 5)
T3_GPU=1 T3_WORKERS=2 bash scripts/Test_3_queue.sh arms_drain
# 判据:Test_3_search done ≥ 15;Test_3_arms done ≥ 60;总表 bash scripts/Test_3_queue.sh compare(臂 C 用 nohup bash scripts/Test_3_arm_c_chain.sh 接力)
```
### 阶段 6:Test_5 不变性
```bash
# 全部子检查入队(幂等,可重跑;缺编码会 SKIP 并列出)
bash scripts/Test_5_queue.sh enqueue
# 后台多卡调度(GPU 政策硬约束:只用空闲 0-3,脚本内固定;换并发改行首 T5_WORKERS;停止用 scheduler_stop,勿直接 kill)
T5_WORKERS=2 bash scripts/Test_5_queue.sh scheduler
# 判据:四子检查 done ≥ 128/66/128/66 且 queue/running 空;再跑 bash scripts/Test_5_queue.sh summarize 与 q_recompute(diff=0)
```
### 阶段 7:Test_6 搜索算法选型
```bash
# 试点 24 个搜索(3 数据集 × 8 算法)调度器;nohup 后台跑,日志 /tmp/t6_scheduler.log
bash scripts/t6_scheduler.sh
# 全部完成后汇总(贪心用 Test_3 搜索结果,--extra-roots 指过去,不重跑)
python scripts/run_bakeoff_report.py --results-root results/Test_6_search/prompt --extra-roots results/Test_3_greedy_vs_works/search --budget_cap 500
# 判据:Test_6_search done ≥ 24 且 queue/running 空;results_display/Test_6_search/decision.json 落盘(人工确认 winner)
```
### 阶段 8:报表(不训练;脚本幂等)
```bash
# Test_1a 两臂对照图 / Δc 排序 / leak×Δc 交叉
python results_display/scripts/Test_1a_field_level.py
# Test_2b Δc 森林图 / 汇总表(Test_1b 分布 / Test_4 三档见 runbook.md 阶段 8,可在此重跑)
python results_display/scripts/Test_2b_delta_report.py
# 判据:4 个脚本退出码 0
```
完整手册、判据细节、env 速查与已知坑见 runbook.md。
