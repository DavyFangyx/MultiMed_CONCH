from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path


def config_fingerprint(config: dict) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SQLiteCache:
    """Small process-safe SQLite cache for completed subset evaluations."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS evaluations (cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self._db.commit()

    def get(self, key: str):
        with self._lock:
            row = self._db.execute("SELECT payload FROM evaluations WHERE cache_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, payload: dict) -> None:
        text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO evaluations(cache_key,payload) VALUES (?,?)", (key, text))
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


def make_cache_key(*, dataset, landmark_tag, encoding, modality, seed, fields, field_index_hash,
                   split_hashes, train_args_hash, schema_version="e2-v1") -> str:
    return config_fingerprint({
        "dataset": dataset, "landmark_tag": landmark_tag, "encoding": encoding,
        "modality": modality, "seed": int(seed), "fields": sorted(fields),
        "field_index_hash": field_index_hash, "split_hashes": list(split_hashes),
        "train_args_hash": train_args_hash, "schema_version": schema_version,
    })
