#!/usr/bin/env python3
"""实验队列统一入口：一套 verb + 一张臂注册表，承载全部 (数据集 × 实验配置) 差异。

收敛口径（实现层同构、结果层零变动）：
  * 队列原语早已统一（`src/greedy/queue.py` / `src/manual_pipeline/cindex.py` /
    `src/selection/queue.py`），本文件只合并三套"调用层"：同一组 verb
    （enqueue / status / retry / recover / trim / drain / watch / report / summarize / list …），
    差异全部落在 ARM_REGISTRY 的每条臂记录里；
  * 每条臂的 drainer argv **逐字**保留旧脚本写法 —— argv 全字段进 job_key 哈希材料
    （greedy/queue.py 跳过 workers/device/conch_python/analyzer_python/queue_root +
    dataset/landmark_tag；selection/queue.py 跳过 queue_root/poll_seconds/max_jobs/workers
    + dataset/landmark_time），改一个字符就会造出新 conf / 孤儿；
  * conf 名与内容由底层 primitives 决定，本文件不构造、不改写；
  * 已退休脚本（s4_enqueue.py / s4_Test_2b_queue.sh / s5_univariate_enqueue.py /
    s5_univariate_queue.sh / s5b_univariate_enqueue.py / s5b_univariate_queue.sh /
    s5c_univariate_enqueue.py / Test_3_queue.sh / Test_5_queue.sh / Test_5_drain.py /
    Test_5_scheduler.py）的每个 verb 在本文件都有等价姿势，见
    `z_notes/experiment_list/usage.md` / `runbook.md`。

三个 backend（= 三套队列原语，臂记录里的 `backend` 字段选择）：
  univariate  greedy/queue.py         Test_1a t0 / off / merged 三臂
  cindex      manual_pipeline/cindex  Test_2b 波次切片 / Test_3 两臂 / Test_5 四个子检查
  search      selection/queue.py      Test_3 搜索 / Test_6 试点（watch/drain 仍留在
                                      Test_3_search_queue.py 与 t6_scheduler.sh，
                                      动态槽位调度不并入本文件）

用法（projects/ 根目录，base python3；训练由各 drainer 自行拉起）：
  python3 scripts/exp_queue.py list                              # 臂注册表
  python3 scripts/exp_queue.py status --arm all                  # 全家族一屏
  python3 scripts/exp_queue.py enqueue --arm test_1a_t0          # 投放（幂等）
  python3 scripts/exp_queue.py enqueue --arm test_2b --slice A1  # 波次切片
  python3 scripts/exp_queue.py drain --arm test_1a_off --gpu 7   # 起 drainer
  python3 scripts/exp_queue.py watch --arm test_1a_off --gpus 7  # 自愈循环（前台）
  python3 scripts/exp_queue.py scheduler                         # Test_5 多卡调度（GPU 0-3）
  python3 scripts/exp_queue.py recover --arm test_3_search       # running 悬挂回收
外壳 `scripts/exp_queue.sh` 负责环境变量前缀透传与 nohup 包装（后台守候用）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common.paths import LANDMARK_OFF_TAG, config_family_dir, test_results_dir  # noqa: E402

SCRIPTS = ROOT / "scripts"
OUTPUTS = ROOT / "outputs"
RESULTS = ROOT / "results"
MANIFEST_CSV = RESULTS / "Test_0_dataset_availability" / "manifest.csv"
EVENT_SUMMARY_CSV = ROOT / "rawdata_stats" / "_shared" / "event_summary.csv"
MAIN_N_EVENT_MIN = 100          # R13：训练范围 = label 宇宙有效事件 >= 100 的 TCGA 主集（2026-10-09 口径）
MAX_RETRIES = 3
BUCKETS = ("queue", "running", "done", "failed")
UNI_BUCKETS = ("queue", "running", "done", "failed")

# Test_6 试点网格（逐字同 scripts/t6_scheduler.sh；该脚本保留负责槽位调度）
T6_DATASETS = ("TCGA-GBM", "TCGA-LGG", "TCGA-PAAD")
T6_ALGOS = ("A1_random", "A3_beam", "A4_anneal", "A5_genetic", "A6_aco", "SEAS",
            "A0_full", "A0b_topk")
T6_WORKERS = 8


# ===========================================================================
# 数据集名单（R13：label 宇宙有效事件派生，不硬编码；2026-10-09 口径）
# ===========================================================================

def main_datasets_from_manifest() -> list[str]:
    from common.patient_universe import main_datasets_by_label_events

    return main_datasets_by_label_events(threshold=MAIN_N_EVENT_MIN)


def n_event_table() -> dict[str, int]:
    """n_event 表 = label 宇宙有效事件（直接读 label metadata；2026-10-09 口径）。"""
    from common.patient_universe import tcga_label_event_table

    table = tcga_label_event_table()
    if not table:
        raise FileNotFoundError(
            "[exp_queue] 未找到 label metadata（R13 权威来源：Clinic_Analyzer/data/datasets_csv/metadata）"
        )
    return table


def datasets_for(arm: "Arm", override: str | None = None) -> list[str]:
    """臂的数据集名单（R13 主集；--datasets 覆盖供冒烟/调试）。"""
    if override:
        names = [x.strip() for x in str(override).split(",") if x.strip()]
        if not names:
            raise SystemExit("[exp_queue] --datasets 为空")
        return names
    if arm.dataset_source == "manifest15":
        return main_datasets_from_manifest()
    if arm.dataset_source == "eventsummary15":
        table = n_event_table()
        names = sorted(
            name for name, n_event in table.items()
            if name.startswith(("TCGA-", "TCGA_")) and int(n_event) >= MAIN_N_EVENT_MIN
        )
        if not names:
            raise SystemExit(f"[exp_queue] 主集为空（n_event >= {MAIN_N_EVENT_MIN}）")
        return names
    raise SystemExit(f"[exp_queue] 臂 {arm.name} 的 dataset_source 未实现: {arm.dataset_source}")


# ===========================================================================
# 小工具
# ===========================================================================

def env_path(arm: "Arm", key: str, default: str) -> Path:
    """带臂前缀的环境变量覆盖（S5B_PID_DIR / S5C_DRAIN_LOG …），同旧脚本。"""
    return Path(os.environ.get(f"{arm.env}{key}", default))


def pid_alive(pid: int) -> bool:
    if not pid or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def log_line(arm: "Arm", msg: str, *, watch_log: Path | None = None) -> None:
    line = f"[{arm.tag}][{datetime.now().strftime('%F_%T')}] {msg}"
    print(line, flush=True)
    if watch_log is None:
        return
    try:
        watch_log.parent.mkdir(parents=True, exist_ok=True)
        with watch_log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def bucket_counts(root: Path, buckets=BUCKETS) -> dict[str, int]:
    return {b: (len(list((root / b).glob("*.conf"))) if (root / b).is_dir() else 0)
            for b in buckets}


def parse_csv_list(value: str) -> list[str]:
    return [x.strip() for x in str(value).split(",") if x.strip()]


def spawn(python_exe: str, argv: list[str], *, log_path: Path | None = None,
          pid_path: Path | None = None, env: dict | None = None,
          run_dir: Path = ROOT) -> int:
    """后台起进程（start_new_session），可选日志/pid 落盘；返回 PID。"""
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    handle_ctx = (log_path.open("ab") if log_path is not None else
                  open(os.devnull, "ab"))
    with handle_ctx as handle:
        proc = subprocess.Popen([python_exe, *argv], cwd=str(run_dir),
                                env=env or dict(os.environ), stdout=handle,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    if pid_path is not None:
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(f"{proc.pid}\n", encoding="utf-8")
    return proc.pid


def pid_from_file(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or 0)
    except ValueError:
        return 0


# ===========================================================================
# 臂注册表
#   * drainer_argv 逐字保留旧脚本写法（job_key 哈希材料，禁用任何"顺手重构"）
#   * queue_root / results_root / pid / log 默认值同旧脚本（env 前缀可覆盖）
# ===========================================================================

@dataclass
class Arm:
    name: str
    backend: str                    # univariate | cindex | search
    tag: str                        # 日志前缀（沿用旧脚本，便于与历史 log 对照）
    queue_root: Path
    env: str                        # 环境变量前缀（S5_/S5B_/S5C_/S4_/T3_/T5_/T6_）
    dataset_source: str = "manifest15"
    results_root: Path | None = None
    field_csv_root: Path | None = None          # report/status 产物根（univariate）
    drainer_argv: Callable[..., list[str]] | None = None
    drainer_script: str = ""                    # 子进程 drainer 入口
    drain_mode: str = ""                        # spawn_legacy | inprocess
    pid_dir_default: str = ""
    drain_log_default: str = ""
    watch_log_default: str = ""
    report_json: Path | None = None             # 最终 report 落盘（旧脚本口径）
    sub: str | None = None                      # Test_5 子检查
    variants: tuple[str, ...] = ()               # Test_3 两臂：b/ksig/best
    workers_default: int = 8
    workers_env: str = "WORKERS"
    gpus_default: str = ""
    nice_level: int = 0                          # 旧 Test_5 壳整体 nice -n 10；其余家族为 0
    extras: dict = field(default_factory=dict)
    note: str = ""

    # --- 派生路径（带 env 前缀覆盖，同旧脚本）---
    @property
    def pid_dir(self) -> Path:
        return env_path(self, "PID_DIR", self.pid_dir_default)

    @property
    def drain_log(self) -> Path:
        return env_path(self, "DRAIN_LOG", self.drain_log_default)

    @property
    def watch_log(self) -> Path:
        return env_path(self, "WATCH_LOG", self.watch_log_default)


# --- univariate：Test_1a 三臂 -------------------------------------------------

# t0：greedy/queue.py 默认队列根（argv 不带 --queue_root，逐字同 s5_univariate_enqueue.py）
_ARM_T0 = Arm(
    name="test_1a_t0", backend="univariate", tag="s5", env="S5_",
    queue_root=config_family_dir("Test_1a_t0"),
    results_root=test_results_dir("Test_1a/arm_t0"),
    field_csv_root=test_results_dir("Test_1a/arm_t0") / "prompt" / "landmark_0",
    dataset_source="manifest15",
    drainer_script="run_univariate_cindex.py",
    drainer_argv=lambda datasets, *, workers: [
        "--dataset", ",".join(datasets),
        "--landmark_time", "0",
        "--encoding", "prompt",
        "--analyzer", "mlp_clinic_flatten",
        "--seed", "0",
        "--workers", str(workers),
    ],
    pid_dir_default="/tmp/s5_univariate",
    drain_log_default="/tmp/s5_drain.log",
    watch_log_default="/tmp/s5_watch.log",
    workers_default=8, workers_env="WORKERS", gpus_default="2,3,4",
    note="landmark_0 全字段（原 s5）：mask 开 + outputs/ 正式 bank",
)

# off：raw 变体（mask off + 患者集显式 landmark_0 + 三根目录改道），逐字同 s5b
_ARM_OFF = Arm(
    name="test_1a_off", backend="univariate", tag="s5b", env="S5B_",
    queue_root=config_family_dir("Test_1a_off"),
    results_root=test_results_dir("Test_1a/arm_off"),
    field_csv_root=test_results_dir("Test_1a/arm_off") / "univariate" / "prompt" / LANDMARK_OFF_TAG,
    dataset_source="eventsummary15",
    drainer_script="run_univariate_cindex.py",
    drainer_argv=lambda datasets, *, workers: [
        "--dataset", ",".join(datasets),
        "--landmark_time", "none",
        "--extraction_mask", "off",
        "--label_tag", "landmark_0",
        "--field_bank_root", str(OUTPUTS / "_raw"),
        "--embeddings_root", str(OUTPUTS / "_raw"),
        "--results_dir", str(test_results_dir("Test_1a/arm_off")),
        "--queue_root", str(config_family_dir("Test_1a_off")),
        "--encoding", "prompt",
        "--analyzer", "mlp_clinic_flatten",
        "--seed", "0",
        "--workers", str(workers),
    ],
    pid_dir_default="/tmp/s5b_univariate",
    drain_log_default="/tmp/s5b_drain.log",
    watch_log_default="/tmp/s5b_watch.log",
    report_json=test_results_dir("Test_1a/arm_off") / "_s5b_report.json",
    workers_default=8, workers_env="WORKERS", gpus_default="7",
    extras={"bank_script": "s5b_build_raw_field_bank.py",
            "bank_root": OUTPUTS / "_raw", "bank_tag": LANDMARK_OFF_TAG,
            "enc_gpu_default": "7", "build_log_default": "/tmp/s5b_build.log"},
    note="off（原 s5b）：extraction_mask off + outputs/_raw bank",
)

# merged：t0 语义 + bank 改道 outputs/_merged，逐字同 s5c
_ARM_MERGED = Arm(
    name="test_1a_merged", backend="univariate", tag="s5c", env="S5C_",
    queue_root=config_family_dir("Test_1a_t0_merged"),
    results_root=test_results_dir("Test_1a/arm_t0_merged"),
    field_csv_root=(test_results_dir("Test_1a/arm_t0_merged") / "univariate" / "prompt"
                    / "landmark_0"),
    dataset_source="eventsummary15",
    drainer_script="run_univariate_cindex.py",
    drainer_argv=lambda datasets, *, workers: [
        "--dataset", ",".join(datasets),
        "--landmark_time", "0",
        "--field_bank_root", str(OUTPUTS / "_merged"),
        "--embeddings_root", str(OUTPUTS / "_merged"),
        "--results_dir", str(test_results_dir("Test_1a/arm_t0_merged")),
        "--queue_root", str(config_family_dir("Test_1a_t0_merged")),
        "--encoding", "prompt",
        "--analyzer", "mlp_clinic_flatten",
        "--seed", "0",
        "--workers", str(workers),
    ],
    pid_dir_default="/tmp/s5c_univariate",
    drain_log_default="/tmp/s5c_drain.log",
    watch_log_default="/tmp/s5c_watch.log",
    report_json=test_results_dir("Test_1a/arm_t0_merged") / "_s5c_report.json",
    workers_default=8, workers_env="WORKERS", gpus_default="1",
    note="merged t0（原 s5c）：landmark_0 + outputs/_merged bank",
)

# --- cindex：Test_2b 波次切片 ------------------------------------------------

# drainer 逐字同 s4_Test_2b_queue.sh cmd_drain（run_a_manual.py cindex，BRCA conf 已在 done/）
_ARM_2B = Arm(
    name="test_2b", backend="cindex", tag="S4", env="S4_",
    queue_root=config_family_dir("Test_2b_arms"),
    results_root=test_results_dir("Test_2b"),
    dataset_source="slice_grid",
    drainer_script="run_a_manual.py",
    drain_mode="spawn_legacy",
    drainer_argv=lambda *, workers: [
        "--dataset", "TCGA-BRCA",
        "--scheme", "MULTISURV",
        "--landmark_time", "none",
        "--encoding", "text",
        "--analyzer", "clinic_cox",
        "--workers", str(workers),
        "--queue_root", str(config_family_dir("Test_2b_arms")),
    ],
    workers_default=8, workers_env="WORKERS", gpus_default="5",
    extras={"slices": ("A1", "A1H", "B1", "B1H", "A2", "A2H", "B2", "B2H",
                       "A3", "A3H", "B3", "B3H"),
            "wave_order": ("A1", "A1H", "B1", "B1H", "A2", "B2", "A3", "B3"),
            "done_expected": 552,
            "cindex_results_root": None,          # 逐字同 s4_enqueue.py（None = cindex 默认）
            "log_dir": test_results_dir("Test_2b") / "logs",
            "conda_env_default": "conch", "encode_parallel_default": "2",
            "encode_list_default": "/tmp/s4_encode_queue.tsv",
            "validate_script": "s4_validate_firstwave.py"},
    note="Test_2b 网格（33 TCGA 全量超集，R13 后波 2/3 空）+ 编码队列",
)

# --- cindex：Test_3 两臂 ----------------------------------------------------

_ARM_3ARMS = Arm(
    name="test_3_arms", backend="cindex", tag="test_3", env="T3_",
    queue_root=config_family_dir("Test_3_arms"),
    results_root=RESULTS / "Test_3_greedy_vs_works",
    dataset_source="manifest15",
    drain_mode="inprocess",
    variants=("b", "ksig", "best"),
    workers_default=2, workers_env="WORKERS", gpus_default="1",
    extras={"cindex_results_root": RESULTS,      # 逐字同 Test_3_arms._cindex_jobs
            "arm_b_results": test_results_dir("Test_2b/arm_B"),
            "log_root": RESULTS / "Test_3_greedy_vs_works" / "logs"},
    note="deleak（Test_3_{work}_{ds}）/ reach（Test_3_greedy_{ds}）cindex 投放与 drain",
)


# --- cindex：Test_5 四个子检查 ----------------------------------------------

def _t5_arm(sub: str, note: str) -> Arm:
    return Arm(
        name=f"test_5_{sub}", backend="cindex", tag="test_5", env="T5_",
        queue_root=config_family_dir(f"Test_5_{sub}"),
        results_root=RESULTS / "Test_5_invariance" / sub,
        dataset_source="manifest15",
        drain_mode="inprocess",
        sub=sub,
        workers_default=1, workers_env="WORKERS", gpus_default="1",
        nice_level=10,                    # 逐字同旧 Test_5_queue.sh（所有子命令 nice -n 10）
        extras={"summarize_script": "Test_5_summarize.py",
                "log_root": RESULTS / "Test_5_invariance" / "logs"},
        note=note,
    )


_ARM_5E_2B = _t5_arm("5E_2b", "E→baseline 复现 Test_2b 臂对 {report/deleak} × mlp_clinic_flatten")
_ARM_5E_3 = _t5_arm("5E_3", "E→baseline 复现 Test_3 臂对 {deleak/reach}")
_ARM_5M_2B = _t5_arm("5M_2b", "M→snn_clinic_flatten（多模态 4 集默认 parked）复现 Test_2b 臂对")
_ARM_5M_3 = _t5_arm("5M_3", "M→clinic_cox 复现 Test_3 臂对 {deleak/reach}")

# --- search：Test_3 搜索 / Test_6 试点 ---------------------------------------


def search_cli() -> Path:
    return SCRIPTS / "run_e2_selection_queue.py"


def t3_search_argv(dataset: str, workers: int | None = None) -> list[str]:
    """逐字同 Test_3_search_queue._runner_argv（--out 绝对路径进 job_key）。"""
    import Test_3_common as C

    argv = [
        sys.executable, str(search_cli()),
        "--dataset", dataset,
        "--landmark_time", str(C.LANDMARK_TIME),
        "--algo", C.ALGO,
        "--stop_mode", C.STOP_MODE,
        "--seed", str(C.SEED),
        "--out", str(C.search_dir(dataset)),
        "--inner_analyzer", C.ANALYZER,
    ]
    if workers is not None:
        argv.extend(["--workers", str(workers)])
    return argv


def t6_search_argv(dataset: str, algo: str, workers: int | None = None) -> list[str]:
    """逐字同 t6_scheduler.sh（--out 相对路径进 job_key，勿改绝对路径）。"""
    return [
        sys.executable, str(search_cli()),
        "--dataset", dataset,
        "--landmark_time", "0",
        "--algo", algo,
        "--stop_mode", "gain_only",
        "--seed", "0",
        "--budget_cap", "500",
        "--queue_root", str(config_family_dir("Test_6_search")),
        "--out", f"results/Test_6_search/prompt/landmark_0/{dataset}/{algo}",
        "--workers", str(T6_WORKERS if workers is None else workers),
    ]


_ARM_T3_SEARCH = Arm(
    name="test_3_search", backend="search", tag="test_3", env="T3_",
    queue_root=config_family_dir("Test_3_search"),
    results_root=RESULTS / "Test_3_greedy_vs_works",
    dataset_source="manifest15",
    workers_default=16, workers_env="SEARCH_WORKERS", gpus_default="1,0,3,4,5,6,4,5,3",
    extras={"landmark": "0", "argv": t3_search_argv,
            "report_out": RESULTS / "Test_3_greedy_vs_works" / "search_summary.csv",
            "watch_script": "Test_3_search_queue.py",
            "workers_map_env": "T3_SEARCH_WORKERS_MAP"},
    note="A2_greedy × landmark_0 × mlp_clinic_flatten × seed 0（drain/watch 见 Test_3_search_queue.py）",
)

_ARM_T6_SEARCH = Arm(
    name="test_6_search", backend="search", tag="test_6", env="T6_",
    queue_root=config_family_dir("Test_6_search"),
    results_root=RESULTS / "Test_6_search",
    dataset_source="t6_grid",
    workers_default=T6_WORKERS, workers_env="WORKERS", gpus_default="0,1,2,3",
    extras={"landmark": "0", "argv": t6_search_argv,
            "report_script": "run_bakeoff_report.py",
            "report_argv": ["--results-root", "results/Test_6_search/prompt",
                            "--extra-roots", "results/Test_3_greedy_vs_works/search",
                            "--budget_cap", "500"],
            "watch_script": "t6_scheduler.sh"},
    note="Test_6 试点 3 数据集 × 8 算法（槽位调度仍由 t6_scheduler.sh 负责）",
)

ARM_REGISTRY: dict[str, Arm] = {
    arm.name: arm for arm in (
        _ARM_T0, _ARM_OFF, _ARM_MERGED,
        _ARM_2B, _ARM_3ARMS, _ARM_5E_2B, _ARM_5E_3, _ARM_5M_2B, _ARM_5M_3,
        _ARM_T3_SEARCH, _ARM_T6_SEARCH,
    )
}

ARM_ALIASES = {
    "t0": "test_1a_t0", "off": "test_1a_off", "merged": "test_1a_merged",
    "1a_t0": "test_1a_t0", "1a_off": "test_1a_off", "1a_merged": "test_1a_merged",
    "2b": "test_2b", "3arms": "test_3_arms", "3search": "test_3_search",
    "6search": "test_6_search", "2b_arms": "test_2b", "3_arms": "test_3_arms",
    "5E_2b": "test_5_5E_2b", "5E_3": "test_5_5E_3",
    "5M_2b": "test_5_5M_2b", "5M_3": "test_5_5M_3",
}

# 组别名：一次带上一族（旧脚本的"全部子检查/三臂一起"用法）
ARM_GROUPS = {
    "test_5": ("test_5_5E_2b", "test_5_5E_3", "test_5_5M_2b", "test_5_5M_3"),
    "test_1a": ("test_1a_t0", "test_1a_off", "test_1a_merged"),
}


def arm_names() -> list[str]:
    return list(ARM_REGISTRY)


def resolve_arms(names: list[str] | None) -> list[Arm]:
    names = [n for n in (names or ["all"]) if n]
    out: list[Arm] = []
    for name in names:
        if name == "all":
            out.extend(ARM_REGISTRY.values())
            continue
        if name in ARM_GROUPS:
            out.extend(ARM_REGISTRY[item] for item in ARM_GROUPS[name])
            continue
        key = ARM_ALIASES.get(name, name)
        if key not in ARM_REGISTRY:
            raise SystemExit(
                f"[exp_queue] 未知臂: {name}（可选: all, {', '.join(ARM_REGISTRY)}；"
                f"组: {', '.join(ARM_GROUPS)}；别名: {', '.join(ARM_ALIASES)}）"
            )
        out.append(ARM_REGISTRY[key])
    return out


def workers_for(arm: Arm, opts) -> int:
    if opts.workers is not None:
        return max(1, int(opts.workers))
    env_value = os.environ.get(f"{arm.env}{arm.workers_env}")
    if env_value:
        try:
            return max(1, int(env_value))
        except ValueError:
            pass
    return max(1, int(arm.workers_default))


def gpus_for(arm: Arm, opts) -> list[str]:
    if opts.gpus:
        return parse_csv_list(opts.gpus)
    env_value = os.environ.get(f"{arm.env}GPUS") or os.environ.get(f"{arm.env}GPU")
    if env_value:
        return parse_csv_list(env_value)
    default = arm.gpus_default or (opts.gpu or "")
    return parse_csv_list(default)


# ===========================================================================
# univariate backend（greedy/queue.py；Test_1a 三臂）
# ===========================================================================

def uni_args(arm: Arm, datasets: list[str], workers: int):
    """与 drainer 完全同源的参数命名空间（enqueue 的 job_key 由它决定）。"""
    from greedy.univariate_cli import make_parser

    args = make_parser().parse_args(arm.drainer_argv(datasets, workers=workers))
    args.queue_kind = "univariate"
    return args


def uni_key(arm: Arm, datasets: list[str], workers: int) -> str:
    """只读算 job_key（job_key_from_args 与 enqueue_jobs 内部同源，不碰盘）。"""
    from greedy.queue import job_key_from_args

    return job_key_from_args(uni_args(arm, datasets, workers))


def uni_counts(arm: Arm, key: str) -> dict[str, int]:
    from greedy.queue import count_bucket

    return {b: count_bucket(arm.queue_root, b, key) for b in UNI_BUCKETS}


def cmd_uni_enqueue(arm: Arm, opts) -> None:
    from greedy.queue import enqueue_jobs

    datasets = datasets_for(arm, opts.datasets)
    args = uni_args(arm, datasets, workers_for(arm, opts))
    result = enqueue_jobs(args, datasets, root=arm.queue_root)
    print(f"[{arm.tag}] enqueue root={result['root']} key={result['job_key']} "
          f"created={len(result['created'])} existing={len(result['existing'])}")
    for path in result["created"]:
        print(f"[{arm.tag}]   + {path.name}")


def cmd_uni_status(arm: Arm, opts) -> None:
    datasets = datasets_for(arm, opts.datasets)
    key = uni_key(arm, datasets, workers_for(arm, opts))
    counts = uni_counts(arm, key)
    total = sum(counts.values())
    print(f"[{arm.tag}] status key={key} queue={counts['queue']} running={counts['running']} "
          f"done={counts['done']} failed={counts['failed']} total={total}/{len(datasets)}")
    n_csv = n_complete = n_rows = n_err = 0
    for ds in datasets:
        csv_path = arm.field_csv_root / ds / "mlp_clinic_flatten" / "field_cindex.csv"
        if not csv_path.exists():
            continue
        n_csv += 1
        rows = csv_path.read_text(encoding="utf-8").splitlines()
        n = max(0, len(rows) - 1)
        err = sum(1 for line in rows[1:] if ",error," in line)
        n_rows += n
        n_err += err
        print(f"[{arm.tag}]   {ds}: rows={n} error={err}")
        if err == 0 and n > 0:
            n_complete += 1
    print(f"[{arm.tag}] field_cindex.csv present: {n_csv}/{len(datasets)} "
          f"(error-free: {n_complete}) rows={n_rows} error={n_err}")


def cmd_uni_retry(arm: Arm, opts) -> None:
    from greedy.queue import ensure_queue_dirs

    root = arm.queue_root
    state_path = root / "retry_state.json"
    max_retries = int(opts.max_retries or MAX_RETRIES)
    ensure_queue_dirs(root)
    state: dict[str, int] = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    moved = skipped = 0
    for path in sorted((root / "failed").glob("*.conf")):
        name = path.name
        tries = int(state.get(name, 0))
        if tries >= max_retries:
            skipped += 1
            print(f"[{arm.tag}] retry skip (max {max_retries}): {name}")
            continue
        dest = root / "queue" / name
        if dest.exists():
            path.unlink(missing_ok=True)
            continue
        path.rename(dest)
        path.with_suffix(".err").unlink(missing_ok=True)
        state[name] = tries + 1
        moved += 1
        print(f"[{arm.tag}] retry requeue {name} (try {tries + 1}/{max_retries})")
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[{arm.tag}] retry moved={moved} skipped={skipped}")


def cmd_uni_recover(arm: Arm, opts) -> int:
    """running/ 里 claimed_pid 已死的 conf 放回 queue/（drainer 被杀后任务不丢）。"""
    from greedy.queue import ensure_queue_dirs, load_job

    root = arm.queue_root
    ensure_queue_dirs(root)
    recovered = 0
    for path in sorted((root / "running").glob("*.conf")):
        try:
            job = load_job(path)
        except Exception:
            continue
        pid = job.get("claimed_pid")
        if pid and pid_alive(int(pid)):
            continue
        dest = root / "queue" / path.name
        if not dest.exists():
            path.rename(dest)
            recovered += 1
    if recovered:
        print(f"[{arm.tag}] recover running->queue: {recovered}")
    return recovered


def uni_dataset_from_conf(path: Path) -> str:
    from greedy.queue import load_job

    try:
        return str(load_job(path).get("dataset") or "")
    except Exception:
        parts = path.stem.split("__")
        return parts[1] if len(parts) > 1 else ""


def cmd_uni_trim(arm: Arm, opts) -> None:
    """把不在当前名单里的任务从 queue/running/failed 撤到 parked/（不删除，可回滚）。"""
    from greedy.queue import ensure_queue_dirs

    root = arm.queue_root
    parked = root / "parked"
    ensure_queue_dirs(root)
    current = set(datasets_for(arm, opts.datasets))
    parked.mkdir(parents=True, exist_ok=True)
    moved = 0
    for bucket in ("queue", "running", "failed"):
        for path in sorted((root / bucket).glob("*.conf")):
            if uni_dataset_from_conf(path) in current:
                continue
            dest = parked / path.name
            if dest.exists():
                path.unlink(missing_ok=True)
            else:
                path.rename(dest)
            path.with_suffix(".err").unlink(missing_ok=True)
            moved += 1
            print(f"[{arm.tag}] trim {bucket}/{path.name} -> parked/")
    print(f"[{arm.tag}] trim moved={moved} (current set={len(current)})")


def uni_start_drainer(arm: Arm, datasets: list[str], gpu: str, workers: int) -> int:
    pid_dir = arm.pid_dir
    pid_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    env["OMP_NUM_THREADS"] = env.get("OMP_NUM_THREADS", "2")
    env["OPENBLAS_NUM_THREADS"] = env.get("OPENBLAS_NUM_THREADS", "1")
    env["MKL_NUM_THREADS"] = env.get("MKL_NUM_THREADS", "1")
    python_exe = os.environ.get(f"{arm.env}PYTHON3", "python3")
    pid = spawn(python_exe,
                [str(SCRIPTS / arm.drainer_script), *arm.drainer_argv(datasets, workers=workers)],
                log_path=arm.drain_log, pid_path=pid_dir / f"gpu{gpu}.pid", env=env)
    return pid


def uni_drainer_alive(arm: Arm, gpu: str) -> bool:
    return pid_alive(pid_from_file(arm.pid_dir / f"gpu{gpu}.pid"))


def cmd_uni_drain(arm: Arm, opts) -> None:
    datasets = datasets_for(arm, opts.datasets)
    workers = workers_for(arm, opts)
    for gpu in gpus_for(arm, opts):
        pid = uni_start_drainer(arm, datasets, gpu, workers)
        print(f"[{arm.tag}] drainer GPU {gpu} PID {pid} (log {arm.drain_log})")


def cmd_uni_watch(arm: Arm, opts) -> None:
    """自愈循环：recover + retry + 重启死掉的 drainer；全部 done 后 report 并退出。"""
    datasets = datasets_for(arm, opts.datasets)
    expected = len(datasets)
    gpus = gpus_for(arm, opts)
    workers = workers_for(arm, opts)
    key = uni_key(arm, datasets, workers)
    log_line(arm, f"watch start key={key} expected={expected} gpus={','.join(gpus)} "
                  f"workers={workers}", watch_log=arm.watch_log)
    last_status = 0.0
    while True:
        cmd_uni_recover(arm, opts)
        cmd_uni_retry(arm, opts)
        counts = uni_counts(arm, key)
        if counts["queue"] > 0:
            for gpu in gpus:
                if not uni_drainer_alive(arm, gpu):
                    pid = uni_start_drainer(arm, datasets, gpu, workers)
                    log_line(arm, f"relaunch drainer GPU {gpu} PID {pid} "
                                  f"(queue={counts['queue']} running={counts['running']})",
                             watch_log=arm.watch_log)
        now = time.time()
        if now - last_status >= 300:
            log_line(arm, f"status queue={counts['queue']} running={counts['running']} "
                          f"done={counts['done']} failed={counts['failed']}",
                     watch_log=arm.watch_log)
            last_status = now
        if counts["done"] >= expected and counts["queue"] == 0 and counts["running"] == 0:
            log_line(arm, f"ALL {expected} done", watch_log=arm.watch_log)
            cmd_uni_report(arm, opts)
            log_line(arm, "watch exit", watch_log=arm.watch_log)
            return
        time.sleep(max(1, int(opts.interval)))


def cmd_uni_report(arm: Arm, opts) -> None:
    datasets = datasets_for(arm, opts.datasets)
    total_rows = total_ok = total_err = 0
    missing: list[str] = []
    payload: dict[str, dict] = {}
    for ds in datasets:
        csv_path = arm.field_csv_root / ds / "mlp_clinic_flatten" / "field_cindex.csv"
        if not csv_path.exists():
            missing.append(ds)
            continue
        ok = err = 0
        for line in csv_path.read_text(encoding="utf-8").splitlines()[1:]:
            if line.endswith(",ok"):
                ok += 1
            elif line.endswith(",error"):
                err += 1
        total_rows += ok + err
        total_ok += ok
        total_err += err
        payload[ds] = {"rows": ok + err, "ok": ok, "error": err}
    print(f"[{arm.tag}] report datasets_with_csv={len(datasets) - len(missing)}/{len(datasets)} "
          f"field_rows={total_rows} ok={total_ok} error={total_err}")
    if missing:
        print(f"[{arm.tag}] missing: {missing}")
    if arm.report_json is None:
        return
    arm.report_json.parent.mkdir(parents=True, exist_ok=True)
    arm.report_json.write_text(
        json.dumps({"n_datasets": len(datasets), "missing": missing, "rows": total_rows,
                    "ok": total_ok, "error": total_err, "per_dataset": payload},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[{arm.tag}] report json: {arm.report_json}")


def cmd_uni_bank(arm: Arm, opts) -> int:
    """raw Field Bank 构建（原 s5b_univariate_queue.sh bank；conch env，已存在即跳过）。"""
    conch_python = os.environ.get(f"{arm.env}CONCH_PYTHON",
                                  "/data/fangyuxuan/miniconda3/envs/conch/bin/python")
    enc_gpu = os.environ.get(f"{arm.env}ENC_GPU", arm.extras.get("enc_gpu_default", "7"))
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = str(enc_gpu)
    argv = [str(SCRIPTS / arm.extras["bank_script"]), "--dataset", "all"]
    print(f"[{arm.tag}] bank build: CUDA_VISIBLE_DEVICES={enc_gpu} {conch_python} "
          f"{' '.join(argv)}", flush=True)
    return subprocess.call([conch_python, *argv], cwd=str(ROOT), env=env)


def cmd_uni_check(arm: Arm, opts) -> int:
    """R13 主集 raw bank 齐备校验（原 s5b_univariate_queue.sh check）。"""
    bank_root = Path(arm.extras["bank_root"])
    tag = arm.extras["bank_tag"]
    datasets = datasets_for(arm, opts.datasets)
    missing = [n for n in datasets
               if not (bank_root / n / "field_bank" / "prompt" / tag / "field_index.json").exists()]
    print(f"[{arm.tag}] R13 主集 raw banks: {len(datasets) - len(missing)}/{len(datasets)}")
    if missing:
        print(f"[{arm.tag}] missing: {missing}")
        return 1
    return 0


# ===========================================================================
# cindex backend（manual_pipeline/cindex.py）
# ===========================================================================

_SCHEMES_LOADED = False


def load_all_schemes() -> None:
    """注册全部方案（论文 10 + 自定义 Test_3_* + HGCN 字段表），进程内只跑一次。

    旧 Test_3_arms.py 漏了这一步（新进程 enqueue 直接 `未知 cindex 方案: Test_3_*`），
    本 backend 统一走保留定义模块 Test_5_common.load_all_schemes()（唯一实现）；
    多臂循环（如 --arm test_5 四个子检查）不再重复触发注册日志。
    """
    global _SCHEMES_LOADED
    if _SCHEMES_LOADED:
        return
    import Test_5_common as C5

    C5.load_all_schemes()
    _SCHEMES_LOADED = True


# --- Test_2b 波次切片（逐字移植 scripts/s4_enqueue.py）-----------------------

S4_PAN_CANCER_SCHEMES = ["MULTISURV", "SURVPGC", "MMSURV", "INTEGRATIVE_DNN"]
S4_HGCN_BINDING = {
    "TCGA-KIRC": "HGCN_KIRC",
    "TCGA_LIHC": "HGCN_LIHC",
    "TCGA-ESCA": "HGCN_ESCA",
    "TCGA-LUSC": "HGCN_LUSC",
    "TCGA-LUAD": "HGCN_LUAD",
    "TCGA-UCEC": "HGCN_UCEC",
}
S4_ANALYZERS = ["clinic_cox", "mlp_clinic_flatten"]
S4_ENCODING = "text"
S4_ARMS = {"A": "none", "B": "0"}


def s4_load_waves() -> tuple[dict[str, list[str]], set[str]]:
    waves: dict[str, list[str]] = {"1": [], "2": [], "3": []}
    mains: set[str] = set()
    with MANIFEST_CSV.open(newline="") as fh:
        for row in csv.DictReader(fh):
            name = row["dataset"]
            if not name.startswith("TCGA"):
                continue
            n_event = float(row["n_event"] or 0)
            if n_event >= MAIN_N_EVENT_MIN:
                mains.add(name)
            wave = "1" if n_event >= 70 else ("2" if n_event >= 30 else "3")
            waves[wave].append(name)
    for wave in waves:
        waves[wave].sort()
    return waves, mains


def s4_slice_spec(slice_name: str, waves, mains) -> tuple[str, str, list[tuple[str, str]]]:
    arm = slice_name[0].upper()
    if arm not in S4_ARMS:
        raise SystemExit(f"未知 slice: {slice_name}（形如 A1 / A1H / B2 / B3H）")
    hgcn = slice_name.endswith("H")
    wave = slice_name[1:2]
    if wave not in ("1", "2", "3"):
        raise SystemExit(f"未知 slice: {slice_name}")
    combos: list[tuple[str, str]] = []
    if hgcn:
        for dataset, scheme in sorted(S4_HGCN_BINDING.items()):
            if dataset in waves[wave] and dataset in mains:
                combos.append((dataset, scheme))
    else:
        for dataset in waves[wave]:
            if dataset in mains:
                for scheme in S4_PAN_CANCER_SCHEMES:
                    combos.append((dataset, scheme))
    return arm, wave, combos


def s4_jobs_for_combos(arm: Arm, combos: list[tuple[str, str]]) -> list[dict]:
    from manual_pipeline.cindex import iter_cindex_jobs
    from manual_pipeline.datasets import expand_source_jobs, load_source_dataset_configs
    from manual_pipeline.landmark import parse_landmark_setting
    from manual_pipeline.paths import (
        DEFAULT_BASELINE_OUT_ROOT,
        DEFAULT_GDC_DATASETS_CONFIG,
        DEFAULT_OUT_DIR,
        DEFAULT_PROMPT_DIR,
    )

    slice_arm = combos[0][2] if combos and len(combos[0]) > 2 else None
    schemes = sorted({scheme for _, scheme, *_ in combos})
    datasets_by_scheme: dict[str, list[str]] = {}
    for dataset, scheme, *_ in combos:
        datasets_by_scheme.setdefault(scheme, []).append(dataset)
    all_jobs: list[dict] = []
    for scheme in schemes:
        dataset_arg = ",".join(datasets_by_scheme[scheme])
        jobs = expand_source_jobs(
            dataset_arg,
            [scheme],
            load_source_dataset_configs(gdc_config=DEFAULT_GDC_DATASETS_CONFIG),
            json_path=None,
            prompt_dir=DEFAULT_PROMPT_DIR,
            out_dir=DEFAULT_OUT_DIR,
            baseline_out=DEFAULT_BASELINE_OUT_ROOT,
        )
        landmark = parse_landmark_setting(S4_ARMS[slice_arm])
        for job in jobs:
            if not job.get("name"):
                continue
            all_jobs.extend(
                iter_cindex_jobs(
                    dataset_name=job["name"],
                    schemes=list(job.get("schemes") or []),
                    datasets=job.get("datasets") or {},
                    baseline_out=DEFAULT_BASELINE_OUT_ROOT,
                    encoding=S4_ENCODING,
                    modalities=S4_ANALYZERS,
                    results_root=arm.extras["cindex_results_root"],
                    landmark_tag=landmark.arm_tag,
                    landmark_time=landmark.landmark_time,
                )
            )
    return all_jobs


def s4_slice_combos(arm: Arm, slice_name: str) -> tuple[str, str, list[tuple[str, str, str]]]:
    """(arm_letter, wave, [(dataset, scheme, arm_letter)…])，可被 --datasets 收窄。"""
    waves, mains = s4_load_waves()
    letter, wave, combos = s4_slice_spec(slice_name, waves, mains)
    return letter, wave, [(d, s, letter) for d, s in combos]


def cmd_2b_enqueue(arm: Arm, opts) -> None:
    from manual_pipeline.cindex import enqueue_cindex_jobs

    # 旧 s4_enqueue.py main() 对每个子命令都先注册方案（custom/baseline/HGCN）；
    # 不注册会让 4 个 pan-cancer 方案在整表里来源绑定为 None -> 静默 0 job。
    load_all_schemes()
    if not opts.slice:
        raise SystemExit("[exp_queue] enqueue --arm test_2b 需要 --slice（如 A1 / B1H；"
                         f"可选 {' '.join(arm.extras['slices'])}）")
    letter, wave, combos = s4_slice_combos(arm, opts.slice)
    if opts.datasets:
        allow = set(datasets_for(arm, opts.datasets))
        combos = [c for c in combos if c[0] in allow]
    print(f"[{arm.tag}] slice={opts.slice} arm=landmark_{S4_ARMS[letter]} wave={wave} "
          f"combos={len(combos)} confs_expected={len(combos) * len(S4_ANALYZERS)}")
    jobs = s4_jobs_for_combos(arm, combos)
    queued = enqueue_cindex_jobs(jobs, queue_root=str(arm.queue_root))
    print(f"[{arm.tag}] queue={queued['root']} created={len(queued['created'])} "
          f"existing={len(queued['existing'])} retried={len(queued.get('retried', []))}")
    print(f"[{arm.tag}] 下一步: 由 drainer 进程 claim 并训练"
          f"（python3 scripts/exp_queue.py drain --arm test_2b）")


def cmd_2b_summarize(arm: Arm, opts) -> None:
    from manual_pipeline.cindex import summarize_dataset
    from manual_pipeline.landmark import parse_landmark_setting

    load_all_schemes()  # 同旧 s4_enqueue.py main()：汇总前也先注册方案
    slices = [opts.slice] if opts.slice else list(arm.extras["slices"])
    for slice_name in slices:
        letter, _wave, combos = s4_slice_combos(arm, slice_name)
        if opts.datasets:
            allow = set(datasets_for(arm, opts.datasets))
            combos = [c for c in combos if c[0] in allow]
        landmark = parse_landmark_setting(S4_ARMS[letter])
        jobs = s4_jobs_for_combos(arm, combos)
        by_dataset: dict[str, list[dict]] = {}
        for job in jobs:
            # run_cindex_queue 用 f"{name}[{source}]" 作表目录键（旧 A_manual 同款），保持一致。
            by_dataset.setdefault(f"{job['dataset']}[gdc]", []).append(job)
        for dataset, dataset_jobs in sorted(by_dataset.items()):
            print(f"[{arm.tag}] summarize {dataset}")
            summarize_dataset(
                dataset_name=dataset,
                jobs=dataset_jobs,
                results_root=arm.extras["cindex_results_root"],
                encoding=S4_ENCODING,
                modality=",".join(S4_ANALYZERS),
                landmark_tag=landmark.arm_tag,
            )


def s4_encodes_exist(dataset: str, scheme: str, arm_letter: str) -> bool:
    subdir = "" if arm_letter == "A" else "landmark_0"
    base = OUTPUTS / dataset / "A_manual" / scheme
    if subdir:
        base = base / subdir
    emb = base / "embeddings" / "pt"
    return (base / "prompts.csv").is_file() and emb.is_dir() and any(emb.glob("*.pt"))


def s4_emit_encodes(arm: Arm) -> list[str]:
    """缺失编码清单（逐字同 s4_enqueue.py cmd_emit_encodes 的行格式）。"""
    waves, mains = s4_load_waves()
    lines = ["wave|dataset|scheme|arm|landmark_arg"]
    for wave in ("1", "2", "3"):
        for letter in ("A", "B"):
            for prefix in ("", "H"):
                _, _, combos = s4_slice_spec(f"{letter}{wave}{prefix}", waves, mains)
                for dataset, scheme in combos:
                    if not s4_encodes_exist(dataset, scheme, letter):
                        lines.append(f"{wave}|{dataset}|{scheme}|{letter}|{S4_ARMS[letter]}")
    return lines


def cmd_2b_emit_encodes(arm: Arm, opts) -> None:
    for line in s4_emit_encodes(arm):
        print(line)


def cmd_2b_list(arm: Arm, opts) -> None:
    from manual_pipeline.paths import DEFAULT_GDC_DATASETS_CONFIG  # noqa: F401  (口径说明)

    waves, mains = s4_load_waves()
    total = 0
    for wave in ("1", "2", "3"):
        print(f"wave {wave}: {len(waves[wave])} datasets {waves[wave]}")
    print("--- grid ---")
    for wave in ("1", "2", "3"):
        for letter in ("A", "B"):
            for prefix in ("", "H"):
                name = f"{letter}{wave}{prefix}"
                _, _, combos = s4_slice_spec(name, waves, mains)
                missing = [(d, s) for d, s in combos if not s4_encodes_exist(d, s, letter)]
                total += len(combos)
                print(f"  slice {name}: {len(combos)} combos, encodes missing {len(missing)}")
    print(f"total combos: {total} (R13 训练范围 = {len(mains)} 主集, 含 A/B 两臂; "
          f"confs = {total} x {len(S4_ANALYZERS)} analyzers = {total * len(S4_ANALYZERS)})")
    print("--- old tables coverage ---")
    missing_old = 0
    for wave in ("1", "2", "3"):
        for prefix in ("", "H"):
            _, _, combos = s4_slice_spec(f"A{wave}{prefix}", waves, mains)
            for dataset, scheme in combos:
                table = test_results_dir("Test_2b/arm_A") / f"{dataset}[gdc]" / "cindex.csv"
                if not table.exists():
                    missing_old += 1
                    continue
                with table.open(newline="") as fh:
                    rows = {(r["scheme"], r["modality"]) for r in csv.DictReader(fh)}
                if (scheme, "clinic_cox") not in rows:
                    missing_old += 1
    print(f"combos without old-table clinic_cox row (no diff check possible): {missing_old}")


def cmd_2b_status(arm: Arm, opts) -> None:
    root = arm.queue_root
    for bucket in ("queue", "running", "done", "failed"):
        print(f"{bucket}: {bucket_counts(root)[bucket]}")
    done_landmark = len(list((root / "done").glob("*__landmark_*.conf"))) \
        if (root / "done").is_dir() else 0
    print(f"done (landmark confs): {done_landmark}")
    encode_list = Path(os.environ.get(f"{arm.env}ENCODE_LIST",
                                      arm.extras["encode_list_default"]))
    if encode_list.exists():
        rows = [line for line in encode_list.read_text(encoding="utf-8").splitlines() if line.strip()]
        left = 0
        for line in rows:
            parts = line.split("|")
            if len(parts) < 5:
                continue
            _wave, ds, scheme, letter, _lm = parts[:5]
            if not s4_encodes_exist(ds, scheme, letter):
                left += 1
        print(f"encode tasks remaining: {left} / {len(rows)}")


def cmd_2b_encode(arm: Arm, opts) -> int:
    """已退役(2026-10-09):apipe 全量编码路径整体删除,文本编码统一 field bank 切片。

    2b 两臂的 bank 切片来源:
      * 臂 B(bank lm0)= Test_3_{work}_{ds} 切片(scripts/Test_3_arms.py encode,零重编码);
      * 臂 A(bank raw)= materialize_bank_subset(variant="raw"),重建批次落地后提供。
    旧实现(conda run ... run_a_manual.py pipeline)指向已删除的 json2prompt/encode
    子命令,不再保留。
    """
    raise SystemExit(
        "[test_2b][encode] 已退役:文本编码统一 field bank 切片(apipe 全量编码已删除,T31)。\n"
        "  臂 B(bank lm0)= scripts/Test_3_arms.py encode(Test_3_{work}_{ds} 切片,零重编码);\n"
        "  臂 A(bank raw)= materialize_bank_subset(variant=\"raw\"),待重建批次落地。")


def s4_start_drainer(arm: Arm, opts) -> int:
    log_dir = env_path(arm, "LOG_DIR", str(arm.extras["log_dir"]))
    log_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = str(gpus_for(arm, opts)[0])
    python_exe = os.environ.get(f"{arm.env}PYTHON3", "python3")
    return spawn(python_exe,
                 [str(SCRIPTS / arm.drainer_script), "cindex",
                  *arm.drainer_argv(workers=workers_for(arm, opts))],
                 log_path=log_dir / "S4_drain.log",
                 pid_path=log_dir / "S4_drain.pid", env=env)


def cmd_2b_drain(arm: Arm, opts) -> None:
    pid = s4_start_drainer(arm, opts)
    gpu = gpus_for(arm, opts)[0]
    log_dir = env_path(arm, "LOG_DIR", str(arm.extras["log_dir"]))
    print(f"[{arm.tag}] drainer PID: {pid}  (GPU {gpu}, workers {workers_for(arm, opts)}, "
          f"log: {log_dir / 'S4_drain.log'})")
    print(f"[{arm.tag}] stop: kill {pid}")


def cmd_2b_watch(arm: Arm, opts) -> None:
    """波次优先级自愈循环（原 s4_Test_2b_queue.sh watch）。"""
    root = arm.queue_root
    log_dir = env_path(arm, "LOG_DIR", str(arm.extras["log_dir"]))
    log_dir.mkdir(parents=True, exist_ok=True)
    watch_log = log_dir / "S4_watch.log"
    summary_log = log_dir / "S4_summary.log"
    expected = int(arm.extras["done_expected"])
    interval = max(5, int(opts.interval or 60))

    def note(msg: str) -> None:
        print(f"[{arm.tag}][watch] {msg}", flush=True)
        with watch_log.open("a", encoding="utf-8") as handle:
            handle.write(f"[{arm.tag}][watch] {msg}\n")

    def summarize_all(tag: str) -> None:
        with summary_log.open("a", encoding="utf-8") as handle:
            handle.write(f"\n===== {tag} {datetime.now().strftime('%F %T')}\n")
        for slice_name in arm.extras["wave_order"]:
            try:
                cmd_2b_summarize(arm, argparse.Namespace(slice=slice_name, datasets=None))
            except Exception as exc:  # noqa: BLE001
                print(f"[{arm.tag}][watch] summarize {slice_name} 失败: {exc}", flush=True)

    last_sum = 0.0
    note(f"start wave_order={' '.join(arm.extras['wave_order'])} done_expected={expected} "
         f"log_dir={log_dir}")
    while True:
        counts = bucket_counts(root)
        q, r = counts["queue"], counts["running"]
        done_c = len(list((root / "done").glob("*__landmark_*.conf"))) \
            if (root / "done").is_dir() else 0
        now = time.time()
        alive = pid_alive(pid_from_file(log_dir / "S4_drain.pid"))
        if not alive and (q > 0 or r > 0):
            note(f"relaunch drainer (q={q} r={r})")
            s4_start_drainer(arm, opts)
            time.sleep(30)
            continue
        if q == 0 and r == 0:
            enqueued = 0
            for slice_name in arm.extras["wave_order"]:
                opts_slice = argparse.Namespace(slice=slice_name, datasets=None)
                before = bucket_counts(root)["queue"]
                cmd_2b_enqueue(arm, opts_slice)
                after = bucket_counts(root)["queue"]
                if after > before:
                    note(f"enqueue slice {slice_name} (+{after - before})")
                    enqueued = 1
                    break
            if done_c >= expected:
                note(f"ALL {expected} done")
                break
            if not enqueued and not pid_alive(pid_from_file(log_dir / "S4_drain.pid")):
                note("relaunch drainer")
                s4_start_drainer(arm, opts)
            summarize_all("queue empty")
            last_sum = now
        elif now - last_sum >= 300:
            summarize_all("periodic")
            last_sum = now
        time.sleep(interval)


def cmd_2b_validate(arm: Arm, opts) -> int:
    python_exe = os.environ.get(f"{arm.env}PYTHON3", "python3")
    return subprocess.call([python_exe, str(SCRIPTS / arm.extras["validate_script"])],
                           cwd=str(ROOT))


# --- Test_3 两臂（逐字移植 scripts/Test_3_arms.py 的 enqueue/drain/summarize/status）---

def t3_scheme_pairs(arm: Arm, variant: str, datasets: list[str]) -> list[tuple[str, str, str | None]]:
    import Test_3_common as C
    from manual_pipeline.config import SCHEME_CONFIG

    pairs: list[tuple[str, str, str | None]] = []
    for dataset in datasets:
        if variant == "b":
            for _d, work in C.work_pairs([dataset]):
                name = C.b_scheme_name(work, dataset)
                if name in SCHEME_CONFIG:
                    pairs.append((dataset, name, work))
        else:
            if not C.search_result_json(dataset).exists():
                print(f"[{arm.tag}][arms] 缺搜索 result.json（臂 C 跳过）: "
                      f"{C.search_result_json(dataset)}")
                continue
            name = C.c_scheme_name(dataset, kind=("ksig" if variant == "ksig" else "best"))
            pairs.append((dataset, name, None))
    return pairs


def t3_cindex_jobs(arm: Arm, dataset: str, scheme: str) -> list[dict]:
    from common.datasets import load_dataset_configs
    from manual_pipeline.cindex import iter_cindex_jobs

    import Test_3_common as C

    return iter_cindex_jobs(
        dataset_name=dataset,
        schemes=[scheme],
        datasets=load_dataset_configs(ROOT / "datasets.json"),
        baseline_out=str(ROOT / "outputs"),
        encoding="text",
        modalities=[C.ANALYZER],
        results_root=arm.extras["cindex_results_root"],
        seed=C.SEED,
        landmark_tag=f"landmark_{C.LANDMARK_TIME}",
        landmark_time=int(C.LANDMARK_TIME),
    )


def cmd_3arms_enqueue(arm: Arm, opts) -> None:
    from manual_pipeline.cindex import enqueue_cindex_jobs

    load_all_schemes()
    datasets = datasets_for(arm, opts.datasets)
    variant = opts.variant or "b"
    pairs = t3_scheme_pairs(arm, variant, datasets)
    if not pairs:
        print(f"[{arm.tag}][arms] enqueue variant={variant} 无匹配方案（臂 b 先跑 "
              f"`python scripts/Test_3_arms.py generate --arm b`；臂 ksig/best 需搜索 "
              f"result.json 先落盘）")
    created = existing = missing = 0
    for dataset, scheme, _work in pairs:
        jobs = t3_cindex_jobs(arm, dataset, scheme)
        if not jobs:
            missing += 1
            print(f"[{arm.tag}][arms] 无 job（缺 embeddings?）: {dataset}/{scheme}")
            continue
        queued = enqueue_cindex_jobs(jobs, queue_root=arm.queue_root)
        created += len(queued["created"])
        existing += len(queued["existing"])
    print(f"[{arm.tag}][arms] enqueue variant={variant} created={created} "
          f"existing={existing} missing={missing}")


def cmd_3arms_summarize(arm: Arm, opts) -> None:
    from manual_pipeline.cindex import summarize_dataset

    import Test_3_common as C

    load_all_schemes()
    datasets = datasets_for(arm, opts.datasets)
    variant = opts.variant or "b"
    for dataset, scheme, _work in t3_scheme_pairs(arm, variant, datasets):
        jobs = t3_cindex_jobs(arm, dataset, scheme)
        # 表目录沿用 S4/Test_2b 约定 "{dataset}[gdc]"（s4_enqueue.table_key），
        # 否则会另建一张无后缀表、与臂 B 的行分家。
        rows = summarize_dataset(dataset_name=f"{dataset}[gdc]", jobs=jobs,
                                 results_root=arm.extras["cindex_results_root"],
                                 encoding="text", modality=C.ANALYZER,
                                 landmark_tag=f"landmark_{C.LANDMARK_TIME}")
        print(f"[{arm.tag}][arms] summarize {dataset}: {len(rows)} 行（表内累计）", flush=True)


def cmd_3arms_status(arm: Arm, opts) -> None:
    from greedy.data import display_to_study
    from manual_pipeline.cindex import conf_filename

    import Test_3_common as C

    load_all_schemes()
    datasets = datasets_for(arm, opts.datasets)
    variant = opts.variant or "b"
    root = arm.queue_root
    pairs = t3_scheme_pairs(arm, variant, datasets)
    if not pairs:
        print(f"[{arm.tag}][arms] status variant={variant} 无匹配方案（臂 b 先跑 "
              f"`python scripts/Test_3_arms.py generate --arm b`；臂 ksig/best 需搜索 "
              f"result.json 先落盘）")
    for dataset, scheme, _work in pairs:
        study = display_to_study(dataset)
        name = conf_filename(study, scheme, C.ANALYZER, f"landmark_{C.LANDMARK_TIME}")
        bucket = next((b for b in BUCKETS if (root / b / name).exists()), "-")
        emb_dir = (ROOT / "outputs" / dataset / "A_manual" / scheme
                   / f"landmark_{C.LANDMARK_TIME}" / "embeddings" / "pt")
        encoded = "emb" if emb_dir.is_dir() else "   "
        table = Path(arm.extras["arm_b_results"]) / f"{dataset}[gdc]" / "cindex.csv"
        extra = ""
        if table.exists():
            with table.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("scheme") == f"{scheme}__landmark_{C.LANDMARK_TIME}" and \
                            row.get("modality") == C.ANALYZER:
                        extra = f" c={row.get('val_c_index_mean')}"
        print(f"[{arm.tag}][arms] {dataset:12s} {scheme:44s} {encoded} {bucket:8s}{extra}")


def cindex_drain_inprocess(arm: Arm, opts) -> None:
    """进程内 drain（Test_3_arms / Test_5 的旧姿势：CUDA_VISIBLE_DEVICES + drain_queue）。"""
    from manual_pipeline.cindex import drain_queue, ensure_queue_dirs

    gpu = gpus_for(arm, opts)[0]
    workers = workers_for(arm, opts)
    poll = float(opts.poll_seconds or 15.0)
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    if arm.nice_level:                    # Test_5 旧壳整体 nice -n 10（训练子进程继承）
        os.nice(arm.nice_level)
    root = ensure_queue_dirs(arm.queue_root)
    label = arm.sub or arm.name
    print(f"[{arm.tag}][drain] {label} queue={root} gpu={gpu} workers={workers} "
          f"pid={os.getpid()} status={bucket_counts(root)}", flush=True)
    drain_queue(root, reuse=True, poll_seconds=poll, workers=workers)
    print(f"[{arm.tag}][drain] {label} end status={bucket_counts(root)}", flush=True)


# --- Test_5 四个子检查（逐字移植 scripts/Test_5_enqueue.py）------------------

def t5_missing_encodings(arm: Arm, datasets: list[str]) -> list[tuple]:
    import Test_5_common as C5

    out = []
    for dataset in datasets:
        for plan in C5.arm_plans(arm.sub, dataset):
            for scheme in plan.schemes:
                path = C5.encoding_paths(dataset, scheme, plan.encoding, plan.landmark_tag)
                if not (path.is_dir() and any(path.glob("*.pt"))):
                    out.append((dataset, plan.arm, scheme, plan.encoding, str(path)))
    return out


def cmd_t5_enqueue(arm: Arm, opts) -> int:
    from manual_pipeline.cindex import enqueue_cindex_jobs

    import Test_5_common as C5

    load_all_schemes()
    datasets = datasets_for(arm, opts.datasets)
    only = tuple(opts.only or ())
    missing = t5_missing_encodings(arm, datasets)
    jobs = C5.build_jobs(arm.sub, datasets, conf_filters=only)
    expect = C5.expected_counts(datasets)[arm.sub]["total"]
    parked_jobs: list[dict] = []
    if arm.sub == "5M_2b" and not opts.include_multimodal:
        parked_jobs = [j for j in jobs if j["modality"] in C5.PARK_MODALITIES]
        jobs = [j for j in jobs if j["modality"] not in C5.PARK_MODALITIES]
    print(f"[{arm.tag}][{arm.sub}] expected={expect} jobs={len(jobs)} "
          f"parked={len(parked_jobs)} missing_encodings={len(missing)}"
          + ("  (dry-run)" if opts.dry_run else ""))
    if parked_jobs:
        print(f"[{arm.tag}][{arm.sub}] PARK {sorted({j['modality'] for j in parked_jobs})}: "
              f"{C5.park_reason(C5.PARK_MODALITIES[0])}")
    for row in missing:
        print(f"[{arm.tag}][{arm.sub}]   SKIP missing encoding: {row[0]} {row[1]} {row[2]} "
              f"({row[3]}) -> {row[4]}")
    if opts.dry_run:
        for job in jobs:
            print(f"[{arm.tag}][{arm.sub}]   {job['conf_name']}")
        return 0  # 同 Test_5_enqueue.py：dry-run 只列不判 rc
    queued = enqueue_cindex_jobs(jobs, queue_root=str(arm.queue_root))
    print(f"[{arm.tag}][{arm.sub}] QUEUE root={queued['root']} "
          f"created={len(queued['created'])} existing={len(queued['existing'])} "
          f"retried={len(queued.get('retried', []))}")
    if parked_jobs:
        # C5.park_jobs 内部用 Test_5_common.queue_root(sub)；--queue-root 演练时 parked/ 同步改道
        #（默认无覆盖时两者相等，行为逐字同旧 Test_5_enqueue.py）。
        real_queue_root = C5.queue_root
        if Path(real_queue_root(arm.sub)) != arm.queue_root:
            C5.queue_root = lambda _sub: arm.queue_root
        try:
            parked = C5.park_jobs(parked_jobs, arm.sub)
        finally:
            C5.queue_root = real_queue_root
        print(f"[{arm.tag}][{arm.sub}] PARKED root={parked['root']} "
              f"created={len(parked['created'])} existing={len(parked['existing'])} "
              f"(drainer 不读 parked/)")
    return 1 if missing else 0


def cmd_t5_status(arm: Arm, opts, *, print_table: bool = True) -> None:
    import Test_5_common as C5

    load_all_schemes()
    datasets = datasets_for(arm, opts.datasets)
    if print_table:
        # C5.print_status 一次覆盖四个子检查的桶 + 期望数（逐臂重复调用会 ×4）。
        C5.print_status(datasets)
    missing = t5_missing_encodings(arm, datasets)
    if missing:
        print(f"[{arm.tag}][{arm.sub}] 缺编码 {len(missing)}:")
        for row in missing:
            print(f"[{arm.tag}][{arm.sub}]   {row[0]} {row[1]} {row[2]} ({row[3]}) -> {row[4]}")


def cmd_t5_list(arm: Arm, opts) -> None:
    import Test_5_common as C5

    load_all_schemes()
    datasets = datasets_for(arm, opts.datasets)
    for job in C5.build_jobs(arm.sub, datasets, conf_filters=tuple(opts.only or ())):
        print(f"{arm.sub}\t{job['conf_name']}\t{job['clinic_dir']}")


def cmd_t5_summarize(arm: Arm, opts) -> int:
    python_exe = os.environ.get("T5_PYTHON3",
                                "/data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python")
    argv = ["nice", "-n", "10", python_exe, str(SCRIPTS / arm.extras["summarize_script"]),
            "--sub", arm.sub]
    if opts.datasets:
        argv.extend(["--datasets", opts.datasets])
    if opts.allow_partial:
        argv.append("--allow-partial")
    print(f"[{arm.tag}][{arm.sub}] summarize: {' '.join(argv)}", flush=True)
    return subprocess.call(argv, cwd=str(ROOT))


# --- Test_5 多卡调度器（原 scripts/Test_5_scheduler.py：GPU 0-3 空闲卡政策）----

T5_GPU_RANGE = (0, 1, 2, 3)          # 公共服务器约定：只用 0-3
T5_FREE_UTIL_MAX = 15.0              # %
T5_FREE_MEM_MAX_MB = 800.0           # MiB
T5_MAX_DRAINERS = 4                  # = 可用卡数上限
T5_SUB_ORDER = ("5M_2b", "5E_2b", "5E_3", "5M_3")


def t5_log_dir(arm: Arm) -> Path:
    return Path(arm.extras.get("log_root", RESULTS / "Test_5_invariance" / "logs"))


def t5_log(msg: str, log_path: Path) -> None:
    line = f"{datetime.now().strftime('[%F %T]')} {msg}"
    print(line, flush=True)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def gpu_stats() -> dict[int, tuple[float, float]]:
    """{gpu: (util%, mem MiB)}；nvidia-smi 失败返回空 dict（本轮不放置）。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout
    except Exception as exc:  # noqa: BLE001
        t5_log(f"nvidia-smi failed: {exc}", t5_log_dir(_ARM_5E_2B) / "scheduler.log")
        return {}
    stats: dict[int, tuple[float, float]] = {}
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            stats[int(parts[0])] = (float(parts[1]), float(parts[2]))
        except ValueError:
            continue
    return stats


