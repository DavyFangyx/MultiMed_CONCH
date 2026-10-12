"""Test_3 两臂对照:bank-only 字段集登记 + 切片编码(2026-10-07 口径)。

句式模板(template.csv)已退役,编码统一走 field bank 切片路径:
  臂 B  = 论文方案 fields.json ∩ landmark_0 bank → 登记(只留 bank 内字段,遗漏记 meta)
  臂 C   = 贪婪最优子集(result.json)→ 同登记
  编码   = 按字段索引切片 bank 嵌入矩阵,零 CONCH 重编码

landmark/bank 变体(两个 tag,不可互相替换;对应 --landmark_time 值域):
  landmark_0   :outputs/{ds}/field_bank/prompt/landmark_0/(mask 开 t_hi≤0,去泄露口径,主)
  raw          :outputs/{ds}/field_bank/prompt/raw/(mask 关 + 与 landmark_0 完全相同的
                kept_fields,时间轴对照专用;"论文组合 × 无 mask 对照"用这个;
                旧产物线 outputs/_raw/{ds}/field_bank/prompt/no_mask 兼容读取,
                no_mask 即"landmark off = 取值不裁剪"的规范 tag — 原 static_only 更名)

产物:
  templates/manual_schemes/{name}/fields.json + Test_3_meta.json(无 template.csv)
  outputs/{ds}/A_manual/{name}/landmark_0/embeddings/pt/{patient}.pt  shape=(k, 512)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import Test_3_common as C  # noqa: E402

BANK_TEMPLATES = ROOT / "templates" / "field_bank"
BANK_OUTPUTS = ROOT / "outputs"
RAW_BANK_OUTPUTS = ROOT / "outputs" / "_raw"
A_TEMPLATES = ROOT / "templates" / "manual_schemes"
SCHEMES_JSON = A_TEMPLATES / "schemes.json"
LANDMARK_TAG = f"landmark_{C.LANDMARK_TIME}"

BANK_VARIANTS = ("landmark_0", "raw")


def bank_variant_dir(dataset: str, variant: str) -> Path:
    """bank 变体 → bank 根目录。两个 tag 互不替换(见模块 docstring)。

    raw 的 canonical 目录 = outputs/{ds}/field_bank/prompt/raw/(主线合并后的新位置);
    旧产物线 outputs/_raw/.../no_mask(landmark off 规范 tag)尚未迁移,保守策略:
    canonical 不存在时兼容读取旧位置(二者同为 mask 关 + landmark_0 kept_fields)。"""
    if variant == "landmark_0":
        return BANK_OUTPUTS / dataset / "field_bank" / "prompt" / "landmark_0"
    if variant == "raw":
        canonical = BANK_OUTPUTS / dataset / "field_bank" / "prompt" / "raw"
        if canonical.is_dir():
            return canonical
        legacy = RAW_BANK_OUTPUTS / dataset / "field_bank" / "prompt" / "no_mask"
        if legacy.is_dir():
            return legacy
        raise SystemExit(
            f"[test_3] 缺 raw bank(找过 {canonical} 与旧产物线 {legacy});"
            f"请先跑 run_field_bank --landmark_time raw 或迁移 outputs/_raw")
    raise SystemExit(f"[test_3] 未知 bank 变体: {variant!r};可用: {BANK_VARIANTS}")


def load_bank_templates(dataset: str, landmark_tag: str = LANDMARK_TAG) -> dict[str, str]:
    """bank 模板表(与 prompt bank 同源);缺表时报错而非静默回落。

    注意:这里的 landmark_tag 是模板表目录名(landmark_0 等),不用于区分
    raw/no_mask 的字段口径(两者模板语义见模块 docstring)。"""
    path = BANK_TEMPLATES / dataset / landmark_tag / "FIELD_BANK.csv"
    if not path.exists():
        raise SystemExit(f"[test_3] 缺 {landmark_tag} bank 模板表: {path}")
    df = pd.read_csv(path)
    tpl: dict[str, str] = {}
    for _, row in df.iterrows():
        sentence = str(row.get("template", "") or "").strip()
        if sentence:
            tpl[str(row["field"]).strip()] = sentence
    return tpl


def load_bank_field_list(dataset: str, variant: str = "landmark_0") -> list[str]:
    """bank 字段集(与嵌入矩阵行序一致);field_index.json 的 fields。

    variant ∈ {"landmark_0", "raw"}(两个 tag,不可互换)。"""
    path = bank_variant_dir(dataset, variant) / "field_index.json"
    if not path.exists():
        raise SystemExit(f"[test_3] 缺 bank field_index.json: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    fields = [str(f).strip() for f in data.get("fields", [])]
    if not fields:
        raise SystemExit(f"[test_3] {path} 的 fields 为空")
    return fields


def load_scheme(scheme: str) -> list[str]:
    """工作方案字段登记(fields.json;句式模板已退役,不读 template.csv)。"""
    fields_path = A_TEMPLATES / scheme / "fields.json"
    if not fields_path.exists():
        raise SystemExit(f"[test_3] 方案 {scheme} 不存在于 templates/manual_schemes/")
    cfg = json.loads(fields_path.read_text(encoding="utf-8"))
    fields = [str(f).strip() for f in cfg.get("fields", [])]
    if not fields:
        raise SystemExit(f"[test_3] 方案 {scheme} 的 fields 为空")
    return fields


def load_greedy_fields(result_json: Path, *, kind: str = "ksig") -> tuple[list[str], str]:
    """读搜索 result.json 的字段子集(2026-10-09 口径订正)。

    kind="ksig" = recommended_subset(gain-only δ=0.005 参考点,主);
    kind="best" = best_subset(历史任意步最优,附录变体;缺失时回退 recommended)。
    """
    if not Path(result_json).exists():
        raise SystemExit(f"[test_3] 缺搜索 result.json: {result_json}")
    data = json.loads(Path(result_json).read_text(encoding="utf-8"))
    if kind == "best":
        subset = data.get("best_subset") or data.get("recommended_subset")
    else:
        subset = data.get("recommended_subset") or data.get("best_subset")
    if not subset:
        raise SystemExit(f"[test_3] result.json 缺 recommended_subset/best_subset: {result_json}")
    algo = data.get("algorithm", "greedy")
    return [str(f).strip() for f in subset], algo


def register_scheme(name: str, schemes_json: Path = SCHEMES_JSON) -> bool:
    """把方案名登记进 schemes.json 的 _schemes(幂等);manual pipeline 只加载名单内的方案。"""
    payload = json.loads(schemes_json.read_text(encoding="utf-8"))
    names = list(payload.get("_schemes") or [])
    if name in names:
        return False
    names.append(name)
    payload["_schemes"] = names
    schemes_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def build_scheme(name: str, dataset: str, fields: list[str], bank_fields: list[str],
                 source_note: str, *, register: bool = True,
                 landmark_tag: str = LANDMARK_TAG) -> tuple[Path, list[str]]:
    """bank-only 登记:fields = 原字段集 ∩ bank;bank 外的字段记入 meta.missing_fields。

    不生成 template.csv(句式模板已退役,编码走切片)。"""
    out = A_TEMPLATES / name
    out.mkdir(parents=True, exist_ok=True)
    kept = [f for f in fields if f in bank_fields]
    missing = [f for f in fields if f not in bank_fields]
    if not kept:
        raise SystemExit(f"[test_3] 方案 {name} 的字段全部不在 bank 中,无法切片: {fields}")

    fields_json = {
        "description": f"Test_3 对照方案 {name} (来源: {source_note};bank-only,无 template.csv)",
        "prompt_file": "prompts.csv",
        "dirname": name,
        "source": "gdc",
        "fields": kept,
        "datasets": [dataset],
    }
    (out / "fields.json").write_text(
        json.dumps(fields_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "Test_3_meta.json").write_text(
        json.dumps({"dataset": dataset, "name": name, "landmark_tag": landmark_tag,
                    "n_fields_original": len(fields), "n_fields": len(kept),
                    "missing_fields": missing, "source": source_note},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    registered = register_scheme(name) if register else False
    print(f"[test_3] 生成方案 {name}: 原 {len(fields)} 字段 → bank 内 {len(kept)},"
          f" 遗漏 {len(missing)}: {missing}"
          f"{'；已登记 schemes.json' if registered else ''}")
    return out, kept


def materialize_bank_subset(dataset: str, fields: list[str], out_pt_dir: Path | str, *,
                            python_exe: str | Path | None = None,
                            overwrite: bool = False, variant: str = "landmark_0") -> dict:
    """按字段索引切片 bank 嵌入矩阵 → {out_pt_dir}/{patient}.pt,零 CONCH 重编码。

    variant ∈ {"landmark_0", "raw"}(bank 变体 tag,见模块 docstring):
      landmark_0  = mask 开(去泄露口径,主)
      raw         = mask 关 + landmark_0 同字段集(时间轴 B_off 对照;规范 tag = no_mask)
    """
    from greedy.clinic_evaluator import DEFAULT_CONCH_PYTHON
    from greedy.embeddings import materialize_subset_embeddings_with_python

    bank_dir = bank_variant_dir(dataset, variant)
    bank_fields = load_bank_field_list(dataset, variant=variant)
    idx = [bank_fields.index(f) for f in fields if f in bank_fields]
    missing = [f for f in fields if f not in bank_fields]
    if missing:
        raise SystemExit(f"[test_3] 字段不在 bank 中,无法切片: {missing}")
    out_pt_dir = Path(out_pt_dir)
    out_pt_dir.mkdir(parents=True, exist_ok=True)
    # 注意:materialize 的 fields 契约 = 完整 bank 字段表(按 bank 行索引取 metadata),
    # 不能传子集名(子集名列表只有 k 个元素,按 idx 索引会越界)。
    return materialize_subset_embeddings_with_python(
        python_exe or str(DEFAULT_CONCH_PYTHON),
        bank_dir,
        idx,
        out_pt_dir,
        fields=bank_fields,
        overwrite=overwrite,
    )


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Test_3 两臂对照: bank-only 方案登记")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--name", required=True, help="新方案名(如 Test_3_MULTISURV_TCGA-BLCA)")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-scheme", help="工作方案名(臂 B): 字段列表取自该方案 fields.json")
    src.add_argument("--from-greedy", type=Path, help="selection result.json(臂 C)")
    parser.add_argument("--no-register", action="store_true", help="只生成目录, 不登记 schemes.json")
    args = parser.parse_args(argv)

    bank_fields = load_bank_field_list(args.dataset)
    if args.from_scheme:
        fields = load_scheme(args.from_scheme)
        note = f"work={args.from_scheme} bank切片({LANDMARK_TAG})"
    else:
        fields, algo = load_greedy_fields(args.from_greedy)
        note = f"greedy={args.from_greedy} algo={algo} bank切片({LANDMARK_TAG})"
    build_scheme(args.name, args.dataset, fields, bank_fields, note,
                 register=not args.no_register)


if __name__ == "__main__":
    main()
