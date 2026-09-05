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
    clinic_dir = _make_pt_dir(tmp_path / "TCGA-BRCA" / "field_bank" / "prompt" / "landmark_365")
    job = resolve_clinic_eval_job(clinic_dir)
    assert job["display_name"] == "TCGA-BRCA"
    assert job["scheme"] == "prompt__landmark_365"
    assert job["encoding"] == "prompt"
    assert job["landmark_tag"] == "landmark_365"
    assert job["study"] == "tcga_brca"
    assert job["run_name"] == "tcga_brca__prompt__landmark_365"


def test_resolve_greedy_subset_job(tmp_path):
    clinic_dir = _make_pt_dir(tmp_path / "TCGA_LIHC" / "greedy" / "onehot" / "landmark_none" / "subsets" / "G3_deadbeef12")
    job = resolve_clinic_eval_job(clinic_dir)
    assert job["display_name"] == "TCGA_LIHC"
    assert job["scheme"] == "onehot__landmark_none__G3_deadbeef12"
    assert job["encoding"] == "onehot"
    assert job["landmark_tag"] == "landmark_none"
    assert job["study"] == "tcga_lihc"
    assert job["run_name"] == "tcga_lihc__onehot__landmark_none__G3_deadbeef12"


def test_resolve_scheme_run_tag_job(tmp_path):
    clinic_dir = _make_pt_dir(tmp_path / "TCGA-READ" / "schemes" / "landmark_730_L2")
    job = resolve_clinic_eval_job(clinic_dir)
    assert job["display_name"] == "TCGA-READ"
    assert job["scheme"] == "landmark_730_L2"
    assert job["encoding"] == "L2"
    assert job["landmark_tag"] == "landmark_730"
    assert job["study"] == "tcga_read"
    assert job["run_name"] == "tcga_read__landmark_730_L2"


def test_resolve_rejects_a_manual(tmp_path):
    clinic_dir = _make_pt_dir(tmp_path / "TCGA-READ" / "A_manual" / "L4")
    with pytest.raises(ValueError, match="field_bank"):
        resolve_clinic_eval_job(clinic_dir)


def test_resolve_longitudinal_field_bank_job(tmp_path):
    clinic_dir = _make_pt_dir(tmp_path / "TCGA-BRCA" / "longitudinal" / "field_bank" / "prompt" / "landmark_365")
    job = resolve_clinic_eval_job(clinic_dir)
    assert job["display_name"] == "TCGA-BRCA"
    assert job["scheme"] == "longitudinal__prompt__landmark_365"
    assert job["encoding"] == "prompt"
    assert job["landmark_tag"] == "landmark_365"
    assert job["study"] == "tcga_brca"
    assert job["run_name"] == "tcga_brca__longitudinal__prompt__landmark_365"


def test_resolve_longitudinal_greedy_subset_job(tmp_path):
    clinic_dir = _make_pt_dir(
        tmp_path / "TCGA_LIHC" / "longitudinal" / "greedy" / "onehot" / "landmark_none" / "subsets" / "G3_deadbeef12"
    )
    job = resolve_clinic_eval_job(clinic_dir)
    assert job["display_name"] == "TCGA_LIHC"
    assert job["scheme"] == "longitudinal__onehot__landmark_none__G3_deadbeef12"
    assert job["encoding"] == "onehot"
    assert job["landmark_tag"] == "landmark_none"
    assert job["run_name"] == "tcga_lihc__longitudinal__onehot__landmark_none__G3_deadbeef12"


def test_default_clinic_embedding_dir_is_field_bank_prompt():
    path = clinic_embedding_dir("tcga_lihc", landmark_tag="landmark_365")
    assert path.parts[-6:] == ("TCGA_LIHC", "field_bank", "prompt", "landmark_365", "embeddings", "pt")


def test_subset_embedding_dir_uses_greedy_encoding():
    path = subset_embedding_dir("TCGA_LIHC", "G2_abc", Path("/tmp/outputs"), encoding="onehot", landmark_tag="landmark_none")
    assert path.as_posix().endswith("TCGA_LIHC/greedy/onehot/landmark_none/subsets/G2_abc/embeddings/pt")
    assert "B_scan" not in path.as_posix()


def test_subset_embedding_dir_uses_longitudinal_experiment():
    path = subset_embedding_dir(
        "TCGA_LIHC",
        "G2_abc",
        Path("/tmp/outputs"),
        encoding="prompt",
        landmark_tag="landmark_365",
        experiment="longitudinal",
    )
    assert path.as_posix().endswith(
        "TCGA_LIHC/longitudinal/greedy/prompt/landmark_365/subsets/G2_abc/embeddings/pt"
    )


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


def test_materialize_longitudinal_tokens_per_field(tmp_path):
    torch = pytest.importorskip("torch")
    bank = tmp_path / "prompt"
    src = _make_pt_dir(bank)
    (bank / "field_index.json").write_text(json.dumps({"encoding": "prompt", "tokens_per_field": 2, "fields": ["a", "b"]}))
    torch.save(torch.arange(4 * 512).reshape(4, 512).float(), src / "TCGA-XX-0001.pt")
    out = tmp_path / "subset" / "pt"
    materialize_subset_embeddings(bank, [1], out)
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
