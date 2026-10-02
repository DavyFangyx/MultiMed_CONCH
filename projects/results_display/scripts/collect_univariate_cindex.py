#!/usr/bin/env python3
"""Collect univariate field c-index tables into results_display/."""

from __future__ import annotations

import argparse
from pathlib import Path

from collect_common import (
    add_common_collect_args,
    print_collect_summary,
    read_csv_rows,
    resolve_collect_context,
    write_combined_csv,
)
from common.paths import dataset_univariate_results_dir


CSV_NAME = "field_cindex.csv"
SOURCE_COLUMNS = [
    "field",
    "field_idx",
    "n_fields",
    "c_index_mean",
    "c_index_std",
    "per_fold",
    "status",
]
COMBINED_EXTRA_KEYS = ["dataset", "encoding", "landmark_tag", "analyzer"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect univariate field_cindex.csv files into "
            "results_display/univariate/{encoding}/{landmark_tag}/."
        )
    )
    parser = add_common_collect_args(parser, experiment="univariate")
    parser.add_argument(
        "--analyzer",
        default=None,
        help="只收集指定 analyzer（逗号分隔）；默认收集结果目录下所有 analyzer 子目录",
    )
    return parser


def parse_analyzer_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def locate_dataset(dataset: str, encoding: str, landmark_tag: str, experiment: str = "") -> dict:
    return {
        "src_dir": dataset_univariate_results_dir(
            dataset,
            encoding=encoding,
            landmark_tag=landmark_tag,
            experiment=experiment,
        )
    }


def iter_univariate_records(
    names,
    *,
    encoding,
    landmark_tag,
    experiment,
    analyzers: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """扫描每个 dataset 结果目录下的 `{analyzer}/field_cindex.csv` 子目录。

    返回 (records, missing)。record 含 `analyzer`、`src_dir`、`rows` 等键；
    某 dataset 在结果目录下没有任何 analyzer 子目录时计入 missing。
    """
    records: list[dict] = []
    missing: list[dict] = []
    for dataset in names:
        src_root = dataset_univariate_results_dir(
            dataset, encoding, landmark_tag, experiment=experiment
        )
        subdirs = sorted(
            path for path in src_root.glob("*/") if (path / CSV_NAME).exists()
        )
        if analyzers:
            subdirs = [path for path in subdirs if path.name in analyzers]
        if not subdirs:
            missing.append(
                {
                    "dataset": dataset,
                    "encoding": encoding,
                    "landmark_tag": landmark_tag,
                    "reason": f"no {CSV_NAME} under {src_root}",
                }
            )
            continue
        for subdir in subdirs:
            csv_path = subdir / CSV_NAME
            records.append(
                {
                    "dataset": dataset,
                    "encoding": encoding,
                    "landmark_tag": landmark_tag,
                    "analyzer": subdir.name,
                    "src_dir": subdir,
                    CSV_NAME: csv_path,
                    "rows": read_csv_rows(csv_path, columns=SOURCE_COLUMNS),
                }
            )
    return records, missing


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    encoding, landmark_tag, experiment, names, out_dir = resolve_collect_context(args)
    records, missing = iter_univariate_records(
        names,
        encoding=encoding,
        landmark_tag=landmark_tag,
        experiment=experiment,
        analyzers=parse_analyzer_list(args.analyzer),
    )
    csv_path = out_dir / CSV_NAME
    wrote: list[Path] = []
    skipped: list[Path] = []
    if records:
        write_combined_csv(csv_path, records, SOURCE_COLUMNS, extra_keys=COMBINED_EXTRA_KEYS)
        wrote.append(csv_path)
    else:
        print("no matching univariate CSV files; skip combined CSV")
        skipped.append(csv_path)
    print_collect_summary(names=names, records=records, missing=missing, wrote=wrote, skipped=skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
