"""Load and deduplicate GDC clinical JSON cases."""

from __future__ import annotations

import json
from pathlib import Path


def normalize_json_paths(json_paths) -> list[str]:
    if isinstance(json_paths, (str, Path)):
        return [str(json_paths)]
    return [str(x) for x in json_paths]


def match_case_project(case: dict, project_ids: list | None) -> bool:
    if not project_ids:
        return True
    project_id = str(case.get("project", {}).get("project_id", "")).strip()
    return project_id in set(project_ids)


def load_clinical_cases(json_paths, project_ids: list | None = None) -> list:
    paths = normalize_json_paths(json_paths)
    cases_by_patient = {}
    total, skipped, duplicated = 0, 0, 0
    project_filtered = 0
    project_ids = list(project_ids or [])

    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            cases = json.load(f)
        print(f"      {path}: {len(cases)} 个病例")
        total += len(cases)

        for case in cases:
            pid = str(case.get("submitter_id", "")).strip()
            if not pid:
                skipped += 1
                continue
            if not match_case_project(case, project_ids):
                project_filtered += 1
                continue
            if pid in cases_by_patient:
                duplicated += 1
                continue
            cases_by_patient[pid] = case

    print(f"      合计病例数: {total}")
    if project_ids:
        print(f"      project_id 过滤: {project_ids}")
        print(f"      project_id 过滤掉病例数: {project_filtered}")
    print(f"      去重后病例数: {len(cases_by_patient)}")
    if duplicated:
        print(f"      重复 submitter_id: {duplicated} 个，保留首次出现记录")
    if skipped:
        print(f"      跳过缺少 submitter_id: {skipped} 个")

    return list(cases_by_patient.values())
