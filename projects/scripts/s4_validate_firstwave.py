"""S4 Test_2b 首波校验（只读，统一 python 3.13.12）。

1. --diff-cox    臂 A clinic_cox vs 旧 results/A_manual 表逐位 diff=0（硬条件 D3-3）
                 （只比较旧表有行的组合；无旧行可比的组合列出，不作数值判断）
2. --audit-prompts  控制变量审计：两臂 prompts.csv 字段表逐字核对（列集/列序、
                 患者行序、行数必须完全一致；差异只允许出现在单元格取值）
3. --compare-dirs  同环境重跑一致性（mlp det1 判据）：两个 run 目录的
                 val_result_fold*.csv 逐位比较

用法：
  python3 scripts/s4_validate_firstwave.py --diff-cox
  python3 scripts/s4_validate_firstwave.py --audit-prompts --limit 8
  python3 scripts/s4_validate_firstwave.py --compare-dirs DIR1 DIR2
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "A_pipeline"))

from common.paths import test_results_dir  # noqa: E402
from greedy.clinic import read_cindex  # noqa: E402
from greedy.data import display_to_study  # noqa: E402

OLD_ROOT = test_results_dir("Test_2b/arm_A")
NEW_ROOT = test_results_dir("Test_2b/arm_B")
OUTPUTS = PROJECT_ROOT / "outputs"

PAN_CANCER_SCHEMES = ["MULTISURV", "SURVPGC", "MMSURV", "INTEGRATIVE_DNN"]
HGCN_BINDING = {
    "TCGA-KIRC": "HGCN_KIRC",
    "TCGA_LIHC": "HGCN_LIHC",
    "TCGA-ESCA": "HGCN_ESCA",
    "TCGA-LUSC": "HGCN_LUSC",
    "TCGA-LUAD": "HGCN_LUAD",
    "TCGA-UCEC": "HGCN_UCEC",
}


def _schemes_for_dataset(dataset: str) -> list[str]:
    schemes = list(PAN_CANCER_SCHEMES)
    if dataset in HGCN_BINDING:
        schemes.append(HGCN_BINDING[dataset])
    return schemes


def _armA_run_dir(dataset: str, scheme: str, modality: str) -> Path:
    # 表目录名形如 "TCGA-BRCA[gdc]"（run_cindex_queue 用 f"{name}[{source}]" 作键）；
    # display_to_study 只认纯名。
    plain = dataset.split("[")[0]
    study = display_to_study(plain)
    return NEW_ROOT / "runs" / f"{study}__{scheme}__landmark_none" / modality


def cmd_diff_cox() -> int:
    checked, mismatch, missing_old, incomplete = [], [], [], []
    for table_dir in sorted((OLD_ROOT).iterdir()):
        if not table_dir.is_dir() or not table_dir.name.endswith("[gdc]"):
            continue
        dataset = table_dir.name
        table = table_dir / "cindex.csv"
        if not table.exists():
            continue
        old_rows = {}
        with table.open(newline="") as f:
            for r in csv.DictReader(f):
                old_rows[(r["scheme"], r["modality"])] = (r["val_c_index_mean"], r["val_c_index_std"])
        for scheme in _schemes_for_dataset(dataset):
            if (scheme, "clinic_cox") not in old_rows:
                missing_old.append((dataset, scheme))
                continue
            run_dir = _armA_run_dir(dataset, scheme, "clinic_cox")
            # 只读已完成 run（run.sh 成功后 touch .done），避免读到写了一半的 fold CSV。
            if not run_dir.is_dir() or not (run_dir / ".done").exists():
                incomplete.append((dataset, scheme))
                continue
            payload = read_cindex(run_dir)
            new_mean, new_std = (
                repr(payload["val_c_index_mean"]),
                repr(payload["val_c_index_std"]),
            )
            old_mean, old_std = old_rows[(scheme, "clinic_cox")]
            ok = (new_mean, new_std) == (old_mean, old_std)
            (checked if ok else mismatch).append(
                (dataset, scheme, old_mean, old_std, new_mean, new_std)
            )
    print(f"[validate] 臂 A clinic_cox vs 旧表: 已比 {len(checked) + len(mismatch)} 组合")
    print(f"  diff=0: {len(checked)}  |  不符: {len(mismatch)}  |  "
          f"run 未完成: {len(incomplete)}  |  旧表无行可比: {len(missing_old)}")
    for row in mismatch:
        print(f"  MISMATCH {row[0]} {row[1]}: old=({row[2]},{row[3]}) new=({row[4]},{row[5]})")
    for row in incomplete:
        print(f"  INCOMPLETE {row[0]} {row[1]}")
    if len(checked) >= 3:
        print("  抽查已比组合（前 8）:")
        for row in checked[:8]:
            print(f"    {row[0]} {row[1]}: mean={row[2]} std={row[3]}  diff=0")
    print(f"  无旧行可比组合数: {len(missing_old)}（SURVPGC/MMSURV 旧 A_manual 未跑的队列，"
          f"按 D3-3 归因：旧表无该行，非不一致）")
    return 1 if mismatch else 0


def _prompt_files(dataset: str, scheme: str) -> tuple[Path, Path] | None:
    arm_a = OUTPUTS / dataset / "A_manual" / scheme / "prompts.csv"
    arm_b = OUTPUTS / dataset / "A_manual" / scheme / "landmark_0" / "prompts.csv"
    if not arm_a.exists() or not arm_b.exists():
        return None
    return arm_a, arm_b


def cmd_audit_prompts(limit: int) -> int:
    import pandas as pd

    audited, failed = 0, 0
    datasets = sorted(
        p.name for p in OUTPUTS.iterdir() if p.is_dir() and p.name.startswith("TCGA")
    )
    for dataset in datasets:
        for scheme in _schemes_for_dataset(dataset):
            files = _prompt_files(dataset, scheme)
            if files is None:
                continue
            arm_a, arm_b = files
            df_a = pd.read_csv(arm_a, dtype=str)
            df_b = pd.read_csv(arm_b, dtype=str)
            problems = []
            if list(df_a.columns) != list(df_b.columns):
                problems.append("列集/列序不一致")
            if len(df_a) != len(df_b):
                problems.append(f"行数不一致 {len(df_a)} vs {len(df_b)}")
            elif not (df_a["patient_id"].astype(str).tolist() == df_b["patient_id"].astype(str).tolist()):
                problems.append("patient_id 行序不一致")
            changed = {}
            if not problems:
                for col in df_a.columns:
                    if col == "patient_id":
                        continue
                    n = int((df_a[col].fillna("") != df_b[col].fillna("")).sum())
                    if n:
                        changed[col] = n
            audited += 1
            if problems:
                failed += 1
                print(f"  FAIL {dataset} {scheme}: {problems}")
            else:
                print(f"  OK   {dataset} {scheme}: 列 {len(df_a.columns)} 同名同序, "
                      f"患者 {len(df_a)} 同行序; 取值变化列: {changed or '无'}")
            if audited >= limit:
                break
        if audited >= limit:
            break
    print(f"[validate] prompts 两臂审计: 抽查 {audited} 组, 失败 {failed}")
    return 1 if failed else 0


def cmd_compare_dirs(dir1: str, dir2: str) -> int:
    import pandas as pd

    d1, d2 = Path(dir1), Path(dir2)
    files1 = sorted(d1.glob("val_result_fold*.csv"))
    files2 = sorted(d2.glob("val_result_fold*.csv"))
    if len(files1) != len(files2):
        print(f"fold 文件数不一致: {len(files1)} vs {len(files2)}")
        return 1
    cindex_ok = True
    for f1, f2 in zip(files1, files2):
        df1 = pd.read_csv(f1)
        df2 = pd.read_csv(f2)
        cidx = (
            "val_cindex" in df1.columns
            and "val_cindex" in df2.columns
            and df1["val_cindex"].iloc[-1] == df2["val_cindex"].iloc[-1]
        )
        frame = df1.equals(df2)
        cindex_ok &= cidx
        print(f"  {f1.name}: val_cindex逐位一致={cidx}, 全帧一致={frame}")
    print(f"[validate] 同环境重跑: val_cindex {'ALL MATCH' if cindex_ok else 'MISMATCH'} "
          f"({len(files1)} folds)")
    return 0 if cindex_ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff-cox", action="store_true")
    parser.add_argument("--audit-prompts", action="store_true")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--compare-dirs", nargs=2, metavar=("DIR1", "DIR2"), default=None)
    args = parser.parse_args(argv)
    if args.compare_dirs:
        raise SystemExit(cmd_compare_dirs(args.compare_dirs[0], args.compare_dirs[1]))
    if args.audit_prompts:
        raise SystemExit(cmd_audit_prompts(args.limit))
    if args.diff_cox or True:
        raise SystemExit(cmd_diff_cox())


if __name__ == "__main__":
    main()
