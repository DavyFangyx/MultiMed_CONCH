"""验收:landmark-first stats 的 coverage 与 t0 臂 field bank .pt mask 逐字段比对。

口径:outputs/{ds}/field_bank/prompt/landmark_0/ 的 field_index.json 给出字段列序,
embeddings/pt/*.pt 的 mask bool [n_fields] 是 t0 臂训练时逐患者逐字段的有效性标记;
rawdata_stats/{ds}/landmark_0/field_stats.csv 的 coverage 必须与之一致(tol 1e-5)。

用法(需 torch 环境):/data/fangyuxuan/miniconda3/envs/conch/bin/python scripts/validate_t0stats_vs_masks.py [--dataset all|name] [--tol 1e-5]
任何不一致 exit 1。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
SRC = PROJECT_ROOT / "src"

for path in (REPO_ROOT, SRC):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def load_mask_coverage(dataset: str) -> tuple[list[str], dict[str, float], int]:
    """返回 (fields, field->mask_mean, n_patients)。"""
    import torch

    bank = Path("outputs") / dataset / "field_bank" / "prompt" / "landmark_0"
    field_index = bank / "field_index.json"
    pt_dir = bank / "embeddings" / "pt"
    if not field_index.exists() or not pt_dir.is_dir():
        raise FileNotFoundError(f"{dataset}: 缺少 field_index.json 或 embeddings/pt")
    fields = json.loads(field_index.read_text(encoding="utf-8"))["fields"]
    n_fields = len(fields)
    totals = torch.zeros(n_fields, dtype=torch.float64)
    n_patients = 0
    for pt_path in sorted(pt_dir.glob("*.pt")):
        payload = torch.load(pt_path, map_location="cpu", weights_only=False)
        totals += payload["mask"].bool().float()
        n_patients += 1
    coverage = {field: float(totals[i] / n_patients) for i, field in enumerate(fields)}
    return fields, coverage, n_patients


def load_stats_coverage(dataset: str) -> dict[str, float]:
    stats_path = Path("rawdata_stats") / dataset / "landmark_0" / "field_stats.csv"
    if not stats_path.exists():
        raise FileNotFoundError(f"{dataset}: 缺少 {stats_path}")
    out = {}
    with stats_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            out[str(row["field_path"])] = float(row["coverage"])
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="all")
    parser.add_argument("--tol", type=float, default=1e-5)
    args = parser.parse_args(argv)

    bank_dirs = sorted(Path("outputs").glob("*/field_bank/prompt/landmark_0"))
    if args.dataset not in {"all", ""}:
        bank_dirs = [p for p in bank_dirs if p.parts[1] == args.dataset]

    failed = 0
    checked = 0
    for bank_dir in bank_dirs:
        dataset = bank_dir.parts[1]
        try:
            fields, mask_cov, n_patients = load_mask_coverage(dataset)
            stats_cov = load_stats_coverage(dataset)
        except FileNotFoundError as exc:
            print(f"⚠️  跳过 {dataset}: {exc}")
            continue
        checked += 1
        mismatches = []
        max_diff = 0.0
        for field in fields:
            mask_val = mask_cov.get(field, 0.0)
            stats_val = stats_cov.get(field)
            if stats_val is None:
                mismatches.append((field, "missing_in_stats"))
                continue
            diff = abs(mask_val - stats_val)
            max_diff = max(max_diff, diff)
            if diff > args.tol:
                mismatches.append((field, f"mask={mask_val:.6f} stats={stats_val:.6f} diff={diff:.6f}"))
        status = "PASS" if not mismatches else "FAIL"
        if mismatches:
            failed += 1
        print(
            f"[{status}] {dataset:12s} n_patients={n_patients:5d} n_fields={len(fields):3d} "
            f"max_abs_diff={max_diff:.2e} n_mismatch={len(mismatches)}"
        )
        for field, detail in mismatches[:10]:
            print(f"    - {field}: {detail}")

    print(f"datasets checked={checked} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
