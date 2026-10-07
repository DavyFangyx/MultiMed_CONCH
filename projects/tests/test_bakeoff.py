"""Test_6 bake-off 分析:比较性 GT / gap / 胜率 / AUC / catchup / decide(合成数据)。"""

import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "src"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from selection.bakeoff import (COMPETING_ALGOS, anytime_auc, catchup_evals,
                               comparative_gt, decide, gap_table, mean_rank_table,
                               win_rate_vs_greedy)

DATASETS = ("TCGA-GBM", "TCGA-LGG", "TCGA-PAAD")
COMPETITORS = tuple(COMPETING_ALGOS)


def _seed_dir(tmp_path, dataset, algo, best, budget=100):
    """写一个最小 seed 目录(evaluations.jsonl 只有一行 = best),返回 record。"""
    seed_dir = tmp_path / f"{dataset}__{algo}" / "seed_0"
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "evaluations.jsonl").write_text(json.dumps({
        "subset": ["f"], "status": "ok", "cv_c_mean": best,
        "logical_eval_idx": 1, "physical_cache_hit": False, "wall_ms": 1,
    }) + "\n", encoding="utf-8")
    return {"dataset": dataset, "landmark_tag": "landmark_0",
            "modality": "mlp_clinic_flatten", "algorithm": algo, "seed": 0,
            "best_cv_c_mean": best, "budget": budget, "seed_dir": str(seed_dir)}


def _records(tmp_path, per_dataset):
    """per_dataset: {dataset: {algo: best}} → 展开成 record 列表。"""
    records = []
    for dataset, scores in per_dataset.items():
        for algo, best in scores.items():
            records.append(_seed_dir(tmp_path, dataset, algo, best))
    return records


def test_comparative_gt_picks_best_competing_algorithm(tmp_path):
    records = _records(tmp_path, {
        "TCGA-GBM": {"A2_greedy": 0.66, "A1_random": 0.60, "SEAS": 0.68},
        "TCGA-LGG": {"A2_greedy": 0.70, "A3_beam": 0.72},
    })
    gt = comparative_gt(records)
    assert gt[("TCGA-GBM", "landmark_0", "mlp_clinic_flatten")]["gt_algo"] == "SEAS"
    assert abs(gt[("TCGA-GBM", "landmark_0", "mlp_clinic_flatten")]["gt_c"] - 0.68) < 1e-12
    assert gt[("TCGA-LGG", "landmark_0", "mlp_clinic_flatten")]["gt_algo"] == "A3_beam"


def test_gap_table_marks_references_and_excludes_them_from_gt(tmp_path):
    records = _records(tmp_path, {
        "TCGA-GBM": {"A2_greedy": 0.66, "SEAS": 0.68, "A0_full": 0.70},
    })
    rows = gap_table(records)
    by_algo = {row["algorithm"]: row for row in rows}
    assert abs(by_algo["SEAS"]["gap_to_best"]) < 1e-12          # SEAS 即 GT
    assert abs(by_algo["A2_greedy"]["gap_to_best"] - 0.02) < 1e-12
    assert by_algo["A0_full"]["reference"] is True
    assert abs(by_algo["A0_full"]["gap_to_best"] - (-0.02)) < 1e-12  # 高于 GT(参考行不参与竞争)


def test_win_rate_vs_greedy_pairs_per_instance(tmp_path):
    records = _records(tmp_path, {
        "TCGA-GBM": {"A2_greedy": 0.66, "A1_random": 0.60, "SEAS": 0.68},
        "TCGA-LGG": {"A2_greedy": 0.70, "A1_random": 0.72, "SEAS": 0.69},
        "TCGA-PAAD": {"A2_greedy": 0.75, "A1_random": 0.74, "SEAS": 0.77},
    })
    rows = {row["algorithm"]: row for row in win_rate_vs_greedy(records)}
    assert rows["A1_random"]["n_wins"] == 1 and rows["A1_random"]["n_instances"] == 3
    assert abs(rows["A1_random"]["mean_difference"] - (-0.06 + 0.02 - 0.01) / 3) < 1e-12
    assert rows["SEAS"]["n_wins"] == 2
    assert "A2_greedy" not in rows


