"""Materialize a field subset as Clinic_Analyzer-ready clinic embeddings."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def subset_scheme_name(subset_idx) -> str:
    idx = [int(i) for i in list(subset_idx)]
    key = ",".join(str(i) for i in sorted(idx))
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:10]
    return f"G{len(idx)}_{digest}"


def subset_embedding_dir(dataset: str, scheme: str, embeddings_root: Path, encoding: str = "prompt") -> Path:
    from common.paths import validate_encoding

    encoding = validate_encoding(encoding)
    return Path(embeddings_root) / dataset / "greedy" / encoding / "subsets" / scheme / "embeddings" / "pt"


def _as_matrix(obj):
    import torch

    if isinstance(obj, dict):
        if "matrix" in obj:
            tensor = obj["matrix"]
        elif "features" in obj:
            tensor = obj["features"]
        else:
            tensor = next(v for v in obj.values() if hasattr(v, "dim"))
    else:
        tensor = obj
    tensor = tensor.detach().cpu().float() if hasattr(tensor, "detach") else tensor
    if tensor.dim() == 1:
        tensor = tensor.unsqueeze(0)
    if tensor.dim() != 2:
        raise ValueError(f"unsupported field-bank tensor shape: {tuple(tensor.shape)}")
    return tensor


def materialize_subset_embeddings(
    field_bank_dir: Path | str,
    subset_idx,
    out_pt_dir: Path | str,
    fields: list[str] | None = None,
    overwrite: bool = False,
) -> dict:
    """Slice field-bank rows into a raw [n_subset, 512] .pt per patient.

    Clinic_Analyzer expects .../{scheme}/embeddings/pt/{case_id}.pt
    as a tensor, not the field-bank dict payload.
    """
    import torch

    bank = Path(field_bank_dir)
    if (bank / "embeddings" / "pt").is_dir():
        src_dir = bank / "embeddings" / "pt"
    elif (bank / "pt").is_dir():
        src_dir = bank / "pt"
    else:
        src_dir = bank
    paths = sorted(src_dir.glob("*.pt"))
    if not paths:
        raise FileNotFoundError(f"no field-bank .pt files under {src_dir}")

    idx = [int(i) for i in list(subset_idx)]
    if not idx:
        raise ValueError("cannot materialize an empty subset")

    out_pt_dir = Path(out_pt_dir)
    out_pt_dir.mkdir(parents=True, exist_ok=True)
    existing = list(out_pt_dir.glob("*.pt"))
    if existing and not overwrite and len(existing) == len(paths):
        return {
            "clinic_dir": str(out_pt_dir),
            "n_patients": len(existing),
            "n_fields": len(idx),
            "skipped": True,
        }

    n_saved = 0
    feat_dim = None
    for src in paths:
        matrix = _as_matrix(torch.load(src, map_location="cpu"))
        if max(idx) >= matrix.shape[0]:
            raise IndexError(f"subset idx {idx} out of range for {src} with {matrix.shape[0]} fields")
        sliced = matrix[idx]
        feat_dim = int(sliced.shape[1])
        torch.save(sliced.contiguous(), out_pt_dir / src.name)
        n_saved += 1

    meta = {
        "subset_idx": idx,
        "fields": [fields[i] for i in idx] if fields else idx,
        "n_patients": n_saved,
        "n_fields": len(idx),
        "feat_dim": feat_dim,
        "source_field_bank": str(src_dir),
    }
    with open(out_pt_dir.parent / "fields.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return {"clinic_dir": str(out_pt_dir), "skipped": False, **meta}


def materialize_subset_embeddings_with_python(
    python_exe: str | Path,
    field_bank_dir: Path | str,
    subset_idx,
    out_pt_dir: Path | str,
    fields: list[str] | None = None,
    overwrite: bool = False,
) -> dict:
    try:
        import torch  # noqa: F401

        return materialize_subset_embeddings(
            field_bank_dir, subset_idx, out_pt_dir, fields=fields, overwrite=overwrite
        )
    except Exception:
        payload = {
            "field_bank_dir": str(field_bank_dir),
            "subset_idx": [int(i) for i in list(subset_idx)],
            "out_pt_dir": str(out_pt_dir),
            "fields": list(fields or []),
            "overwrite": bool(overwrite),
        }
        proc = subprocess.run(
            [str(python_exe), str(Path(__file__).resolve()), json.dumps(payload)],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "failed to materialize subset embeddings:\n"
                + (proc.stderr or proc.stdout or "")
            )
        return json.loads(proc.stdout.strip().splitlines()[-1])


def main(argv=None):
    raw = (argv or sys.argv[1:])[0]
    payload = json.loads(raw)
    result = materialize_subset_embeddings(
        payload["field_bank_dir"],
        payload["subset_idx"],
        payload["out_pt_dir"],
        fields=payload.get("fields") or None,
        overwrite=bool(payload.get("overwrite", False)),
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
