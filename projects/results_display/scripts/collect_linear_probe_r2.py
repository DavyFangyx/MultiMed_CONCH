#!/usr/bin/env python3
"""Collect numeric linear-probe R2 tables into results_display/."""

from __future__ import annotations

import argparse
from pathlib import Path

from collect_common import (
    add_common_collect_args,
    collect_named_files,
    print_collect_summary,
    resolve_collect_context,
    write_combined_csv,
)
from common.paths import dataset_linear_probe_results_dir


CSV_NAME = "numeric_r2.csv"
SOURCE_COLUMNS = ["field", "field_idx", "n_valid", "r2", "status", "error"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect linear_probe numeric_r2.csv files into "
            "results_display/linear_probe/{encoding}/{landmark_tag}/."
        )
    )
    return add_common_collect_args(parser, experiment="linear_probe")


def locate_dataset(dataset: str, encoding: str, landmark_tag: str, experiment: str = "") -> dict:
    return {
        "src_dir": dataset_linear_probe_results_dir(
            dataset,
            encoding=encoding,
            landmark_tag=landmark_tag,
            experiment=experiment,
        )
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    encoding, landmark_tag, experiment, names, out_dir = resolve_collect_context(args)

    def _locate(dataset, encoding, landmark_tag):
        return locate_dataset(dataset, encoding, landmark_tag, experiment=getattr(args, "experiment", ""))

    records, missing = collect_named_files(
        names,
        encoding=encoding,
        landmark_tag=landmark_tag,
        locate=_locate,
        required=[CSV_NAME],
        csv_key=CSV_NAME,
        csv_columns=SOURCE_COLUMNS,
    )
    csv_path = out_dir / CSV_NAME
    wrote: list[Path] = []
    skipped: list[Path] = []
    if records:
        write_combined_csv(csv_path, records, SOURCE_COLUMNS)
        wrote.append(csv_path)
    else:
        print("no matching linear_probe CSV files; skip combined CSV")
        skipped.append(csv_path)
    print_collect_summary(names=names, records=records, missing=missing, wrote=wrote, skipped=skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
