"""Replace rows in shared CSV/JSON tables by dataset without wiping other queues."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def unique_in_order(values) -> list[str]:
    out = []
    seen = set()
    for value in values:
        name = str(value)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def upsert_dataframe_by_key(
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame,
    key: str,
    *,
    sort_by=None,
    ascending=True,
) -> pd.DataFrame:
    incoming = incoming.copy()
    if incoming.empty:
        if existing is None:
            return incoming.reset_index(drop=True)
        merged = existing.copy()
    elif existing is None or existing.empty:
        merged = incoming
    else:
        existing = existing.copy()
        cols = list(dict.fromkeys(list(existing.columns) + list(incoming.columns)))
        existing = existing.reindex(columns=cols)
        incoming = incoming.reindex(columns=cols)
        incoming_keys = set(incoming[key].astype(str).unique())
        kept = existing[~existing[key].astype(str).isin(incoming_keys)]
        merged = pd.concat([kept, incoming], ignore_index=True)

    if sort_by:
        merged = merged.sort_values(sort_by, ascending=ascending, kind="mergesort")
    return merged.reset_index(drop=True)


def upsert_csv_by_key(
    path: Path,
    incoming: pd.DataFrame,
    key: str,
    *,
    sort_by=None,
    ascending=True,
) -> pd.DataFrame:
    existing = pd.read_csv(path) if path.exists() else None
    merged = upsert_dataframe_by_key(
        existing,
        incoming,
        key,
        sort_by=sort_by,
        ascending=ascending,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path, index=False)
    return merged


def upsert_json_mapping(path: Path, incoming: dict) -> dict:
    existing = {}
    if path.exists():
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            existing = loaded
    existing.update(incoming)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(existing, handle, ensure_ascii=False, indent=2)
        handle.write(chr(10))
    return existing
