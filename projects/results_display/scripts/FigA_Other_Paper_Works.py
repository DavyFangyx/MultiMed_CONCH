#!/usr/bin/env python3
"""Overlay paper-scheme c-index reference lines on greedy growth curves.

Also draws one curve per clinical model across field combinations (every
greedy subset + paper schemes), saved as per-dataset PNGs, a collage, and
``model_fieldcombo_cindex.csv``.

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
MODEL_NAMES = [
    "mlp_clinic_mean",
    "mlp_clinic_flatten",
    "snn_clinic_mean",
    "snn_clinic_flatten",
    "clinic_cox",
]
MODEL_COLORS = {
    "mlp_clinic_mean": "#1f77b4",
    "mlp_clinic_flatten": "#ff7f0e",
    "snn_clinic_mean": "#2ca02c",
    "snn_clinic_flatten": "#d62728",
    "clinic_cox": "#9467bd",
}
MODEL_LINESTYLES = {
    "mlp_clinic_mean": ("-", "o"),
    "mlp_clinic_flatten": ("--", "s"),
    "snn_clinic_mean": ("-.", "^"),
    "snn_clinic_flatten": (":", "D"),
    "clinic_cox": ("-", "v"),
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
MODEL_BASELINE_COLUMNS = [
    "dataset",
    "encoding",
    "landmark_tag",
    "model",
    "c_index_mean",
    "c_index_std",
    "source",
    "status",
]
METHOD_STYLES = [
    ("greedy", "-", "o"),
    ("baseline 1", "--", "s"),
    ("baseline 2", "-.", "^"),
    ("baseline 3", ":", "D"),
]
FIELDCOMBO_COLUMNS = [
    "dataset",
    "encoding",
    "landmark_tag",
    "model",
    "field_combo",
    "kind",
    "n_fields",
    "c_index_mean",
    "c_index_std",
    "source",
    "status",
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
        "--analyzer",
        default=DEFAULT_MODALITY,
        help=f"Analyzer used for paper-scheme reference lines. Default: {DEFAULT_MODALITY}.",
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


def paper_model_lookup(rows: list[dict[str, str]], *, encoding: str) -> dict[tuple[str, str, str], dict]:
    table: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        if str(row.get("encoding") or "").strip() != encoding:
            continue
        dataset = canonicalize_dataset(str(row.get("dataset") or "").strip())
        scheme = str(row.get("scheme") or "").strip()
        modality = str(row.get("modality") or "").strip()
        if not dataset or not scheme or modality not in MODEL_NAMES:
            continue
        mean_raw = row.get("val_c_index_mean") or row.get("test_c_index_mean") or ""
        if mean_raw == "":
            continue
        std_raw = row.get("val_c_index_std") or row.get("test_c_index_std") or "0"
        table[(dataset, scheme, modality)] = {
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


def paper_model_refs_for_dataset(
    dataset: str,
    *,
    schemes: dict[str, dict],
    lookup: dict[tuple[str, str, str], dict],
    datasets: dict | None = None,
) -> list[dict]:
    refs: list[dict] = []
    for name in PAPER_SCHEMES:
        cfg = schemes[name]
        if not scheme_applies(cfg, dataset, datasets):
            continue
        scores = {model: lookup.get((dataset, name, model)) for model in MODEL_NAMES}
        if any(score is not None for score in scores.values()):
            refs.append({"scheme": name, "scores": scores})
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


def plot_dataset_curve_without_model_average(
    path: Path,
    *,
    dataset: str,
    rows: list[dict],
    model_scores: dict[str, dict],
    encoding: str,
    landmark_tag: str,
) -> None:
    """Plot the greedy curve with one baseline line per model.

    The greedy curve is intentionally retained as the selected inner model's
    curve; model-specific values come from ``run_config.json.outer_scores``.
    """
    os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [int(row["n_fields"]) for row in rows]
    ys = [float(row["c_index_mean"]) for row in rows]
    stds = [float(row.get("c_index_std") or 0.0) for row in rows]
    drawn_models = [
        name for name in MODEL_NAMES
        if model_scores.get(name, {}).get("c_index_mean") is not None
    ]

    xmin = min(xs) if xs else 1
    xmax = max(xs) if xs else 1
    xpad = max(0.4, 0.08 * max(xmax - xmin, 1))

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.plot(xs, ys, marker="o", linewidth=1.8, color="#111111", label="greedy")
    if any(std > 0 for std in stds):
        lo = [y - std for y, std in zip(ys, stds)]
        hi = [y + std for y, std in zip(ys, stds)]
        ax.fill_between(xs, lo, hi, color="#111111", alpha=0.10)
    for name in drawn_models:
        score = model_scores[name]
        ax.axhline(
            float(score["c_index_mean"]),
            color=MODEL_COLORS[name],
            linestyle="--",
            linewidth=1.5,
            label=name,
        )
    ax.set_xlim(xmin - xpad, xmax + xpad)
    y_all = list(ys) + [float(model_scores[name]["c_index_mean"]) for name in drawn_models]
    if y_all:
        ymin, ymax = min(y_all), max(y_all)
        ypad = max(0.02, 0.08 * max(ymax - ymin, 0.05))
        ax.set_ylim(ymin - ypad, ymax + ypad)
    ax.set_xlabel("number of selected fields")
    ax.set_ylabel("5-fold mean c-index")
    ax.set_title(f"{dataset}  |  {encoding} / {landmark_tag}")
    ax.grid(True, alpha=0.3)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, frameon=False, loc="best", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def load_model_scores(path: Path) -> dict[str, dict]:
    """Read model-specific final scores without requiring all five models."""
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scores = config.get("outer_scores") or {}
    result: dict[str, dict] = {}
    for name in MODEL_NAMES:
        raw = scores.get(name)
        if not isinstance(raw, dict):
            continue
        value = raw.get("c_index_mean")
        if value in (None, ""):
            continue
        try:
            result[name] = {
                "c_index_mean": float(value),
                "c_index_std": float(raw.get("c_index_std") or 0.0),
                "source": raw.get("source") or "test",
            }
        except (TypeError, ValueError):
            continue
    return result


def _test_score(path: Path) -> float | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        values = [float(row["test_cindex"]) for row in rows if row.get("test_cindex")]
        return sum(values) / len(values) if values else None
    except (OSError, KeyError, TypeError, ValueError):
        return None


def load_greedy_model_curves(dataset: str, landmark_tag: str, path_rows: list[dict]) -> dict[str, list[dict]]:
    """Load each model's score for every selected greedy subset."""
    root = PROJECT_ROOT / "Clinic_Analyzer" / "results" / "greedy"
    dataset_key = canonicalize_dataset(dataset).lower().replace("-", "_")
    subset_root = PROJECT_ROOT / "outputs" / dataset / "greedy" / "prompt" / landmark_tag / "subsets"
    curves = {name: [] for name in MODEL_NAMES}
    for step_row in path_rows:
        fields = set(step_row.get("subset") or [])
        match = None
        for fields_path in subset_root.glob("*/embeddings/fields.json"):
            try:
                cfg = json.loads(fields_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if set(cfg.get("fields") or []) == fields:
                match = fields_path.parent.parent.name
                break
        if not match:
            continue
        run_dirs = sorted(root.glob(f"{dataset_key}__{match}/*"))
        run_dirs += sorted((PROJECT_ROOT / "results" / "greedy" / "prompt" / landmark_tag / dataset / "runs" / match).glob("*"))
        for name in MODEL_NAMES:
            score = None
            for run_dir in run_dirs:
                if run_dir.name != name:
                    continue
                score = _test_score(run_dir / "test_result.csv")
            if score is not None:
                n_fields = step_row.get("n_fields") or len(step_row.get("subset") or [])
                curves[name].append({"n_fields": int(n_fields), "c_index_mean": score})
    return curves


def plot_model_method_curve(path: Path, *, dataset: str, greedy_curves: dict[str, list[dict]], baseline_refs: list[dict], encoding: str, landmark_tag: str, greedy_only: bool = False) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    for model in MODEL_NAMES:
        points = greedy_curves.get(model) or []
        if points:
            ax.plot([p["n_fields"] for p in points], [p["c_index_mean"] for p in points], color=MODEL_COLORS[model], linestyle="-", marker="o", linewidth=1.5, label=model)
    if not greedy_only:
        for idx, ref in enumerate(baseline_refs, start=1):
            method = f"baseline {idx}"
            _, line, marker = METHOD_STYLES[(idx - 1) % len(METHOD_STYLES)]
            for model in MODEL_NAMES:
                score = ref["scores"].get(model)
                if score is not None:
                    ax.axhline(float(score["c_index_mean"]), color=MODEL_COLORS[model], linestyle=line, marker=marker, markevery=[0], linewidth=1.3)
    ax.set_xlabel("number of selected fields")
    ax.set_ylabel("5-fold mean c-index")
    ax.set_title(f"{dataset}  |  {encoding} / {landmark_tag}")
    ax.grid(True, alpha=0.3)
    color_handles = [plt.Line2D([], [], color=MODEL_COLORS[m], linestyle="-", marker="o", label=m) for m in MODEL_NAMES if greedy_curves.get(m)]
    method_handles = [plt.Line2D([], [], color="#333333", linestyle=METHOD_STYLES[0][1], marker=METHOD_STYLES[0][2], label="greedy")]
    for idx in range(1, len(baseline_refs) + 1):
        _, line, marker = METHOD_STYLES[(idx - 1) % len(METHOD_STYLES)]
        method_handles.append(plt.Line2D([], [], color="#333333", linestyle=line, marker=marker, label=f"baseline {idx}"))
    leg1 = ax.legend(handles=color_handles, title="model", frameon=False, loc="best", fontsize=8)
    ax.add_artist(leg1)
    ax.legend(handles=method_handles, title="method", frameon=False, loc="lower right", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def build_fieldcombo_categories(
    path_rows: list[dict],
    scheme_refs: list[dict],
    schemes: dict[str, dict],
) -> list[dict]:
    """Ordered x-axis categories: every greedy subset (labeled by its field
    count), then paper schemes in their canonical order."""
    cats: list[dict] = []
    for step_row in path_rows:
        subset = step_row.get("subset") or []
        n_fields = len(subset) or int(step_row.get("n_fields") or 0)
        cats.append(
            {
                "key": f"greedy_step_{int(step_row['step'])}",
                "kind": "greedy",
                "label": f"greedy_{n_fields}",
                "n_fields": n_fields,
            }
        )
    for ref in scheme_refs:
        name = ref["scheme"]
        cats.append(
            {
                "key": name,
                "kind": "paper",
                "label": name,
                "n_fields": len(schemes[name]["fields"]),
            }
        )
    return cats


def load_greedy_step_scores(
    dataset: str,
    landmark_tag: str,
    path_rows: list[dict],
    csv_rows: list[dict],
    final_scores: dict[str, dict],
) -> dict[int, dict[str, dict]]:
    """Per greedy step index -> {model: {c_index_mean, c_index_std, source}}.

    The greedy search itself uses only the inner model (mlp_clinic_flatten),
    whose per-step scores come from the growth CSV; the five outer models are
    evaluated only on the final greedy subset (run_config.json outer_scores),
    so every intermediate step carries the inner model alone.
    """
    csv_by_step = {int(row["step"]): row for row in csv_rows}
    by_step: dict[int, dict[str, dict]] = {}
    for step_row in path_rows:
        step = int(step_row["step"])
        scores: dict[str, dict] = {}
        csv_row = csv_by_step.get(step)
        if csv_row and csv_row.get("c_index_mean"):
            try:
                scores["mlp_clinic_flatten"] = {
                    "c_index_mean": float(csv_row["c_index_mean"]),
                    "c_index_std": float(csv_row.get("c_index_std") or 0.0),
                    "source": "test",
                }
            except (TypeError, ValueError):
                pass
        by_step[step] = scores

    if not path_rows:
        return by_step

    # final greedy subset: all five models from run_config.json outer_scores
    final_step = int(path_rows[-1]["step"])
    for name in MODEL_NAMES:
        score = final_scores.get(name)
        if score is not None:
            by_step[final_step][name] = score
    return by_step


def plot_model_fieldcombo_curve(
    path: Path,
    *,
    dataset: str,
    categories: list[dict],
    category_scores: dict[str, dict[str, dict]],
    encoding: str,
    landmark_tag: str,
) -> None:
    """One line per clinical model across field combinations: every greedy
    subset plus the paper schemes."""
    os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp") / "mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    n_greedy = sum(1 for cat in categories if cat["kind"] == "greedy")
    if n_greedy:
        ax.axvspan(-0.5, n_greedy - 0.5, color="#eef2f7", zorder=0)

    for model in MODEL_NAMES:
        linestyle, marker = MODEL_LINESTYLES[model]
        xs, ys = [], []
        for idx, cat in enumerate(categories):
            score = (category_scores.get(cat["key"]) or {}).get(model)
            if score is None or score.get("c_index_mean") is None:
                continue
            xs.append(idx)
            ys.append(float(score["c_index_mean"]))
        if xs:
            ax.plot(
                xs,
                ys,
                color=MODEL_COLORS[model],
                linestyle=linestyle,
                marker=marker,
                markersize=4.5,
                linewidth=1.5,
                label=model,
            )

    ax.set_xticks(range(len(categories)))
    ax.set_xticklabels([cat["label"] for cat in categories], fontsize=9)
    ax.set_xlim(-0.5, len(categories) - 0.5)
    ax.set_xlabel("field combination")
    ax.set_ylabel("5-fold mean c-index")
    ax.set_title(f"{dataset}  |  {encoding} / {landmark_tag}")
    ax.grid(True, alpha=0.3, axis="y")
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, frameon=False, loc="best", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def model_fieldcombo_csv_rows(
    *,
    dataset: str,
    encoding: str,
    landmark_tag: str,
    categories: list[dict],
    category_scores: dict[str, dict[str, dict]],
) -> list[dict]:
    rows: list[dict] = []
    for cat in categories:
        for model in MODEL_NAMES:
            score = (category_scores.get(cat["key"]) or {}).get(model)
            if score is None or score.get("c_index_mean") is None:
                rows.append(
                    {
                        "dataset": dataset,
                        "encoding": encoding,
                        "landmark_tag": landmark_tag,
                        "model": model,
                        "field_combo": cat["label"],
                        "kind": cat["kind"],
                        "n_fields": cat["n_fields"],
                        "c_index_mean": "",
                        "c_index_std": "",
                        "source": "",
                        "status": "missing",
                    }
                )
                continue
            rows.append(
                {
                    "dataset": dataset,
                    "encoding": encoding,
                    "landmark_tag": landmark_tag,
                    "model": model,
                    "field_combo": cat["label"],
                    "kind": cat["kind"],
                    "n_fields": cat["n_fields"],
                    "c_index_mean": score["c_index_mean"],
                    "c_index_std": score.get("c_index_std") or 0.0,
                    "source": score.get("source") or "",
                    "status": "ok",
                }
            )
    return rows


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
    per_model_dir = out_dir / "per_dataset_no_model_average"
    datasets = json.loads(Path(args.datasets_config).read_text(encoding="utf-8"))
    schemes = load_paper_schemes(Path(args.template_dir))
    lookup = paper_lookup(
        load_paper_cindex_rows(Path(args.paper_results_root)),
        encoding=encoding,
        modality=args.analyzer,
    )
    paper_rows = load_paper_cindex_rows(Path(args.paper_results_root))
    model_lookup = paper_model_lookup(paper_rows, encoding=encoding)

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
    model_baseline_rows: list[dict] = []
    fieldcombo_rows: list[dict] = []
    collage_records: list[dict] = []
    model_collage_records: list[dict] = []
    greedy_collage_records: list[dict] = []
    fieldcombo_collage_records: list[dict] = []
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

        model_scores = load_model_scores(Path(record["src_dir"]) / "run_config.json")
        path_payload = Path(record["src_dir"]) / "path.json"
        try:
            path_rows = json.loads(path_payload.read_text(encoding="utf-8")).get("path") or []
        except (OSError, json.JSONDecodeError):
            path_rows = []
        greedy_curves = load_greedy_model_curves(dataset, landmark_tag, path_rows)
        baseline_refs = paper_model_refs_for_dataset(dataset, schemes=schemes, lookup=model_lookup, datasets=datasets)
        model_png_path = per_model_dir / f"{dataset}.png"
        plot_model_method_curve(
            model_png_path,
            dataset=dataset,
            greedy_curves=greedy_curves,
            baseline_refs=baseline_refs,
            encoding=encoding,
            landmark_tag=landmark_tag,
        )
        model_record = dict(record)
        model_record["png_path"] = model_png_path
        model_collage_records.append(model_record)
        wrote.append(model_png_path)
        greedy_png_path = out_dir / "per_dataset_greedy_by_model" / f"{dataset}.png"
        plot_model_method_curve(
            greedy_png_path,
            dataset=dataset,
            greedy_curves=greedy_curves,
            baseline_refs=[],
            encoding=encoding,
            landmark_tag=landmark_tag,
            greedy_only=True,
        )
        greedy_record = dict(record)
        greedy_record["png_path"] = greedy_png_path
        greedy_collage_records.append(greedy_record)
        wrote.append(greedy_png_path)

        if not path_rows:
            path_rows = [
                {
                    "step": int(row["step"]),
                    "n_fields": int(row["n_fields"]),
                    "subset": [
                        item.strip()
                        for item in (row.get("subset") or "").split("|")
                        if item.strip()
                    ],
                }
                for row in record["rows"]
            ]
        per_step_scores = load_greedy_step_scores(
            dataset, landmark_tag, path_rows, record["rows"], model_scores
        )
        categories = build_fieldcombo_categories(path_rows, baseline_refs, schemes)
        category_scores = {
            f"greedy_step_{step}": scores for step, scores in per_step_scores.items()
        }
        for ref in baseline_refs:
            category_scores[ref["scheme"]] = ref["scores"]
        fieldcombo_png_path = out_dir / "per_dataset_model_fieldcombo" / f"{dataset}.png"
        plot_model_fieldcombo_curve(
            fieldcombo_png_path,
            dataset=dataset,
            categories=categories,
            category_scores=category_scores,
            encoding=encoding,
            landmark_tag=landmark_tag,
        )
        fieldcombo_record = dict(record)
        fieldcombo_record["png_path"] = fieldcombo_png_path
        fieldcombo_collage_records.append(fieldcombo_record)
        wrote.append(fieldcombo_png_path)
        fieldcombo_rows.extend(
            model_fieldcombo_csv_rows(
                dataset=dataset,
                encoding=encoding,
                landmark_tag=landmark_tag,
                categories=categories,
                category_scores=category_scores,
            )
        )
        for name in MODEL_NAMES:
            score = model_scores.get(name)
            model_baseline_rows.append(
                {
                    "dataset": dataset,
                    "encoding": encoding,
                    "landmark_tag": landmark_tag,
                    "model": name,
                    "c_index_mean": "" if score is None else score["c_index_mean"],
                    "c_index_std": "" if score is None else score["c_index_std"],
                    "source": "" if score is None else score["source"],
                    "status": "ok" if score is not None else "missing_model_score",
                }
            )
        for ref in refs:
            overlay_rows.append(
                {
                    "dataset": dataset,
                    "encoding": encoding,
                    "landmark_tag": landmark_tag,
                    "modality": args.analyzer,
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
    model_baseline_csv = out_dir / "model_baseline_cindex.csv"
    model_collage_png = out_dir / "cindex_by_n_fields_no_model_average.png"
    greedy_collage_png = out_dir / "greedy_by_model.png"
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
            heading=f"FigA other paper works  |  {encoding} / {landmark_tag}  |  {args.analyzer}",
            cols=args.cols,
        )
        wrote.append(collage_png)
    else:
        skipped.append(collage_png)
        print("no matching greedy CSV files; skip FigA overlay")

    if model_baseline_rows:
        write_rows_csv(model_baseline_csv, model_baseline_rows, MODEL_BASELINE_COLUMNS)
        wrote.append(model_baseline_csv)
    else:
        skipped.append(model_baseline_csv)

    if model_collage_records:
        compose_collage(
            model_collage_records,
            model_collage_png,
            heading=f"FigA no model average  |  {encoding} / {landmark_tag}",
            cols=args.cols,
        )
        wrote.append(model_collage_png)
    else:
        skipped.append(model_collage_png)

    if greedy_collage_records:
        compose_collage(
            greedy_collage_records,
            greedy_collage_png,
            heading=f"Greedy by model  |  {encoding} / {landmark_tag}",
            cols=args.cols,
        )
        wrote.append(greedy_collage_png)
    else:
        skipped.append(greedy_collage_png)

    fieldcombo_csv = out_dir / "model_fieldcombo_cindex.csv"
    fieldcombo_collage_png = out_dir / "model_cindex_by_fieldcombo.png"

    if fieldcombo_rows:
        write_rows_csv(fieldcombo_csv, fieldcombo_rows, FIELDCOMBO_COLUMNS)
        wrote.append(fieldcombo_csv)
    else:
        skipped.append(fieldcombo_csv)

    if fieldcombo_collage_records:
        compose_collage(
            fieldcombo_collage_records,
            fieldcombo_collage_png,
            heading=f"Model c-index by field combination  |  {encoding} / {landmark_tag}",
            cols=args.cols,
        )
        wrote.append(fieldcombo_collage_png)
    else:
        skipped.append(fieldcombo_collage_png)

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
