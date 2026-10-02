#!/usr/bin/env python3
"""Test_0：实验可用数据集评估（规格见 z_notes/Test_series_spec.md §4）。

输入（全部只读，不跑训练）：
- ``datasets.json``                                  注册队列全集（33 TCGA + CPTAC + MMRF）
- ``rawdata_stats/_shared/event_summary.csv``        队列级事件汇总
- ``rawdata_stats/{dataset}/event_stats.csv``        患者级事件表（submitter_id/event/ground_truth_time）
- ``Clinic_Analyzer/data/splits/5foldcv/{study}/splits_*.csv``  5 折划分（每折事件数）

产物（``results/Test_0_dataset_availability/``）：
- ``manifest.csv``          每队列一行，列见 ``MANIFEST_COLUMNS``
- ``{dataset}_profile.json`` 每队列的完整画像（含规则命中、每折事件数、landmark 候选口径）

口径要点
--------
- 分层规则：spec §4.2 R1–R5、R7、R8；**D1 未确认**，故 ``tier`` 一律标注 ``provisional``。
- ``effective_events_lm*``：**D2 未确认**，manifest 留空并写 TODO；候选口径的两个数值
  记录在 profile JSON 的 ``landmark.candidates``，仅供决策，不作为门槛依据。
- 可重复：同输入重跑 diff=0（确定性排序、固定缩进/换行、数值定点舍入）。
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# 规格常量（spec §4.2；数值以 D1 确认为准）
# ---------------------------------------------------------------------------

TIER_MAIN_MIN_EVENTS = 150       # R1 主集
TIER_EXT_MIN_EVENTS = 70         # R2 扩展集
TIER_SUPP_MIN_EVENTS = 30        # R3 补充集（低于此值为 R4 排除集）
EVENT_RATE_DOWNGRADE = 0.1       # R5 次级规则：event_rate < 0.1 降一级
EPV_EVENTS_PER_FIELD = 10        # R8 多字段实验：每折事件数 >= 10 x 字段数
DEGEN_FOLD_MAX_EVENTS = 1        # R7 结构退化折：折内 val 事件数 <= 1（c-index 只能取 0/1 或无定义）

TIER_ORDER = ("main", "extended", "supplementary", "excluded")
TIER_LABEL_ZH = {
    "main": "主集",
    "extended": "扩展集",
    "supplementary": "补充集",
    "excluded": "排除集",
}

LANDMARK_TIMES_DEFAULT = ("0", "365", "730")

MANIFEST_COLUMNS = [
    "dataset",
    "tier",
    "n_patients",
    "n_event",
    "event_rate",
    "per_fold_events",
    "effective_events_lm0",
    "effective_events_lm365",
    "effective_events_lm730",
    "degen_folds",
    "rule_hits",
    "note",
]

PER_FOLD_SEP = "|"
SPLIT_RE = re.compile(r"splits_(\d+)\.csv$")


# ---------------------------------------------------------------------------
# 纯函数：分层规则（可单测，不接触真实数据）
# ---------------------------------------------------------------------------


def base_tier(
    n_event,
    *,
    main_min: int = TIER_MAIN_MIN_EVENTS,
    ext_min: int = TIER_EXT_MIN_EVENTS,
    supp_min: int = TIER_SUPP_MIN_EVENTS,
) -> tuple[str, str]:
    """spec §4.2 R1–R4 的基础档位。返回 (tier, rule_code)。"""
    n = _as_int(n_event)
    if n >= main_min:
        return "main", "R1"
    if n >= ext_min:
        return "extended", "R2"
    if n >= supp_min:
        return "supplementary", "R3"
    return "excluded", "R4"


def classify_tier(
    n_event,
    event_rate,
    *,
    main_min: int = TIER_MAIN_MIN_EVENTS,
    ext_min: int = TIER_EXT_MIN_EVENTS,
    supp_min: int = TIER_SUPP_MIN_EVENTS,
    rate_floor: float = EVENT_RATE_DOWNGRADE,
) -> tuple[str, str, list[str]]:
    """返回 (最终 tier, 基础 tier, 命中的规则码列表)。

    R5（event_rate < rate_floor）在基础档位上下调一级；``excluded`` 不再下调。
    event_rate 缺失（None/NaN）时不触发 R5。
    """
    tier, code = base_tier(n_event, main_min=main_min, ext_min=ext_min, supp_min=supp_min)
    hits = [code]
    base = tier
    rate = _as_float(event_rate)
    if rate is not None and rate < float(rate_floor):
        hits.append("R5")
        idx = TIER_ORDER.index(tier)
        tier = TIER_ORDER[min(idx + 1, len(TIER_ORDER) - 1)]
    return tier, base, hits


def degen_fold_indices(per_fold_events, *, max_events: int = DEGEN_FOLD_MAX_EVENTS) -> list[int]:
    """结构退化折（R7）：折内 val 事件数 <= max_events 的折下标（0-based）。

    折内事件数为 1 时 c-index 只能取精确 0.0/1.0；为 0 时 c-index 无定义。
    """
    return [i for i, v in enumerate(per_fold_events or []) if _as_int(v) <= max_events]


def epv_field_budget(per_fold_events, *, events_per_field: int = EPV_EVENTS_PER_FIELD) -> int:
    """R8：EPV 规则允许的最大字段数 = floor(最小折事件数 / 10)。"""
    values = [_as_int(v) for v in (per_fold_events or [])]
    if not values:
        return 0
    return int(min(values) // int(events_per_field))


def format_per_fold(per_fold_events) -> str:
    return PER_FOLD_SEP.join(str(_as_int(v)) for v in (per_fold_events or []))


def parse_per_fold(text) -> list[int]:
    text = str(text or "").strip()
    if not text:
        return []
    return [_as_int(part) for part in text.split(PER_FOLD_SEP) if part.strip() != ""]


def strict_landmark_events(per: pd.DataFrame, landmark_days) -> int:
    """候选口径②（严格 landmark）：#{event==1 且 ground_truth_time > T}。

    仅作为 D2 决策的候选数值记录在 profile JSON，**不写入 manifest**。
    """
    if per is None or per.empty or "event" not in per.columns:
        return 0
    event = pd.to_numeric(per.get("event"), errors="coerce")
    gt = pd.to_numeric(per.get("ground_truth_time"), errors="coerce")
    mask = (event == 1) & gt.notna() & (gt > float(landmark_days))
    return int(mask.sum())


def _as_int(value) -> int:
    try:
        if value is None:
            return 0
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value):
    try:
        if value is None:
            return None
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 输入读取
# ---------------------------------------------------------------------------


def study_name_for(dataset: str) -> str:
    """display 名 → splits 目录名：TCGA-BRCA→tcga_brca，TCGA_LIHC→tcga_lihc，MMRF→mmrf。"""
    return str(dataset).strip().lower().replace("-", "_")


def _split_index(path: Path) -> tuple[int, str]:
    match = SPLIT_RE.search(path.name)
    if match:
        return int(match.group(1)), path.name
    return 10**6, path.name


def fold_events_from_splits(split_dir: Path, per: pd.DataFrame) -> tuple[list[int], list[int], list[str]]:
    """按折序返回 (每折 val 事件数, 每折 val 患者数, 警告列表)。

    折序 = splits_{i}.csv 的 i 升序；事件判定用患者级 event 列（submitter_id 对齐）。
    """
    warnings: list[str] = []
    if not split_dir.is_dir():
        return [], [], [f"split_dir 缺失: {split_dir}"]
    files = sorted(split_dir.glob("splits_*.csv"), key=_split_index)
    if not files:
        return [], [], [f"split_dir 内无 splits_*.csv: {split_dir}"]

    event_by_case: dict[str, int] = {}
    if per is not None and not per.empty and "submitter_id" in per.columns:
        ev = pd.to_numeric(per.get("event"), errors="coerce")
        for case, val in zip(per["submitter_id"].astype(str), ev):
            event_by_case[case] = 1 if val == 1 else 0
    else:
        warnings.append("event_stats 缺失或缺少 submitter_id：每折事件数按 0 计")

    per_fold_events: list[int] = []
    per_fold_patients: list[int] = []
    for path in files:
        try:
            frame = pd.read_csv(path)
        except Exception as exc:  # pragma: no cover - 读取异常路径
            warnings.append(f"{path.name} 读取失败: {exc}")
            per_fold_events.append(0)
            per_fold_patients.append(0)
            continue
        column = "val" if "val" in frame.columns else frame.columns[min(1, len(frame.columns) - 1)]
        cases = [str(x) for x in frame[column].dropna().tolist()]
        unknown = [c for c in cases if c not in event_by_case]
        if unknown and event_by_case:
            warnings.append(f"{path.name}: {len(unknown)} 个 val 患者在 event_stats 中未找到")
        per_fold_patients.append(len(cases))
        per_fold_events.append(sum(event_by_case.get(c, 0) for c in cases))
    return per_fold_events, per_fold_patients, warnings


def split_case_ids(split_dir: Path) -> set[str]:
    """spilts 中出现的全部患者 id（train/val/test 并集）。"""
    ids: set[str] = set()
    if not split_dir.is_dir():
        return ids
    for path in sorted(split_dir.glob("splits_*.csv"), key=_split_index):
        try:
            frame = pd.read_csv(path)
        except Exception:  # pragma: no cover
            continue
        for column in frame.columns:
            ids.update(str(x) for x in frame[column].dropna().tolist())
    return ids


def load_event_summary(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["dataset", "n_patients", "n_event", "n_censored", "n_unknown", "event_rate"])
    return pd.read_csv(path)


def load_patient_events(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:  # pragma: no cover
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def build_dataset_record(
    dataset: str,
    *,
    project_root: Path,
    summary_row: dict | None,
    per: pd.DataFrame,
    split_dir: Path,
    landmark_times=LANDMARK_TIMES_DEFAULT,
) -> dict:
    warnings: list[str] = []
    n_patients = _as_int((summary_row or {}).get("n_patients"))
    n_event = _as_int((summary_row or {}).get("n_event"))
    event_rate = _as_float((summary_row or {}).get("event_rate"))
    if summary_row is None:
        warnings.append("event_summary.csv 中无该队列")

    per_fold_events, per_fold_patients, split_warnings = fold_events_from_splits(split_dir, per)
    warnings.extend(split_warnings)

    n_event_in_splits = int(sum(per_fold_events))
    if event_rate is None and n_patients:
        event_rate = n_event / float(n_patients)

    degen = degen_fold_indices(per_fold_events)
    epv_budget = epv_field_budget(per_fold_events)

    tier, tier_base, hits = classify_tier(n_event, event_rate)
    if degen:
        hits.append("R7")
    if epv_budget == 0 and per_fold_events:
        hits.append("R8")

    # --- D2 未确认：候选口径数值只进 profile，不进 manifest ---
    landmark_block = {
        "status": "todo_D2",
        "caliber": None,
        "manifest_columns": "effective_events_lm* 留空（TODO），待 D2 确认口径后回填",
        "current_implementation": {
            "mechanism": "mask_only",
            "excludes_patients": False,
            "changes_survival_endpoint": False,
            "note": (
                "现实现下 landmark 只把 t_hi>T 的字段取值置为缺失占位符，不改变患者集与生存终点，"
                "故事件的“实际生效数”等于原始 n_event_in_splits（见 src/discovery/landmark.py:1-12,120-132；"
                "src/time_stats.py:722-754；src/greedy/data.py:228-258）"
            ),
            "effective_events": {f"lm{tag}": n_event_in_splits for tag in landmark_times},
        },
        "candidates": {
            "strict_landmark_exclude_le_T": {
                "definition": "#{event==1 且 ground_truth_time > T}（排除 T 之前已发生事件/删失的患者）",
                "dataset_level": {
                    f"lm{tag}": strict_landmark_events(per, tag) for tag in landmark_times
                },
                "split_restricted": _strict_landmark_split_restricted(per, split_dir, landmark_times),
            },
            "mask_only_as_implemented": {
                "definition": "口径同现状：患者集不变，effective = n_event_in_splits",
                "dataset_level": {f"lm{tag}": n_event_in_splits for tag in landmark_times},
            },
        },
    }

    record = {
        "dataset": dataset,
        "study": study_name_for(dataset),
        "tier": tier,
        "tier_base": tier_base,
        "tier_label_zh": TIER_LABEL_ZH[tier],
        "provisional": True,
        "provisional_reason": "D1 门槛数值未确认（spec §4.2 照搬 event_impact_analysis 建议）",
        "n_patients": n_patients,
        "n_event": n_event,
        "n_censored": _as_int((summary_row or {}).get("n_censored")),
        "n_unknown": _as_int((summary_row or {}).get("n_unknown")),
        "event_rate": None if event_rate is None else round(event_rate, 6),
        "n_event_in_splits": n_event_in_splits,
        "n_folds": len(per_fold_events),
        "per_fold_events": per_fold_events,
        "per_fold_patients": per_fold_patients,
        "degen_folds": len(degen),
        "degen_fold_indices": degen,
        "degen_fold_definition": f"折内 val 事件数 <= {DEGEN_FOLD_MAX_EVENTS}（c-index 只能取 0.0/1.0 或无定义）",
        "epv_field_budget": epv_budget,
        "epv_definition": f"floor(min(每折事件数) / {EPV_EVENTS_PER_FIELD})：多字段实验允许的最大字段数（R8）",
        "rule_hits": list(hits),
        "rules": {
            "R1": f"n_event >= {TIER_MAIN_MIN_EVENTS} → 主集",
            "R2": f"{TIER_EXT_MIN_EVENTS} <= n_event < {TIER_MAIN_MIN_EVENTS} → 扩展集",
            "R3": f"{TIER_SUPP_MIN_EVENTS} <= n_event < {TIER_EXT_MIN_EVENTS} → 补充集",
            "R4": f"n_event < {TIER_SUPP_MIN_EVENTS} → 排除集",
            "R5": f"event_rate < {EVENT_RATE_DOWNGRADE} → 降一级",
            "R7": "退化折标注并降级（本步只做标注，降级在 S8/D5 逐项确认）",
            "R8": f"每折事件数 >= {EPV_EVENTS_PER_FIELD} x 字段数",
        },
        "landmark": landmark_block,
        "sources": {
            "event_summary": "rawdata_stats/_shared/event_summary.csv",
            "event_stats": f"rawdata_stats/{dataset}/event_stats.csv",
            "splits": str(_relative(split_dir, project_root)),
        },
        "warnings": warnings,
    }
    return record


def _strict_landmark_split_restricted(per: pd.DataFrame, split_dir: Path, landmark_times) -> dict:
    """严格口径下、限定在 splits 覆盖患者内的事件数（含每折）。"""
    ids = split_case_ids(split_dir)
    if per is None or per.empty or not ids or "submitter_id" not in per.columns:
        return {}
    subset = per[per["submitter_id"].astype(str).isin(ids)]
    out: dict[str, object] = {"n_patients": int(len(subset))}
    for tag in landmark_times:
        ev = pd.to_numeric(subset.get("event"), errors="coerce")
        gt = pd.to_numeric(subset.get("ground_truth_time"), errors="coerce")
        keep = gt > float(tag)
        out[f"lm{tag}"] = int(((ev == 1) & keep).sum())
        out[f"lm{tag}_n_at_risk"] = int((gt.notna() & keep).sum())
    return out


def _relative(path: Path, root: Path) -> Path:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return Path(path)


def manifest_row(record: dict) -> dict:
    """由 profile record 生成 manifest 行（列序固定，D2 未定的列留空）。"""
    hits = list(record["rule_hits"])
    notes = ["provisional(D1)"]
    if record["dataset"] == "MMRF":
        notes.append("口径待 D2")
    if "R5" in hits:
        notes.append(f"event_rate<{EVENT_RATE_DOWNGRADE} 降级 {record['tier_base']}->{record['tier']}")
    if "R7" in hits:
        notes.append(f"退化折 {record['degen_folds']} 个（折下标 {record['degen_fold_indices']}）")
    if "R8" in hits:
        notes.append(f"每折事件数 < {EPV_EVENTS_PER_FIELD}，EPV 字段预算 0，多字段实验不可行")
    elif record["epv_field_budget"]:
        notes.append(f"EPV 字段预算 {record['epv_field_budget']}")
    notes.append("effective_events_lm*: TODO(D2)")
    if record["warnings"]:
        notes.append("warnings=" + " / ".join(record["warnings"]))

    return {
        "dataset": record["dataset"],
        "tier": record["tier"],
        "n_patients": record["n_patients"],
        "n_event": record["n_event"],
        "event_rate": "" if record["event_rate"] is None else record["event_rate"],
        "per_fold_events": format_per_fold(record["per_fold_events"]),
        # D2 未确认 → 留空，见 note 的 TODO
        "effective_events_lm0": "",
        "effective_events_lm365": "",
        "effective_events_lm730": "",
        "degen_folds": record["degen_folds"],
        "rule_hits": ";".join(hits),
        "note": "; ".join(notes),
    }


def run(
    *,
    project_root: Path,
    out_dir: Path,
    datasets_json: Path | None = None,
    event_summary: Path | None = None,
    split_root: Path | None = None,
    rawdata_stats: Path | None = None,
    landmark_times=LANDMARK_TIMES_DEFAULT,
    quiet: bool = False,
) -> tuple[Path, Path]:
    project_root = Path(project_root)
    datasets_json = Path(datasets_json or project_root / "datasets.json")
    event_summary = Path(event_summary or project_root / "rawdata_stats/_shared/event_summary.csv")
    split_root = Path(split_root or project_root / "Clinic_Analyzer/data/splits/5foldcv")
    rawdata_stats = Path(rawdata_stats or project_root / "rawdata_stats")
    out_dir = Path(out_dir)

    registry = json.loads(Path(datasets_json).read_text(encoding="utf-8"))
    datasets = sorted(registry.keys()) if isinstance(registry, dict) else sorted(registry)

    summary = load_event_summary(event_summary)
    summary_by_dataset = {}
    if not summary.empty and "dataset" in summary.columns:
        for _, row in summary.iterrows():
            summary_by_dataset[str(row["dataset"])] = row.to_dict()

    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for dataset in datasets:
        per = load_patient_events(Path(rawdata_stats) / dataset / "event_stats.csv")
        record = build_dataset_record(
            dataset,
            project_root=project_root,
            summary_row=summary_by_dataset.get(dataset),
            per=per,
            split_dir=Path(split_root) / study_name_for(dataset),
            landmark_times=landmark_times,
        )
        profile_path = out_dir / f"{dataset}_profile.json"
        profile_path.write_text(
            json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        rows.append(manifest_row(record))
        if not quiet:
            print(
                f"[test_0] {dataset:12s} tier={record['tier']:13s} n_event={record['n_event']:4d} "
                f"per_fold={format_per_fold(record['per_fold_events']):>24s} degen={record['degen_folds']}"
            )

    frame = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
    manifest_path = out_dir / "manifest.csv"
    frame.to_csv(manifest_path, index=False, lineterminator="\n")

    counts = frame["tier"].value_counts().to_dict() if not frame.empty else {}
    if not quiet:
        print(f"[test_0] wrote {manifest_path} ({len(frame)} rows) tiers={counts}")
    return manifest_path, out_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test_0 实验可用数据集评估（只读，不训练）")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--out-dir", default=None, help="默认 {project_root}/results/Test_0_dataset_availability")
    parser.add_argument("--datasets-json", default=None)
    parser.add_argument("--event-summary", default=None)
    parser.add_argument("--split-root", default=None)
    parser.add_argument("--rawdata-stats", default=None)
    parser.add_argument("--landmark-times", default=",".join(LANDMARK_TIMES_DEFAULT))
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(args.project_root)
    out_dir = Path(args.out_dir) if args.out_dir else project_root / "results/Test_0_dataset_availability"
    landmark_times = tuple(t.strip() for t in str(args.landmark_times).split(",") if t.strip())
    run(
        project_root=project_root,
        out_dir=out_dir,
        datasets_json=args.datasets_json,
        event_summary=args.event_summary,
        split_root=args.split_root,
        rawdata_stats=args.rawdata_stats,
        landmark_times=landmark_times,
        quiet=args.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
