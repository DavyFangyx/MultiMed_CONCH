from pathlib import Path
import sys

import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from discovery.field_bank import TEMPLATE_COLUMNS, write_field_bank_template_skeleton
from discovery.field_bank_spec import (
    field_convert,
    load_shared_spec,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIELD_BANK_ROOT = PROJECT_ROOT / "templates" / "field_bank"

ALLOWED_CONVERT = {"", "days_to_years", "int"}


def _dataset_tables():
    return sorted(
        path
        for path in FIELD_BANK_ROOT.rglob("FIELD_BANK.csv")
        if "_shared" not in path.parts
    )


def _all_fields():
    fields = set()
    for path in _dataset_tables():
        df = pd.read_csv(path)
        fields.update(str(value) for value in df["field"].tolist())
    return fields


def test_shared_spec_covers_all_kept_fields():
    fields = _all_fields()
    spec = load_shared_spec()
    shared_path = FIELD_BANK_ROOT / "_shared" / "field_prompt_spec.csv"
    shared_df = pd.read_csv(shared_path).fillna("")

    # The checked-in shared template is the source of truth for this test.
    assert shared_df["field"].is_unique
    expected = {
        str(row.field): {
            "field": str(row.field),
            "convert": str(row.convert),
            "unit": str(row.unit),
            "template": str(row.template),
            "note": str(row.note),
        }
        for row in shared_df.itertuples(index=False)
    }
    assert spec == expected
    assert fields <= set(spec)


def test_convert_and_unit_are_shared():
    spec = load_shared_spec()
    seen = {}
    for path in _dataset_tables():
        df = pd.read_csv(path)
        for row in df.itertuples(index=False):
            field = str(row.field)
            convert = "" if pd.isna(row.convert) else str(row.convert)
            unit = "" if pd.isna(row.unit) else str(row.unit)
            template = "" if pd.isna(row.template) else str(row.template)
            assert convert in ALLOWED_CONVERT, field
            assert template.count("{}") == 1, field
            assert template.endswith("."), field
            key = (convert, unit)
            if field not in seen:
                seen[field] = key
            assert seen[field] == key, field
            assert spec[field]["convert"] == convert, field
            assert spec[field]["unit"] == unit, field
    assert not df.empty


def test_templates_are_complete():
    for path in _dataset_tables():
        df = pd.read_csv(path)
        assert df["field"].is_unique, path
        blank = df["template"].isna() | (df["template"].astype(str).str.strip() == "") | (df["template"].astype(str).str.lower() == "nan")
        assert not blank.any(), path
        assert df["template"].astype(str).str.count(r"\{\}").eq(1).all(), path
        assert df["template"].astype(str).str.endswith(".").all(), path
def test_age_at_diagnosis_uses_days_to_years():
    assert field_convert("diagnoses[].age_at_diagnosis") == "days_to_years"
    for path in _dataset_tables():
        df = pd.read_csv(path)
        sub = df[df["field"] == "diagnoses[].age_at_diagnosis"]
        if sub.empty:
            continue
        row = sub.iloc[0]
        assert row["convert"] == "days_to_years"
        assert row["unit"] == "years"
        assert str(row["template"]).strip()
        assert str(row["template"]).count("{}") == 1


def test_write_templates_preserves_filled_rows(tmp_path):
    out_dir = tmp_path / "TCGA-CESC"
    out_dir.mkdir()
    existing = pd.DataFrame(
        [
            {
                "field": "diagnoses[].age_at_diagnosis",
                "example": "8900.0",
                "convert": "days_to_years",
                "unit": "years",
                "template": "Age at diagnosis is {} years.",
            },
            {
                "field": "demographic.race",
                "example": "white",
                "convert": "",
                "unit": "",
                "template": "Race is {}.",
            },
        ],
        columns=TEMPLATE_COLUMNS,
    )
    existing.to_csv(out_dir / "FIELD_BANK.csv", index=False)
    write_field_bank_template_skeleton(
        "TCGA-CESC",
        [
            "diagnoses[].age_at_diagnosis",
            "demographic.race",
            "diagnoses[].figo_stage",
        ],
        out_dir=out_dir,
        examples={"diagnoses[].figo_stage": "Stage I"},
    )
    df = pd.read_csv(out_dir / "FIELD_BANK.csv").fillna("")
    by_field = {row.field: row for row in df.itertuples(index=False)}
    assert by_field["diagnoses[].age_at_diagnosis"].convert == "days_to_years"
    assert by_field["diagnoses[].age_at_diagnosis"].unit == "years"
    assert by_field["diagnoses[].age_at_diagnosis"].template == "Age at diagnosis is {} years."
    assert by_field["diagnoses[].age_at_diagnosis"].example == "8900.0"
    assert by_field["demographic.race"].template == "Race is {}."
    assert by_field["diagnoses[].figo_stage"].template == "The FIGO stage is {}."
    assert by_field["diagnoses[].figo_stage"].example == "Stage I"


if __name__ == "__main__":
    import tempfile
    test_shared_spec_covers_all_kept_fields()
    test_convert_and_unit_are_shared()
    test_templates_are_complete()
    test_age_at_diagnosis_uses_days_to_years()
    with tempfile.TemporaryDirectory() as tmp:
        test_write_templates_preserves_filled_rows(Path(tmp))
    print("ok")
