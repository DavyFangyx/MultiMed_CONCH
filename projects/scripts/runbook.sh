#!/bin/bash
# =============================================================================
# scripts/runbook.sh —— 实验全链路串行入口(人可读)
#
# 与 z_notes/experiment_list/runbook.md 一一对应:阶段编号、命令、判据、产物相同。
# 本文档只负责"顺序 + 判据",不重复实现任何环境/GPU 逻辑——那些都在各 queue 脚本里。
#
# 阶段表(编号同 runbook.md):
#   0  前置闸门            check_search_labels.py / cache_status.py(退出码判据)
#   1  原始文件审查        扫描 → 统计 → 筛选(命令同步跑完,查产物落盘)
#   2  编码                Field Bank / 方案 / off 臂 raw bank(命令同步跑完,查产物落盘)
#   3  Test_1a 单字段      s5(t0 臂)+ s5b(off 臂);等两家族队列四桶
#   4  Test_2 时间轴链     2a 审计 + s4_Test_2b_queue(encode/enqueue/drain/watch→validate)
#   5  Test_3 字段轴链     搜索 → 三臂 → compare + Test_4 三档
#   6  Test_5 不变性       4 子检查 enqueue/scheduler → summarize/q_recompute
#   7  Test_6 算法选型     t6_scheduler → run_bakeoff_report
#   8  报表                4 个 results_display 脚本(幂等)
#
# 用法(在 projects/ 根目录,或任意目录——ROOT 自动定位):
#   bash scripts/runbook.sh run_all     # 按 0→8 串行跑;每阶段先探测判据,已满足 → SKIP
#   bash scripts/runbook.sh stage 3     # 只跑阶段 3(编号含义见上表 / runbook.md)
#   bash scripts/runbook.sh status      # 一屏总览:四桶计数 vs 期望 / 阶段判据 / 最新产物 / 最近日志
#   bash scripts/runbook.sh help
#
# 环境变量:
#   RUNBOOK_POLL_INTERVAL=60      轮询间隔(秒)
#   RUNBOOK_STAGE_TIMEOUT=86400   单阶段轮询超时(秒;默认 24h)
#   RUNBOOK_ROOT=...              projects 根目录覆盖(默认 = 本脚本目录的上一级)
#   FIELD_BANK_GPU / A_PIPELINE_GPU / S5_* / S4_* / T3_* / T5_* 见 runbook.md "env 变量速查"
#
# 日志:每次运行在 results/_runbook/runs/{YYYYmmdd_HHMMSS}/ 写 runbook.log(tee)+ started_at/ended_at;
#       stage N 复用最近一次的日志目录(results/_runbook/current 指针)。
# =============================================================================
set -uo pipefail

ROOT="${RUNBOOK_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT" || { echo "[runbook][错误] 无法进入根目录: $ROOT" >&2; exit 1; }

# -----------------------------------------------------------------------------
# 常量区(对应 runbook.md 的"一页速览/各阶段判据";改判据只改这里)
# -----------------------------------------------------------------------------
CONFIG_ROOT="$ROOT/Clinic_Analyzer/configs"

POLL_INTERVAL="${RUNBOOK_POLL_INTERVAL:-60}"      # 轮询间隔(秒)
STAGE_TIMEOUT="${RUNBOOK_STAGE_TIMEOUT:-86400}"   # 单阶段轮询超时(秒)= 24h

# R13 主集 = n_event ≥ 100 的 15 个 TCGA(派生自 results/Test_0_dataset_availability/manifest.csv)
MAIN_DATASETS="TCGA-BLCA TCGA-BRCA TCGA-COAD TCGA-GBM TCGA-HNSC TCGA-KIRC TCGA-LAML TCGA-LGG TCGA-LUAD TCGA-LUSC TCGA-OV TCGA-PAAD TCGA-SKCM TCGA-STAD TCGA_LIHC"
EXP_MAIN=15                                       # 主集数据集数(阶段 2 判据 / Test_1a 期望)
EXP_REVIEW_DATASETS=36                            # 阶段 1 判据:rawdata_stats/*/landmark_0/kept_fields.json 个数