def gpu_is_free(stats: dict[int, tuple[float, float]], gpu: int) -> bool:
    util, mem = stats.get(gpu, (1e9, 1e9))
    return util < T5_FREE_UTIL_MAX and mem < T5_FREE_MEM_MAX_MB


def t5_spawn_drainer(arm: Arm, gpu: int, workers: int, log_path: Path) -> int:
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    argv = ["-u", str(Path(__file__).resolve()), "drain", "--arm", arm.name,
            "--gpu", str(gpu), "--workers", str(workers)]
    pid = spawn("nice", ["-n", "10", sys.executable, *argv],
                log_path=t5_log_dir(arm) / f"drain_{arm.sub}_gpu{gpu}.log", env=env)
    t5_log(f"spawn drainer sub={arm.sub} gpu={gpu} pid={pid}", log_path)
    return pid


def cmd_t5_scheduler_stop(opts) -> int:
    """停调度器：只 kill 自己写的 scheduler.pid（原 Test_5_queue.sh scheduler_stop）。

    纪律：不直接 kill 无关进程；pid 已死则只清理 pid 文件；本命令不碰 drainer 自身
    （drainer 是队列语义，停下后重跑 scheduler / drain 即可续跑）。
    """
    pid_path = t5_log_dir(_ARM_5E_2B) / "scheduler.pid"
    if not pid_path.exists():
        print("[test_5] no scheduler.pid", flush=True)
        return 0
    pid = pid_from_file(pid_path)
    if not pid_alive(pid):
        print(f"[test_5] scheduler pid={pid} 已不在，清理 pid 文件", flush=True)
        pid_path.unlink(missing_ok=True)
        return 0
    os.kill(pid, signal.SIGTERM)
    print(f"[test_5] killed scheduler {pid}（pid 文件保留，下次 start 会先校验存活）", flush=True)
    return 0


