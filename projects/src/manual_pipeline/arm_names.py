"""臂方案命名与 bank 定位(F×T 因子口径,2026-10-13 拍板)。

决策依据:
  * 臂是实验原语(arm_registry):F 字段组合 ∈ {work 论文组合, greedy 贪婪最优},
    T 时间口径 ∈ {raw mask 关, lm0 landmark_0}。Test 只是臂的组合。
  * 方案产物按臂条件命名,不按"谁生成/谁先消费"命名——原 Test_3_* 前缀是
    Test_2 被 Test_3 工具链污染的根因。
  * 训练时解析(用户拍板):不物化切片文件,analyzer 读 bank 的 field_index.json
    按字段名单取列;conf 只携带(bank 根 + 字段名单来源 + bank 指纹)。

命名:
  work_raw_{work}_{ds}      报告值臂(论文组合 × mask 关,数据源 = raw bank no_mask)
  work_lm0_{work}_{ds}      去泄露臂(论文组合 × landmark_0,数据源 = 主 bank landmark_0)
  greedy_lm0_{ds}           可达臂(贪婪推荐子集 × landmark_0;ksig 口径)
  greedy_lm0_best_{ds}      可达臂 best 子集变体
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from common.paths import (
    LANDMARK_OFF_TAG,
    PROJECT_ROOT,
    dataset_field_bank_dir,
)

T_RAW = "raw"
T_LM0 = "lm0"

ARM_ANALYZER = "mlp_clinic_flatten"     # 可达臂搜索唯一目标模型(E2)
ARM_SEED = 0

_DS_RE = r"TCGA[-_A-Za-z0-9]+"
_WORK_RE = re.compile(rf"^work_(raw|lm0)_(.+)_({_DS_RE})$")
_GREEDY_RE = re.compile(rf"^greedy_(raw|lm0)(_best)?_({_DS_RE})$")


def parse_arm_scheme(scheme: str) -> dict | None:
    """F×T 臂方案名解析;非臂方案(baseline__*/D*/L0-L5/HGCN)返回 None。

    work_lm0_MULTISURV_TCGA-BLCA → {kind: work, t: lm0, work: MULTISURV, dataset: TCGA-BLCA}
    greedy_lm0_TCGA-GBM        → {kind: greedy, t: lm0, kind2: ksig, dataset: TCGA-GBM}
    greedy_raw_TCGA-GBM        → {kind: greedy, t: raw, kind2: ksig, dataset: TCGA-GBM}
    """
    match = _WORK_RE.fullmatch(str(scheme))
    if match:
        return {"kind": "work", "t": match.group(1), "work": match.group(2), "dataset": match.group(3)}
    match = _GREEDY_RE.fullmatch(str(scheme))
    if match:
        return {
            "kind": "greedy",
            "t": match.group(1),
            "kind2": "best" if match.group(2) else "ksig",
            "dataset": match.group(3),
        }
    return None


def work_scheme_name(work: str, dataset: str, t: str) -> str:
    """论文组合臂的方案名。t: raw | lm0。"""
    if t not in (T_RAW, T_LM0):
        raise ValueError(f"未知时间口径: {t}")
    return f"work_{t}_{work}_{dataset}"


def greedy_scheme_name(dataset: str, *, kind: str = "ksig", t: str = T_LM0) -> str:
    """可达臂方案名。kind: ksig = recommended_subset, best = best_subset;t: lm0 | raw。"""
    if t not in (T_RAW, T_LM0):
        raise ValueError(f"未知时间口径: {t}")
    suffix = "" if kind == "ksig" else "_best"
    return f"greedy_{t}{suffix}_{dataset}"


def template_json(work: str) -> Path:
    """论文方案模板 fields.json(唯一字段名单来源,无 per-dataset 变体)。"""
    return PROJECT_ROOT / "templates" / "manual_schemes" / work / "fields.json"


def greedy_result_json(dataset: str) -> Path:
    """搜索 result.json(可达臂字段名单来源 = recommended_subset)。"""
    return (PROJECT_ROOT / "results" / "greedy_lm0" / "search"
            / dataset / ARM_ANALYZER / f"seed_{ARM_SEED}" / "result.json")


def bank_dir(dataset: str, t: str, encoding: str = "prompt") -> Path:
    """臂的数据源 bank 根(tag 目录,含 field_index.json 与 embeddings/pt)。

    raw:prompt → outputs/_raw/{ds}/field_bank/prompt/no_mask(Test_1a off 臂历史布局);
    raw:onehot → outputs/{ds}/field_bank/onehot/no_mask(run_field_bank 自然落点);
    lm0 一律 → outputs/{ds}/field_bank/{enc}/landmark_0。
    """
    if t == T_RAW:
        if encoding == "onehot":
            return dataset_field_bank_dir(dataset, "onehot", LANDMARK_OFF_TAG)
        return PROJECT_ROOT / "outputs" / "_raw" / dataset / "field_bank" / encoding / LANDMARK_OFF_TAG
    return dataset_field_bank_dir(dataset, encoding, "landmark_0")


def bank_embeddings(bank_root: Path) -> Path:
    """bank 根的 embeddings/pt 目录(conf 的 CLINIC_DIR_PATH 指向这里)。"""
    return Path(bank_root) / "embeddings" / "pt"


def bank_field_index(bank_root: Path) -> Path:
    """bank 根的 field_index.json(tag 目录直属)。"""
    return Path(bank_root) / "field_index.json"


def bank_fingerprint(bank_root: Path) -> str:
    """field_index.json 的字段名单指纹(sha256 前 16 位)。

    用途:enqueue 时写进 conf,训练时对不上即失败——防 bank 重建后
    conf 语义静默漂移(与 cache.sqlite label 哈希同一纪律)。
    """
    index_path = bank_field_index(bank_root)
    if not index_path.exists():
        return ""
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    blob = json.dumps(payload.get("fields") or [], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def resolve_field_indices(bank_root: Path, wanted_fields: list[str]) -> tuple[list[int], list[str]]:
    """字段名单 ∩ bank 字段 → 列位号(保留名单顺序;不在 bank 的字段丢弃)。"""
    index_path = bank_field_index(bank_root)
    if not index_path.exists():
        raise FileNotFoundError(f"bank field_index 缺失: {index_path}")
    bank_fields = json.loads(index_path.read_text(encoding="utf-8"))["fields"]
    keep = [f for f in wanted_fields if f in bank_fields]
    return [bank_fields.index(f) for f in keep], keep


def template_fields(template_json: Path) -> list[str]:
    """论文方案模板 fields.json 的字段名单。"""
    payload = json.loads(Path(template_json).read_text(encoding="utf-8"))
    fields = payload.get("fields")
    if not isinstance(fields, list):
        raise ValueError(f"模板 fields 缺失: {template_json}")
    return [str(f) for f in fields]


def greedy_fields(result_json: Path, *, kind: str = "ksig") -> list[str]:
    """搜索 result.json 的字段子集。kind: ksig = recommended_subset, best = best_subset。"""
    payload = json.loads(Path(result_json).read_text(encoding="utf-8"))
    key = "recommended_subset" if kind == "ksig" else "best_subset"
    fields = payload.get(key) or []
    return [str(f) for f in fields]