# 队列家族表:"家族名|队列根|期望 done 数|阶段标签"
# 判据统一 = queue 空 && running 空 && done ≥ 期望数(桶里可能含历史超集,故用 ≥)
FAMILIES=(
  "Test_1a_t0|$CONFIG_ROOT/Test_1a_t0|15|阶段3 t0 臂"
  "Test_1a_off|$CONFIG_ROOT/Test_1a_off|15|阶段3 off 臂"
  "Test_2b_arms|$CONFIG_ROOT/Test_2b_arms|256|阶段4(R13 口径;桶内 552 为全量遗留)"
  "Test_3_search|$CONFIG_ROOT/Test_3_search|15|阶段5 搜索"
  "Test_3_arms|$CONFIG_ROOT/Test_3_arms|60|阶段5 臂 B′(15×4;C 臂/HGCN 另计)"
  "Test_5_5E_2b|$CONFIG_ROOT/Test_5_5E_2b|128|阶段6"
  "Test_5_5E_3|$CONFIG_ROOT/Test_5_5E_3|66|阶段6"
  "Test_5_5M_2b|$CONFIG_ROOT/Test_5_5M_2b|128|阶段6(期望 200,其中 72 多模态 parked)"
  "Test_5_5M_3|$CONFIG_ROOT/Test_5_5M_3|66|阶段6"
  "Test_6_search|$CONFIG_ROOT/Test_6_search|24|阶段7(3 数据集 × 8 算法)"
)

# 阶段 1 / 2 / 8 的命令(顺序即 runbook.md 对应小节的命令块)
STAGE1_CMDS=(
  "python scripts/run_scan_fields.py --dataset all"
  "python scripts/run_field_presence.py --dataset all"
  "python scripts/run_landmark_first_filter.py"
  "python scripts/run_time_stats.py --dataset all"
)
STAGE2_CMDS=(
  "conda run -n conch python scripts/run_field_bank.py --dataset all --landmark_time 0 --encoding prompt"
  "conda run -n conch python scripts/run_schemes.py --dataset all --scheme all --landmark_time 0"
  "conda run -n conch python scripts/run_a_manual.py pipeline --dataset all --scheme paper"
  "conda run -n conch python scripts/run_a_manual.py baseline --dataset all --scheme paper"
  "python scripts/run_a_manual.py hgcn_clinic --dataset all --scheme paper"
  "bash scripts/s5b_univariate_queue.sh bank"
  "bash scripts/s5b_univariate_queue.sh check"
)
STAGE8_CMDS=(
  "python results_display/scripts/Test_1a_field_level.py"
  "python results_display/scripts/Test_1b_dataset_cindex.py"
  "python results_display/scripts/Test_2b_delta_report.py"
  "python results_display/scripts/Test_4_three_tiers.py"
)

# 产物路径(阶段 8 判据 + status 的"最新产物"段)
ARTIFACT_PATHS=(
  "results/Test_1a/arm_off/_s5b_report.json"
  "results/Test_2a_leak_audit/leak_audit_summary.csv"
  "results/Test_2b/arm_B"
  "results/Test_3_greedy_vs_works/three_arm.csv"
  "results/Test_5_invariance/5E_2b"
  "results/Test_6_search/prompt"
  "results_display/Test_6_search/decision.json"
  "results_display/Test_1a_field_level"
  "results_display/Test_1b_dataset_cindex"
  "results_display/Test_2b_delta"
  "results_display/Test_4_three_tiers/Main_three_tiers.csv"
)

# -----------------------------------------------------------------------------
# 输出helper(全部走 stdout → tee 进 runbook.log)
# -----------------------------------------------------------------------------
info()   { printf '[runbook] %s\n' "$*"; }
warn()   { printf '[runbook][警告] %s\n' "$*"; }
err()    { printf '[runbook][错误] %s\n' "$*" >&2; }
die()    { err "$*"; exit 1; }
banner() { printf '\n============================================================\n[阶段 %s] %s\n============================================================\n' "$1" "$2"; }

