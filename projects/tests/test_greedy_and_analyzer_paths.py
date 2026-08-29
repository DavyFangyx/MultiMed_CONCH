from pathlib import Path
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ANALYZER = ROOT / "Clinic_Analyzer"
for path in (SRC, ANALYZER):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dataset_deployment.registry import clinic_embedding_dir, resolve_clinic_eval_job
from greedy.data import load_field_bank
from greedy.embeddings import materialize_subset_embeddings, subset_embedding_dir


def _make_pt_dir(root: Path) -> Path:
    pt_dir = root / "embeddings" / "pt"
    pt_dir.mkdir(parents=True, exist_ok=True)
    return pt_dir


def test_resolve_field_bank_prompt_job(tmp_path):
    clinic_dir = _make_pt_dir(tmp_path / "TCGA-BRCA" / "field_bank" / "prompt")
    job = resolve_clinic_eval_job(clinic_dir)
    assert job["display_name"] == "TCGA-BRCA"
    assert job["scheme"] == "prompt"
    assert job["study"] == "tcga_brca"
    assert job["run_name"] == "tcga_brca__prompt"


def test_resolve_greedy_subset_job(tmp_path):
    clinic_dir = _make_pt_dir(tmp_path / "TCGA_LIHC" / "greedy" / "onehot" / "subsets" / "G3_deadbeef12")
    job = resolve_clinic_eval_job(clinic_dir)
    assert job["display_name"] == "TCGA_LIHC"
    assert job["scheme"] == "G3_deadbeef12"
    assert job["study"] == "tcga_lihc"
    assert job["run_name"] == "tcga_lihc__G3_deadbeef12"


def test_resolve_rejects_a_manual(tmp_path):
    clinic_dir = _make_pt_dir(tmp_path / "TCGA-READ" / "A_manual" / "L4")
    with pytest.raises(ValueError, match="field_bank"):
        resolve_clinic_eval_job(clinic_dir)


def test_default_clinic_embedding_dir_is_field_bank_prompt():
    path = clinic_embedding_dir("tcga_lihc")
    assert path.parts[-5:] == ("TCGA_LIHC", "field_bank", "prompt", "embeddings", "pt")


def test_subset_embedding_dir_uses_greedy_encoding():
    path = subset_embedding_dir("TCGA_LIHC", "G2_abc", Path("/tmp/outputs"), encoding="onehot")
    assert path.as_posix().endswith("TCGA_LIHC/greedy/onehot/subsets/G2_abc/embeddings/pt")
    assert "B_scan" not in path.as_posix()


def test_load_field_bank_prefers_index_encoding(tmp_path):
    bank = tmp_path / "custom_bank"
    _make_pt_dir(bank)
    (bank / "field_index.json").write_text(json.dumps({"encoding": "onehot", "fields": ["a", "b"]}))
    loaded = load_field_bank(bank)
    assert loaded["encoding"] == "onehot"
    assert loaded["fields"] == ["a", "b"]


def test_load_field_bank_uses_dirname_when_index_omits_encoding(tmp_path):
    bank = tmp_path / "prompt"
    _make_pt_dir(bank)
    (bank / "field_index.json").write_text(json.dumps({"fields": ["a"]}))
    loaded = load_field_bank(bank)
    assert loaded["encoding"] == "prompt"


def test_materialize_onehot_keeps_2d(tmp_path):
    torch = pytest.importorskip("torch")
    bank = tmp_path / "onehot"
    src = _make_pt_dir(bank)
    torch.save(torch.arange(28).reshape(4, 7).float(), src / "TCGA-XX-0001.pt")
    out = tmp_path / "subset" / "pt"
    materialize_subset_embeddings(bank, [0, 2], out)
    sliced = torch.load(out / "TCGA-XX-0001.pt", map_location="cpu")
    assert tuple(sliced.shape) == (2, 7)
    assert sliced.dim() == 2


def test_materialize_prompt_tensor_keeps_512(tmp_path):
    torch = pytest.importorskip("torch")
    bank = tmp_path / "prompt"
    src = _make_pt_dir(bank)
    matrix = torch.arange(4 * 512).reshape(4, 512).float()
    torch.save(matrix, src / "TCGA-XX-0001.pt")
    out = tmp_path / "subset" / "pt"
    materialize_subset_embeddings(bank, [0, 2], out)
    sliced = torch.load(out / "TCGA-XX-0001.pt", map_location="cpu")
    assert tuple(sliced.shape) == (2, 512)


def test_materialize_prompt_dict_payload_keeps_512(tmp_path):
    torch = pytest.importorskip("torch")
    bank = tmp_path / "prompt"
    src = _make_pt_dir(bank)
    payload = {
        "matrix": torch.arange(4 * 512).reshape(4, 512).float(),
        "mask": torch.ones(4),
        "patient_id": "TCGA-XX-0001",
    }
    torch.save(payload, src / "TCGA-XX-0001.pt")
    out = tmp_path / "subset" / "pt"
    materialize_subset_embeddings(bank, [1, 3], out)
    sliced = torch.load(out / "TCGA-XX-0001.pt", map_location="cpu")
    assert tuple(sliced.shape) == (2, 512)


if __name__ == "__main__":
    pytest.main([__file__])