def cmd_t5_scheduler(opts) -> int:
    """只在 GPU 0-3 的空闲卡上起 drainer，每卡一个 drainer，最多 4 并发。"""
    subs = opts.sub or list(T5_SUB_ORDER)
    arms = {sub: ARM_REGISTRY[f"test_5_{sub}"] for sub in subs}
    log_dir = t5_log_dir(_ARM_5E_2B)
    log_path = log_dir / "scheduler.log"
    pid_path = log_dir / "scheduler.pid"
    log_dir.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(2, int(opts.workers or os.environ.get("T5_WORKERS", 1) or 1)))
    poll_seconds = float(opts.poll_seconds or 30.0)

    if not opts.once:
        if pid_path.exists() and not opts.force:
            old = pid_from_file(pid_path)
            if pid_alive(old):
                t5_log(f"refuse to start: scheduler.pid={old} still alive (use --force)", log_path)
                return 1
        pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
        t5_log(f"scheduler start pid={os.getpid()} subs={subs} workers={workers} "
               f"poll={poll_seconds}s max_hours={opts.max_hours or 'inf'} "
               f"policy=gpu{list(T5_GPU_RANGE)} util<{T5_FREE_UTIL_MAX}% "
               f"mem<{T5_FREE_MEM_MAX_MB}MiB max_drainers={T5_MAX_DRAINERS}", log_path)

    deadline = time.time() + float(opts.max_hours) * 3600 if (opts.max_hours or 0) > 0 else None
    state: dict[int, dict] = {}
    cooldown: dict[str, float] = {}
    poll_no = 0
    while True:
        poll_no += 1
        # 1) 回收自己起的 drainer
        for gpu, info in list(state.items()):
            if pid_alive(info["pid"]):
                continue
            t5_log(f"drainer exit sub={info['sub']} gpu={gpu} pid={info['pid']}", log_path)
            cooldown[info["sub"]] = time.time() + 60.0
            del state[gpu]
        # 2) 队列状态（conf 数；running 计入"未清空"）
        status = {sub: bucket_counts(arms[sub].queue_root, ("queue", "running", "done", "failed"))
                  for sub in subs}
        work = {sub: status[sub]["queue"] + status[sub]["running"] for sub in subs}
        # 3) 全部清空且无 drainer -> 收工
        if not state and all(v == 0 for v in work.values()):
            if opts.once:
                stats = gpu_stats()
                free = [g for g in T5_GPU_RANGE if gpu_is_free(stats, g)]
                t5_log(f"dry-run poll: status={status} free={free} "
                       f"(queues empty; nothing to place)", log_path)
                return 0
            t5_log(f"all subs drained {status} -> scheduler exit", log_path)
            if pid_path.exists():
                pid_path.unlink()
            return 0
        # 4) 空闲卡（重新查询，逐卡判定）
        stats = gpu_stats()
        free = [g for g in T5_GPU_RANGE if g not in state and gpu_is_free(stats, g)]
        active_subs = {info["sub"] for info in state.values()}
        now = time.time()
        placements: list[tuple[int, str]] = []
        for gpu in free:
            if len(state) >= T5_MAX_DRAINERS:
                break
            cands = [s for s in subs if work[s] > 0 and s not in active_subs
                     and cooldown.get(s, 0.0) <= now]
            if not cands:
                break
            sub = max(cands, key=lambda s: work[s])   # 剩余最多的子检查优先
            if gpu_is_free(gpu_stats(), gpu):         # 放置前 re-check 同一张卡
                placements.append((gpu, sub))
                active_subs.add(sub)
            else:
                t5_log(f"skip gpu={gpu}: busy on re-check", log_path)
        if opts.once:
            t5_log(f"dry-run poll: status={status} free={free} placements={placements}", log_path)
            return 0
        for gpu, sub in placements:
            pid = t5_spawn_drainer(arms[sub], gpu, workers, log_path)
            state[gpu] = {"pid": pid, "sub": sub}
        if placements or poll_no % 10 == 1:
            t5_log(f"poll#{poll_no} status={status} active="
                   f"{ {g: i['sub'] for g, i in state.items()} } free={free}", log_path)
        if deadline is not None and time.time() >= deadline:
            t5_log(f"max-hours reached, scheduler exit (still active: "
                   f"{ {g: i['sub'] for g, i in state.items()} })", log_path)
            if pid_path.exists():
                pid_path.unlink()
            return 0
        time.sleep(poll_seconds)


