"""Test_3 两臂对照报表: 贪婪最优组合 vs 各工作组合（字段轴链收口, spec §7.2 T31）。

两臂（全部 landmark_0 × mlp_clinic_flatten × seed 0 × 5 折, bank 切片链路）:
  臂 B = 工作完整组合 × bank 模板（自定义方案 Test_3_{work}_{dataset}）
  臂 C = 贪婪最优组合 × bank 模板（自定义方案 Test_3_greedy_{dataset}, field 取搜索 result.json;
        其 c-index 即搜索 best_cv_c_mean, 同嵌入同模型同折同 seed）

输出:
  * results/Test_3_greedy_vs_works/compare/{dataset}__{work}.json  逐 (dataset, work) 明细
  * results/Test_3_greedy_vs_works/two_arm.csv                    两臂 c-index 总表
  * results/Test_3_greedy_vs_works/missed_fields.csv              遗漏字段清单(C \\ 工作组合)
  头条 Δc = C − B（编码、模型、划分全同, 唯一差异 = 字段集）。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import Test_3_common as C  # noqa: E402
from common.paths import test_results_dir  # noqa: E402

A_TEMPLATES = ROOT / "templates" / "manual_schemes"
ARM_B_RESULTS = test_results_dir("Test_2b/arm_B")  # 臂 B 汇总表根（Test_3_* 行所在）
OUT_ROOT = C.OUT_ROOT
DISPLAY_ROOT = ROOT / "results_display" / "Test_3_greedy_vs_works"
HEADLINE_MODALITY = C.ANALYZER                      # mlp_clinic_flatten（E2 唯一搜索目标模型）


class MissingArm(RuntimeError):
    pass


def load_fields(scheme: str) -> list[str]:
    path = A_TEMPLATES / scheme / "fields.json"
    if not path.exists():
        raise MissingArm(f"方案不存在: {scheme}")
    return [str(f).strip() for f in json.loads(path.read_text(encoding="utf-8")).get("fields", [])]


def bank_sentences(dataset: str, landmark_tag: str = f"landmark_{C.LANDMARK_TIME}") -> dict[str, str]:
    path = ROOT / "templates" / "field_bank" / dataset / landmark_tag / "FIELD_BANK.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        sentence = str(row.get("template", "") or "").strip()
        if sentence:
            out[str(row["field"]).strip()] = sentence
    return out


def rows_for(dataset: str, scheme: str) -> pd.DataFrame:
    path = ARM_B_RESULTS / f"{dataset}[gdc]" / "cindex.csv"
    if not path.exists():
        raise MissingArm(f"缺 cindex 表: {path}")
    df = pd.read_csv(path)
    mask = df["scheme"] == f"{scheme}__landmark_0"
    if not mask.any():
        raise MissingArm(f"表内无 {scheme}__landmark_0 行: {path}")
    return df[mask]


def cindex_by_modality(rows: pd.DataFrame) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for _, row in rows.iterrows():
        modality = str(row.get("modality", ""))
        out[modality] = {
            "c": float(row["val_c_index_mean"]),
            "std": float(row["val_c_index_std"]),
        }
    return out


def compare(dataset: str, work: str, name_b: str | None = None, name_c: str | None = None) -> dict:
    name_b = name_b or C.b_scheme_name(work, dataset)
    name_c = name_c or C.c_scheme_name(dataset)
    b = cindex_by_modality(rows_for(dataset, name_b))
    c = cindex_by_modality(rows_for(dataset, name_c))
    work_fields = load_fields(name_b)
    c_fields = load_fields(name_c)
    sentences = bank_sentences(dataset)
    missed = sorted(set(c_fields) - set(work_fields))
    report = {
        "dataset": dataset, "work": work,
        "scheme_b": name_b, "scheme_c": name_c,
        "n_fields_work": len(work_fields), "n_fields_greedy": len(c_fields),
        "n_missed": len(missed),
        "missed_fields": missed,
        "missed_fields_semantics": {field: sentences.get(field, "") for field in missed},
        "per_modality": {},
    }
    common = sorted(set(c) & set(b))
    for modality in common:
        report["per_modality"][modality] = {
            "B": b[modality], "C": c[modality],
            "delta_C_minus_B": round(c[modality]["c"] - b[modality]["c"], 6),
        }
    if HEADLINE_MODALITY not in report["per_modality"]:
        raise MissingArm(f"{dataset}/{work}: 两臂缺 {HEADLINE_MODALITY}（B={sorted(b)} C={sorted(c)}）")
    return report


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def batch(datasets: list[str]) -> dict:
    pairs = C.work_pairs(datasets)
    table_rows: list[dict] = []
    missed_rows: list[dict] = []
    pending: list[str] = []
    for dataset, work in pairs:
        try:
            report = compare(dataset, work)
        except MissingArm as exc:
            pending.append(f"{dataset}/{work}: {exc}")
            continue
        per = report["per_modality"][HEADLINE_MODALITY]
        row = {
            "dataset": dataset, "work": work,
            "n_fields_work": report["n_fields_work"], "n_fields_greedy": report["n_fields_greedy"],
            "B_c": per["B"]["c"], "B_std": per["B"]["std"],
            "C_c": per["C"]["c"], "C_std": per["C"]["std"],
            "delta_C_minus_B": per["delta_C_minus_B"],
            "n_missed": report["n_missed"],
        }
        table_rows.append(row)
        for field in report["missed_fields"]:
            missed_rows.append({
                "dataset": dataset, "work": work, "field": field,
                "bank_sentence": report["missed_fields_semantics"].get(field, ""),
                "in_work": 0,
            })
        out = OUT_ROOT / "compare" / f"{dataset}__{work}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    table_fields = ["dataset", "work", "n_fields_work", "n_fields_greedy",
                    "B_c", "B_std", "C_c", "C_std",
                    "delta_C_minus_B", "n_missed"]
    _write_csv(OUT_ROOT / "two_arm.csv", table_rows, table_fields)
    _write_csv(OUT_ROOT / "missed_fields.csv", missed_rows,
               ["dataset", "work", "field", "bank_sentence", "in_work"])
    # 展示副本（results_display/ 为展示层，不参与提交）
    DISPLAY_ROOT.mkdir(parents=True, exist_ok=True)
    (DISPLAY_ROOT / "two_arm.csv").write_text(
        (OUT_ROOT / "two_arm.csv").read_text(encoding="utf-8"), encoding="utf-8")
    (DISPLAY_ROOT / "missed_fields.csv").write_text(
        (OUT_ROOT / "missed_fields.csv").read_text(encoding="utf-8"), encoding="utf-8")
    figure = _plot_delta(pd.DataFrame(table_rows), DISPLAY_ROOT) if table_rows else None
    return {"pairs": len(pairs), "done": len(table_rows), "pending": pending,
            "table": OUT_ROOT / "two_arm.csv", "missed": OUT_ROOT / "missed_fields.csv",
            "figure": figure}


def _plot_delta(df: pd.DataFrame, display_root: Path) -> Path | None:
    """Δc 图（spec §7.3）：左 = 每数据集均值 Δc（头条 C−B），右 = Δc vs 遗漏字段数。"""
    if df.empty:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # pragma: no cover - 无 matplotlib 时不阻塞总表
        return None
    display_root.mkdir(parents=True, exist_ok=True)
    per_dataset = df.groupby("dataset")["delta_C_minus_B"].mean()
    per_dataset = per_dataset.sort_values()
    fig, axes = plt.subplots(1, 2, figsize=(12, 0.45 * len(per_dataset) + 2.4))
    y = range(len(per_dataset))
    axes[0].barh(list(y), per_dataset.values, height=0.36,
                 color="#c0504d", label="Δc = C − B (headline)")
    axes[0].axvline(0.0, color="black", linewidth=0.8)
    axes[0].set_yticks(list(y), per_dataset.index, fontsize=7)
    axes[0].set_xlabel("mean Δc over works")
    axes[0].legend(fontsize=7)
    axes[0].set_title("Test_3 two-arm Δc (mean over works per dataset)", fontsize=9)
    axes[1].scatter(df["n_missed"], df["delta_C_minus_B"], s=14, color="#c0504d")
    axes[1].axhline(0.0, color="black", linewidth=0.8)
    axes[1].set_xlabel("missed fields |C \\ work|")
    axes[1].set_ylabel("Δc = C − B")
    axes[1].set_title("missed fields vs field-axis gain", fontsize=9)
    fig.tight_layout()
    out = display_root / "two_arm_delta.png"
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def _summary(table_path: Path) -> None:
    df = pd.read_csv(table_path)
    if df.empty:
        print("[test_3][compare] 总表为空")
        return
    delta = df["delta_C_minus_B"]
    print(f"[test_3][compare] n={len(df)}  Δc=C−B 均值 {delta.mean():+.4f} "
          f"中位 {delta.median():+.4f}  正比例 {(delta > 0).mean():.1%}")
    per_dataset = df.groupby("dataset")["delta_C_minus_B"].mean().sort_values(ascending=False)
    for dataset, value in per_dataset.items():
        print(f"[test_3][compare]   {dataset:12s} meanΔc={value:+.4f}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Test_3 贪婪 vs 工作 两臂对照")
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--work", default=None, help="工作方案名(如 MULTISURV); 与 --dataset 单对模式")
    parser.add_argument("--all", action="store_true", help="批模式: 全部主集 × 全部工作组合")
    parser.add_argument("--name-b", default=None)
    parser.add_argument("--name-c", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    if args.all or not (args.dataset and args.work):
        datasets = [args.dataset] if args.dataset and not args.all else C.main_datasets()
        result = batch(datasets)
        print(f"[test_3][compare] pairs={result['pairs']} done={result['done']} "
              f"pending={len(result['pending'])}")
        for item in result["pending"][:20]:
            print(f"[test_3][compare]   pending: {item}")
        _summary(result["table"])
        print(f"[test_3][compare] 写 {result['table']} / {result['missed']}")
        return

    report = compare(args.dataset, args.work, args.name_b, args.name_c)
    out = Path(args.out) if args.out else OUT_ROOT / "compare" / f"{args.dataset}__{args.work}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[test_3][compare] 写 {out}")


if __name__ == "__main__":
    main()