# 逐条打印后执行;失败返回 1(set -e 语义由调用方 die 实现)
run_cmd() {
  printf '\n$ %s\n' "$1"
  eval "$1" || { err "命令失败(阶段 ${CURRENT_STAGE:-?}):$1"; return 1; }
}

# -----------------------------------------------------------------------------
# 队列四桶计数(直接 ls 数 conf,不解析各 status 子命令文本)
# -----------------------------------------------------------------------------
cnt() { ls "$1"/*.conf 2>/dev/null | wc -l; }

# 家族记录查找:$1=家族名 → 回显 "队列根|期望数|阶段标签"
family_lookup() {
  local want="$1" rec
  for rec in "${FAMILIES[@]}"; do
    if [ "${rec%%|*}" = "$want" ]; then printf '%s\n' "${rec#*|}"; return 0; fi
  done
  return 1
}

# 单家族判据:queue 空 && running 空 && done ≥ 期望
family_ok() {
  local rest root exp
  rest="$(family_lookup "$1")" || return 1
  root="${rest%%|*}"; rest="${rest#*|}"; exp="${rest%%|*}"
  [ "$(cnt "$root/queue")" -eq 0 ] && [ "$(cnt "$root/running")" -eq 0 ] && [ "$(cnt "$root/done")" -ge "$exp" ]
}

# 家族进度串(轮询/status 用)
family_progress() {
  local rest root exp
  rest="$(family_lookup "$1")" || { printf '??'; return 0; }
  root="${rest%%|*}"; rest="${rest#*|}"; exp="${rest%%|*}"
  printf 'done=%s/%s queue=%s running=%s failed=%s' \
    "$(cnt "$root/done")" "$exp" "$(cnt "$root/queue")" "$(cnt "$root/running")" "$(cnt "$root/failed")"
}

# -----------------------------------------------------------------------------
# 产物计数(阶段 1 / 2 的判据)
# -----------------------------------------------------------------------------
count_kept_fields() { ls "$ROOT"/rawdata_stats/*/landmark_0/kept_fields.json 2>/dev/null | wc -l; }

count_main_field_bank() {          # 15 主集的 Field Bank 文本基座
  local ds n=0
  for ds in $MAIN_DATASETS; do
    [ -f "$ROOT/outputs/$ds/field_bank/prompt/landmark_0/field_index.json" ] && n=$((n + 1))
  done
  printf '%s' "$n"
}

count_main_raw_bank() {            # 15 主集的 off 臂 raw bank(outputs/_raw)
  local ds n=0
  for ds in $MAIN_DATASETS; do
    [ -f "$ROOT/outputs/_raw/$ds/field_bank/prompt/static_only/field_index.json" ] && n=$((n + 1))
  done
  printf '%s' "$n"
}

# -----------------------------------------------------------------------------
# 阶段判据探测:满足 → run_all 里 SKIP
# (阶段 0/8 无产物判据:闸门只读、报表幂等,每次都执行)
# -----------------------------------------------------------------------------
stage_satisfied() {
  case "$1" in
    0) return 1 ;;
    1) [ "$(count_kept_fields)" -ge "$EXP_REVIEW_DATASETS" ] ;;
    2) [ "$(count_main_field_bank)" -ge "$EXP_MAIN" ] && [ "$(count_main_raw_bank)" -ge "$EXP_MAIN" ] ;;
    3) family_ok Test_1a_t0 && family_ok Test_1a_off ;;
    4) family_ok Test_2b_arms ;;
    5) family_ok Test_3_search && family_ok Test_3_arms \
         && [ -f "$ROOT/results/Test_3_greedy_vs_works/three_arm.csv" ] ;;
    6) family_ok Test_5_5E_2b && family_ok Test_5_5E_3 \
         && family_ok Test_5_5M_2b && family_ok Test_5_5M_3 ;;
    7) family_ok Test_6_search && [ -f "$ROOT/results_display/Test_6_search/decision.json" ] ;;
    8) return 1 ;;
    *) return 1 ;;
  esac
}

