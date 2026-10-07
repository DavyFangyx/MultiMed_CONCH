"""共享评估缓存状态盘点:按 schema 版本统计行数(只读;--apply 才删旧行)。

背景:gt≤0 修复后 cache key 新增 label 哈希并升 schema e2-v2
(src/selection/cache.py)。旧 v1 行的评估结果无法证明是修复后产物,
新运行永不命中它们。本脚本给出计数与处理建议,删除动作留给 --apply。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from common.paths import test_results_dir
from selection.cache import SCHEMA_VERSION


def count_by_schema(db_path: Path) -> dict[str, int]:
    db_path = Path(db_path)
    counts = {}
    if not db_path.exists():
        return counts
    connection = sqlite3.connect(str(db_path))
    try:
        rows = connection.execute("SELECT payload FROM evaluations").fetchall()
    except sqlite3.OperationalError as exc:
        print(f"[error] 读表失败: {exc}")
        return counts
    finally:
        connection.close()
    for (payload_text,) in rows:
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            counts["unparseable"] = counts.get("unparseable", 0) + 1
            continue
        # 旧行 payload 无 schema_version 字段 → 按 v1 处理
        version = payload.get("schema_version", "e2-v1")
        counts[version] = counts.get(version, 0) + 1
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="共享评估缓存按 schema 版本盘点")
    parser.add_argument("--cache", default=str(test_results_dir("Test_3_search") / "cache.sqlite"))
    parser.add_argument("--apply", action="store_true",
                        help="删除当前 schema(SCHEMA_VERSION)以外的旧行(默认只读)")
    args = parser.parse_args(argv)

    path = Path(args.cache)
    counts = count_by_schema(path)
    print(f"cache: {path}")
    if not counts:
        print("(空或不存在)")
        return
    for version in sorted(counts):
        print(f"  {version}: {counts[version]} 行")
    current = counts.get(SCHEMA_VERSION, 0)
    stale = sum(value for key, value in counts.items() if key != SCHEMA_VERSION)
    print(f"当前 schema {SCHEMA_VERSION}: {current} 行;旧 schema: {stale} 行")
    if stale:
        print("旧行永不命中,只占空间;是否可信为修复后产物需人工判定(见 z_notes/cleaned_runs_20261005.md)。")
        if args.apply:
            connection = sqlite3.connect(str(path))
            try:
                # 逐行过滤删除:payload 不含 schema_version 或版本不一致
                rows = connection.execute("SELECT cache_key, payload FROM evaluations").fetchall()
                doomed = []
                for key, payload_text in rows:
                    try:
                        version = json.loads(payload_text).get("schema_version", "e2-v1")
                    except json.JSONDecodeError:
                        version = "unparseable"
                    if version != SCHEMA_VERSION:
                        doomed.append((key,))
                connection.executemany("DELETE FROM evaluations WHERE cache_key=?", doomed)
                connection.commit()
            finally:
                connection.close()
            print(f"[apply] 已删除 {len(doomed)} 行旧 schema 记录")
    return


if __name__ == "__main__":
    main()
