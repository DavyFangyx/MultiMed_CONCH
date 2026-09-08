#!/usr/bin/env python3
"""Overlay paper-scheme c-index reference lines on greedy growth curves.

Usage:
conda activate conch
python results_display/scripts/FigA_Other_Paper_Works.py \
    --dataset all \
    --landmark_time 0
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from collect_common import (
    PROJECT_ROOT,
    add_common_collect_args,
    collect_named_files,
    compose_collage,
    print_collect_summary,
    resolve_collect_context,
)
from common.datasets import DATASET_ALIASES, canonical_dataset_name
from common.paths import dataset_greedy_results_dir


CSV_STEM = "cindex_by_n_fields"
SOURCE_COLUMNS = ["step", "n_fields", "added", "c_index_mean", "c_index_std", "c_index_se", "subset"]
DEFAULT_MODALITY = "mlp_clinic_flatten"
DEFAULT_TEMPLATE_DIR = PROJECT_ROOT / "A_pipeline" / "templates"
DEFAULT_PAPER_RESULTS_ROOT = PROJECT_ROOT / "results" / "A_manual"
FIG_DIRNAME = "FigA_Other_Paper_Works"

PAPER_SCHEMES = [
    "MULTISURV",
    "SURVPGC",
    "MMSURV",
    "INTEGRATIVE_DNN",
    "HGCN_KIRC",
    "HGCN_LIHC",
    "HGCN_ESCA",
    "HGCN_LUSC",
    "HGCN_LUAD",
    "HGCN_UCEC",
]
PAPER_COLORS = {
    "MULTISURV": "#d62728",
    "SURVPGC": "#2ca02c",
    "MMSURV": "#ff7f0e",
    "INTEGRATIVE_DNN": "#9467bd",
    "HGCN_KIRC": "#8c564b",
    "HGCN_LIHC": "#e377c2",
    "HGCN_ESCA": "#7f7f7f",
    "HGCN_LUSC": "#bcbd22",
    "HGCN_LUAD": "#17becf",
    "HGCN_UCEC": "#1f77b4",
}
OVERLAY_COLUMNS = [
    "dataset",
    "encoding",
    "landmark_tag",
    "modality",
    "scheme",
    "n_fields",
    "c_index_mean",
    "c_index_std",
    "source",
    "status",
    "fields",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Redraw greedy c-index growth curves for TCGA datasets and overlay "
            "paper-scheme field-combination c-index as colored reference lines."
        )
    )
    add_common_collect_args(
        parser,
        experiment="greedy",
        extra_help="Override default results_display/FigA_Other_Paper_Works/{encoding}/{landmark_tag}",
    )
    parser.add_argument(
        "--modality",
        default=DEFAULT_MODALITY,
        help=f"Modality used for paper-scheme reference lines. Default: {DEFAULT_MODALITY}.",
    )
    parser.add_argument(
        "--paper_results_root",
        default=str(DEFAULT_PAPER_RESULTS_ROOT),
        help="Root of paper-scheme cindex.csv files. Default: results/A_manual.",
    )
    parser.add_argument(
        "--template_dir",
        default=str(DEFAULT_TEMPLATE_DIR),
        help="Paper-scheme fields.json directory. Default: A_pipeline/templates.",
    )
    return parser


def locate_dataset(dataset: str, encoding: str, landmark_tag: str, experiment: str = "") -> dict:
    return {
        "src_dir": dataset_greedy_results_dir(
            dataset,
            encoding=encoding,
            landmark_tag=landmark_tag,
            experiment=experiment,
        )
    }


def is_tcga_dataset(name: str) -> bool:
    return str(name).upper().startswith("TCGA")


def figa_out_dir(encoding: str, landmark_tag: str, override: str | None = None) -> Path:
    if override:
        return Path(override)
    return PROJECT_ROOT / "results_display" / FIG_DIRNAME / encoding / landmark_tag


def strip_dataset_source_suffix(name: str) -> str:
    text = str(name).strip()
    if text.endswith("]") and "[" in text:
        return text[: text.rfind("[")].strip()
    return text


def canonicalize_dataset(name: str, datasets: dict | None = None) -> str:
    canonical = canonical_dataset_name(strip_dataset_source_suffix(name), datasets or {})
    return DATASET_ALIASES.get(canonical, canonical)


def load_paper_schemes(template_dir: Path) -> dict[str, dict]:
    schemes: dict[str, dict] = {}
    for name in PAPER_SCHEMES:
        path = template_dir / name / "fields.json"
        if not path.exists():
            raise FileNotFoundError(f"missing paper scheme fields: {path}")
        cfg = json.loads(path.read_text(encoding="utf-8"))
        fields = [str(item).strip() for item in cfg.get("fields") or [] if str(item).strip()]
        raw_datasets = cfg.get("datasets")
        bound = None
        if raw_datasets is not None:
            bound = []
            values = [raw_datasets] if isinstance(raw_datasets, str) else list(raw_datasets)
            for item in values:
                item = str(item).strip()
                if not item:
                    continue
                canonical = DATASET_ALIASES.get(item, item)
                if canonical not in bound:
                    bound.append(canonical)
        schemes[name] = {"fields": fields, "datasets": bound, "source": str(path)}
    return schemes


def scheme_applies(scheme_cfg: dict, dataset: str, datasets: dict | None = None) -> bool:
    bound = scheme_cfg.get("datasets")
    if bound is None:
        return True
    return canonicalize_dataset(dataset, datasets) in bound


def load_paper_cindex_rows(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not root.exists():
        return rows
    for csv_path in sorted(p for p in root.glob("*/cindex.csv") if "runs" not in p.parts):
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            rows.extend(list(csv.DictReader(handle)))
    return rows


def paper_lookup(rows: list[dict[str, str]], *, encoding: str, modality: str) -> dict[tuple[str, str], dict]:
    table: dict[tuple[str, str], dict] = {}
    for row in rows:
        if str(row.get("encoding") or "").strip() != encoding:
            continue
        if str(row.get("modality") or "").strip() != modality:
            continue
        dataset = canonicalize_dataset(str(row.get("dataset") or "").strip())
        scheme = str(row.get("scheme") or "").strip()
        if not dataset or not scheme:
            continue
        mean_raw = row.get("val_c_index_mean") or row.get("test_c_index_mean") or ""
        if mean_raw == "":
            continue
        std_raw = row.get("val_c_index_std") or row.get("test_c_index_std") or "0"
        table[(dataset, scheme)] = {
            "c_index_mean": float(mean_raw),
            "c_index_std": float(std_raw or 0.0),
            "source": row.get("source") or "val",
        }
    return table


def paper_refs_for_dataset(
    dataset: str,
    *,
    schemes: dict[str, dict],
    lookup: dict[tuple[str, str], dict],
    datasets: dict | None = None,
) -> list[dict]:
    refs: list[dict] = []
    for name in PAPER_SCHEMES:
        cfg = schemes[name]
        if not scheme_applies(cfg, dataset, datasets):
            continue
        fields = list(cfg.get("fields") or [])
        hit = lookup.get((dataset, name))
        refs.append(
            {
                "scheme": name,
                "n_fields": len(fields),
                "fields": " | ".join(fields),
                "c_index_mean": None if hit is None else hit["c_index_mean"],
                "c_index_std": None if hit is None else hit["c_index_std"],
                "source": "" if hit is None else hit["source"],
                "status": "ok" if hit is not None else "missing_cindex",
            }
        )
    return refs


def plot_dataset_curve(
    path: Path,
    *,
    dataset: str,
    rows: list[dict],
    refs: list[dict],
    encoding: str,
    landmark_tag: str,
) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [int(row["n_fields"]) for row in rows]
    ys = [float(row["c_index_mean"]) for row in rows]
    stds = [float(row.get("c_index_std") or 0.0) for row in rows]
    drawn_refs = [ref for ref in refs if ref["c_index_mean"] is not None]

    xmin = min(xs) if xs else 1
    xmax = max(xs) if xs else 1
    if drawn_refs:
        xmax = max(xmax, max(int(ref["n_fields"] or 1) for ref in drawn_refs))
    xpad = max(0.4, 0.08 * max(xmax - xmin, 1))

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.plot(xs, ys, marker="o", linewidth=1.8, color="#1f4e79", label="greedy")
    if any(std > 0 for std in stds):
        lo = [y - std for y, std in zip(ys, stds)]
        hi = [y + std for y, std in zip(ys, stds)]
        ax.fill_between(xs, lo, hi, color="#1f4e79", alpha=0.12)
    for ref in drawn_refs:
        ax.axhline(
            float(ref["c_index_mean"]),
            color=PAPER_COLORS.get(ref["scheme"], "#333333"),
            linestyle="--",
            linewidth=1.5,
            label=ref["scheme"],
        )
    ax.set_xlim(xmin - xpad, xmax + xpad)
    y_all = list(ys) + [float(ref["c_index_mean"]) for ref in drawn_refs]
    if y_all:
        ymin, ymax = min(y_all), max(y_all)
        ypad = max(0.02, 0.08 * max(ymax - ymin, 0.05))
        ax.set_ylim(ymin - ypad, ymax + ypad)
    ax.set_xlabel("number of selected fields")
    ax.set_ylabel("5-fold mean c-index")
    ax.set_title(f"{dataset}  |  {encoding} / {landmark_tag}")
    ax.grid(True, alpha=0.3)
    handles, labels = ax.get_legend_handles_labels()
    seen: set[str] = set()
    uniq_handles = []
    uniq_labels = []
    for handle, label in zip(handles, labels):
        if label in seen:
            continue
        seen.add(label)
        uniq_handles.append(handle)
        uniq_labels.append(label)
    if uniq_handles:
        ax.legend(uniq_handles, uniq_labels, frameon=False, loc="best", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_rows_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    encoding, landmark_tag, experiment, names, _ignored_out = resolve_collect_context(args)
    names = [name for name in names if is_tcga_dataset(name)]
    if not names:
        raise ValueError("no TCGA datasets resolved from --dataset")
    out_dir = figa_out_dir(encoding, landmark_tag, args.out)
    per_dir = out_dir / "per_dataset"
    datasets = json.loads(Path(args.datasets_config).read_text(encoding="utf-8"))
    schemes = load_paper_schemes(Path(args.template_dir))
    lookup = paper_lookup(
        load_paper_cindex_rows(Path(args.paper_results_root)),
        encoding=encoding,
        modality=args.modality,
    )

    def _locate(dataset, encoding, landmark_tag):
        return locate_dataset(dataset, encoding, landmark_tag, experiment=getattr(args, "experiment", ""))

    records, missing = collect_named_files(
        names,
        encoding=encoding,
        landmark_tag=landmark_tag,
        locate=_locate,
        required=[f"{CSV_STEM}.csv"],
        csv_key=f"{CSV_STEM}.csv",
        csv_columns=SOURCE_COLUMNS,
    )

    overlay_rows: list[dict] = []
    collage_records: list[dict] = []
    wrote: list[Path] = []
    skipped: list[Path] = []

    for record in records:
        dataset = record["dataset"]
        refs = paper_refs_for_dataset(dataset, schemes=schemes, lookup=lookup, datasets=datasets)
        png_path = per_dir / f"{dataset}.png"
        plot_dataset_curve(
            png_path,
            dataset=dataset,
            rows=record["rows"],
            refs=refs,
            encoding=encoding,
            landmark_tag=landmark_tag,
        )
        record["png_path"] = png_path
        collage_records.append(record)
        wrote.append(png_path)
        for ref in refs:
            overlay_rows.append(
                {
                    "dataset": dataset,
                    "encoding": encoding,
                    "landmark_tag": landmark_tag,
                    "modality": args.modality,
                    "scheme": ref["scheme"],
                    "n_fields": ref["n_fields"],
                    "c_index_mean": "" if ref["c_index_mean"] is None else ref["c_index_mean"],
                    "c_index_std": "" if ref["c_index_std"] is None else ref["c_index_std"],
                    "source": ref["source"],
                    "status": ref["status"],
                    "fields": ref["fields"],
                }
            )

    overlay_csv = out_dir / "paper_reference_cindex.csv"
    collage_png = out_dir / "cindex_by_n_fields.png"
    missing_csv = out_dir / "missing.csv"

    if overlay_rows:
        write_rows_csv(overlay_csv, overlay_rows, OVERLAY_COLUMNS)
        wrote.append(overlay_csv)
    else:
        skipped.append(overlay_csv)

    if collage_records:
        compose_collage(
            collage_records,
            collage_png,
            heading=f"FigA other paper works  |  {encoding} / {landmark_tag}  |  {args.modality}",
            cols=args.cols,
        )
        wrote.append(collage_png)
    else:
        skipped.append(collage_png)
        print("no matching greedy CSV files; skip FigA overlay")

    if missing:
        write_rows_csv(
            missing_csv,
            [
                {
                    "dataset": row["dataset"],
                    "encoding": row["encoding"],
                    "landmark_tag": row["landmark_tag"],
                    "reason": row["reason"],
                }
                for row in missing
            ],
            ["dataset", "encoding", "landmark_tag", "reason"],
        )
        wrote.append(missing_csv)
    elif missing_csv.exists():
        missing_csv.unlink()

    print_collect_summary(names=names, records=records, missing=missing, wrote=wrote, skipped=skipped)
    n_ok = sum(1 for row in overlay_rows if row["status"] == "ok")
    n_miss = sum(1 for row in overlay_rows if row["status"] != "ok")
    print(f"  paper refs drawn: {n_ok}")
    print(f"  paper refs missing cindex: {n_miss}")
    print(f"  out_dir: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
