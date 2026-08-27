#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gdc_clinical_batch.py — 批量下载 GDC 临床数据，只下 clinic，不碰任何组学文件。

两条路线：
  A. portal clinical JSON : form POST /cases?attachment=true
                            -> ClinicDatasets/gdc_clinical/raw_json/<PROJECT>.json
  B. BCR Biotab            : POST /files -> POST /data
                            -> ClinicDatasets/gdc_clinical/biotab/<PROJECT>/*.txt

A 下的是 GDC 门户同款临床 JSON，不再自己 expand /cases，也不再压成一行表。
全部 open access，不需要 token / dbGaP 申请。

运行示例按 stage / 分支分开写。默认 --program TCGA；给了 --projects 就不再看 --program。
从项目根目录调用。输出目录写死，没有 --outdir。

# dry-run：只报计数，不下载
python ClinicDatasets/gdc_clinical_batch.py --dry-run
python ClinicDatasets/gdc_clinical_batch.py --program TARGET,CPTAC --dry-run
python ClinicDatasets/gdc_clinical_batch.py --program CPTAC-3,TARGET --dry-run
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-LIHC TCGA-LUAD --dry-run
python ClinicDatasets/gdc_clinical_batch.py --program all --dry-run

# 单独运行 A 分支，下载门户 clinical JSON
python ClinicDatasets/gdc_clinical_batch.py --skip-biotab
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-KIRP --skip-biotab
python ClinicDatasets/gdc_clinical_batch.py --program TARGET --skip-biotab

# 单独运行 B 分支，下载 BCR Biotab
python ClinicDatasets/gdc_clinical_batch.py --skip-indexed
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-KIRP --skip-indexed
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-KIRP --skip-indexed --manifest-only
python ClinicDatasets/gdc_clinical_batch.py --projects TCGA-KIRP --skip-indexed --raw-only

依赖：pip install requests pandas
"""

import argparse
import hashlib
import io
import json
import re
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except ImportError:  # 老版本 requests 自带 urllib3
    from requests.packages.urllib3.util.retry import Retry


API = "https://api.gdc.cancer.gov"

# 门户 clinical JSON 只要病例级临床实体，不要 sample / file / aliquot 那些默认字段。
CLINICAL_CASE_FIELDS = (
    "case_id",
    "submitter_id",
    "disease_type",
    "primary_site",
    "lost_to_followup",
    "days_to_lost_to_followup",
    "consent_type",
    "days_to_consent",
    "index_date",
    "state",
    "updated_datetime",
    "project.project_id",
)
CLINICAL_PREFIXES = (
    "demographic.",
    "diagnoses.",
    "exposures.",
    "family_histories.",
    "follow_ups.",
)
CLINICAL_SKIP_PREFIXES = (
    "diagnoses.annotations.",
    "follow_ups.annotations.",
)
GDC_CASES_PAGE = 10000

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "gdc_clinical"
RAW_JSON_DIR = OUT_DIR / "raw_json"
BIOTAB_DIR = OUT_DIR / "biotab"
DETAIL_PATH = ROOT / "gdc_download_detail.json"

# ---------------------------------------------------------------- HTTP

def make_session(retries=5, timeout=120):
    s = requests.Session()
    retry = Retry(
        total=retries, connect=retries, read=retries,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
    s.mount("https://", adapter)
    s.request_timeout = timeout
    return s


def api_post(sess, endpoint, payload, raw=False):
    r = sess.post(f"{API}/{endpoint}", json=payload, timeout=sess.request_timeout)
    r.raise_for_status()
    if raw:
        return r
    return r.json()


def get_data_release(sess):
    """GDC 是活库，每次 release 数据会变。记下来，否则半年后重跑对不上。"""
    try:
        r = sess.get(f"{API}/status", timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def load_download_detail():
    if DETAIL_PATH.exists():
        try:
            return json.loads(DETAIL_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def file_md5(path: Path, chunk=1024 * 1024):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def file_record(branch, project, path: Path, data_release, downloaded_utc, extra=None):
    rec = {
        "branch": branch,
        "project_id": project,
        "path": str(path),
        "md5": file_md5(path),
        "downloaded_utc": downloaded_utc,
        "data_release": data_release,
        "size": path.stat().st_size,
    }
    if extra:
        rec.update(extra)
    return rec


def write_download_detail(status, branches, file_rows):
    """A/B 跑完后把每个落盘文件的 md5、下载日期、GDC data release 写到 ClinicDatasets/gdc_download_detail.json。
    分两次跑 A、B 时，按 branch+path 覆盖，其余记录保留。"""
    detail = load_download_detail()
    now = datetime.now(timezone.utc).isoformat()
    detail["updated_utc"] = now
    detail["data_release"] = status.get("data_release")
    detail["data_release_version"] = status.get("data_release_version")
    detail["gdc_status"] = status
    seen = set(detail.get("branches") or [])
    seen.update(branches)
    detail["branches"] = sorted(seen)
    replace = {(r.get("branch"), r.get("path")) for r in file_rows}
    kept = [r for r in (detail.get("files") or []) if (r.get("branch"), r.get("path")) not in replace]
    detail["files"] = kept + file_rows
    DETAIL_PATH.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    ver = status.get("data_release_version") or {}
    ver_s = ".".join(str(ver[k]) for k in ("major", "minor") if k in ver) or "?"
    print(f"  data release: {status.get('data_release', status)}  (v{ver_s})")
    print(f"  明细 {len(file_rows)} 个文件 -> {DETAIL_PATH}")
    return detail


# ---------------------------------------------------------------- 项目清单

def split_names(value):
    """把 --program 的逗号/空白分隔拆成名字列表。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        names = []
        for item in value:
            names.extend(split_names(item))
        return names
    parts = []
    for chunk in str(value).replace(";", ",").split(","):
        parts.extend(chunk.split())
    return [p.strip() for p in parts if p.strip()]


def list_projects(sess, program=None):
    """按 program 名取 project。token 也可以是 project_id，因此 CPTAC-3,TARGET 这种混写能用。
    program=all 或空列表表示全部 GDC。"""
    payload = {"fields": "project_id,program.name", "format": "JSON", "size": 2000}
    hits = api_post(sess, "projects", payload)["data"]["hits"]
    catalog = []
    for h in hits:
        catalog.append({
            "project_id": h["project_id"],
            "program": ((h.get("program") or {}).get("name")) or "",
        })
    names = split_names(program)
    if not names or any(n.lower() == "all" for n in names):
        return sorted(h["project_id"] for h in catalog)

    program_names = {h["program"] for h in catalog if h["program"]}
    project_ids = {h["project_id"] for h in catalog}
    wanted_programs, wanted_projects, unknown = set(), set(), []
    for name in names:
        if name in program_names:
            wanted_programs.add(name)
        elif name in project_ids:
            wanted_projects.add(name)
        else:
            unknown.append(name)
    if unknown:
        raise SystemExit(
            "[program] 无法识别: " + ", ".join(unknown) + "\n"
            "  可用 program: " + ", ".join(sorted(program_names)) + "\n"
            "  project 示例: " + ", ".join(sorted(project_ids)[:8]) + " ..."
        )
    selected = [
        h["project_id"] for h in catalog
        if h["program"] in wanted_programs or h["project_id"] in wanted_projects
    ]
    return sorted(selected)


def count_cases(sess, projects):
    payload = {
        "filters": {"op": "in", "content": {"field": "project.project_id", "value": projects}},
        "size": 0,
    }
    return api_post(sess, "cases", payload)["data"]["pagination"]["total"]

# ---------------------------------------------------------- A: portal JSON

def api_form_post(sess, endpoint, data):
    """门户下载走 form-urlencoded，不是 JSON body。JSON body + attachment 只会得到残缺响应。"""
    r = sess.post(f"{API}/{endpoint}", data=data, timeout=sess.request_timeout)
    r.raise_for_status()
    return r


def load_clinical_fields(sess):
    r = sess.get(f"{API}/cases/_mapping", timeout=sess.request_timeout)
    r.raise_for_status()
    mapping = r.json()
    fields = []
    for name in mapping.get("fields") or []:
        if name.startswith(CLINICAL_SKIP_PREFIXES):
            continue
        if name in CLINICAL_CASE_FIELDS or name.startswith(CLINICAL_PREFIXES):
            fields.append(name)
    if not fields:
        raise SystemExit("[A] /cases/_mapping 没有返回可用的 clinical 字段")
    return fields


def parse_case_list(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        hits = ((payload.get("data") or {}).get("hits"))
        if isinstance(hits, list):
            return hits
    raise TypeError(f"unexpected JSON type: {type(payload).__name__}")


def clinical_json_filename(project):
    return f"{project}.json"


def download_clinical_json(sess, project, fields, dest: Path, expected=None, verbose=True):
    """按 GDC 门户同样的附件接口拉 clinical JSON，原样落盘。"""
    filters = json.dumps({
        "op": "in",
        "content": {"field": "project.project_id", "value": [project]},
    })
    collected = []
    bodies = []
    frm = 0
    while True:
        data = {
            "filters": filters,
            "fields": ",".join(fields),
            "format": "JSON",
            "pretty": "true",
            "size": str(GDC_CASES_PAGE),
            "from": str(frm),
            "attachment": "true",
            "filename": f"clinical.project-{project.lower()}.json",
        }
        r = api_form_post(sess, "cases", data)
        body = r.content or b""
        if body.strip() in (b"", b"["):
            raise RuntimeError(f"{project}: GDC 返回空附件（{len(body)} bytes）")
        chunk = parse_case_list(r.json())
        collected.extend(chunk)
        bodies.append(body)
        if verbose:
            shown = expected if expected is not None else "?"
            print(f"    {project}: {len(collected)}/{shown}", end="\r", flush=True)
        if len(chunk) < GDC_CASES_PAGE:
            break
        if expected is not None and len(collected) >= expected:
            break
        frm += GDC_CASES_PAGE

    dest.parent.mkdir(parents=True, exist_ok=True)
    if len(bodies) == 1:
        dest.write_bytes(bodies[0])
    else:
        dest.write_text(json.dumps(collected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if expected is not None and len(collected) != expected:
        print(f"    [warn] {project} 取回 {len(collected)} 条，API 报告 {expected} 条，对不上", file=sys.stderr)
    if verbose:
        print(f"    {project}: {len(collected)} 例 -> {dest.name}      ")
    return collected


# ------------------------------------------------------------ B: Biotab

def biotab_filters(project):
    """三个条件把同源的 BCR XML 和病理报告 PDF 全排除掉。"""
    return {"op": "and", "content": [
        {"op": "in", "content": {"field": "cases.project.project_id", "value": [project]}},
        {"op": "in", "content": {"field": "data_category", "value": ["Clinical"]}},
        {"op": "in", "content": {"field": "data_type", "value": ["Clinical Supplement"]}},
        {"op": "in", "content": {"field": "data_format", "value": ["BCR Biotab"]}},
        {"op": "in", "content": {"field": "access", "value": ["open"]}},
    ]}


def query_biotab_files(sess, project):
    payload = {
        "filters": biotab_filters(project),
        # 不要在 fields 里写 cases.*：project 级文件关联全部病例，会返回几百条重复行
        "fields": "file_id,file_name,file_size,md5sum",
        "format": "JSON",
        "size": 500,
    }
    return api_post(sess, "files", payload)["data"]["hits"]


def download_files(sess, file_ids, dest: Path, chunk=40):
    """/data 的行为：一个 id 返回原文件，多个 id 返回 tar.gz 打包。必须分别处理，
    否则你会拿到一个后缀 .tar.gz 其实是纯文本的文件。"""
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for i in range(0, len(file_ids), chunk):
        batch = file_ids[i:i + chunk]
        r = api_post(sess, "data", {"ids": batch}, raw=True)
        body = r.content
        if body[:2] == b"\x1f\x8b":                       # gzip magic -> tar.gz
            with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tf:
                for m in tf.getmembers():
                    if not m.isfile() or m.name.endswith("MANIFEST.txt"):
                        continue
                    name = Path(m.name).name
                    data = tf.extractfile(m).read()
                    (dest / name).write_bytes(data)
                    written.append(name)
        else:                                             # 单文件，文件名在响应头里
            cd = r.headers.get("Content-Disposition", "")
            m = re.search(r'filename=["\']?([^"\';]+)', cd)
            name = m.group(1) if m else f"{batch[0]}.txt"
            (dest / name).write_bytes(body)
            written.append(name)
        time.sleep(0.3)
    return written


def biotab_header(path: Path):
    """BCR Biotab 的 TSV 有三行表头：机器名 / 显示名 / CDE_ID，数据从第 4 行开始。
    直接 pd.read_csv 会把后两行当成数据。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = [f.readline().rstrip("\n") for _ in range(3)]
    cols = lines[0].split("\t")
    n_header = 3 if (len(lines) > 2 and lines[2].upper().startswith("CDE_ID")) else 1
    return cols, n_header


def read_biotab(path):
    """给你自己后面用的读取函数：自动跳过多余表头。"""
    path = Path(path)
    _, n_header = biotab_header(path)
    skip = list(range(1, n_header)) if n_header > 1 else None
    return pd.read_csv(path, sep="\t", skiprows=skip, dtype=str, low_memory=False)


def inventory_biotab(root: Path):
    rows = []
    for proj_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for f in sorted(proj_dir.glob("*.txt")):
            try:
                cols, n_header = biotab_header(f)
                with open(f, encoding="utf-8", errors="replace") as fh:
                    n_lines = sum(1 for _ in fh)
                rows.append({
                    "project_id": proj_dir.name,
                    "file_name": f.name,
                    "table": re.sub(r"^nationwidechildrens\.org_", "", f.stem),
                    "n_columns": len(cols),
                    "n_rows": max(n_lines - n_header, 0),
                    "columns": ";".join(cols),
                })
            except Exception as e:
                rows.append({"project_id": proj_dir.name, "file_name": f.name,
                             "table": f.stem, "n_columns": None, "n_rows": None,
                             "columns": f"[read error] {e}"})
    return pd.DataFrame(rows)

# ----------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="批量下载 GDC 临床数据（只下 clinic）")
    ap.add_argument("--projects", nargs="+", help="指定 project_id，如 TCGA-LIHC TCGA-LUAD；给了这个就不走 --program")
    ap.add_argument(
        "--program", default="TCGA",
        help="按 program 取全部 project，逗号分隔，默认 TCGA。all 表示全部 GDC；也接受 project_id，如 CPTAC-3,TARGET",
    )
    ap.add_argument("--skip-indexed", action="store_true", help="跳过 A：不下门户 clinical JSON")
    ap.add_argument("--skip-biotab", action="store_true")
    ap.add_argument("--raw-only", action="store_true",
                    help="B 只落原始 biotab，不写字段清单；A 本身就是原始 JSON")
    ap.add_argument("--manifest-only", action="store_true", help="只出 gdc-client manifest，不下文件")
    ap.add_argument("--cdr", help=argparse.SUPPRESS)  # 旧开关，A 不再出拉平表
    ap.add_argument("--page-size", type=int, default=100, help=argparse.SUPPRESS)
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--dry-run", action="store_true", help="只报计数，不下载")
    args = ap.parse_args()

    if args.cdr:
        print("[warn] --cdr 已失效：A 现在只下载门户 clinical JSON，不再生成 clinical_indexed.csv", file=sys.stderr)

    sess = make_session(retries=args.retries, timeout=args.timeout)

    status = get_data_release(sess)
    print(f"GDC status: {status.get('data_release', status)}")

    projects = args.projects or list_projects(sess, program=args.program)
    print(f"project 数: {len(projects)}")

    if args.dry_run:
        total = count_cases(sess, projects)
        print(f"病例总数: {total}")
        print("A 将按 project 各下一份门户 clinical JSON")
        for p in projects:
            files = query_biotab_files(sess, p)
            size = sum(f.get("file_size", 0) for f in files)
            n = count_cases(sess, [p])
            print(f"  {p:<18} cases {n:>5}    biotab 文件 {len(files):>3} 个, {size/1e6:.1f} MB")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ran_branches = []
    file_rows = []
    downloaded_utc = datetime.now(timezone.utc).isoformat()
    data_release = status.get("data_release")
    run_meta = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "gdc_status": status,
        "projects": projects,
        "args": {k: v for k, v in vars(args).items() if k != "cdr"},
    }

    # ---------- A: portal clinical JSON
    if not args.skip_indexed:
        print("\n[A] portal clinical JSON")
        fields = load_clinical_fields(sess)
        run_meta["n_clinical_json_fields"] = len(fields)
        n_ok = 0
        for p in projects:
            dest = RAW_JSON_DIR / clinical_json_filename(p)
            expected = count_cases(sess, [p])
            hits = download_clinical_json(sess, p, fields, dest, expected=expected)
            run_meta.setdefault("n_cases_per_project", {})[p] = len(hits)
            file_rows.append(file_record(
                "A", p, dest, data_release, downloaded_utc,
                extra={"n_cases": len(hits)},
            ))
            n_ok += 1
        print(f"  -> {n_ok} 个 JSON  -> {RAW_JSON_DIR}")
        ran_branches.append("A")

    # ---------- B: BCR Biotab
    if not args.skip_biotab:
        print("\n[B] BCR Biotab")
        biotab_root = BIOTAB_DIR
        manifest_rows = []
        for p in projects:
            hits = query_biotab_files(sess, p)
            for h in hits:
                manifest_rows.append({"id": h["file_id"], "filename": h["file_name"],
                                      "md5": h.get("md5sum", ""), "size": h.get("file_size", ""),
                                      "state": "released", "project_id": p})
            if args.manifest_only:
                print(f"  {p:<18} {len(hits):>3} 个文件（未下载）")
                continue
            if not hits:
                print(f"  {p:<18} 无 Biotab 文件")
                continue
            names = download_files(sess, [h["file_id"] for h in hits], biotab_root / p)
            by_name = {h["file_name"]: h for h in hits}
            for name in names:
                path = biotab_root / p / name
                meta = by_name.get(name) or {}
                extra = {"file_id": meta.get("file_id"), "gdc_md5": meta.get("md5sum")}
                file_rows.append(file_record(
                    "B", p, path, data_release, downloaded_utc, extra=extra,
                ))
            print(f"  {p:<18} {len(names):>3} 个文件")

        if manifest_rows:
            mdf = pd.DataFrame(manifest_rows)
            mdf.to_csv(OUT_DIR / "biotab_manifest.txt", sep="\t", index=False)
            run_meta["n_biotab_files"] = len(mdf)

        if biotab_root.exists() and not args.raw_only:
            inv = inventory_biotab(biotab_root)
            inv.to_csv(OUT_DIR / "biotab_field_inventory.csv", index=False, encoding="utf-8-sig")
            print(f"  -> biotab_field_inventory.csv  {len(inv)} 张表")

    if not args.skip_biotab:
        ran_branches.append("B")

    write_download_detail(status, ran_branches, file_rows)

    (OUT_DIR / "run_metadata.json").write_text(
        json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成。输出在 {OUT_DIR}")


if __name__ == "__main__":
    main()