# ===========================================================================
# search backend（selection/queue.py；Test_3 搜索 / Test_6 试点）
# ===========================================================================

_RUNNER_MODULE = None


def runner_module():
    """加载 drainer 模块，借用它的 parser——job_key 哈希全部 argparse 字段，
    手抄默认值极易漂移，故直接复用同一 parser 保证逐位一致（照抄
    Test_3_search_queue.py:82-97 的 parser 复用姿势）。"""
    global _RUNNER_MODULE
    if _RUNNER_MODULE is None:
        path = search_cli()
        spec = importlib.util.spec_from_file_location("run_e2_selection_queue", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RUNNER_MODULE = module
    return _RUNNER_MODULE


def search_units(arm: Arm) -> list[tuple[str, tuple]]:
    """[(dataset, extra…)]：extra 逐臂不同（Test_3 无；Test_6 为 algo）。"""
    if arm.dataset_source == "manifest15":
        return [(ds, ()) for ds in main_datasets_from_manifest()]
    if arm.dataset_source == "t6_grid":
        return [(ds, (algo,)) for ds in T6_DATASETS for algo in T6_ALGOS]
    raise SystemExit(f"[exp_queue] 臂 {arm.name} 的 search 网格未实现: {arm.dataset_source}")


def search_argv_for(arm: Arm, dataset: str, extra: tuple, workers: int | None) -> list[str]:
    if not extra:
        return arm.extras["argv"](dataset, workers)
    return arm.extras["argv"](dataset, *extra, workers)


def search_job(arm: Arm, dataset: str, extra: tuple, workers: int | None = None):
    """(args, key, conf_name)：单个搜索作业的身份，与 drainer 同源。"""
    from selection.queue import _payload

    argv = search_argv_for(arm, dataset, extra, workers)
    args = runner_module().parser().parse_args(argv[2:])
    payload = _payload(args)
    payload.pop("dataset", None)
    payload.pop("landmark_time", None)
    key = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False)
                       .encode("utf-8")).hexdigest()[:12]
    name = f"{key}__{dataset}__landmark_{arm.extras['landmark']}.conf"
    return args, key, name