stage_desc() {
  case "$1" in
    0) printf '前置闸门(label 检查 + 缓存盘点;退出码判据,每次都跑)' ;;
    1) printf '原始文件审查(扫描/统计/筛选;kept_fields.json %s/%s)' "$(count_kept_fields)" "$EXP_REVIEW_DATASETS" ;;
    2) printf '编码(Field Bank %s/%s;off 臂 raw bank %s/%s)' "$(count_main_field_bank)" "$EXP_MAIN" "$(count_main_raw_bank)" "$EXP_MAIN" ;;
    3) printf 'Test_1a 单字段泄露对照(t0 + off 两家族)' ;;
    4) printf 'Test_2 时间轴链(2a 审计 + 2b 训练)' ;;
    5) printf 'Test_3 字段轴链(搜索 → 三臂 → Test_4 三档)' ;;
    6) printf 'Test_5 不变性(4 子检查)' ;;
    7) printf 'Test_6 搜索算法选型(试点 24 搜索 → decision.json)' ;;
    8) printf '报表(4 个展示层脚本;幂等,每次都跑)' ;;
    *) printf '?' ;;
  esac
}

# -----------------------------------------------------------------------------
# 轮询:$1=阶段号,其余=家族名;直到全部满足或超时
# -----------------------------------------------------------------------------
wait_families() {
  local stage="$1"; shift
  local fam start now waited ok line
  start=$(date +%s)
  while :; do
    ok=1; line=""
    for fam in "$@"; do
      line="$line $fam[$(family_progress "$fam")]"
      family_ok "$fam" || ok=0
    done
    now=$(date +%s); waited=$((now - start))
    printf '[阶段%s]%s (已等 %dm)\n' "$stage" "$line" "$((waited / 60))"
    if [ "$ok" -eq 1 ]; then
      info "阶段 $stage 判据满足(用时 ${waited}s)"
      return 0
    fi
    if [ "$waited" -ge "$STAGE_TIMEOUT" ]; then
      err "阶段 $stage 轮询超时(${STAGE_TIMEOUT}s 未达判据):$line"
      return 1
    fi
    sleep "$POLL_INTERVAL"
  done
}

# -----------------------------------------------------------------------------
# 日志:results/_runbook/runs/{ts}/runbook.log(tee)+ started_at/ended_at
# -----------------------------------------------------------------------------
RUN_DIR_PTR="$ROOT/results/_runbook/current"

setup_logging() {   # $1 = new(新 run 目录) | reuse(复用 current)
  local mode="$1" run_dir=""
  if [ "$mode" = reuse ] && [ -f "$RUN_DIR_PTR" ]; then
    run_dir="$(cat "$RUN_DIR_PTR")"
  fi
  if [ -z "$run_dir" ] || [ ! -d "$run_dir" ]; then
    run_dir="$ROOT/results/_runbook/runs/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$run_dir"
    printf '%s\n' "$run_dir" > "$RUN_DIR_PTR"
  fi
  RUN_DIR="$run_dir"
  RUN_LOG="$RUN_DIR/runbook.log"
  date '+%F %T' >> "$RUN_DIR/started_at"      # 追加(stage N 复用目录时保留历次记录)
  exec > >(tee -a "$RUN_LOG") 2>&1
  trap 'date "+%F %T" >> "$RUN_DIR/ended_at"' EXIT
  info "runbook 运行目录:$RUN_DIR"
  info "日志:$RUN_LOG"
}

