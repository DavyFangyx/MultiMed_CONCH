"""本地派生 slide 级 label metadata(多模态 WSI filter 用)。

背景:Clinic_Analyzer 本地 metadata 是 case 级(一行一 case,slide_id 为合成名
"{case_id}.svs"),而 WSI P 特征文件是 slide 级命名(TCGA-XX-XXXX-01Z-00-DX1.<hash>.pt),
WSI filter 按 slide_id 匹配 → kept=0(多模态 conf 被 park 的直接原因)。

派生规则与 PGC 自己的做法等价(pipeline.py::generate_metadata_for_study):
  1. slide 清单 = 枚举 SurvPGC_Workspace/{study}/P/uni_v1/*.pt 的 stem;
     slide_id = stem + ".svs";case_id = stem 前 12 位(TCGA barcode)。
  2. 按 case_id 左连接本地 case 级 metadata,取 label 各列;case 不在本地表的
     slide 丢弃(P 目录比旧 metadata 新时会出现,如 kirc)。
  3. rna_file_name 置空(survgc_f/survpgc_f 训练不使用该列)。

输出 metadata_slide/{study}.csv,与 case 级表分离存放;多模态 conf 解 park 时
显式设置 LABEL_FILE_PATH 指向这里即可(registry 默认仍用 case 级表,clinic-only
链路不受 slide 级行数影响)。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SURVPGC_ROOT = Path("/data/fangyuxuan/projects/medical_dl/SurvPGC_github_init")
DEFAULT_LABEL_ROOT = PROJECT_ROOT / "Clinic_Analyzer" / "data" / "datasets_csv" / "metadata"
DEFAULT_OUT_ROOT = PROJECT_ROOT / "Clinic_Analyzer" / "data" / "datasets_csv" / "metadata_slide"
MULTIMODAL_STUDIES = ("tcga_brca", "tcga_coad", "tcga_kirc", "tcga_kirp", "tcga_lihc")


def build_slide_table(
    study: str,
    *,
    survpgc_root: Path = DEFAULT_SURVPGC_ROOT,
    label_root: Path = DEFAULT_LABEL_ROOT,
) -> tuple[pd.DataFrame, dict]:
    p_dir = survpgc_root / "SurvPGC_Workspace" / study / "P" / "uni_v1"
    if not p_dir.is_dir():
        raise FileNotFoundError(f"P 特征目录不存在: {p_dir}")
    slides = sorted(pt.stem for pt in p_dir.glob("*.pt"))
    if not slides:
        raise FileNotFoundError(f"P 特征目录为空: {p_dir}")

    label_file = label_root / f"{study}.csv"
    if not label_file.exists():
        raise FileNotFoundError(f"case 级 label 不存在: {label_file}")
    case_df = pd.read_csv(label_file)

    rows = []
    for stem in slides:
        case_id = stem[:12]
        matched = case_df[case_df["case_id"].astype(str).str.upper() == case_id.upper()]
        if matched.empty:
            continue
        first = matched.iloc[0]
        rows.append(
            {
                "case_id": case_id,
                "slide_id": f"{stem}.svs",
                "age": first.get("age"),
                "site": first.get("site", case_id.split("-")[1] if "-" in case_id else ""),
                "survival_months": first.get("survival_months"),
                "censorship": first.get("censorship"),
                "is_female": first.get("is_female"),
                "oncotree_code": first.get("oncotree_code"),
                "rna_file_name": "",  # survgc_f/survpgc_f 不使用;hgcn native 需要时再回填
            }
        )
    table = pd.DataFrame(rows)
    stats = {
        "study": study,
        "n_slides_in_P": len(slides),
        "n_rows_out": len(table),
        "n_slides_dropped": len(slides) - len(table),
        "n_cases": table["case_id"].nunique() if len(table) else 0,
    }
    return table, stats


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="派生 slide 级 label metadata(多模态 WSI filter 用)")
    parser.add_argument(
        "--study",
        default=",".join(MULTIMODAL_STUDIES),
        help="study 列表,逗号分隔(默认多模态 5 个)",
    )
    parser.add_argument("--survpgc_root", default=str(DEFAULT_SURVPGC_ROOT))
    parser.add_argument("--label_root", default=str(DEFAULT_LABEL_ROOT))
    parser.add_argument("--out_root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--dry_run", action="store_true", help="只统计,不写文件")
    args = parser.parse_args(argv)

    studies = [name.strip() for name in args.study.split(",") if name.strip()]
    all_stats = []
    for study in studies:
        table, stats = build_slide_table(
            study,
            survpgc_root=Path(args.survpgc_root),
            label_root=Path(args.label_root),
        )
        all_stats.append(stats)
        out_dir = Path(args.out_root)
        out_file = out_dir / f"{study}.csv"
        if not args.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            table.to_csv(out_file, index=False)
        print(
            f"{study}: P 幻灯片 {stats['n_slides_in_P']} -> 输出 {stats['n_rows_out']} 行"
            f"(丢弃 {stats['n_slides_dropped']}, case {stats['n_cases']})"
            + ("" if args.dry_run else f" -> {out_file}")
        )


if __name__ == "__main__":
    main()