def search_conf_path(arm: Arm, dataset: str, name: str, bucket: str,
                     root: Path | None = None) -> Path:
    """conf 路径：优先当前 key 的精确名，回退按 dataset 后缀 glob（旧 key/旧 --out 遗留 conf）。

    drain 只认 conf 文件本身，故 recover/retry/status 用回退查找与旧脚本
    Test_3_search_queue.conf_path 的 glob 口径一致；enqueue 判重仍走 selection.queue
    的精确名（job_key 由 --out 等全字段决定）。
    """
    root = root or arm.queue_root
    exact = root / bucket / name
    if exact.exists():
        return exact
    suffix = f"*__{dataset}__landmark_{arm.extras['landmark']}.conf"
    hits = sorted((root / bucket).glob(suffix))
    return hits[0] if hits else exact


def search_find(arm: Arm, dataset: str, name: str, root: Path | None = None) -> str | None:
    """所在桶；返回 (bucket, exact) 供 status 标注遗留键。"""
    root = root or arm.queue_root
    for bucket in BUCKETS:
        if (root / bucket / name).exists():
            return bucket
    for bucket in BUCKETS:
        if list((root / bucket).glob(f"*__{dataset}__landmark_{arm.extras['landmark']}.conf")):
            return bucket
    return None


def cmd_search_enqueue(arm: Arm, opts, *, root: Path | None = None) -> str:
    import selection.queue as SQ

    root = root or arm.queue_root
    created = existing = 0
    # workers 一律 None：test_3_search 逐字同 Test_3_search_queue.cmd_enqueue（旧 argv
    # 不带 --workers），test_6_search 由 t6_search_argv 自带（T6_WORKERS）。二者都不改
    # job_key/conf 字节（selection.queue WORKER_LOCAL_KEYS 含 workers）。
    workers = None
    for dataset, extra in search_units(arm):
        args, _key, _name = search_job(arm, dataset, extra, workers)
        result = SQ.enqueue(args, [dataset], [arm.extras["landmark"]], root=root)
        created += len(result["created"])
        existing += len(result["existing"])
    print(f"[{arm.tag}][enqueue] created={created} existing={existing} queue_root={root}",
          flush=True)
    return f"{arm.tag}: created={created} existing={existing}"