def test_anytime_auc_and_catchup_evals(tmp_path):
    evals_path = tmp_path / "evals.jsonl"
    evals_path.write_text("".join(
        json.dumps({"subset": ["f"], "status": "ok", "cv_c_mean": value,
                    "logical_eval_idx": idx, "physical_cache_hit": False, "wall_ms": 1}) + "\n"
        for idx, value in [(1, 0.5), (2, 0.6), (3, 0.55)]
    ), encoding="utf-8")
    evals = [json.loads(line) for line in evals_path.read_text(encoding="utf-8").splitlines()]
    auc = anytime_auc(evals, budget=4)
    # 曲线 (1,.5)(2,.6)(3,.6)(4,.6):面积 .55+.6+.6=1.75,/4=0.4375
    assert abs(auc - 1.75 / 4) < 1e-12
    assert catchup_evals(evals, 0.59) == 2
    assert catchup_evals(evals, 0.61) is None


def test_mean_rank_and_auc_tiebreak(tmp_path):
    records = _records(tmp_path, {
        "TCGA-GBM": {"A2_greedy": 0.66, "A1_random": 0.60, "SEAS": 0.68},
        "TCGA-LGG": {"A2_greedy": 0.70, "A1_random": 0.62, "SEAS": 0.74},
    })
    ranks, per_instance = mean_rank_table(records)
    by_algo = {row["algorithm"]: row for row in ranks}
    assert by_algo["SEAS"]["mean_rank"] == 1.0
    assert by_algo["A2_greedy"]["mean_rank"] == 2.0
    assert by_algo["SEAS"]["n_first"] == 2
    assert per_instance[("TCGA-GBM", "landmark_0", "mlp_clinic_flatten")]["SEAS"] == 1.0


def test_decide_greedy_wins_when_no_meaningful_advantage(tmp_path):
    records = _records(tmp_path, {
        ds: {"A2_greedy": 0.66, "A1_random": 0.60, "SEAS": 0.65} for ds in DATASETS
    })
    decision = decide(records)
    assert decision["greedy_wins"] is True
    assert decision["ambiguous"] is False
    assert decision["winner"] == "A2_greedy"
    assert decision["best_competitor_advantage"] < 0
    assert decision["run_seas_ablations"] is True   # SEAS 平均 rank 第 2


def test_decide_competitor_wins_above_delta(tmp_path):
    records = _records(tmp_path, {
        ds: {"A2_greedy": 0.66, "SEAS": 0.67, "A4_anneal": 0.64} for ds in DATASETS
    })
    decision = decide(records)
    assert decision["greedy_wins"] is False
    assert decision["ambiguous"] is False
    assert decision["winner"] == "SEAS"
    assert decision["best_competitor_advantage"] >= decision["delta"]
    assert decision["run_seas_ablations"] is True
    assert decision["per_instance_winner"]["TCGA-PAAD/landmark_0/mlp_clinic_flatten"] == "SEAS"


def test_decide_ambiguous_when_advantage_positive_but_below_delta(tmp_path):
    records = _records(tmp_path, {
        ds: {"A2_greedy": 0.66, "SEAS": 0.663} for ds in DATASETS
    })
    decision = decide(records)
    assert decision["ambiguous"] is True
    assert decision["greedy_wins"] is False
    assert 0 < decision["best_competitor_advantage"] < decision["delta"]


def test_decide_reports_no_ablation_signal_without_seas(tmp_path):
    records = _records(tmp_path, {
        "TCGA-GBM": {"A2_greedy": 0.66, "A1_random": 0.60, "A4_anneal": 0.67},
    })
    decision = decide(records)
    assert decision["run_seas_ablations"] is False
    assert decision["seas_rank"] is None
    assert decision["winner"] == "A4_anneal"


def test_decide_empty_records(tmp_path):
    decision = decide([])
    assert decision["winner"] is None
    assert decision["ambiguous"] is True
    assert decision["reason"] == "no_competitor_records"


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn(Path(tmp))
    print("ok")
