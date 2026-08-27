# Case JSON Array Flatten Keep Rules

Audience: another model that must reproduce or consume the flattened patient row.
Scope: how array fields in a case JSON are reduced to a single CSV row.
Do not invent extra selection logic. Follow this document exactly.

Source of truth:

- A_manual: `src/schemes/extract.py` via `src/schemes/json2prompt.py`
- Field Bank: `src/discovery/field_bank.py` (`extract_field_bank_value`)
- Shared helpers: `src/common/fields.py`
- Missing-value helpers: `src/common/missingness.py`

Output contract: one case -> one row. Arrays are never exploded into extra rows.

---

## Decision Order

For each field that lives under an array:

1. Collect candidate values from JSON.
2. Decide whether this field is a diagnoses leaf or some other array field.
3. Keep either one diagnosis object, or all valid values joined into one cell.
4. If nothing valid remains, write `not reported`.

Never choose a record by time, recency, `updated_datetime`, or follow-up day counts.

---

## Rule A. diagnoses leaf fields keep one object

Function: `get_primary_diagnosis(diagnoses)`

Keep exactly one diagnosis object:

1. If any item has `diagnosis_is_primary_disease` equal to `"true"` after lowercasing, keep that item.
2. Else keep `diagnoses[0]`.
3. If the array is empty, every diagnoses leaf is missing.

This rule applies to:

- A_manual diagnosis fields such as `primary_diagnosis`, `morphology`, `ajcc_pathologic_*`, `prior_treatment`
- Field Bank paths of the form `diagnoses[].<leaf>`

This rule does **not** apply to nested arrays under diagnosis:

- `diagnoses[].treatments[]...`
- `diagnoses[].pathology_details[]...`

Those use Rule B.

Field Bank extra constraint: use the primary diagnosis object only when that object actually contains the requested leaf. If the leaf is absent there, fall back to Rule B and join all matching values.

---

## Rule B. all other arrays keep every valid value, then unique-join

Applies to:

- `treatments`
- `follow_ups`
- `exposures`
- `pathology_details`
- `follow_ups[].other_clinical_attributes`
- any Field Bank path containing `[]` that is not `diagnoses[].<leaf>`

### What to collect

A_manual `treatments`:

1. Use top-level `case["treatments"]` if nonempty.
2. Else walk `diagnoses` in order and take the treatments list from the first diagnosis that has one.
3. Do not merge treatments from every diagnosis.

A_manual `pathology_details`: concatenate `pathology_details` from every diagnosis.

A_manual `follow_ups`: use the full top-level `follow_ups` list.

A_manual `exposures`: not read.

Field Bank: walk the field path and collect every matching node. Example: `exposures[].cigarettes_per_day` keeps values from all exposure records.

### How to collapse collected values

Use `unique_join`:

1. Run `clean_value` on each value.
2. Drop empty strings.
3. Deduplicate.
4. Sort.
5. Join with `", "`.
6. If nothing remains, write `not reported`.

Field Bank first filters with `classify_raw_value` and keeps only `valid` values, then runs the same `unique_join`.

Example cell:

```text
Pharmaceutical Therapy, NOS, Radiation Therapy, NOS
```

Do not keep only the first item. Do not keep the latest follow-up. Do not join with `" | "`.

---

## Missing And Sentinel Values

Drop these before a value can be kept.

A_manual `clean_value` treats these as missing and replaces them with the fallback, default `not reported`:

- empty string
- `not reported`
- `unknown`
- `not applicable`
- `--`

Field Bank `classify_raw_value` is stricter. Case-insensitive sentinel strings, not kept:

- `not reported`
- `unknown`
- `not applicable`
- `not available`
- `not evaluated`
- `not otherwise specified`
- `indeterminate`
- `cannot be assessed`
- `unspecified`
- `na`
- `n/a`
- `none`
- `null`
- `missing`
- `--`

Also not kept: `None`, empty string, empty list, empty dict.

---

## Pathway Map

| Path | A_manual | Field Bank |
|---|---|---|
| `diagnoses[].<leaf>` | one primary diagnosis, else first item | same; if primary lacks the leaf, unique-join all matches |
| `diagnoses[].treatments[]` | top-level treatments, else first diagnosis that has treatments; unique-join | all matching treatments; unique-join |
| `diagnoses[].pathology_details[]` | all diagnoses; unique-join | all matches; unique-join |
| `follow_ups[]` | all follow_ups; unique-join | all matches; unique-join |
| `exposures[]` | unused | all matches; unique-join |

---

## Hard Constraints For Downstream Code

- One case equals one row. Never explode arrays.
- Diagnoses leaf fields must not merge multiple diagnoses.
- Non-diagnosis arrays must unique-join all valid values.
- Drop missing and sentinel values before joining.
- Join token is sorted `", "`, not `" | "`.
- Do not use `updated_datetime` or follow-up day fields to pick a record.

Do not confuse this with `collapse_patient_values` in `src/discovery/stats.py`. That stats helper averages numeric values and joins conflicting categoricals with `" | "`. It is not the prompt-row flatten rule.