def search_status_rows(arm: Arm, root: Path | None = None):
    """[(dataset, extra, key, bucket, exact, result_json)]，只读。"""
    rows = []
    for dataset, extra in search_units(arm):
        args, key, name = search_job(arm, dataset, extra)
        bucket = search_find(arm, dataset, name, root)
        exact = bucket is not None and ((root or arm.queue_root) / bucket / name).exists()
        out_dir = Path(args.out)
        if not out_dir.is_absolute():
            out_dir = ROOT / out_dir
        result_json = out_dir / args.inner_analyzer / f"seed_{args.seed}" / "result.json"
        rows.append((dataset, extra, key, bucket, exact, result_json))
    return rows


def cmd_search_status(arm: Arm, opts, *, root: Path | None = None) -> None:
    rows = search_status_rows(arm, root)
    counts = {bucket: 0 for bucket in BUCKETS}
    counts["missing"] = 0
    for _ds, _extra, _key, bucket, _exact, _rj in rows:
        if bucket is None:
            counts["missing"] += 1
        else:
            counts[bucket] += 1
    print(f"[{arm.tag}][status] {counts}", flush=True)
    for dataset, extra, key, bucket, exact, result_json in rows:
        label = f"{dataset}/{extra[0]}" if extra else dataset
        extra_info = ""
        if result_json.exists():
            payload = json.loads(result_json.read_text(encoding="utf-8"))
            extra_info = (f" k={payload.get('recommended_k')} "
                          f"c={payload.get('recommended_cv_c_mean')} "
                          f"best_c={payload.get('best_cv_c_mean')} "
                          f"stop={payload.get('stop_reason')} "
                          f"evals={payload.get('logical_evals')}")
        mark = key if exact else f"{key}(遗留键)"
        print(f"[{arm.tag}][status] {label:22s} {bucket or '-':8s} {mark}{extra_info}",
              flush=True)


