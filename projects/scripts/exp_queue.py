#!/usr/bin/env python3
"""实验队列统一入口(2026-10-13 重构)。

设计决策与依据(替代旧的禁令式注释):
  * **enqueue 需要 arm,run 不需要**——arm 的"实验定义"半部(datasets 来源、
    2b 波次网格、3arms 绑定、t5 子检查)是 enqueue 模板,省去手写 argv 网格
    (使用便捷);运行半部(drainer/调度/自愈)已并入统一 run。
  * **conf 自描述**:enqueue 时写入 kind/label(JSON conf;
    cindex 的 bash 风格 conf 由 conf_text 写 KIND 行)。
    `run` 只读 conf,按名排序认领(一次 run 自然按序调度多个实验)。
  * **GPU 唯一旋钮 = 调用方 CUDA_VISIBLE_DEVICES**(决策:2026-10-13 用户拍板,
    删 gpu_policy 机制——nvidia-smi 轮询/空闲卡放置/占位跟踪是旧 T5 调度器残留;
    要多卡分账就起多个 run 进程各绑一张卡,claim 原子 mv 天然不抢同一 conf)。
  * **job_key = 语义元组的哈希**(本地参数 workers/queue_root/device/解释器
    路径不进哈希)——同一实验配置在任何机器/并发数下同键。

用法(projects/ 根目录,base python3):
  python3 scripts/exp_queue.py list                              # 臂注册表(enqueue 模板视图)
  python3 scripts/exp_queue.py enqueue --arm test_1a_t0          # 投放(幂等,写自描述 conf)
  python3 scripts/exp_queue.py run --workers 16                  # 无臂统一执行,守到完成(自愈)
  python3 scripts/exp_queue.py status                            # flat 四桶一屏(arm 仅过滤标签)
外壳 `scripts/exp_queue.sh` 负责环境变量前缀透传与后台包装。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
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
MAIN_N_EVENT_MIN = 100          # R13：训练范围 = label 患者集有效事件 >= 100 的 TCGA 主集（2026-10-09 口径）
MAX_RETRIES = 3
BUCKETS = ("queue", "running", "done", "failed")
UNI_BUCKETS = ("queue", "running", "done", "failed")

# Test_6 试点网格（槽位调度已并入统一 run）
T6_DATASETS = ("TCGA-GBM", "TCGA-LGG", "TCGA-PAAD")
T6_ALGOS = ("A1_random", "A3_beam", "A4_anneal", "A5_genetic", "A6_aco", "SEAS",
            "A0_full", "A0b_topk")
T6_WORKERS = 8
T6_BUDGET_CAP = 500            # 试点默认预算上限（enqueue --budget_cap 可覆盖;结果落 cap_{cap} 目录,report 自动发现）


# ===========================================================================
# 数据集名单（R13：label 患者集有效事件派生，不硬编码；2026-10-09 口径）
# ===========================================================================

def main_datasets() -> list[str]:
    from common.patient_set import main_datasets_by_label_events

    return main_datasets_by_label_events(threshold=MAIN_N_EVENT_MIN)




def datasets_for(arm: "Arm", override: str | None = None) -> list[str]:
    """臂的数据集名单（R13 主集；--datasets 覆盖供冒烟/调试）。"""
    if override:
        names = [x.strip() for x in str(override).split(",") if x.strip()]
        if not names:
            raise SystemExit("[exp_queue] --datasets 为空")
        return names
    if arm.dataset_source == "main":
        return main_datasets()
    raise SystemExit(f"[exp_queue] 臂 {arm.name} 的 dataset_source 未实现: {arm.dataset_source}")


# ===========================================================================
# 小工具
# ===========================================================================


def pid_alive(pid: int) -> bool:
    if not pid or int(pid) <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def bucket_counts(root: Path, buckets=BUCKETS, prefix: str = "") -> dict[str, int]:
    return {b: (len(list((root / b).glob(f"{prefix}*.conf"))) if (root / b).is_dir() else 0)
            for b in buckets}


def parse_csv_list(value: str) -> list[str]:
    return [x.strip() for x in str(value).split(",") if x.strip()]




# ===========================================================================
# 臂注册表(enqueue 模板视图)
#   每条臂 = 一个实验定义:dataset 来源 + argv 模板 + 报表标签;
#   运行半部(drainer/pid/log/gpus 默认)已随统一 run 移除。
# ===========================================================================

@dataclass
class Arm:
    name: str
    backend: str                    # univariate | cindex | search
    tag: str                        # 日志前缀
    queue_root: Path
    dataset_source: str = "main"
    enqueue_argv: Callable[..., list[str]] | None = None   # 实验定义:conf args 模板
    results_root: Path | None = None
    field_csv_root: Path | None = None          # report/status 产物根（univariate）
    report_json: Path | None = None             # 最终 report 落盘（旧脚本口径）
    sub: str | None = None                      # Test_5 子检查
    workers_default: int = 8
    extras: dict = field(default_factory=dict)
    note: str = ""


# --- univariate：Test_1a 三臂 -------------------------------------------------

# t0：greedy/queue.py 默认队列根（argv 不带 --queue_root）
_ARM_T0 = Arm(
    name="test_1a_t0", backend="univariate", tag="t0",
    queue_root=config_family_dir("Test_1a_t0"),
    results_root=RESULTS / "single_lm0",
    field_csv_root=RESULTS / "single_lm0" / "univariate" / "prompt" / "landmark_0",
    dataset_source="main",
    enqueue_argv=lambda datasets, *, workers: [
        "--dataset", ",".join(datasets),
        "--landmark_time", "0",
        "--encoding", "prompt",
        "--analyzer", "mlp_clinic_flatten",
        "--seed", "0",
        "--workers", str(workers),
    ],

    workers_default=8,
    note="landmark_0 全字段：mask 开 + outputs/ 正式 bank",
)

# 1b：纯消费 single×lm0（与 t0 同 argv → 同 job_key → conf 判重共享；Test_1b 只读结果）
_ARM_1B = Arm(
    name="test_1b", backend="univariate", tag="1b",
    queue_root=config_family_dir("Test_1b"),
    results_root=RESULTS / "single_lm0",
    field_csv_root=RESULTS / "single_lm0" / "univariate" / "prompt" / "landmark_0",
    dataset_source="main",
    enqueue_argv=lambda datasets, *, workers: [
        "--dataset", ",".join(datasets),
        "--landmark_time", "0",
        "--encoding", "prompt",
        "--analyzer", "mlp_clinic_flatten",
        "--seed", "0",
        "--workers", str(workers),
    ],

    workers_default=8,
    note="纯消费 single×lm0：enqueue 与 test_1a_t0 完全同源（无新增训练）",
)


# off：raw 变体（mask off + 患者集显式 landmark_0 + 三根目录改道）
_ARM_OFF = Arm(
    name="test_1a_off", backend="univariate", tag="off",
    queue_root=config_family_dir("Test_1a_off"),
    results_root=RESULTS / "single_raw",
    field_csv_root=RESULTS / "single_raw" / "univariate" / "prompt" / LANDMARK_OFF_TAG,
    dataset_source="main",
    enqueue_argv=lambda datasets, *, workers: [
        "--dataset", ",".join(datasets),
        "--landmark_time", "none",
        "--extraction_mask", "off",
        "--label_tag", "landmark_0",
        "--field_bank_root", str(OUTPUTS / "_raw"),
        "--embeddings_root", str(OUTPUTS / "_raw"),
        "--results_dir", str(RESULTS / "single_raw"),
        "--queue_root", str(config_family_dir("Test_1a_off")),
        "--encoding", "prompt",
        "--analyzer", "mlp_clinic_flatten",
        "--seed", "0",
        "--workers", str(workers),
    ],

    report_json=RESULTS / "single_raw" / "_test_1a_off_report.json",
    workers_default=8,
    extras={"bank_script": "build_raw_field_bank.py",
            "bank_root": OUTPUTS / "_raw", "bank_tag": LANDMARK_OFF_TAG,
            "build_log_default": "/tmp/raw_bank_build.log"},
    note="off：extraction_mask off + outputs/_raw bank",
)

# --- cindex：Test_2b 波次切片 ------------------------------------------------

_ARM_2B = Arm(
    name="test_2b", backend="cindex", tag="2b",
    queue_root=config_family_dir("Test_2b_arms"),
    results_root=RESULTS / "paper_lm0",
    dataset_source="slice_grid",
    workers_default=8,
    extras={"done_expected": 240,   # 60 combos(14 主集 × 4 泛癌种 + 4 HGCN 绑定)× 2 臂 × 2 分析器
            "cindex_results_root": None,          # None = cindex 默认
            "log_dir": RESULTS / "logs"},
    note="Test_2b 网格（14 主集 × 4 泛癌种 + 4 HGCN 绑定;F×T 臂方案,训练时解析,不分波次）",
)

# --- cindex：Test_3 两臂 ----------------------------------------------------

_ARM_3ARMS = Arm(
    name="test_3_arms", backend="cindex", tag="test_3",
    queue_root=config_family_dir("Test_3_arms"),
    results_root=RESULTS / "greedy_lm0",
    dataset_source="main",

    workers_default=2,
    extras={"cindex_results_root": RESULTS,      # 逐字同 Test_3_arms._cindex_jobs
            "log_root": RESULTS / "logs"},
    note="deleak（work_lm0_{work}_{ds}）/ reach（greedy_lm0_{ds}）cindex 投放,训练时解析",
)


# --- cindex：Test_4 四档对照（纯消费：生成四配置组的全套 conf）-------------

_ARM_T4 = Arm(
    name="test_4", backend="cindex", tag="test_4",
    queue_root=config_family_dir("Test_4"),
    results_root=RESULTS,
    dataset_source="main",

    workers_default=2,
    extras={"cindex_results_root": RESULTS,
            "log_root": RESULTS / "logs"},
    note="四档纯消费：enqueue 生成 paper×{raw,lm0}、greedy×{raw,lm0} 全组 conf"
         "（与 2b/3arms 同 conf 名——先跑谁谁生成，后跑的直接判重跳过）",
)


# --- cindex：Test_5 四个子检查 ----------------------------------------------

def _test5_arm(sub: str, note: str) -> Arm:
    return Arm(
        name=f"test_5_{sub}", backend="cindex", tag="test_5",
        queue_root=config_family_dir(f"Test_5_{sub}"),
        results_root=RESULTS / "Test_5_invariance" / sub,
        dataset_source="main",

        sub=sub,
        workers_default=1,

        extras={"log_root": RESULTS / "Test_5_invariance" / "logs"},
        note=note,
    )


_ARM_E_TIME = _test5_arm("E_time", "E→onehot_ordinary 复现时间轴链对照 {report/deleak} × mlp_clinic_flatten")
_ARM_E_FIELD = _test5_arm("E_field", "E→onehot_ordinary 复现字段轴链对照 {deleak/reach}")
_ARM_M_TIME = _test5_arm("M_time", "M→snn_clinic_flatten（多模态 3 集 BRCA/LIHC/KIRC 默认 parked）复现时间轴链对照")
_ARM_M_FIELD = _test5_arm("M_field", "M→clinic_cox 复现字段轴链对照 {deleak/reach}")

# --- search：Test_3 搜索 / Test_6 试点 ---------------------------------------


def search_cli() -> Path:
    return SCRIPTS / "run_selection_queue.py"


def t3_search_argv(dataset: str, workers: int | None = None) -> list[str]:
    """搜索作业 argv（--out 绝对路径进 job_key；与 conf args 同源）。"""
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


def t6_search_argv(dataset: str, algo: str, workers: int | None = None,
                   budget_cap: int | None = None) -> list[str]:
    """Test_6 搜索作业 argv（cap 进 --out 路径做产物指纹,report 无需再传）。"""
    cap = T6_BUDGET_CAP if budget_cap is None else budget_cap
    return [
        sys.executable, str(search_cli()),
        "--dataset", dataset,
        "--landmark_time", "0",
        "--algo", algo,
        "--stop_mode", "gain_only",
        "--seed", "0",
        "--budget_cap", str(cap),
        "--queue_root", str(config_family_dir("Test_6_search")),
        "--out", f"results/Test_6_search/prompt/landmark_0/cap_{cap}/{dataset}/{algo}",
        "--workers", str(T6_WORKERS if workers is None else workers),
    ]


_ARM_T3_SEARCH = Arm(
    name="test_3_search", backend="search", tag="test_3",
    queue_root=config_family_dir("Test_3_search"),
    results_root=RESULTS / "greedy_lm0",
    dataset_source="main",
    workers_default=16,
    extras={"landmark": "0", "argv": t3_search_argv,
            "report_out": RESULTS / "greedy_lm0" / "search_summary.csv",
            "workers_map_env": "T3_SEARCH_WORKERS_MAP"},
    note="A2_greedy × landmark_0 × mlp_clinic_flatten × seed 0（经统一 run 执行）",
)

_ARM_T6_SEARCH = Arm(
    name="test_6_search", backend="search", tag="test_6",
    queue_root=config_family_dir("Test_6_search"),
    results_root=RESULTS / "Test_6_search",
    dataset_source="t6_grid",
    workers_default=T6_WORKERS,
    extras={"landmark": "0", "argv": t6_search_argv,
            "report_script": "run_bakeoff_report.py",
            "report_argv": ["--results-root", "results/Test_6_search/prompt",
                            "--extra-roots", "results/greedy_lm0/search"]},
    note="Test_6 试点 3 数据集 × 8 算法（经统一 run 执行；GPU 由调用方 CUDA_VISIBLE_DEVICES 控制）",
)

ARM_REGISTRY: dict[str, Arm] = {
    arm.name: arm for arm in (
        _ARM_T0, _ARM_1B, _ARM_OFF,
        _ARM_2B, _ARM_3ARMS, _ARM_T4,
        _ARM_E_TIME, _ARM_E_FIELD, _ARM_M_TIME, _ARM_M_FIELD,
        _ARM_T3_SEARCH, _ARM_T6_SEARCH,
    )
}

ARM_ALIASES = {
    "t0": "test_1a_t0", "off": "test_1a_off",
    "1a_t0": "test_1a_t0", "1a_off": "test_1a_off", "1b": "test_1b",
    "4": "test_4",
    "2b": "test_2b", "3arms": "test_3_arms", "3search": "test_3_search",
    "6search": "test_6_search", "2b_arms": "test_2b", "3_arms": "test_3_arms",
    "E_time": "test_5_E_time", "E_field": "test_5_E_field",
    "M_time": "test_5_M_time", "M_field": "test_5_M_field",
}

# 组别名：一次带上一族（旧脚本的"全部子检查/三臂一起"用法）
ARM_GROUPS = {
    "test_5": ("test_5_E_time", "test_5_E_field", "test_5_M_time", "test_5_M_field"),
    "test_1a": ("test_1a_t0", "test_1a_off"),
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
    env_value = os.environ.get("WORKERS")
    if env_value:
        try:
            return max(1, int(env_value))
        except ValueError:
            pass
    return max(1, int(arm.workers_default or 1))



# ===========================================================================
# univariate backend（greedy/queue.py；Test_1a 三臂）
# ===========================================================================

def uni_args(arm: Arm, datasets: list[str], workers: int):
    """与 drainer 完全同源的参数命名空间（enqueue 的 job_key 由它决定）。"""
    from greedy.univariate_cli import make_parser

    args = make_parser().parse_args(arm.enqueue_argv(datasets, workers=workers))
    args.queue_kind = "univariate"
    return args


def uni_key(arm: Arm, datasets: list[str], workers: int) -> str:
    """只读算 job_key（job_key_from_args 与 enqueue_jobs 内部同源，不碰盘）。"""
    from greedy.queue import job_key_from_args

    return job_key_from_args(uni_args(arm, datasets, workers))



def cmd_uni_enqueue(arm: Arm, opts) -> None:
    from greedy.queue import enqueue_jobs

    datasets = datasets_for(arm, opts.datasets)
    args = uni_args(arm, datasets, workers_for(arm, opts))
    result = enqueue_jobs(args, datasets, root=arm.queue_root)
    print(f"[{arm.tag}] enqueue root={result['root']} key={result['job_key']} "
          f"created={len(result['created'])} existing={len(result['existing'])}")
    for path in result["created"]:
        print(f"[{arm.tag}]   + {path.name}")




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
    """raw Field Bank 构建(原 s5b_univariate_queue.sh bank;conch env,已存在即跳过)。

    GPU 由调用方 CUDA_VISIBLE_DEVICES 控制(库内不再覆写)。
    """
    conch_python = os.environ.get("CONCH_PYTHON",
                                  "/data/fangyuxuan/miniconda3/envs/conch/bin/python")
    argv = [str(SCRIPTS / arm.extras["bank_script"]), "--dataset", "all"]
    print(f"[{arm.tag}] bank build: {conch_python} {' '.join(argv)}", flush=True)
    return subprocess.call([conch_python, *argv], cwd=str(ROOT))


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
    """注册全部方案（论文 10 + 自定义 paper_* + HGCN 字段表），进程内只跑一次。

    旧 Test_3_arms.py 漏了这一步（新进程 enqueue 直接 `未知 cindex 方案: paper_*`），
    本 backend 统一走保留定义模块 Test_5_common.load_all_schemes()（唯一实现）；
    多臂循环（如 --arm test_5 四个子检查）不再重复触发注册日志。
    """
    global _SCHEMES_LOADED
    if _SCHEMES_LOADED:
        return
    import Test_5_common as C5

    C5.load_all_schemes()
    _SCHEMES_LOADED = True


# --- Test_2b 波次切片(F×T 命名:raw_*/lm0_* 替代退役字母 A1/B1H) --------------

T2B_PAN_CANCER_SCHEMES = ["MULTISURV", "SURVPGC", "MMSURV", "INTEGRATIVE_DNN"]
T2B_HGCN_BINDING = {
    "TCGA-KIRC": "HGCN_KIRC",
    "TCGA_LIHC": "HGCN_LIHC",
    "TCGA-ESCA": "HGCN_ESCA",
    "TCGA-LUSC": "HGCN_LUSC",
    "TCGA-LUAD": "HGCN_LUAD",
    "TCGA-UCEC": "HGCN_UCEC",
}
T2B_ANALYZERS = ["clinic_cox", "mlp_clinic_flatten"]
T2B_ENCODING = "text"
# 臂 T 口径:raw = 报告值臂(mask 关),lm0 = 去泄露臂(landmark_0 三要件)。
T2B_ARMS = {"raw": "none", "lm0": "0"}


def paper_work_combos() -> list[tuple[str, str]]:
    """paper 全量组合:14 主集 × (4 泛癌种 + HGCN 绑定)。主集 = label 派生(main_datasets)。

    2026-10-13 用户拍板:删波次分层(历史遗留,训练只在主集,波次产不出任何 conf),
    全部实验只跑主集;Test_0 manifest 亦随之退役。
    """
    mains = set(main_datasets())
    combos = [(ds, w) for ds in mains for w in T2B_PAN_CANCER_SCHEMES]
    combos += [(ds, w) for ds, w in sorted(T2B_HGCN_BINDING.items()) if ds in mains]
    return sorted(combos)


def paper_arm_jobs(arm: Arm, combos: list[tuple[str, str]], t: str) -> list[dict]:
    """paper 臂的 cindex conf(训练时索引口径:不物化切片)。

    (dataset, work) × t(raw/lm0) → F×T 臂方案名:
      raw(报告值)= work_raw_{work}_{ds}(数据源 = raw bank no_mask);
      lm0(去泄露)= work_lm0_{work}_{ds}(数据源 = 主 bank landmark_0)。
      两臂同一字段名单(论文模板),唯一差异 = T(取值 mask + 结局表口径)。
    """
    from common.datasets import load_dataset_configs
    from manual_pipeline.arm_names import work_scheme_name
    from manual_pipeline.cindex import iter_cindex_jobs
    from manual_pipeline.landmark import parse_landmark_setting

    if not combos:
        return []                       # 过滤后无组合 = 无事可做,非错误
    landmark = parse_landmark_setting(T2B_ARMS[t])
    all_jobs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for dataset, work in combos:
        key = (dataset, work)
        if key in seen:
            continue
        seen.add(key)
        scheme_name = work_scheme_name(work, dataset, t)
        all_jobs.extend(
            iter_cindex_jobs(
                dataset_name=dataset,
                schemes=[scheme_name],
                datasets=load_dataset_configs(ROOT / "datasets.json"),
                baseline_out=str(OUTPUTS),
                encoding=T2B_ENCODING,
                modalities=T2B_ANALYZERS,
                conf_prefix="",          # 语义名(无家族前缀):与 test_3_arms/test_4 同配置同名,判重共享
                results_root=arm.extras["cindex_results_root"],
                landmark_tag=landmark.arm_tag,
                landmark_time=landmark.landmark_time,
            )
        )
    return all_jobs


def cmd_2b_enqueue(arm: Arm, opts) -> None:
    from manual_pipeline.cindex import enqueue_cindex_jobs

    # 一条命令投完整个 2b:14 主集 × 60 组合 × 两臂(raw/lm0) × 2 分析器 = 240 confs。
    combos = paper_work_combos()
    if opts.datasets:
        allow = set(datasets_for(arm, opts.datasets))
        combos = [c for c in combos if c[0] in allow]
    all_jobs: list[dict] = []
    for t in ("raw", "lm0"):
        label = "报告值 raw" if t == "raw" else "去泄露 lm0"
        jobs = paper_arm_jobs(arm, combos, t)
        print(f"[{arm.tag}] T={t}({label}) combos={len(combos)} jobs={len(jobs)}", flush=True)
        all_jobs.extend(jobs)
    if not all_jobs:
        print(f"[{arm.tag}] 无组合(过滤后为空)")
        return
    queued = enqueue_cindex_jobs(all_jobs, queue_root=str(arm.queue_root))
    print(f"[{arm.tag}] queue={queued['root']} created={len(queued['created'])} "
          f"existing={len(queued['existing'])} retried={len(queued.get('retried', []))} "
          f"confs={len(all_jobs)}")
    print(f"[{arm.tag}] 下一步: bash scripts/exp_queue.sh run(字段名单元训练时解析,无切片步骤)")








# --- Test_3 两臂(enqueue 模板;汇总在 results_display/scripts/Test_3_arms_summarize.py)---

def t3_scheme_pairs(arm: Arm, variant: str, datasets: list[str]) -> list[tuple[str, str, str | None]]:
    """F×T 臂方案对(variant: deleak | reach | reach_best;旧名 b/ksig/best 兼容)。"""
    import Test_3_common as C
    from manual_pipeline.arm_names import greedy_scheme_name, work_scheme_name

    variant = {"b": "deleak", "ksig": "reach", "best": "reach_best"}.get(variant, variant)
    pairs: list[tuple[str, str, str | None]] = []
    for dataset in datasets:
        if variant == "deleak":
            for _d, work in C.work_pairs([dataset]):
                pairs.append((dataset, work_scheme_name(work, dataset, "lm0"), work))
        else:
            if not C.search_result_json(dataset).exists():
                print(f"[{arm.tag}][arms] 缺搜索 result.json(reach 臂跳过,先跑 Test_3 搜索): "
                      f"{C.search_result_json(dataset)}")
                continue
            kind = "ksig" if variant == "reach" else "best"
            pairs.append((dataset, greedy_scheme_name(dataset, kind=kind), None))
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
        conf_prefix="",          # 语义名(无家族前缀):与 test_2b/test_4 同配置同名,判重共享
        results_root=arm.extras["cindex_results_root"],
        seed=C.SEED,
        landmark_tag=f"landmark_{C.LANDMARK_TIME}",
        landmark_time=int(C.LANDMARK_TIME),
    )


def t4_greedy_raw_jobs(arm: Arm, dataset: str, scheme: str) -> list[dict]:
    """greedy × raw 的 cindex conf(字段名单 = 搜索 recommended_subset,与 reach 同名;
    数据源 = raw bank no_mask、结局 = 原始口径,与 paper×raw 同设置;行落 paper_raw 表)。"""
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
        conf_prefix="",
        results_root=arm.extras["cindex_results_root"],
        seed=C.SEED,
        landmark_tag="",
        landmark_time=None,
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




# --- Test_4 四档对照（纯消费：四配置组全套 conf，与 2b/3arms 同源同判重）----

def cmd_4_enqueue(arm: Arm, opts) -> None:
    """Test_4 enqueue：paper × {raw, lm0} + greedy × {raw, lm0} 的全套 conf。

    语义 = 配置组(实验定义)：Test_4 只消费这四个配置，但按"每个实验独立生成自己
    配置组的 conf"口径（2026-10-14 用户拍板），enqueue 生成全套 conf——
    与 test_2b / test_3_arms 同一语义元组 → 同一 conf 名 → 同配置谁先生成谁落盘，
    后 enqueue 的直接判重跳过；结果落点也是同一配置表（paper_raw/paper_lm0）。
    """
    from manual_pipeline.arm_names import greedy_scheme_name
    from manual_pipeline.cindex import enqueue_cindex_jobs

    import Test_3_common as C

    load_all_schemes()
    combos = paper_work_combos()
    if opts.datasets:
        allow = set(datasets_for(arm, opts.datasets))
        combos = [c for c in combos if c[0] in allow]
    all_jobs: list[dict] = []
    # ① paper × {raw, lm0}：与 test_2b 同一作业生成器（同一 conf 名，判重共享）
    for t in ("raw", "lm0"):
        label = "报告值 raw" if t == "raw" else "去泄露 lm0"
        jobs = paper_arm_jobs(arm, combos, t)
        print(f"[{arm.tag}] T={t}({label}) combos={len(combos)} jobs={len(jobs)}", flush=True)
        all_jobs.extend(jobs)
    # ② greedy × {lm0, raw}：lm0 与 test_3_arms reach 同一作业生成器；raw 是四档对照
    #    新增配置（同字段名单,数据源 = raw bank）。搜索 result.json 是 greedy 配置的
    #    生成器（不是实验依赖）：缺则 conf 不生成（pending），搜索落盘后重投本命令即可补齐。
    datasets = datasets_for(arm, opts.datasets)
    for dataset, scheme, _work in t3_scheme_pairs(arm, "reach", datasets):
        all_jobs.extend(t3_cindex_jobs(arm, dataset, scheme))
        all_jobs.extend(t4_greedy_raw_jobs(
            arm, dataset, greedy_scheme_name(dataset, t="raw")))
    if not all_jobs:
        print(f"[{arm.tag}] 无组合（过滤后为空）")
        return
    queued = enqueue_cindex_jobs(all_jobs, queue_root=str(arm.queue_root))
    print(f"[{arm.tag}] queue={queued['root']} created={len(queued['created'])} "
          f"existing={len(queued['existing'])} retried={len(queued.get('retried', []))} "
          f"confs={len(all_jobs)}")
    print(f"[{arm.tag}] 下一步: bash scripts/exp_queue.sh run")


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
    if arm.sub == "M_time" and not opts.include_multimodal:
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







# ===========================================================================
# search backend（selection/queue.py；Test_3 搜索 / Test_6 试点）
# ===========================================================================

_RUNNER_MODULE = None


def runner_module():
    """加载 drainer 模块，借用它的 parser——job_key 哈希全部 argparse 字段，
    手抄默认值极易漂移，故直接复用同一 parser 保证逐位一致（照抄
    旧 watch 的 parser 复用姿势,经统一 run 逐 conf 执行）。"""
    global _RUNNER_MODULE
    if _RUNNER_MODULE is None:
        path = search_cli()
        spec = importlib.util.spec_from_file_location("run_selection_queue", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RUNNER_MODULE = module
    return _RUNNER_MODULE


def search_units(arm: Arm) -> list[tuple[str, tuple]]:
    """[(dataset, extra…)]：extra 逐臂不同（Test_3 无；Test_6 为 algo）。"""
    if arm.dataset_source == "main":
        return [(ds, ()) for ds in main_datasets()]
    if arm.dataset_source == "t6_grid":
        return [(ds, (algo,)) for ds in T6_DATASETS for algo in T6_ALGOS]
    raise SystemExit(f"[exp_queue] 臂 {arm.name} 的 search 网格未实现: {arm.dataset_source}")


def search_argv_for(arm: Arm, dataset: str, extra: tuple, workers: int | None,
                    budget_cap: int | None = None) -> list[str]:
    if not extra:
        return arm.extras["argv"](dataset, workers)
    return arm.extras["argv"](dataset, *extra, workers, budget_cap)


def search_job(arm: Arm, dataset: str, extra: tuple, workers: int | None = None,
               budget_cap: int | None = None):
    """(args, key, conf_name)：单个搜索作业的身份，与 drainer 同源。"""
    from selection.queue import _payload

    argv = search_argv_for(arm, dataset, extra, workers, budget_cap)
    args = runner_module().parser().parse_args(argv[2:])
    payload = _payload(args)
    payload.pop("dataset", None)
    payload.pop("landmark_time", None)
    key = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False)
                       .encode("utf-8")).hexdigest()[:12]
    name = f"{key}__{dataset}__landmark_{arm.extras['landmark']}.conf"
    return args, key, name


def cmd_search_enqueue(arm: Arm, opts, *, root: Path | None = None) -> str:
    import selection.queue as SQ

    root = root or arm.queue_root
    created = existing = 0
    # workers 一律 None：test_3_search 的 enqueue argv(旧 watch 口径,现经统一 run 执行)
    # 不带 --workers），test_6_search 由 t6_search_argv 自带（T6_WORKERS）。二者都不改
    # job_key/conf 字节（selection.queue WORKER_LOCAL_KEYS 含 workers）。
    # budget_cap：t6 由 opts 传入（不同 cap = 不同 conf 身份）；t3 无此参数自动忽略。
    workers = None
    for dataset, extra in search_units(arm):
        args, _key, _name = search_job(arm, dataset, extra, workers, opts.budget_cap)
        result = SQ.enqueue(args, [dataset], [arm.extras["landmark"]], root=root)
        created += len(result["created"])
        existing += len(result["existing"])
    print(f"[{arm.tag}][enqueue] created={created} existing={existing} queue_root={root}",
          flush=True)
    return f"{arm.tag}: created={created} existing={existing}"


def cmd_search_report(arm: Arm, opts) -> int:
    if arm.name == "test_6_search":
        python_exe = os.environ.get("PYTHON3", "python3")
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

# ===========================================================================
# 统一 dispatch
# ===========================================================================

def cmd_list(opts) -> int:
    print(f"{'arm':18s} {'backend':11s} {'queue_root':48s} note")
    for arm in ARM_REGISTRY.values():
        try:
            qr = str(arm.queue_root.relative_to(ROOT))
        except ValueError:
            qr = str(arm.queue_root)
        print(f"{arm.name:18s} {arm.backend:11s} {"":6s} {qr:48s} {arm.note}")
    print(f"\n别名: " + ", ".join(f"{k}={v}" for k, v in ARM_ALIASES.items()))
    return 0



def _stamp_json_confs(arm: Arm) -> None:
    """enqueue 后给本臂新产生的 JSON conf 补自描述字段(2026-10-13:run 只读 conf)。"""
    from queue_core import ensure_dirs as ensure_queue_dirs

    root = ensure_queue_dirs(arm.queue_root)
    for path in sorted((root / "queue").glob("*.conf")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if job.get("kind"):
            continue
        kind = {"univariate": "univariate", "cindex": "cindex", "search": "search"}[arm.backend]
        job["kind"] = kind
        job["label"] = arm.name
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_enqueue(arm: Arm, opts) -> int:
    if arm.backend == "univariate":
        cmd_uni_enqueue(arm, opts)
    elif arm.backend == "cindex":
        if arm.name == "test_4":
            cmd_4_enqueue(arm, opts)
        elif arm.dataset_source == "slice_grid":
            cmd_2b_enqueue(arm, opts)
        elif arm.sub:
            rc = cmd_t5_enqueue(arm, opts)
            if rc:
                return rc
        else:
            cmd_3arms_enqueue(arm, opts)
    elif arm.backend == "search":
        cmd_search_enqueue(arm, opts)
    else:
        raise SystemExit(f"[exp_queue] 未知 backend: {arm.backend}")
    _stamp_json_confs(arm)
    return 0





def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="实验队列统一入口（臂注册表 + 三 backend）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="臂: " + ", ".join(arm_names()),
    )
    parser.add_argument("command", choices=[
        "list", "status", "enqueue", "run", "report", "bank", "check",
    ])
    parser.add_argument("--arm", action="append", default=None,
                        help="臂名/别名，可重复；status 支持 all（默认 all）")
    parser.add_argument("--datasets", default=None, help="覆盖数据集名单（冒烟/调试，逗号分隔）")
    parser.add_argument("--workers", type=int, default=None, help="并发数（默认取臂注册表/环境）")
    parser.add_argument("--budget_cap", type=int, default=None,
                        help="Test_6 搜索预算上限（enqueue 用；默认 500;结果落 cap_{cap} 目录,report 自动发现）")
    parser.add_argument("--interval", type=int, default=None, help="run 监督轮询秒数（默认 30）")
    parser.add_argument("--variant", default=None, help="Test_3 两臂变体（b / ksig / best）")
    parser.add_argument("--only", action="append", default=[], help="conf 过滤子串，可重复（Test_5 enqueue 用）")
    parser.add_argument("--include_multimodal", action="store_true",
                        help="Test_5 M_time 的 survgc_f/survpgc_f 也按常规投放")
    parser.add_argument("--sub", action="append", default=[],
                        help="scheduler 纳入的 Test_5 子检查，可重复")
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--queue_root", default=None,
                        help="覆盖队列根（仅供等价性验证/临时演练；job_key 不含 queue_root，安全）")
    opts = parser.parse_args(argv)

    try:
        opts.workers = opts.workers if opts.workers is None else max(1, int(opts.workers))
    except (TypeError, ValueError):
        raise SystemExit(f"[exp_queue] --workers 需要正整数: {opts.workers}")
    if opts.budget_cap is not None and opts.budget_cap < 0:
        raise SystemExit(f"[exp_queue] --budget_cap 需要非负整数: {opts.budget_cap}")

    if opts.command == "run":
        return cmd_run(opts)
    if opts.command == "list":
        return cmd_list(opts)

    arms = resolve_arms(opts.arm)
    if opts.queue_root:
        if len(arms) != 1:
            raise SystemExit("[exp_queue] --queue-root 只支持单臂（--arm 一次给一个；"
                             "组别名会撞同一目录）")
        for arm in arms:
            arm.queue_root = Path(opts.queue_root)
    if opts.command == "status":
        return cmd_status_all(opts, arms)
    rc = 0
    for arm in arms:
        if opts.command == "enqueue":
            if opts.dry_run and arm.backend != "cindex":
                raise SystemExit("--dry-run 只支持 cindex 臂（Test_5 子检查）")
            rc |= cmd_enqueue(arm, opts)
        elif opts.command == "report":
            if arm.backend == "univariate":
                cmd_uni_report(arm, opts)
            elif arm.backend == "search":
                rc |= cmd_search_report(arm, opts)
            else:
                raise SystemExit(f"[exp_queue] report 见 results_display/scripts 汇总(臂 {arm.name})")
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


# ===========================================================================
# 统一 run(2026-10-13 重构)——无 --arm:conf 自描述(kind/label),认领即执行
#
# 决策依据:
#   * enqueue 是唯一需要 arm 的地方(实验定义模板);drain/run 只读 conf。
#   * GPU 唯一旋钮 = 调用方 CUDA_VISIBLE_DEVICES(删 gpu_policy,见文件头)。
#   * 进程模型:WORKERS = 每卡同时跑的 conf 数(用户口径);每 conf 内固定 4 字段并发
#     (univariate);cindex/search 每 conf 一个进程。
# ===========================================================================

RUN_FIELD_TARGET = 4          # 每 conf 内字段并发数(univariate;进程总数以 WORKERS 为上限)


def _run_uni_conf(path: Path, field_workers: int) -> None:
    from greedy.queue import load_job, mark_done, mark_failed, merge_job_args
    from greedy.univariate_cli import make_parser, run_one

    try:
        job = load_job(path)
        # worker 本地键(conch_python / analyzer_python / device / queue_root)不进 conf,
        # 必须来自 drainer 的 parser 默认值——用带默认值的 namespace 做 merge 基座
        # (旧 drainer 的等价姿势;空 Namespace 会 AttributeError)。
        worker = make_parser().parse_args(["--dataset", job["dataset"], "--landmark_time", "0"])
        merged = merge_job_args(worker, job)
        merged.workers = field_workers
        run_one(merged, job["dataset"])
    except Exception as exc:  # noqa: BLE001
        mark_failed(path, error=f"{type(exc).__name__}: {exc}")
        print(f"[run] fail {path.name}: {exc}", flush=True)
        return
    mark_done(path)
    print(f"[run] done {path.name}", flush=True)


def _ensure_cindex_slice(clinic_dir: Path) -> None:
    """训练前的数据加载(切片 = dataloader):CLINIC_DIR_PATH 指向方案切片目录,
    缺/陈旧时现场从 bank 物化(零 CONCH,纯矩阵索引)。

    只处理 A_manual 切片形态 outputs/{ds}/A_manual/{scheme}[/{tag}]/embeddings/pt:
    无 tag = raw 变体(Test_2b 臂 A),landmark_0 = mask 开。baseline__ 与他线
    形态是阶段 2 产物,交给 harness(缺则 harness 报错)。
    """
    parts = clinic_dir.parts
    if "A_manual" not in parts or "baseline" in parts:
        return
    i = parts.index("A_manual")
    dataset, scheme = parts[i - 1], parts[i + 1]
    rest = parts[i + 2:]
    if rest[:2] == ("embeddings", "pt"):
        variant = "raw"
    elif len(rest) >= 3 and rest[1:3] == ("embeddings", "pt"):
        variant = "landmark_0" if rest[0] == "landmark_0" else "raw"
    else:
        return
    from Test_3_custom_scheme import ensure_scheme_slice

    print(f"[run] {ensure_scheme_slice(dataset, scheme, clinic_dir, variant=variant)}", flush=True)


def _run_cindex_conf(path: Path) -> None:
    from manual_pipeline.cindex import mark_failed, parse_conf, run_claimed_conf

    try:
        payload = parse_conf(path)
        clinic = payload.get("CLINIC_DIR_PATH")
        if clinic:
            _ensure_cindex_slice(Path(clinic))
        # run_claimed_conf 内部已 mark_done(成功与 reuse 跳过后都自己 mark),
        # 这里不能再 mark 第二次——否则 move 撞 FileNotFoundError(2026-10-14 实锤)。
        run_claimed_conf(path, reuse=True)
    except Exception as exc:  # noqa: BLE001
        if path.exists():   # conf 可能已被 run_claimed_conf 移走,存在才 mark_failed
            mark_failed(path, error=f"{type(exc).__name__}: {exc}")
        print(f"[run] fail {path.name}: {exc}", flush=True)
        return
    print(f"[run] done {path.name}", flush=True)


def _search_argv_from_conf(job: dict) -> list[str]:
    args = job.get("args") or {}
    argv = [str(SCRIPTS / "run_selection.py")]
    for key in ("dataset", "landmark_time", "algo", "stop_mode", "seed", "out",
                "inner_analyzer", "budget_cap", "anchor_p", "workers", "max_epochs"):
        if key in args and args[key] is not None:
            argv.extend([f"--{key}", str(args[key])])
    return argv


def _run_search_conf(path: Path) -> None:
    from queue_core import load_job, mark_done, mark_failed

    job = load_job(path)
    argv = _search_argv_from_conf(job)
    python_exe = os.environ.get("PYTHON3", "python3")
    rc = subprocess.call([python_exe, *argv], cwd=str(ROOT))
    if rc != 0:
        mark_failed(path, error=f"run_selection rc={rc}: {' '.join(argv)}")
        print(f"[run] fail {path.name} rc={rc}", flush=True)
        return
    mark_done(path)
    print(f"[run] done {path.name}", flush=True)


def _skip_if_done(path: Path) -> bool:
    """结果已存在 → mark_done + 日志 [run] skip,返回 True(调度层统一 skip 机制,
    2026-10-14 用户拍板:跑任何实验都生成全套 conf,已完成的配置直接跳过)。

    判据:cindex = OUT_DIR/.done(run.sh 成功才写);search = result.json 已落盘。
    univariate 不在此层 skip——其 per-field reuse 已保证"只补缺失字段"。
    """
    from queue_core import load_job, mark_done

    try:
        job = load_job(path)
    except Exception:  # noqa: BLE001
        # bash 风格 conf(cindex):OUT_DIR = RESULTS_BASE/EXP_GROUP/RUN_NAME/PRESET
        try:
            from manual_pipeline.cindex import parse_conf

            payload = parse_conf(path)
            out_dir = (Path(payload["RESULTS_BASE"]) / payload["EXP_GROUP"]
                       / payload["RUN_NAME"] / payload["PRESET"])
            if (out_dir / ".done").exists():
                mark_done(path)
                print(f"[run] skip {path.name}（结果已存在 {out_dir}/.done）", flush=True)
                return True
        except Exception:  # noqa: BLE001
            return False
        return False
    kind = job.get("kind")
    if kind == "search":
        args = job.get("args") or {}
        out = args.get("out")
        if out:
            result = Path(out) / args.get("inner_analyzer", "mlp_clinic_flatten") \
                / f"seed_{args.get('seed', 0)}" / "result.json"
            if result.exists():
                mark_done(path)
                print(f"[run] skip {path.name}（结果已存在 {result}）", flush=True)
                return True
    return False


def _run_conf(path: Path, field_workers: int) -> None:
    """认领后按 conf 自描述分发执行(先 skip 检查,再按 kind 分发)。

    GPU 唯一旋钮 = 调用方 CUDA_VISIBLE_DEVICES(决策:2026-10-13 用户拍板——
    删 gpu_policy 机制:原 T5 调度器的 nvidia-smi 轮询/空闲卡放置/占位跟踪是残留,
    一律不要;要多卡分账就起多个 run 进程各绑一张卡,claim 原子 mv 天然不抢同一 conf)。
    """
    if _skip_if_done(path):
        return
    job = None
    try:
        from queue_core import load_job as _load

        job = _load(path)
    except Exception:  # noqa: BLE001
        job = None
    if job and job.get("kind") == "cindex":
        _run_cindex_conf(path)
    elif job and job.get("kind") == "search":
        _run_search_conf(path)
    elif job and job.get("kind") == "univariate":
        _run_uni_conf(path, field_workers)
    elif job is None:
        # bash 风格 conf 只出自 cindex(conf_text 是唯一 bash 格式);直接按 cindex 执行。
        # 解析失败由 _run_cindex_conf 内部 mark_failed(conf 名已是语义元组,无家族前缀)。
        _run_cindex_conf(path)
    else:
        from queue_core import mark_failed

        mark_failed(path, error=f"未知 kind: {job.get('kind')}")
        print(f"[run] fail {path.name}: 未知 kind {job.get('kind')}", flush=True)


def _recover_stale_running(root: Path) -> int:
    """running/ 里 claimed_pid 已死的 conf 放回 queue/(自愈:死进程补位)。"""
    from queue_core import load_job as _load, release as _release

    moved = 0
    for path in sorted((root / "running").glob("*.conf")):
        try:
            job = _load(path)
            pid = int(job.get("claimed_pid") or 0)
        except Exception:  # noqa: BLE001
            # bash 风格 conf:从注释行解析 claimed_pid(见 queue_core._stamp_claimed);
            # 无盖章注释 = 旧代码时代的死进程遗留,直接回收。
            pid = 0
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("# claimed_pid="):
                    try:
                        pid = int(line.split("=", 1)[1].strip())
                    except ValueError:
                        pid = 0
        if not pid or not pid_alive(pid):
            _release(path)
            moved += 1
            print(f"[run] recover {path.name} (pid {pid} 已死)", flush=True)
    return moved


def _retry_failed(root: Path) -> int:
    from queue_core import load_job as _load, release as _release

    moved = 0
    for path in sorted((root / "failed").glob("*.conf")):
        try:
            job = _load(path)
        except Exception:  # noqa: BLE001
            # 非 JSON 的 bash 风格 cindex conf:无 run_tries 记账,清 .err 后直接放回队列重试
            path.with_suffix(".err").unlink(missing_ok=True)
            _release(path)
            moved += 1
            print(f"[run] retry {path.name} (bash conf)", flush=True)
            continue
        tries = int(job.get("run_tries") or 0)
        if tries >= MAX_RETRIES:
            continue
        job["run_tries"] = tries + 1
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _release(path)
        moved += 1
        print(f"[run] retry {path.name} (第 {tries + 1} 次)", flush=True)
    return moved


def cmd_run(opts) -> int:
    """统一 run:认领 conf(名排序)→ 按 conf 自描述执行,守到完成。

    GPU 一行一卡(2026-10-13 拍板):一条 run 命令 = 一张卡(CUDA_VISIBLE_DEVICES 绑定),
    WORKERS = 这张卡上同时跑的 work(conf)数(各卡独立:卡 6 WORKERS=8 = 8 个 conf);
    多卡分账 = 起多个 run 各绑一张卡并行(claim 原子 mv 互不抢同一 conf),
    顺序分批 = 分批 enqueue 再逐批 run。每 conf 内固定 4 字段并发(内部实现)。
    """
    from queue_core import BUCKETS as _B, claim, count

    root = Path(opts.queue_root) if opts.queue_root else config_family_dir("")
    workers = max(1, int(opts.workers or os.environ.get("WORKERS") or 16))
    interval = max(1, int(opts.interval or 30))
    total = sum(count(root, b) for b in _B)
    if total == 0:
        print("[run] 无任务(桶全空;先 enqueue)")
        return 0
    n_conf = max(1, workers)          # WORKERS = 每卡 conf 数(用户口径,非进程数)
    pool = ThreadPoolExecutor(max_workers=n_conf)
    futures: dict = {}
    while True:
        # 自愈:死进程补位 + 失败重试
        _recover_stale_running(root)
        _retry_failed(root)
        # 补位式认领:完成一个立即认领下一个,保持 n_conf 在飞。
        # (不能整批等全部完成再认领——慢 conf 会把整批拖住,running 掉到个位数,
        #  队列看着像卡死。2026-10-14 修。)
        while len(futures) < n_conf:
            path = claim(root, "")
            if path is None:
                break
            futures[pool.submit(_run_conf, path, RUN_FIELD_TARGET)] = path
        if futures:
            # 带超时等完成(interval 秒):超时也回到补位——空位随下轮顶部补满。
            # (不带超时的阻塞等待会把补位饿死:剩余 conf 都很长时,空位空转数小时,
            #  队列看着不动。2026-10-14 过夜实锤。)
            try:
                for fut in as_completed(list(futures), timeout=interval):
                    fut.result()
                    del futures[fut]
            except TimeoutError:
                pass
        counts = {b: count(root, b) for b in _B}
        print(f"[run] queue={counts['queue']} running={counts['running']} "
              f"done={counts['done']} failed={counts['failed']} "
              f"inflight={len(futures)}/{n_conf} total={total}", flush=True)
        # 收工判据:全桶跑干
        if counts["queue"] == 0 and counts["running"] == 0 \
                and counts["done"] + counts["failed"] >= total:
            print(f"[run] finish done={counts['done']} failed={counts['failed']}")
            return 0 if counts["failed"] == 0 else 1


def _bash_conf_label(path: Path) -> str:
    """bash 风格 cindex conf 的配置口径标签:读 conf 的 EXP_GROUP(结果落点),不猜名字。"""
    try:
        from manual_pipeline.cindex import parse_conf

        group = parse_conf(path).get("EXP_GROUP", "")
        if group.startswith("Test_5_invariance/"):
            return group.split("/")[1]
        for marker, label in (("paper_raw", "paper_raw"), ("paper_lm0", "paper_lm0"),
                              ("greedy_lm0", "greedy_lm0")):
            if marker in group:
                return label
    except Exception:  # noqa: BLE001
        pass
    return path.name.split("__")[0]


def cmd_status_all(opts, arms: list[Arm]) -> int:
    """统一 status(无臂必需):flat 四桶按 label 分组计数;arm 仅作过滤标签。

    机器可判定:queue+running 非空或 failed>0 时退出码 1(实验未完成/有失败),
    否则 0。桶内 conf 数 = 期望数的对照由 enqueue 时的 total 计数承担。
    """
    from queue_core import BUCKETS as _B, load_job

    root = config_family_dir("")
    want_labels = {arm.name for arm in arms} if opts.arm else None
    rows: dict[str, dict[str, int]] = {}
    for bucket in _B:
        for path in sorted((root / bucket).glob("*.conf")):
            label = path.name.split("__")[0]
            try:
                job = load_job(path)
                label = str(job.get("label") or label)
                kind = str(job.get("kind") or "?")
            except Exception:  # noqa: BLE001
                kind = "cindex"
                label = _bash_conf_label(path) or label
            if want_labels is not None and label not in want_labels:
                continue
            row = rows.setdefault((label, kind), {b: 0 for b in _B})
            row[bucket] += 1
    print(f"{'label':18s} {'kind':10s} " + " ".join(f"{b:>7s}" for b in _B))
    verdict = 0
    for (label, kind), row in sorted(rows.items()):
        print(f"{label:18s} {kind:10s} " + " ".join(f"{row[b]:7d}" for b in _B))
        if row["queue"] or row["running"] or row["failed"]:
            verdict = 1
    if not rows:
        print("(桶全空;先 enqueue)")
        return 0
    print(f"[status] {'未完成/有失败' if verdict else '全部完成'} "
          f"({sum(r['done'] for r in rows.values())} done)")
    return verdict


def _install_group_kill() -> None:
    """SIGTERM/SIGINT → 杀整个进程组(训练子进程连坐,不留孤儿)。

    前提:run 由 exp_queue.sh 以 setsid 起(独立进程组),子进程继承同组;
    直接前台跑 python scripts/exp_queue.py run 时进程组 = 终端组,不要安装
    (会误伤终端)——只在经 sh 壳(setsid)启动时生效。
    """
    import signal as _signal

    if os.getsid(0) == os.getpid():
        def _handler(signum, _frame):
            # 先对自己忽略本信号(killpg 会向整组含自己投递,不设忽略会 handler 重入
            # 递归 ~1000 层 RecursionError,os._exit 到不了),再连坐整组,最后 C 级硬退。
            # os._exit 立即终止,不可能被吞(旧 bug = SIG_IGN + SystemExit 被吞成僵尸;
            # 独立查验 2026-10-14 实锤:无 SIG_IGN 时 RecursionError)。
            try:
                _signal.signal(signum, _signal.SIG_IGN)
                os.killpg(0, _signal.SIGTERM)
            except OSError:
                pass
            os._exit(128 + int(signum))

        _signal.signal(_signal.SIGTERM, _handler)
        _signal.signal(_signal.SIGINT, _handler)


if __name__ == "__main__":
    _install_group_kill()
    raise SystemExit(main())
