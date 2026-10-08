"""Test_5 不变性批跑（spec §8bis）共享定义：子检查 → conf 枚举 / 队列 / EXP_GROUP 映射。

口径来源（唯一来源 = `z_notes/Test_series_spec.md` §8bis）：
  5E_2b  E→baseline 复现 Test_2b 两臂 A(landmark_none)/B(landmark_0) × mlp_clinic_flatten
  5E_3   E→baseline 复现 Test_3 臂 B（Test_3_{work}_{dataset}）/ C（Test_3_greedy_{dataset}）
  5M_2b  M→snn_clinic_flatten（15 主集）+ M→survgc_f/survpgc_f（多模态 4 数据集）复现 Test_2b 两臂
  5M_3   M→clinic_cox 复现 Test_3 臂 B/C

纪律（spec §2.4 / §8bis.5）：
  * 数据集名单一律读 results/Test_0_dataset_availability/manifest.csv（n_event >= 100 的 15 主集）；
  * 方案 × 数据集绑定一律读 templates/manual_schemes/*/fields.json 的 `datasets`（不硬编码名单；
    code 里只有"子检查逻辑"常量：臂定义、模型名、编码名）；
  * 本轮 E/M 轴只换一个轴，其余与基线一致：landmark_0 / 5 折 / seed 0 / 协议 A 训练范围；
  * 本模块只读 + 建目录，不写任何 results/Test_2b|Test_3 产物。

EXP_GROUP 映射（可复用 cindex 的既有机制，不新增目录约定）：
  manual_pipeline/cindex.py::analyzer_exp_group() 返回模块级常量 ANALYZER_EXP_GROUP /
  LANDMARK_ANALYZER_EXP_GROUP；iter_cindex_jobs 用它写入 conf 的 EXP_GROUP=，run.sh 按
  `$RESULTS_BASE/$EXP_GROUP/$RUN_NAME/$RESULTS_SUBDIR` 落 run dir，run_claimed_conf 再从
  conf 读回。故本模块只在 enqueue/summarize 进程内覆写这两个常量（in-process 覆写惯例），
  drainer 无需打补丁。
  runs   -> results/Test_5_invariance/{sub}/runs
  tables -> results/Test_5_invariance/{sub}/{dataset}[gdc]/cindex.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common.paths import config_family_dir, test_results_dir  # noqa: E402

MANIFEST_CSV = ROOT / "results" / "Test_0_dataset_availability" / "manifest.csv"
OUTPUTS = ROOT / "outputs"
RESULTS_ROOT = ROOT / "results"
DATASETS_JSON = ROOT / "datasets.json"
TEMPLATE_DIR = ROOT / "templates" / "manual_schemes"

INVARIANCE_ROOT = RESULTS_ROOT / "Test_5_invariance"          # 本步唯一可写的 results 子树
LOG_ROOT = INVARIANCE_ROOT / "logs"

MAIN_N_EVENT_MIN = 100        # 协议 A 主集阈值（R13，spec §12 U1）
SEED = 0
LANDMARK_ARM_TAG = "landmark_0"
LANDMARK_DAYS = 0

SUBS = ("5E_2b", "5E_3", "5M_2b", "5M_3")

# 子检查语义（臂 × 编码 × 模型）；方案集合与数据集绑定全部从数据派生。
SUB_SPEC = {
    "5E_2b": {"encoding": "baseline", "arms": ("A", "B"), "modalities": ("mlp_clinic_flatten",),
              "schemes": "work"},
    "5E_3": {"encoding": "baseline", "arms": ("Bp", "C"), "modalities": ("mlp_clinic_flatten",),
             "schemes": "test3"},
    "5M_2b": {"encoding": "text", "arms": ("A", "B"),
              "modalities": ("snn_clinic_flatten", "survgc_f", "survpgc_f"), "schemes": "work"},
    "5M_3": {"encoding": "text", "arms": ("Bp", "C"), "modalities": ("clinic_cox",),
             "schemes": "test3"},
}

# 臂 → (landmark_tag, landmark_time)：A = Test_2b 臂 A（mask 关，label 回退默认 metadata），
# 其余 = landmark_0（landmark mask + 风险集 + 时间原点平移 + 派生 label 文件）。
ARM_LANDMARK = {"A": ("", None), "B": (LANDMARK_ARM_TAG, LANDMARK_DAYS),
                "Bp": (LANDMARK_ARM_TAG, LANDMARK_DAYS), "C": (LANDMARK_ARM_TAG, LANDMARK_DAYS)}

# Test_3 臂 B 的本轮范围 = 4 个泛癌种工作 × 15 主集（spec §8bis.2 "15 × 2 臂"）。
# Test_3_HGCN_*_TCGA-* 变体（4 个：KIRC/LIHC/LUAD/LUSC）不在本轮 B 范围：
# S12a 只为 60 个 B 落了 baseline 编码，5E_3 的 E 轴对照需要有同集合 baseline 产物。
BP_WORKS = ("MULTISURV", "SURVPGC", "MMSURV", "INTEGRATIVE_DNN")

# 多模态（WSI+omics）模型：本轮暂不投放（parked/），原因见 park_reason()。
# 实证：2026-10-04 BRCA survgc_f 试跑，"[WSI filter] kept cases: 0 | removed cases: 1030"
# —— Clinic_Analyzer 的 label metadata 是 case 级 slide_id（TCGA-A8-A08S.svs），而
# SurvPGC_Workspace/{study}/P/uni_v1/*.pt 是 slide 级（TCGA-...-DX1.<hash>.pt）；
# 换成上游 slide 级 metadata（SurvPGC_github_init/datasets_csv/metadata/{study}.csv）
# 后同一 run 通过（"[WSI filter] kept cases: 1055 | removed cases: 0"，[DONE]）。
PARK_MODALITIES = ("survgc_f", "survpgc_f")


def park_reason(modality: str) -> str:
    return (f"{modality} 需要 slide 级 label metadata（SurvPGC_github_init/datasets_csv/"
            "metadata/{study}.csv）；Clinic_Analyzer case 级 metadata 的 slide_id 与 "
            "P/uni_v1/*.pt 命名不匹配 -> WSI filter kept 0。待 S13 决定 label 源"
            "（含 landmark_0 派生口径）后再投放。")


# ---------------------------------------------------------------------------
# 方案注册 / 数据集
# ---------------------------------------------------------------------------

def load_all_schemes() -> None:
    """注册全部方案（论文 10 + 自定义 Test_3_* + HGCN 字段表），同 s4_enqueue 惯例。"""
    from manual_pipeline.baseline import load_baseline_scheme_fields
    from manual_pipeline.config import SCHEME_FIELDS, load_custom_schemes
    from manual_pipeline.hgcn_clinic import load_hgcn_scheme_fields

    load_custom_schemes(str(TEMPLATE_DIR))
    load_baseline_scheme_fields(SCHEME_FIELDS)
    load_hgcn_scheme_fields(SCHEME_FIELDS)


def main_datasets() -> list[str]:
    """协议 A 主集：manifest 中 TCGA 且 n_event >= 100（字典序，不硬编码）。"""
    rows = list(csv.DictReader(MANIFEST_CSV.open(newline="", encoding="utf-8")))
    names = sorted(
        row["dataset"] for row in rows
        if str(row["dataset"]).upper().startswith("TCGA")
        and float(row.get("n_event") or 0) >= MAIN_N_EVENT_MIN
    )
    if not names:
        raise SystemExit(f"[test_5] 主集为空（{MANIFEST_CSV}, n_event >= {MAIN_N_EVENT_MIN}）")
    return names


def _datasets_config() -> dict:
    return json.loads(DATASETS_JSON.read_text(encoding="utf-8"))


def paper_works() -> list[str]:
    """10 个论文工作方案（PAPER_SCHEMES 的基线部分；Test_3_* 是自定义复评方案，不算工作）。"""
    from manual_pipeline.config import PAPER_SCHEMES

    return [name for name in PAPER_SCHEMES if not name.startswith("Test_3")]


def work_bound_to(scheme: str, dataset: str) -> bool:
    """spec §2.4 方案 × 数据集绑定。

    论文模板的 fields.json `datasets` 是"全 33 TCGA"（未编码 HGCN 绑定），故 HGCN_* 的
    本癌种绑定按模板名的癌种码判定（HGCN_KIRC ↔ TCGA-KIRC / TCGA_LIHC ↔ HGCN_LIHC），
    泛癌种方案（其余 4 个）对全部数据集成立——不硬编码名单。
    """
    if not scheme.startswith("HGCN_"):
        return True
    code = scheme[len("HGCN_"):].upper()
    dataset_code = dataset.upper()
    for prefix in ("TCGA-", "TCGA_"):
        if dataset_code.startswith(prefix):
            dataset_code = dataset_code[len(prefix):]
            break
    return code == dataset_code


def work_schemes(dataset: str) -> list[str]:
    """绑定到该数据集的论文工作方案（spec §2.4 绑定 + fields.json datasets 门）。"""
    from manual_pipeline.config import scheme_applies_to_dataset

    datasets = _datasets_config()
    return sorted(s for s in paper_works()
                  if work_bound_to(s, dataset) and scheme_applies_to_dataset(s, dataset, datasets))


def b_schemes(dataset: str) -> list[str]:
    """Test_3 臂 B 方案（已注册 + 绑定该数据集），本轮 = 4 泛癌种工作。"""
    from manual_pipeline.config import SCHEME_CONFIG

    return [name for name in (f"Test_3_{w}_{dataset}" for w in BP_WORKS) if name in SCHEME_CONFIG]


def c_schemes(dataset: str) -> list[str]:
    """Test_3 臂 C（贪婪最优，模板/编码存在才算；否则空 = 该数据集本轮无 C）。"""
    from manual_pipeline.config import SCHEME_CONFIG

    name = f"Test_3_greedy_{dataset}"
    return [name] if name in SCHEME_CONFIG else []


def greedy_template_datasets() -> list[str]:
    """存在 Test_3_greedy_{dataset} 模板的数据集（数据驱动，供报告用）。"""
    from manual_pipeline.config import SCHEME_CONFIG

    return sorted(name[len("Test_3_greedy_"):] for name in SCHEME_CONFIG
                  if name.startswith("Test_3_greedy_"))


# ---------------------------------------------------------------------------
# 队列 / EXP_GROUP
# ---------------------------------------------------------------------------

def queue_root(sub: str) -> Path:
    return config_family_dir(f"Test_5_{sub}")


def runs_group(sub: str) -> str:
    return f"Test_5_invariance/{sub}/runs"


def tables_group(sub: str) -> str:
    return f"Test_5_invariance/{sub}"


@contextmanager
def exp_group_override(sub: str, *, tables: bool = False):
    """进程内覆写 cindex 的 EXP_GROUP 常量（runs 落点 / 汇总表落点）。

    四个常量全覆写：
      * ANALYZER_EXP_GROUP / LANDMARK_ANALYZER_EXP_GROUP -> runs dir（iter_cindex_jobs
        写进 conf 的 EXP_GROUP=，也是 job["out_dir"] 的来源）；
      * DEFAULT_EXP_GROUP / DEFAULT_LANDMARK_EXP_GROUP -> 汇总表 dir
        （result_table_dir = root/DEFAULT_*_ / dataset，summarize_dataset 用）。
    不覆写会把 run/表写到 results/Test_2b/arm_A|arm_B（cindex 的默认 arm 落点）。
    """
    from src import cindex

    group = tables_group(sub) if tables else runs_group(sub)
    saved = (cindex.ANALYZER_EXP_GROUP, cindex.LANDMARK_ANALYZER_EXP_GROUP,
             cindex.DEFAULT_EXP_GROUP, cindex.DEFAULT_LANDMARK_EXP_GROUP)
    cindex.ANALYZER_EXP_GROUP = cindex.LANDMARK_ANALYZER_EXP_GROUP = group
    cindex.DEFAULT_EXP_GROUP = cindex.DEFAULT_LANDMARK_EXP_GROUP = group
    try:
        yield group
    finally:
        (cindex.ANALYZER_EXP_GROUP, cindex.LANDMARK_ANALYZER_EXP_GROUP,
         cindex.DEFAULT_EXP_GROUP, cindex.DEFAULT_LANDMARK_EXP_GROUP) = saved


# ---------------------------------------------------------------------------
# conf 枚举
# ---------------------------------------------------------------------------

@dataclass
class ArmPlan:
    arm: str
    encoding: str
    schemes: list[str]
    modalities: list[str]
    landmark_tag: str = ""
    landmark_time: int | None = None
    notes: list[str] = field(default_factory=list)


def _multimodal_modalities(dataset: str) -> list[str]:
    """5M_2b 的模型集合：snn 全 15 主集；survgc_f/survpgc_f 仅 registry 多模态 4 集。"""
    from greedy.clinic import MULTIMODAL_STUDIES
    from greedy.data import display_to_study

    mods = ["snn_clinic_flatten"]
    if display_to_study(dataset) in MULTIMODAL_STUDIES:
        mods += ["survgc_f", "survpgc_f"]
    return mods


def arm_plans(sub: str, dataset: str) -> list[ArmPlan]:
    spec = SUB_SPEC[sub]
    encoding = spec["encoding"]
    plans: list[ArmPlan] = []
    for arm in spec["arms"]:
        if spec["schemes"] == "work":
            schemes = work_schemes(dataset)
            notes = []
        else:
            schemes = (b_schemes(dataset) if arm == "B" else c_schemes(dataset))
            notes = [] if schemes else ["no template/registration"]
        if sub == "5M_2b":
            modalities = _multimodal_modalities(dataset)
        else:
            modalities = list(spec["modalities"])
        tag, time = ARM_LANDMARK[arm]
        plans.append(ArmPlan(arm=arm, encoding=encoding, schemes=schemes, modalities=modalities,
                             landmark_tag=tag, landmark_time=time, notes=notes))
    return plans


def _reuse_existing_landmark_labels() -> None:
    """把 cindex 的 build_landmark_label_file 替换为"存在即只读复用"（幂等装入）。

    原实现每次枚举 landmark 臂都无条件重写 results/Test_2b/arm_B/labels/*.csv
    （内容确定：已核 blca/brca/laml/stad 与现文件逐字节一致，仅 mtime 变化）。本步对
    Test_2b 是只读范围，故在 Test_5 进程内避免重写；现成文件缺失才回退原实现（新建）。
    """
    from manual_pipeline import cindex
    from manual_pipeline import landmark_labels as LL

    current = getattr(cindex, "build_landmark_label_file", None)
    if current is not None and getattr(current, "_test5_reuse", False):
        return
    original = LL.build_landmark_label_file

    def reuse(*, study, landmark_time, **kw):
        out = Path(kw["out_path"]) if kw.get("out_path") else LL.landmark_label_path(
            study=study, landmark_time=landmark_time,
            results_root=kw.get("results_root"))
        if out.exists():
            stats_path = out.with_suffix(".json")
            if stats_path.exists():
                return out, json.loads(stats_path.read_text(encoding="utf-8"))
        return original(study=study, landmark_time=landmark_time, **kw)

    reuse._test5_reuse = True
    cindex.build_landmark_label_file = reuse


def build_jobs(sub: str, datasets: list[str] | None = None,
               conf_filters: tuple[str, ...] = ()) -> list[dict]:
    """枚举该子检查的全部 cindex job（含 out_dir / conf_name，可幂等入队）。

    只读：不存在的编码目录由 iter_cindex_jobs 打印后跳过（不产生 conf）；landmark 派生
    label 文件已存在时只读复用（不重写 results/Test_2b/arm_B/labels/*，见上）。
    """
    from manual_pipeline.cindex import iter_cindex_jobs

    _reuse_existing_landmark_labels()
    datasets = list(datasets or main_datasets())
    datasets_cfg = _datasets_config()
    jobs: list[dict] = []
    with exp_group_override(sub):
        for dataset in datasets:
            for plan in arm_plans(sub, dataset):
                if not plan.schemes:
                    continue
                for job in iter_cindex_jobs(
                    dataset_name=dataset,
                    schemes=plan.schemes,
                    datasets=datasets_cfg,
                    baseline_out=str(OUTPUTS),
                    encoding=plan.encoding,
                    modalities=plan.modalities,
                    results_root=RESULTS_ROOT,
                    seed=SEED,
                    landmark_tag=plan.landmark_tag,
                    landmark_time=plan.landmark_time,
                ):
                    job["arm"] = plan.arm
                    jobs.append(job)
    if conf_filters:
        jobs = [job for job in jobs
                if any(token in job["conf_name"] or token in f"{job['dataset']}|{job['scheme']}"
                       for token in conf_filters)]
    return jobs


def encoding_paths(dataset: str, scheme: str, encoding: str, landmark_tag: str) -> Path:
    """conf 的 CLINIC_DIR_PATH（与 cindex.scheme_output_dir 同口径，供缺件报告）。"""
    from manual_pipeline.cindex import scheme_output_dir

    # 注意：必须保留 `baseline__` 前缀再交给 scheme_output_dir（它用前缀判定
    # `A_manual/baseline/{scheme}` 子目录；先 bound_scheme_name 会得到 prompt 路径）。
    name = f"baseline__{scheme}" if encoding == "baseline" and not scheme.startswith("baseline__") \
        else scheme
    subdir = "" if landmark_tag in ("", "no_mask") else landmark_tag
    return scheme_output_dir(dataset, name, str(OUTPUTS), landmark_subdir=subdir)


def expected_counts(datasets: list[str] | None = None) -> dict[str, dict]:
    """每子检查的 conf 期望数（按枚举逻辑算，不跑 iter_cindex_jobs）。"""
    datasets = list(datasets or main_datasets())
    out: dict[str, dict] = {}
    for sub in SUBS:
        per_ds: dict[str, int] = {}
        total = 0
        for dataset in datasets:
            n = 0
            for plan in arm_plans(sub, dataset):
                n += len(plan.schemes) * len(plan.modalities)
            per_ds[dataset] = n
            total += n
        out[sub] = {"total": total, "per_dataset": per_ds}
    return out


def park_jobs(jobs: list[dict], sub: str) -> dict:
    """把 job 写成 `<queue_root>/parked/*.conf`（flat，同 s5b 的 parked 惯例）。

    parked/ 不被 drainer 读取（cindex 只扫 queue/running/done/failed），= 暂缓投放、
    不丢 conf，S13 决定后可手工 mv 回 queue/。幂等：同名已存在即 existing。
    """
    from manual_pipeline.cindex import _write_exclusive, conf_text

    root = queue_root(sub) / "parked"
    root.mkdir(parents=True, exist_ok=True)
    created, existing = [], []
    for job in jobs:
        dest = root / job["conf_name"]
        if dest.exists():
            existing.append(dest)
            continue
        content = conf_text(
            study=job["study"],
            scheme=job["scheme"],
            modality=job["modality"],
            clinic_dir=job["clinic_dir"],
            split_dir=job["split_dir"],
            results_base=job["results_base"],
            seed=job.get("seed", 0),
            max_epochs=job.get("max_epochs"),
            landmark_tag=job.get("landmark_run_tag", job.get("landmark_tag", "")),
            exp_group=job.get("exp_group"),
            label_file=job.get("label_file"),
        )
        if _write_exclusive(dest, content):
            created.append(dest)
    return {"root": root, "created": created, "existing": existing}


def queue_status(sub: str) -> dict[str, int]:
    root = queue_root(sub)
    return {bucket: len(list((root / bucket).glob("*.conf")))
            for bucket in ("queue", "running", "done", "failed", "parked")}


def print_status(datasets: list[str] | None = None) -> None:
    datasets = list(datasets or main_datasets())
    counts = expected_counts(datasets)
    grand = 0
    print(f"[test_5] 主集 {len(datasets)}: {', '.join(datasets)}")
    print(f"[test_5] 有 greedy 模板的数据集（臂 C 来源）: {', '.join(greedy_template_datasets())}")
    for sub in SUBS:
        st = queue_status(sub)
        n = counts[sub]["total"]
        grand += n
        print(f"[test_5] {sub}: expected={n:4d} queue={st['queue']:3d} running={st['running']:2d} "
              f"done={st['done']:4d} failed={st['failed']:3d} parked={st['parked']:3d} "
              f"root={queue_root(sub)}")
    print(f"[test_5] 合计 expected={grand}（5M_2b 的 survgc_f/survpgc_f 在 parked/ 时少 72）")
    print(f"[test_5] 多模态暂缓: {park_reason(PARK_MODALITIES[0])}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Test_5 conf 枚举（只读预览）")
    ap.add_argument("--sub", default=None, choices=SUBS)
    ap.add_argument("--datasets", default=None)
    ap.add_argument("--list", action="store_true", help="打印每 conf 的 conf_name/clinic_dir")
    args = ap.parse_args()

    load_all_schemes()
    datasets = ([x.strip() for x in args.datasets.split(",") if x.strip()]
                if args.datasets else main_datasets())
    if args.list:
        for sub in ([args.sub] if args.sub else SUBS):
            for job in build_jobs(sub, datasets):
                exists = "OK " if Path(job["clinic_dir"]).is_dir() else "MISS"
                print(f"{sub}\t{exists}\t{job['conf_name']}\t{job['clinic_dir']}")
    else:
        print_status(datasets)