def cmd_search_recover(arm: Arm, opts, *, root: Path | None = None) -> int:
    """running/ 里 claimed_pid 已死的 conf 放回 queue/（drainer 被杀后任务不丢）。"""
    from selection.queue import move

    root = root or arm.queue_root
    recovered = 0
    for dataset, extra in search_units(arm):
        _args, _key, name = search_job(arm, dataset, extra)
        path = search_conf_path(arm, dataset, name, "running", root)
        if not path.exists():
            continue
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if pid_alive(int(job.get("claimed_pid") or 0)):
            continue
        for stale in ("claimed_at", "claimed_pid", "cuda_visible_devices"):
            job.pop(stale, None)
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        move(path, "queue")
        recovered += 1
    if recovered:
        print(f"[{arm.tag}][recover] requeued {recovered}", flush=True)
    return recovered


def cmd_search_retry(arm: Arm, opts, *, root: Path | None = None) -> int:
    """failed/ 桶限次重入队（conf 内记 retries）。"""
    from selection.queue import move

    root = root or arm.queue_root
    max_retries = int(opts.max_retries or MAX_RETRIES)
    retried = 0
    for dataset, extra in search_units(arm):
        _args, _key, name = search_job(arm, dataset, extra)
        path = search_conf_path(arm, dataset, name, "failed", root)
        if not path.exists():
            continue
        job = json.loads(path.read_text(encoding="utf-8"))
        attempts = int(job.get("retries") or 0)
        if attempts >= max_retries:
            continue
        job["retries"] = attempts + 1
        for stale in ("claimed_at", "claimed_pid", "cuda_visible_devices"):
            job.pop(stale, None)
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        move(path, "queue")
        retried += 1
    if retried:
        print(f"[{arm.tag}][retry] requeued {retried}", flush=True)
    return retried


