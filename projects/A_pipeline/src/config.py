"""Load L0-L5 and paper-scheme configs. FIELD_BANK is not a scheme."""

from __future__ import annotations

import json
from pathlib import Path

from common.datasets import canonical_dataset_name, DATASET_ALIASES
from common.fields import field_output_col


SCHEME_TEMPLATE = {}
SCHEME_PROMPT_FILE = {}
SCHEME_DIRNAME = {}
SCHEME_COLS = {}
SCHEME_FIELDS = {}
SCHEME_DATASETS = {}
SCHEME_CONFIG = {}

RESERVED_SCHEME_NAMES = {"FIELD_BANK"}

DEFAULT_TEXT_SCHEMES = ["L0", "L1", "L2", "L3", "L4", "L5"]
D_SCHEME_BY_TEXT_SCHEME = {
    "L0": "D0",
    "L1": "D1",
    "L2": "D2",
    "L3": "D3",
    "L4": "D4",
    "L5": "D5",
}


def reset_scheme_registry() -> None:
    SCHEME_TEMPLATE.clear()
    SCHEME_PROMPT_FILE.clear()
    SCHEME_DIRNAME.clear()
    SCHEME_COLS.clear()
    SCHEME_FIELDS.clear()
    SCHEME_DATASETS.clear()
    SCHEME_CONFIG.clear()


def _normalize_bound_datasets(raw) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        values = [raw]
    else:
        values = list(raw)
    seen = []
    for name in values:
        name = str(name).strip()
        if not name:
            continue
        canonical = DATASET_ALIASES.get(name, name)
        if canonical not in seen:
            seen.append(canonical)
    return seen


def _register_scheme(name: str, cfg: dict, source: Path) -> None:
    fields = list(cfg["fields"])
    if not fields:
        raise ValueError(f"方案 '{name}' 的 fields 为空。")
    if len(fields) != len(set(fields)):
        raise ValueError(f"方案 '{name}' 的 fields 有重复。")
    output_cols = [field_output_col(field) for field in fields]
    template_file = cfg.get("template_file") or f"{name}/template.csv"
    prompt_file = cfg.get("prompt_file", "prompts.csv")
    dirname = cfg.get("dirname", name)
    datasets = _normalize_bound_datasets(cfg.get("datasets"))
    SCHEME_TEMPLATE[name] = template_file
    SCHEME_PROMPT_FILE[name] = prompt_file
    SCHEME_DIRNAME[name] = dirname
    SCHEME_COLS[name] = output_cols
    SCHEME_FIELDS[name] = fields
    SCHEME_DATASETS[name] = datasets
    SCHEME_CONFIG[name] = {
        "fields": fields,
        "output_cols": output_cols,
        "datasets": datasets,
        "source": str(source),
    }


def _load_scheme_dir(scheme_dir: Path, name: str) -> dict:
    fields_file = scheme_dir / "fields.json"
    template_file = scheme_dir / "template.csv"
    if not fields_file.exists():
        raise ValueError(f"方案 '{name}' 缺少 {fields_file}")
    if not template_file.exists():
        raise ValueError(f"方案 '{name}' 缺少 {template_file}")
    with open(fields_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if "fields" not in cfg:
        raise ValueError(f"{fields_file.name} 缺少 fields")
    cfg["template_file"] = f"{name}/template.csv"
    cfg.setdefault("prompt_file", "prompts.csv")
    cfg.setdefault("dirname", name)
    return cfg


def load_custom_schemes(template_dir: str) -> None:
    template_path = Path(template_dir)
    cfg_file = template_path / "schemes.json"
    if not cfg_file.exists():
        cfg_file = template_path / "custom_schemes.json"
    if not cfg_file.exists():
        return

    with open(cfg_file, "r", encoding="utf-8") as f:
        custom: dict = json.load(f)

    skipped = []
    loaded = []
    if "_schemes" in custom:
        names = list(custom["_schemes"])
        for name in names:
            if name in RESERVED_SCHEME_NAMES:
                skipped.append(name)
                continue
            scheme_dir = template_path / name
            cfg = _load_scheme_dir(scheme_dir, name)
            _register_scheme(name, cfg, scheme_dir / "fields.json")
            loaded.append(name)
    else:
        for name, cfg in custom.items():
            if name.startswith("_"):
                continue
            if name in RESERVED_SCHEME_NAMES:
                skipped.append(name)
                continue
            required_keys = {"template_file", "prompt_file", "dirname", "fields"}
            missing = required_keys - cfg.keys()
            if missing:
                raise ValueError(f"{cfg_file.name} 中方案 '{name}' 缺少必要字段: {missing}")
            _register_scheme(name, cfg, cfg_file)
            loaded.append(name)

    if loaded:
        print(f"[方案配置] 已加载 {len(loaded)} 个: {loaded}  （来自 {cfg_file}）")
    if skipped:
        print(
            f"[方案配置] 已忽略 {skipped}；FIELD_BANK 不属于 A_pipeline。"
        )


def resolve_scheme_names(scheme: str) -> list[str]:
    if scheme == "FIELD_BANK":
        raise ValueError(
            "FIELD_BANK 不属于 A_pipeline。可用方案是 L0-L5 以及论文方案。"
        )
    known = list(SCHEME_CONFIG.keys())
    if scheme == "all":
        missing = [name for name in DEFAULT_TEXT_SCHEMES if name not in SCHEME_CONFIG]
        if missing:
            raise ValueError(f"方案配置缺少默认 L0-L5: {missing}")
        return list(DEFAULT_TEXT_SCHEMES)
    if scheme not in SCHEME_CONFIG:
        raise ValueError(f"未知方案: '{scheme}'。已注册方案: {sorted(known)}")
    return [scheme]


def scheme_bound_datasets(scheme: str) -> list[str] | None:
    text_scheme = scheme
    for src, dst in D_SCHEME_BY_TEXT_SCHEME.items():
        if scheme == dst:
            text_scheme = src
            break
    return SCHEME_DATASETS.get(text_scheme)


def scheme_applies_to_dataset(scheme: str, dataset_name: str | None, datasets: dict | None = None) -> bool:
    bound = scheme_bound_datasets(scheme)
    if bound is None:
        return True
    if not dataset_name:
        return True
    canonical = canonical_dataset_name(dataset_name, datasets or {})
    canonical = DATASET_ALIASES.get(canonical, canonical)
    return canonical in bound


def schemes_for_dataset(schemes: list[str], dataset_name: str | None, datasets: dict | None = None) -> list[str]:
    return [scheme for scheme in schemes if scheme_applies_to_dataset(scheme, dataset_name, datasets)]


def resolve_scheme_template_file(scheme: str, template_dir: str) -> Path:
    return Path(template_dir) / SCHEME_TEMPLATE[scheme]
