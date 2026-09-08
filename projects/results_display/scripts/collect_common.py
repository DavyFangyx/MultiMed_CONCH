#!/usr/bin/env python3
"""Shared helpers for results_display collectors."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
SRC = PROJECT_ROOT / "src"

for path in (REPO_ROOT, SRC):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from common.datasets import load_dataset_configs, resolve_dataset_names
from common.paths import (
    DEFAULT_DATASETS_CONFIG,
    VALID_ENCODINGS,
    display_results_dir,
    landmark_tag_from_args,
    result_experiment_name,
    validate_encoding,
)


GRID_COLS = 6
TITLE_HEIGHT = 56
PAD = 12
BACKGROUND = (255, 255, 255)
TITLE_COLOR = (32, 32, 32)
CELL_TITLE_COLOR = (40, 40, 40)
BORDER_COLOR = (220, 220, 220)


def add_common_collect_args(
    parser: argparse.ArgumentParser,
    *,
    experiment: str,
    extra_help: str | None = None,
) -> argparse.ArgumentParser:
    parser.add_argument(
        "--dataset",
        default="all",
        help="数据集名；支持 all 或逗号分隔列表。默认 all。",
    )
    parser.add_argument("--datasets_config", default=DEFAULT_DATASETS_CONFIG)
    parser.add_argument(
        "--encoding",
        default="prompt",
        choices=list(VALID_ENCODINGS),
    )
    parser.add_argument(
        "--experiment",
        default="",
        help="空=默认实验；longitudinal=走 longitudinal_* 结果树。",
    )
    parser.add_argument(
        "--landmark_time",
        required=True,
        help="全局 landmark 起点：天数（非负整数）或 none。",
    )
    parser.add_argument(
        "--out",
        default=None,
        help=extra_help or f"覆盖默认 results_display/{experiment}/{{encoding}}/{{landmark_tag}}",
    )
    parser.add_argument(
        "--cols",
        type=int,
        default=GRID_COLS,
        help="拼图列数，默认 6。",
    )
    parser.set_defaults(collect_kind=experiment)
    return parser


def resolve_collect_context(args):
    encoding = validate_encoding(args.encoding)
    landmark_tag = landmark_tag_from_args(args)
    experiment = result_experiment_name(args.collect_kind, getattr(args, "experiment", ""))
    datasets = load_dataset_configs(args.datasets_config)
    names = resolve_dataset_names(args.dataset, datasets)
    if not names:
        raise ValueError("--dataset did not resolve to any datasets")
    out_dir = Path(args.out) if args.out else display_results_dir(experiment, encoding, landmark_tag)
    return encoding, landmark_tag, experiment, names, out_dir


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf",
    ]
    search_dirs = [
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/usr/share/fonts/truetype/freefont"),
    ]
    for name in names:
        for root in search_dirs:
            path = root / name
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def compose_collage(
    records: list[dict],
    out_path: Path,
    *,
    heading: str,
    cols: int,
    image_key: str = "png_path",
    label_key: str = "dataset",
) -> None:
    if not records:
        raise ValueError("no PNG records to collage")
    if cols < 1:
        raise ValueError("--cols must be >= 1")

    images = [Image.open(record[image_key]).convert("RGB") for record in records]
    cell_w = max(im.width for im in images)
    cell_h = max(im.height for im in images)
    n = len(images)
    cols = min(cols, n)
    rows = math.ceil(n / cols)
    title_font = load_font(36, bold=True)
    cell_font = load_font(28, bold=True)

    canvas_w = cols * cell_w + (cols + 1) * PAD
    canvas_h = TITLE_HEIGHT + rows * (TITLE_HEIGHT + cell_h) + (rows + 1) * PAD
    canvas = Image.new("RGB", (canvas_w, canvas_h), BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    tw, th = _text_size(draw, heading, title_font)
    draw.text(((canvas_w - tw) / 2, (TITLE_HEIGHT - th) / 2), heading, fill=TITLE_COLOR, font=title_font)

    for idx, (record, image) in enumerate(zip(records, images)):
        row, col = divmod(idx, cols)
        x0 = PAD + col * (cell_w + PAD)
        y0 = TITLE_HEIGHT + PAD + row * (TITLE_HEIGHT + cell_h + PAD)
        label = record[label_key]
        lw, lh = _text_size(draw, label, cell_font)
        draw.text((x0 + (cell_w - lw) / 2, y0 + (TITLE_HEIGHT - lh) / 2), label, fill=CELL_TITLE_COLOR, font=cell_font)

        img_x = x0 + (cell_w - image.width) // 2
        img_y = y0 + TITLE_HEIGHT + (cell_h - image.height) // 2
        canvas.paste(image, (img_x, img_y))
        draw.rectangle(
            [x0, y0, x0 + cell_w - 1, y0 + TITLE_HEIGHT + cell_h - 1],
            outline=BORDER_COLOR,
            width=1,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    for image in images:
        image.close()


def read_csv_rows(csv_path: Path, columns: list[str] | None = None) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"empty CSV header: {csv_path}")
        if columns is None:
            columns = list(reader.fieldnames)
        missing = [col for col in columns if col not in reader.fieldnames]
        if missing:
            raise ValueError(f"{csv_path} missing columns: {missing}")
        return [{col: (row.get(col) or "") for col in columns} for row in reader]


def write_combined_csv(path: Path, records: list[dict], columns: list[str], extra_keys: list[str] | None = None) -> None:
    extra_keys = extra_keys or ["dataset", "encoding", "landmark_tag"]
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [*extra_keys, *columns]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            for row in record["rows"]:
                payload = {key: record.get(key, "") for key in extra_keys}
                payload.update(row)
                writer.writerow(payload)


def collect_named_files(
    names: list[str],
    *,
    encoding: str,
    landmark_tag: str,
    locate,
    required: list[str],
    optional: list[str] | None = None,
    csv_key: str | None = None,
    csv_columns: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    optional = optional or []
    records: list[dict] = []
    missing: list[dict] = []
    for name in names:
        located = locate(name, encoding, landmark_tag)
        src_dir = Path(located["src_dir"])
        reasons = []
        paths = {}
        for filename in required:
            path = src_dir / filename
            paths[filename] = path
            if not path.exists():
                reasons.append(f"missing {filename}")
        for filename in optional:
            path = src_dir / filename
            if path.exists():
                paths[filename] = path
        if reasons:
            missing.append(
                {
                    "dataset": name,
                    "encoding": encoding,
                    "landmark_tag": landmark_tag,
                    "src_dir": str(src_dir),
                    "reason": "; ".join(reasons),
                }
            )
            print(f"  skip {name}: {'; '.join(reasons)}")
            continue
        record = {
            "dataset": name,
            "encoding": encoding,
            "landmark_tag": landmark_tag,
            "src_dir": src_dir,
            **{key.replace(".", "_"): path for key, path in paths.items()},
        }
        if csv_key:
            record["rows"] = read_csv_rows(paths[csv_key], csv_columns)
        records.append(record)
    return records, missing


def print_collect_summary(
    *,
    names: list[str],
    records: list[dict],
    missing: list[dict],
    wrote: list[Path],
    skipped: list[Path] | None = None,
) -> None:
    print(f"  datasets requested: {len(names)}")
    print(f"  kept: {len(records)}")
    print(f"  missing: {len(missing)}")
    for path in wrote:
        print(f"  wrote {path}")
    for path in skipped or []:
        print(f"  skip {path}")