# -----------------------------------------------------------------------------
# 各阶段
# -----------------------------------------------------------------------------
stage_0() {
  banner 0 "前置闸门(label 检查 + 缓存盘点)"
  local gate
  for gate in "scripts/check_search_labels.py" "scripts/cache_status.py"; do
    if [ ! -f "$ROOT/$gate" ]; then
      warn "闸门脚本缺失,跳过(不阻塞):$gate"
      continue
    fi
    run_cmd "python $gate" || die "阶段 0 闸门失败:$gate —— 先修此问题,再投任何队列"
  done
  info "阶段 0 完成:闸门通过"
}

stage_1() {
  banner 1 "原始文件审查(扫描 → 统计 → 筛选)"
  local cmd n
  for cmd in "${STAGE1_CMDS[@]}"; do
    run_cmd "$cmd" || die "阶段 1 命令失败,已中止"
  done
  n="$(count_kept_fields)"
  [ "$n" -ge "$EXP_REVIEW_DATASETS" ] \
    || die "阶段 1 判据不满足:rawdata_stats/*/landmark_0/kept_fields.json 只有 $n/$EXP_REVIEW_DATASETS"
  info "阶段 1 完成:kept_fields.json $n/$EXP_REVIEW_DATASETS 数据集"
}

stage_2() {
  banner 2 "编码(Field Bank / 方案 / label 派生)"
  export FIELD_BANK_GPU="${FIELD_BANK_GPU:-7}"    # Field Bank 编码卡
  export A_PIPELINE_GPU="${A_PIPELINE_GPU:-7}"    # run_a_manual 编码卡
  local cmd fb rb
  for cmd in "${STAGE2_CMDS[@]}"; do
    run_cmd "$cmd" || die "阶段 2 命令失败,已中止"
  done
  fb="$(count_main_field_bank)"; rb="$(count_main_raw_bank)"
  [ "$fb" -ge "$EXP_MAIN" ] || die "阶段 2 判据不满足:主集 Field Bank 基座 $fb/$EXP_MAIN"
  [ "$rb" -ge "$EXP_MAIN" ] || die "阶段 2 判据不满足:主集 off 臂 raw bank $rb/$EXP_MAIN"
  info "阶段 2 完成:Field Bank $fb/$EXP_MAIN;off 臂 raw bank $rb/$EXP_MAIN(label 派生随评估自动落盘)"
}

stage_3() {
  banner 3 "Test_1a 单字段泄露对照(t0 臂 + off 臂)"
  run_cmd "bash scripts/s5_univariate_queue.sh enqueue"  || die "阶段 3 命令失败,已中止"
  run_cmd "bash scripts/s5_univariate_queue.sh watch"    || die "阶段 3 命令失败,已中止"
  run_cmd "bash scripts/s5b_univariate_queue.sh enqueue" || die "阶段 3 命令失败,已中止"
  run_cmd "bash scripts/s5b_univariate_queue.sh drain"   || die "阶段 3 命令失败,已中止"
  run_cmd "bash scripts/s5b_univariate_queue.sh watch"   || die "阶段 3 命令失败,已中止"
  wait_families 3 Test_1a_t0 Test_1a_off || die "阶段 3 判据未达成"
  info "阶段 3 完成:两臂队列四桶均满足"
}

stage_4() {
  banner 4 "Test_2 时间轴链(2a 审计 → 2b 训练)"
  run_cmd "python scripts/run_leak_audit.py"              || die "阶段 4 命令失败,已中止"
  run_cmd "bash scripts/s4_Test_2b_queue.sh encode"       || die "阶段 4 命令失败,已中止"
  run_cmd "bash scripts/s4_Test_2b_queue.sh enqueue A1"   || die "阶段 4 命令失败,已中止"
  run_cmd "bash scripts/s4_Test_2b_queue.sh drain"        || die "阶段 4 命令失败,已中止"
  run_cmd "bash scripts/s4_Test_2b_queue.sh watch"        || die "阶段 4 命令失败,已中止"
  wait_families 4 Test_2b_arms || die "阶段 4 判据未达成"
  run_cmd "bash scripts/s4_Test_2b_queue.sh validate"     || die "阶段 4 首波校验失败"
  info "阶段 4 完成:Test_2b 队列四桶满足 + validate 通过"
}

