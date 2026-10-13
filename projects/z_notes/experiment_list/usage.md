# 实验全链路速查(usage)
> **在 `projects/` 根目录执行**。环境三分:训练 = conda env **SurvPGC**,编码 = conda env **conch**,投递/监控 = **base python 3.13**(速查表见 runbook.md §env 变量速查)。
> **结果在哪看**:训练落 `results/`、报表落 `results_display/`(各 Test 对应目录见 runbook.md「结果在哪看(总览)」表)。
> **队列纪律**:上一步判据满足再走下一步(唯一并行例外:Test_2 时间轴链 与 Test_3 字段轴链);长序列运行,关键节点须人工核查审计(runbook.md 各阶段判据)。
> **队列入口(已收敛)**:全部投递/监控走 `bash scripts/exp_queue.sh <verb> --arm <臂>`(臂与别名 `bash scripts/exp_queue.sh list`);环境配置只有三个通用变量:`CUDA_VISIBLE_DEVICES`(GPU)/ `WORKERS`(并发)/ `PYTHON3`(解释器)。
> 例外:Test_3 搜索 / Test_6 的 **watch·drain** 仍是动态槽位调度,留在 `scripts/Test_3_search_queue.py` / `scripts/t6_scheduler.sh`。

## 分步手动(按阶段自己跑;每个阶段的完整子命令见 runbook.md 对应小节)
### 阶段 0:前置闸门
```bash
# 闸门:搜索链路 label 无 gt≤0 患者(FAIL → 先修 label,再投任何队列)
python scripts/check_search_labels.py
# 判据:退出码 0
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

# 判据:退出码 0 且 rawdata_stats/*/landmark_0/kept_fields.json 齐备(registry 全量 35 数据集;存在性审计 field_presence / 时间统计 time_stats 见 runbook.md 阶段 1)
```
### 阶段 2:编码(一律 conch env;换卡改行首 env,默认卡 7)
```bash
# Field Bank 文本基座(Test_1a t0 臂 / Test_3 字段基座;失败 → 先补阶段 1;换卡改行首 CUDA_VISIBLE_DEVICES)
CUDA_VISIBLE_DEVICES=7 conda run -n conch python scripts/run_field_bank.py --dataset all --landmark_time 0 --encoding prompt
# 论文方案 gdc 线:基线 / HGCN 子命令(文本嵌入一律 bank 切片,apipe 全量编码已删除;
#   Test_3_* 切片 = scripts/Test_3_arms.py slice,零重编码)
conda run -n conch python scripts/run_a_manual.py baseline --dataset all --scheme paper
# off 臂 raw Field Bank(mask off;唯一差异 = 取值 mask;产物 outputs/_raw/;换卡改行首 CUDA_VISIBLE_DEVICES)
CUDA_VISIBLE_DEVICES=7 bash scripts/exp_queue.sh bank --arm test_1a_off
# 判据:退出码 0;bash scripts/exp_queue.sh check --arm test_1a_off 通过(raw bank 齐);主集 field_index.json 存在
```
### 阶段 3:实验(所有 Test;细节见 runbook.md 阶段 3)

```bash
# Test_1a t0 臂(mask 开,landmark_0):预投放主集 conf(幂等)
bash scripts/exp_queue.sh enqueue --arm test_1a_t0
# Test_1a t0 臂训练:drain 守到完成(失败重试/死进程补位/收尾报表;GPU 2,3,4 × 8 workers)
CUDA_VISIBLE_DEVICES=2,3,4 WORKERS=8 bash scripts/exp_queue.sh drain --arm test_1a_t0
# Test_1a off 臂(mask 关,no_mask):同上,GPU 7 × 8 workers
bash scripts/exp_queue.sh enqueue --arm test_1a_off
CUDA_VISIBLE_DEVICES=7 WORKERS=8 bash scripts/exp_queue.sh drain --arm test_1a_off

# Test_2:2a 审计(不训练)→ 2b 逐波投放 + 训练
python scripts/run_leak_audit.py
bash scripts/exp_queue.sh enqueue --arm test_2b --slice A1   # 按 wave_order 逐波
CUDA_VISIBLE_DEVICES=5 WORKERS=8 bash scripts/exp_queue.sh drain --arm test_2b
python3 results_display/scripts/Test_2b_delta_report.py

# Test_3:搜索(动态槽位调度保留在 Test_3_search_queue.py)→ 两臂 → Test_4
bash scripts/exp_queue.sh enqueue --arm test_3_search
T3_SEARCH_WORKERS=16 nohup python scripts/Test_3_search_queue.py watch --gpus 1,0,3,4,5,6 --interval 60 \
    > results/Test_3_greedy_vs_works/logs/watch.log 2>&1 &
python scripts/Test_3_arms.py generate --arm b
python scripts/Test_3_arms.py slice --arm b --parallel 3
bash scripts/exp_queue.sh enqueue --arm test_3_arms --variant b
CUDA_VISIBLE_DEVICES=1 WORKERS=2 bash scripts/exp_queue.sh drain --arm test_3_arms
python scripts/Test_3_arms.py generate --arm ksig
CUDA_VISIBLE_DEVICES=1 WORKERS=2 bash scripts/exp_queue.sh drain --arm test_3_arms
python scripts/Test_3_compare.py --all
python results_display/scripts/Test_4_three_tiers.py

# Test_5:入队 → 后台多卡调度(GPU 硬约束 0-3 空闲卡)→ 汇总 → Q 重算
bash scripts/exp_queue.sh enqueue --arm test_5
bash scripts/exp_queue.sh scheduler
bash scripts/exp_queue.sh summarize --arm test_5
bash scripts/exp_queue.sh q_recompute          # 判据 diff=0

# Test_6:试点 24 搜索(GPU 0-3 × 8 槽 × 8 workers,脚本内固定)→ bakeoff 汇总
bash scripts/t6_scheduler.sh
python scripts/run_bakeoff_report.py --results-root results/Test_6_search/prompt \
    --extra-roots results/Test_3_greedy_vs_works/search --budget_cap 500
# 判据:各臂 queue 空 && running 空 && done == 期望数(exp_queue 派生);Test_6 done ≥ 24
```
### 阶段 4:报表(不训练;脚本幂等)
```bash
# Test_1a 两臂对照图 / Δc 排序 / leak×Δc 交叉
python results_display/scripts/Test_1a_field_level.py
# Test_2b Δc 森林图 / 汇总表(Test_1b 分布 / Test_4 三档见 runbook.md 阶段 4,可在此重跑)
python results_display/scripts/Test_2b_delta_report.py
# 判据:4 个脚本退出码 0
```
完整手册、判据细节、env 速查与已知坑见 runbook.md。
