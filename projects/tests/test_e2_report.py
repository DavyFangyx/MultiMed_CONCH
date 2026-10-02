from pathlib import Path
import json
import sys


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from selection.report import aggregate_seed_records, seed_record


def _make_seed_dir(tmp_path, *, dataset="TCGA-BRCA", modality="mlp_clinic_flatten",
                   algorithm="A2_greedy", seed=0) -> Path:
    seed_dir = tmp_path / f"seed_{seed}"
    seed_dir.mkdir()
    (seed_dir / "result.json").write_text(
        json.dumps({
            "algorithm": algorithm,
            "seed": seed,
            "recommended_subset": ["f0"],
            "recommended_k": 1,
            "recommended_cv_c_mean": 0.66,
            "recommended_cv_folds": [0.6, 0.7, 0.65, 0.68, 0.67],
            "best_subset": ["f0"],
            "best_cv_c_mean": 0.66,
            "logical_evals": 3,
            "physical_trains": 3,
            "cache_hits": 0,
            "proposal_count": 3,
            "wall_ms": 100,
            "stop_reason": "budget",
            "metadata": {},
        }),
        encoding="utf-8",
    )
    (seed_dir / "run_config.json").write_text(
        json.dumps({
            "dataset": dataset,
            "landmark_tag": "landmark_0",
            "modality": modality,
            "seed": seed,
            "fields": ["f0", "f1"],
            "restricted_anchor": False,
        }),
        encoding="utf-8",
    )
    (seed_dir / "evaluations.jsonl").write_text(
        json.dumps({"subset": ["f0"], "status": "ok", "cv_c_mean": 0.66,
                    "logical_eval_idx": 0, "physical_cache_hit": False, "wall_ms": 100}) + "\n",
        encoding="utf-8",
    )
    return seed_dir


def test_seed_record_and_aggregate_carry_modality(tmp_path):
    record = seed_record(_make_seed_dir(tmp_path, modality="clinic_cox"))
    assert record["modality"] == "clinic_cox"
    assert record["dataset"] == "TCGA-BRCA"
    assert record["algorithm"] == "A2_greedy"
    aggregate = aggregate_seed_records([record])
    assert aggregate["modality"] == "clinic_cox"


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        test_seed_record_and_aggregate_carry_modality(Path(tmp))
    print("ok")