stage_5() {
  banner 5 "Test_3 字段轴链(搜索 → 三臂 → Test_4 三档)"
  run_cmd "bash scripts/Test_3_queue.sh search_enqueue" || die "阶段 5 命令失败,已中止"
  run_cmd "bash scripts/Test_3_queue.sh search_watch"   || die "阶段 5 命令失败,已中止"
  wait_families 5a Test_3_search || die "阶段 5 搜索判据未达成"
  run_cmd "bash scripts/Test_3_queue.sh arms_generate"  || die "阶段 5 命令失败,已中止"
  run_cmd "bash scripts/Test_3_queue.sh arms_encode_bg" || die "阶段 5 命令失败,已中止"
  run_cmd "bash scripts/Test_3_queue.sh arms_enqueue"   || die "阶段 5 命令失败,已中止"
  run_cmd "bash scripts/Test_3_queue.sh arms_drain"     || die "阶段 5 命令失败,已中止"
  run_cmd "bash scripts/Test_3_queue.sh arms_generate_c" || die "阶段 5 命令失败,已中止"
  run_cmd "bash scripts/Test_3_queue.sh arms_drain"     || die "阶段 5 命令失败,已中止"
  wait_families 5b Test_3_arms || die "阶段 5 三臂判据未达成"
  run_cmd "bash scripts/Test_3_queue.sh compare"        || die "阶段 5 三臂总表失败"
  run_cmd "python results_display/scripts/Test_4_three_tiers.py" || die "阶段 5 Test_4 三档失败"
  [ -f "$ROOT/results/Test_3_greedy_vs_works/three_arm.csv" ] \
    || die "阶段 5 判据不满足:three_arm.csv 未落盘"
  info "阶段 5 完成:搜索 + 三臂 + Test_4 三档"
}

stage_6() {
  banner 6 "Test_5 不变性(5E_2b / 5E_3 / 5M_2b / 5M_3)"
  run_cmd "bash scripts/Test_5_queue.sh enqueue"   || die "阶段 6 命令失败,已中止"
  run_cmd "bash scripts/Test_5_queue.sh scheduler" || die "阶段 6 命令失败,已中止"
  wait_families 6 Test_5_5E_2b Test_5_5E_3 Test_5_5M_2b Test_5_5M_3 || die "阶段 6 判据未达成"
  run_cmd "bash scripts/Test_5_queue.sh summarize" || die "阶段 6 汇总失败"
  run_cmd "bash scripts/Test_5_queue.sh q_recompute" || die "阶段 6 Q 轴重算失败"
  info "阶段 6 完成:四子检查落盘 + summarize + q_recompute(diff 见上方输出)"
}

stage_7() {
  banner 7 "Test_6 搜索算法选型(试点 24 搜索 → bake-off 汇总)"
  run_cmd "bash scripts/t6_scheduler.sh" || die "阶段 7 调度器失败"
  wait_families 7 Test_6_search || die "阶段 7 判据未达成"
  run_cmd "python scripts/run_bakeoff_report.py --results-root results/Test_6_search/prompt --extra-roots results/Test_3_greedy_vs_works/search --budget_cap 500" \
    || die "阶段 7 bake-off 汇总失败"
  [ -f "$ROOT/results_display/Test_6_search/decision.json" ] \
    || die "阶段 7 判据不满足:decision.json 未落盘"
  info "阶段 7 完成:需人工确认 winner / greedy_wins / ambiguous / run_seas_ablations(runbook.md 阶段 7)"
}

stage_8() {
  banner 8 "报表(展示层,不训练)"
  local cmd f missing=0
  for cmd in "${STAGE8_CMDS[@]}"; do
    run_cmd "$cmd" || die "阶段 8 脚本失败,已中止"
  done
  for f in results_display/Test_1a_field_level results_display/Test_1b_dataset_cindex \
           results_display/Test_2b_delta results_display/Test_4_three_tiers/Main_three_tiers.csv; do
    [ -e "$ROOT/$f" ] || { warn "阶段 8 产物缺失:$f"; missing=1; }
  done
  [ "$missing" -eq 0 ] || die "阶段 8 判据不满足:有产物缺失(见上方警告)"
  info "阶段 8 完成:results_display/ 4 个目录已刷新"
}