def cmd_search_report(arm: Arm, opts) -> int:
    if arm.name == "test_6_search":
        python_exe = os.environ.get(f"{arm.env}PYTHON3", "python3")
        argv = [python_exe, str(SCRIPTS / arm.extras["report_script"]),
                *arm.extras["report_argv"]]
        print(f"[{arm.tag}][report] {' '.join(argv)}", flush=True)
        return subprocess.call(argv, cwd=str(ROOT))

    import Test_3_common as C

    rows = []
    for dataset, _extra in search_units(arm):
        path = C.search_result_json(dataset)
        if not path.exists():
            rows.append({"dataset": dataset, "status": "missing"})
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        meta = payload.get("metadata") or {}
        rows.append({
            "dataset": dataset,
            "status": "ok",
            "stop_reason": payload.get("stop_reason"),
            "recommended_k": payload.get("recommended_k"),
            "recommended_cv_c_mean": payload.get("recommended_cv_c_mean"),
            "best_k": len(payload.get("best_subset") or []),
            "best_cv_c_mean": payload.get("best_cv_c_mean"),
            "logical_evals": payload.get("logical_evals"),
            "physical_trains": payload.get("physical_trains"),
            "cache_hits": payload.get("cache_hits"),
            "failure_count": payload.get("failure_count"),
            "wall_s": round(float(payload.get("wall_ms") or 0) / 1000.0, 1),
            "wilcoxon_fallback": meta.get("wilcoxon_fallback"),
            "recommended_subset": ";".join(payload.get("recommended_subset") or []),
            "best_subset": ";".join(payload.get("best_subset") or []),
        })
    if not rows:
        print(f"[{arm.tag}][report] 无作业", flush=True)
        return 1
    out = Path(arm.extras["report_out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[{arm.tag}][report] {out} rows={len(rows)}", flush=True)
    return 0


# ===========================================================================
# 共用 verb（与臂无关：Test_5 baseline_c / Q 轴重算 / 汇总入口）
# ===========================================================================

def cmd_baseline_c(opts) -> int:
    conch_python = os.environ.get("T5_CONCH_PYTHON",
                                  "/data/fangyuxuan/miniconda3/envs/conch/bin/python")
    # 逐字同旧 Test_5_queue.sh cmd_baseline_c（nice -n 10，共享机礼貌）
    argv = ["nice", "-n", "10", conch_python, str(SCRIPTS / "Test_5_baseline_c.py"), "--all"]
    print(f"[exp_queue] baseline_c: {' '.join(argv)}", flush=True)
    return subprocess.call(argv, cwd=str(ROOT))


def cmd_q_recompute(opts) -> int:
    python_exe = os.environ.get("T5_PYTHON3",
                                "/data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python")
    out = os.environ.get("T5_Q_OUT", "/tmp/test_5_q_metrics.csv")
    # Q 轴离线重算（D7：dump vs online diff=0）。输出默认写 /tmp——results_display/ 不在
    # S12b 写权限内（Test_5_invariance/q_metrics.csv 现由 Test_2b 批次占用，4221 行）；
    # 正式归档落点由 S13 决定，可用 T5_Q_OUT 覆盖。
    argv = ["nice", "-n", "10", python_exe,
            str(ROOT / "results_display" / "scripts" / "Test_5_q_recompute.py"),
            "--results-root", "results/Test_5_invariance", "--out", out, "--merge",
            *(opts.extra or [])]
    print(f"[exp_queue] q_recompute: {' '.join(argv)}", flush=True)
    rc = subprocess.call(argv, cwd=str(ROOT))
    print(f"[exp_queue] q_metrics -> {out}")
    return rc


# ===========================================================================
# 统一 dispatch
# ===========================================================================

def cmd_list(opts) -> int:
    print(f"{'arm':18s} {'backend':11s} {'env':6s} {'queue_root':48s} note")
    for arm in ARM_REGISTRY.values():
        try:
            qr = str(arm.queue_root.relative_to(ROOT))
        except ValueError:
            qr = str(arm.queue_root)
        print(f"{arm.name:18s} {arm.backend:11s} {arm.env:6s} {qr:48s} {arm.note}")
    print(f"\n别名: " + ", ".join(f"{k}={v}" for k, v in ARM_ALIASES.items()))
    return 0


def cmd_status(arm: Arm, opts) -> int:
    if arm.backend == "univariate":
        cmd_uni_status(arm, opts)
    elif arm.backend == "cindex":
        if arm.dataset_source == "slice_grid":
            cmd_2b_status(arm, opts)
        elif arm.sub:
            cmd_t5_status(arm, opts)
        else:
            cmd_3arms_status(arm, opts)
    elif arm.backend == "search":
        cmd_search_status(arm, opts)
    return 0


def cmd_enqueue(arm: Arm, opts) -> int:
    if arm.backend == "univariate":
        cmd_uni_enqueue(arm, opts)
        return 0
    if arm.backend == "cindex":
        if arm.dataset_source == "slice_grid":
            cmd_2b_enqueue(arm, opts)
            return 0
        if arm.sub:
            return cmd_t5_enqueue(arm, opts)
        cmd_3arms_enqueue(arm, opts)
        return 0
    if arm.backend == "search":
        cmd_search_enqueue(arm, opts)
        return 0
    raise SystemExit(f"[exp_queue] 未知 backend: {arm.backend}")


def cmd_retry(arm: Arm, opts) -> int:
    if arm.backend == "univariate":
        cmd_uni_retry(arm, opts)
    elif arm.backend == "search":
        cmd_search_retry(arm, opts)
    else:
        raise SystemExit(f"[exp_queue] retry 不适用于臂 {arm.name}（cindex conf 由 enqueue 自愈）")
    return 0


def cmd_recover(arm: Arm, opts) -> int:
    if arm.backend == "univariate":
        cmd_uni_recover(arm, opts)
    elif arm.backend == "search":
        cmd_search_recover(arm, opts)
    else:
        raise SystemExit(f"[exp_queue] recover 不适用于臂 {arm.name}（cindex claim 自带回收）")
    return 0


def cmd_trim(arm: Arm, opts) -> int:
    if arm.backend != "univariate":
        raise SystemExit(f"[exp_queue] trim 只适用于 univariate 臂（{arm.name} 是 {arm.backend}）")
    cmd_uni_trim(arm, opts)
    return 0


def cmd_drain(arm: Arm, opts) -> int:
    if arm.backend == "univariate":
        cmd_uni_drain(arm, opts)
        return 0
    if arm.backend == "cindex":
        if arm.drain_mode == "spawn_legacy":
            cmd_2b_drain(arm, opts)
        else:
            cindex_drain_inprocess(arm, opts)
        return 0
    raise SystemExit(f"[exp_queue] drain 见 {arm.extras.get('watch_script', '?')}"
                     f"（search 臂保留动态槽位调度，不并入 exp_queue）")


def cmd_watch(arm: Arm, opts) -> int:
    if arm.backend == "univariate":
        cmd_uni_watch(arm, opts)
        return 0
    if arm.backend == "cindex":
        if arm.dataset_source == "slice_grid":
            cmd_2b_watch(arm, opts)
            return 0
        raise SystemExit(f"[exp_queue] watch 见 scripts/{arm.extras.get('summarize_script', '?')}"
                         "；Test_3/Test_5 的守候用 drain + scheduler（cindex 队列自带续跑）")
    raise SystemExit(f"[exp_queue] search 臂 watch 保留在 scripts/"
                     f"{arm.extras.get('watch_script', '?')}（动态槽位调度）")


def maybe_scheduler_resolves(sub: str) -> Arm:
    return ARM_REGISTRY[f"test_5_{sub}"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="实验队列统一入口（臂注册表 + 三 backend）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="臂: " + ", ".join(arm_names()),
    )
    parser.add_argument("command", choices=[
        "list", "status", "enqueue", "retry", "recover", "trim", "drain", "watch",
        "report", "summarize", "encode", "validate", "emit_encodes", "bank", "check",
        "scheduler", "scheduler_stop", "baseline_c", "q_recompute",
    ])
    parser.add_argument("--arm", action="append", default=None,
                        help="臂名/别名，可重复；status 支持 all（默认 all）")
    parser.add_argument("--datasets", default=None, help="覆盖数据集名单（冒烟/调试，逗号分隔）")
    parser.add_argument("--workers", type=int, default=None, help="并发数（默认取臂注册表/环境）")
    parser.add_argument("--gpu", default=None, help="单卡 GPU 号")
    parser.add_argument("--gpus", default=None, help="多卡 GPU 列表（逗号分隔）")
    parser.add_argument("--interval", type=int, default=None, help="watch 轮询秒数（默认 60）")
    parser.add_argument("--poll-seconds", type=float, default=None)
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES)
    parser.add_argument("--max-hours", type=float, default=0.0)
    parser.add_argument("--slice", default=None, help="Test_2b 波次切片（A1 / B1H …）")
    parser.add_argument("--variant", default=None, help="Test_3 两臂变体（b / ksig / best）")
    parser.add_argument("--only", action="append", default=[], help="conf 过滤子串，可重复")
    parser.add_argument("--include-multimodal", action="store_true",
                        help="Test_5 5M_2b 的 survgc_f/survpgc_f 也按常规投放")
    parser.add_argument("--allow-partial", action="store_true", help="Test_5 汇总允许缺件")
    parser.add_argument("--sub", action="append", default=[],
                        help="scheduler 纳入的 Test_5 子检查，可重复")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true", help="scheduler 单轮干跑")
    parser.add_argument("--force", action="store_true", help="scheduler 忽略已存在的 pid")
    parser.add_argument("--queue-root", default=None,
                        help="覆盖队列根（仅供等价性验证/临时演练；job_key 不含 queue_root，安全）")
    parser.add_argument("extra", nargs="*", help="透传参数（q_recompute 用）")
    opts = parser.parse_args(argv)

    try:
        opts.workers = opts.workers if opts.workers is None else max(1, int(opts.workers))
    except (TypeError, ValueError):
        raise SystemExit(f"[exp_queue] --workers 需要正整数: {opts.workers}")

    if opts.command == "list":
        # `--arm <test_5 子检查>` 时列出逐 conf 明细（原 Test_5_queue.sh list /
        # Test_5_enqueue.py --list）；不带 --arm（或 all）时列臂注册表。
        if opts.arm and "all" not in opts.arm:
            sel = resolve_arms(opts.arm)
            if all(a.sub for a in sel):
                for arm in sel:
                    cmd_t5_list(arm, opts)
                return 0
        return cmd_list(opts)
    if opts.command == "baseline_c":
        return cmd_baseline_c(opts)
    if opts.command == "q_recompute":
        return cmd_q_recompute(opts)
    if opts.command == "scheduler":
        return cmd_t5_scheduler(opts)
    if opts.command == "scheduler_stop":
        return cmd_t5_scheduler_stop(opts)
    if opts.command == "emit_encodes":
        arm = resolve_arms(opts.arm or ["test_2b"])[0]
        if arm.dataset_source != "slice_grid":
            raise SystemExit("emit_encodes 只适用于 --arm test_2b")
        cmd_2b_emit_encodes(arm, opts)
        return 0

    arms = resolve_arms(opts.arm)
    if opts.queue_root:
        if len(arms) != 1:
            raise SystemExit("[exp_queue] --queue-root 只支持单臂（--arm 一次给一个；"
                             "组别名会撞同一目录）")
        for arm in arms:
            arm.queue_root = Path(opts.queue_root)
    if opts.command == "status":
        # Test_5 子检查（含 --arm test_5 组）共用一张桶表：只打一次，
        # 缺编码逐个子检查列出（原 Test_5_queue.sh status 一次打全的口径）。
        table_printed = False
        for arm in arms:
            if arm.sub:
                cmd_t5_status(arm, opts, print_table=not table_printed)
                table_printed = True
            else:
                cmd_status(arm, opts)
        return 0
    rc = 0
    for arm in arms:
        if opts.command == "enqueue":
            if opts.dry_run and arm.backend != "cindex":
                raise SystemExit("--dry-run 只支持 cindex 臂（Test_5 子检查）")
            rc |= cmd_enqueue(arm, opts)
        elif opts.command == "retry":
            rc |= cmd_retry(arm, opts)
        elif opts.command == "recover":
            rc |= cmd_recover(arm, opts)
        elif opts.command == "trim":
            rc |= cmd_trim(arm, opts)
        elif opts.command == "drain":
            rc |= cmd_drain(arm, opts)
        elif opts.command == "watch":
            rc |= cmd_watch(arm, opts)
        elif opts.command == "report":
            if arm.backend == "univariate":
                cmd_uni_report(arm, opts)
            elif arm.backend == "search":
                rc |= cmd_search_report(arm, opts)
            else:
                raise SystemExit(f"[exp_queue] report 见 summarize/status（臂 {arm.name}）")
        elif opts.command == "summarize":
            if arm.dataset_source == "slice_grid":
                cmd_2b_summarize(arm, opts)
            elif arm.sub:
                rc |= cmd_t5_summarize(arm, opts)
            elif arm.backend == "cindex":
                cmd_3arms_summarize(arm, opts)
            else:
                raise SystemExit(f"[exp_queue] summarize 不适用于臂 {arm.name}")
        elif opts.command == "encode":
            if arm.dataset_source != "slice_grid":
                raise SystemExit("encode 只适用于 --arm test_2b（Test_3 编码见 Test_3_arms.py）")
            rc |= cmd_2b_encode(arm, opts)
        elif opts.command == "validate":
            if arm.dataset_source != "slice_grid":
                raise SystemExit("validate 只适用于 --arm test_2b（s4_validate_firstwave.py）")
            rc |= cmd_2b_validate(arm, opts)
        elif opts.command == "bank":
            if not arm.extras.get("bank_script"):
                raise SystemExit(f"[exp_queue] bank 只适用于 --arm test_1a_off")
            rc |= cmd_uni_bank(arm, opts)
        elif opts.command == "check":
            if not arm.extras.get("bank_script"):
                raise SystemExit(f"[exp_queue] check 只适用于 --arm test_1a_off")
            rc |= cmd_uni_check(arm, opts)
        else:  # pragma: no cover - argparse choices 已限制
            raise SystemExit(f"[exp_queue] 未知 command: {opts.command}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
