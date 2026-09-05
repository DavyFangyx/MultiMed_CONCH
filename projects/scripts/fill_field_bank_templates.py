import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
for path in (PROJECT_ROOT.parent, SRC):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from discovery.field_bank import TEMPLATE_COLUMNS, _clean_text, _read_existing_templates
from discovery.field_bank_spec import (
    SHARED_SPEC_PATH,
    fill_from_spec,
    load_shared_spec,
    write_shared_spec,
)


def dataset_template_paths(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.glob("*/FIELD_BANK.csv")
        if path.parent.name != "_shared"
    )


def collect_fields(paths: list[Path]) -> list[str]:
    fields = set()
    for path in paths:
        df = pd.read_csv(path)
        if "field" not in df.columns:
            raise ValueError(f"FIELD_BANK missing field column: {path}")
        fields.update(_clean_text(value) for value in df["field"].tolist() if _clean_text(value))
    return sorted(fields)


def fill_dataset_table(path: Path, spec: dict, overwrite_templates: bool) -> dict[str, int]:
    preserved = _read_existing_templates(path)
    df = pd.read_csv(path)
    rows = []
    filled_templates = 0
    overwritten_templates = 0
    for field in df["field"].tolist():
        field = _clean_text(field)
        old = preserved.get(field, {})
        before = _clean_text(old.get("template"))
        filled = fill_from_spec(
            field,
            old,
            spec,
            overwrite_convert_unit=True,
            overwrite_template=overwrite_templates,
        )
        after = filled["template"]
        if not before and after:
            filled_templates += 1
        if overwrite_templates and before and before != after:
            overwritten_templates += 1
        rows.append(
            {
                "field": field,
                "example": old.get("example", ""),
                "convert": filled["convert"],
                "unit": filled["unit"],
                "template": after,
            }
        )
    pd.DataFrame(rows, columns=TEMPLATE_COLUMNS).to_csv(path, index=False)
    return {
        "rows": len(rows),
        "filled_templates": filled_templates,
        "overwritten_templates": overwritten_templates,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Fill Field Bank convert/unit/template from the shared spec.")
    parser.add_argument(
        "--root",
        default=str(PROJECT_ROOT / "templates" / "field_bank"),
        help="Field Bank template root",
    )
    parser.add_argument(
        "--spec",
        default=str(SHARED_SPEC_PATH),
        help="Shared spec CSV path",
    )
    parser.add_argument(
        "--overwrite-templates",
        action="store_true",
        help="Overwrite existing template sentences. Default keeps non-empty templates.",
    )
    parser.add_argument(
        "--rewrite-spec",
        action="store_true",
        help="Regenerate the shared spec from code before filling.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    root = Path(args.root)
    spec_path = Path(args.spec)
    paths = dataset_template_paths(root)
    if not paths:
        raise SystemExit(f"no FIELD_BANK.csv files under {root}")
    fields = collect_fields(paths)
    if args.rewrite_spec or not spec_path.exists():
        write_shared_spec(path=spec_path)
        print(f"✅ shared spec: {spec_path}  fields={len(load_shared_spec(spec_path))}")
    spec = load_shared_spec(spec_path)
    missing = [field for field in fields if field not in spec]
    if missing:
        raise SystemExit(
            f"shared spec missing {len(missing)} dataset fields: {missing[:8]}"
        )
    total_filled = 0
    total_overwritten = 0
    for path in paths:
        stats = fill_dataset_table(path, spec, args.overwrite_templates)
        total_filled += stats["filled_templates"]
        total_overwritten += stats["overwritten_templates"]
        print(
            f"✅ {path.parent.name}: rows={stats['rows']} "
            f"filled_templates={stats['filled_templates']} "
            f"overwritten_templates={stats['overwritten_templates']}"
        )
    print(
        f"✅ filled {len(paths)} datasets; new templates={total_filled}; "
        f"overwritten templates={total_overwritten}"
    )


if __name__ == "__main__":
    main()