# 执行某阶段(含 SKIP 探测)
run_stage() {
  local n="$1"
  CURRENT_STAGE="$n"
  if stage_satisfied "$n"; then
    info "阶段 $n 判据已满足 → SKIP($(stage_desc "$n"))"
    return 0
  fi
  "stage_$n"
}

run_all() {
  local n
  date '+%F %T' | { read -r t; info "run_all 开始:$t"; }
  for n in 0 1 2 3 4 5 6 7 8; do
    run_stage "$n"
  done
  info "run_all 完成:阶段 0-8 全部通过"
}

# -----------------------------------------------------------------------------
# status:一屏总览
# -----------------------------------------------------------------------------
mtime_line() {
  local p="$ROOT/$1"
  if [ -e "$p" ]; then
    printf '  %-56s %s\n' "$1" "$(date -r "$p" '+%F %T')"
  else
    printf '  %-56s %s\n' "$1" "--(缺失)"
  fi
}

cmd_status() {
  printf '==== runbook status @ %s ====\n' "$(date '+%F %T')"
  printf -- '--- 队列家族(判据 = queue/running 空 且 done >= 期望)---\n'
  printf '%-12s %-38s %6s %8s %8s %10s %8s %8s\n' \
         "家族" "阶段标签" "queue" "running" "done" "期望" "failed" "parked"
  local rec name root exp label q r d f
  for rec in "${FAMILIES[@]}"; do
    name="${rec%%|*}"; rec="${rec#*|}"
    root="${rec%%|*}"; rec="${rec#*|}"
    exp="${rec%%|*}"; label="${rec#*|}"
    q="$(cnt "$root/queue")"; r="$(cnt "$root/running")"; d="$(cnt "$root/done")"
    f="$(cnt "$root/failed")"
    printf '%-12s %-38s %6s %8s %8s %10s %8s %8s\n' \
           "$name" "$label" "$q" "$r" "$d" "$exp" "$f" "$(cnt "$root/parked")"
  done

  printf -- '--- 阶段判据 ---\n'
  local n mark
  for n in 0 1 2 3 4 5 6 7 8; do
    if stage_satisfied "$n"; then mark="满足"; else mark="未满足"; fi
    printf '  阶段 %s: %-6s %s\n' "$n" "$mark" "$(stage_desc "$n")"
  done

  printf -- '--- 最新产物(mtime)---\n'
  local p
  for p in "${ARTIFACT_PATHS[@]}"; do mtime_line "$p"; done

  printf -- '--- 最近 runbook 运行 ---\n'
  if [ -f "$RUN_DIR_PTR" ]; then
    printf '  运行目录:%s\n' "$(cat "$RUN_DIR_PTR")"
    printf '  日志    :%s\n' "$(cat "$RUN_DIR_PTR")/runbook.log"
  else
    printf '  (还没有运行记录:先跑 bash scripts/runbook.sh run_all 或 stage N)\n'
  fi
}

usage() {
  sed -n '2,40p' "${BASH_SOURCE[0]}"
}

# -----------------------------------------------------------------------------
# 入口
# -----------------------------------------------------------------------------
cmd="${1:-help}"
case "$cmd" in
  run_all)
    setup_logging new
    run_all
    ;;
  stage)
    n="${2:-}"
    case "$n" in
      0|1|2|3|4|5|6|7|8) ;;
      *) err "用法: bash scripts/runbook.sh stage {0..8}(含义见 runbook.md 阶段表)"; exit 2 ;;
    esac
    setup_logging reuse
    run_stage "$n"
    ;;
  status)
    cmd_status
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac
