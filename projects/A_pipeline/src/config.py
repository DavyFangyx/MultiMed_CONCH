"""Load L0-L5 scheme configs. FIELD_BANK is not a scheme."""

from __future__ import annotations

import json
from pathlib import Path


SCHEME_TEMPLATE = {}
SCHEME_PROMPT_FILE = {}
SCHEME_DIRNAME = {}
SCHEME_COLS = {}
SCHEME_CONFIG = {}

RESERVED_SCHEME_NAMES = {"FIELD_BANK"}


def reset_scheme_registry() -> None:
    SCHEME_TEMPLATE.clear()
    SCHEME_PROMPT_FILE.clear()
    SCHEME_DIRNAME.clear()
    SCHEME_COLS.clear()
    SCHEME_CONFIG.clear()


def load_custom_schemes(template_dir: str) -> None:
    template_path = Path(template_dir)
    cfg_file = template_path / "schemes.json"
    if not cfg_file.exists():
        cfg_file = template_path / "custom_schemes.json"
    if not cfg_file.exists():
        return

    with open(cfg_file, "r", encoding="utf-8") as f:
        custom: dict = json.load(f)

    required_keys = {
        "template_file",
        "prompt_file",
        "dirname",
        "template_cols",
        "placeholders",
        "output_cols",
    }
    skipped = []
    for name, cfg in custom.items():
        if name.startswith("_"):
            continue
        if name in RESERVED_SCHEME_NAMES:
            skipped.append(name)
            continue
        missing = required_keys - cfg.keys()
        if missing:
            raise ValueError(f"{cfg_file.name} 中方案 '{name}' 缺少必要字段: {missing}")
        if not (len(cfg["template_cols"]) == len(cfg["placeholders"]) == len(cfg["output_cols"])):
            raise ValueError(
                f"方案 '{name}' 的 template_cols / placeholders / output_cols 长度不一致。"
            )
        SCHEME_TEMPLATE[name] = cfg["template_file"]
        SCHEME_PROMPT_FILE[name] = cfg["prompt_file"]
        SCHEME_DIRNAME[name] = cfg["dirname"]
        SCHEME_COLS[name] = list(cfg["output_cols"])
        SCHEME_CONFIG[name] = {
            "template_cols": list(cfg["template_cols"]),
            "placeholders": list(cfg["placeholders"]),
            "output_cols": list(cfg["output_cols"]),
        }

    loaded = [k for k in custom.keys() if not k.startswith("_") and k not in RESERVED_SCHEME_NAMES]
    if loaded:
        print(f"[方案配置] 已加载 {len(loaded)} 个: {loaded}  （来自 {cfg_file}）")
    if skipped:
        print(
            f"[方案配置] 已忽略 {skipped}；FIELD_BANK 不属于 A_pipeline。"
        )


def resolve_scheme_names(scheme: str) -> list[str]:
    if scheme == "FIELD_BANK":
        raise ValueError(
            "FIELD_BANK 不属于 A_pipeline。可用方案是 L0-L5。"
        )
    known = list(SCHEME_CONFIG.keys())
    if scheme == "all":
        return known
    if scheme not in SCHEME_CONFIG:
        raise ValueError(f"未知方案: '{scheme}'。已注册方案: {sorted(known)}")
    return [scheme]


def resolve_scheme_template_file(scheme: str, template_dir: str) -> Path:
    return Path(template_dir) / SCHEME_TEMPLATE[scheme]
