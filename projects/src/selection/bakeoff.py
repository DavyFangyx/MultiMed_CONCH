"""Test_6 搜索算法选型 bake-off:比较性 GT 与判定规则。

口径:GT(ds) = max over 竞争算法 {A1..A6, SEAS} 的预算内历史最佳 cv_c_mean
(比较性 GT,非全局最优;不做 ANCHOR 穷举)。所有函数为纯函数,合成数据可单测。
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from .config import DELTA
from .report import anytime_curve

# 竞争算法(参与 GT 与排名);SEAS 消融 / A0 系参考线不在其中
COMPETING_ALGOS = ("A1_random", "A2_greedy", "A3_beam", "A4_anneal",
                   "A5_genetic", "A6_aco", "SEAS")


def _instance_algo_means(records, competitors=COMPETING_ALGOS):
    """{(dataset, landmark, modality): {algo: mean(best_cv_c_mean across seeds)}}。"""
    grouped = defaultdict(list)
    for row in records:
        if row["algorithm"] not in competitors:
            continue
        grouped[(row["dataset"], row["landmark_tag"], row["modality"],
                 row["algorithm"])].append(float(row["best_cv_c_mean"]))
    out = defaultdict(dict)
    for (dataset, landmark, modality, algo), values in grouped.items():
        out[(dataset, landmark, modality)][algo] = float(np.mean(values))
    return out


def comparative_gt(records, competitors=COMPETING_ALGOS):
    """GT(ds) = 对比算法中预算内最好的历史最佳;平局按算法名字典序。"""
    means = _instance_algo_means(records, competitors)
    gt = {}
    for instance, scores in means.items():
        if not scores:
            continue
        best_algo = max(scores, key=lambda name: (scores[name], _reverse_name(name)))
        gt[instance] = {"gt_c": float(scores[best_algo]), "gt_algo": best_algo}
    return gt


def _reverse_name(name):
    # 平局取字典序更小者:max 用负 name 排序
    return tuple(-ord(ch) for ch in name)


def gap_table(records, competitors=COMPETING_ALGOS):
    """每 (instance, algo) 一行:mean_best、gap_to_best(对比较性 GT)、是否参考行。

    A0/A0b/消融等非竞争算法行标 reference=True,不参与 GT 也不参与排名。
    """
    means = _instance_algo_means(records, competitors)
    gt = comparative_gt(records, competitors)
    rows = []
    grouped = defaultdict(list)
    for row in records:
        grouped[(row["dataset"], row["landmark_tag"], row["modality"],
                 row["algorithm"])].append(float(row["best_cv_c_mean"]))
    for (dataset, landmark, modality, algo), values in sorted(grouped.items()):
        mean_best = float(np.mean(values))
        rows.append({
            "dataset": dataset, "landmark_tag": landmark, "modality": modality,
            "algorithm": algo, "n_seeds": len(values),
            "mean_best_cv_c_mean": mean_best,
            "gap_to_best": (gt[(dataset, landmark, modality)]["gt_c"] - mean_best
                            if (dataset, landmark, modality) in gt else math.nan),
            "reference": algo not in competitors,
        })
    return rows


def win_rate_vs_greedy(records, competitors=COMPETING_ALGOS):
    """每竞争算法对 A2 贪心的实例级配对差(同 instance 内 seeds 取均值)。"""
    means = _instance_algo_means(records, competitors)
    rows = []
    for algo in competitors:
        if algo == "A2_greedy":
            continue
        differences = []
        for instance, scores in means.items():
            if algo in scores and "A2_greedy" in scores:
                differences.append(scores[algo] - scores["A2_greedy"])
        if not differences:
            continue
        wins = sum(value > 0 for value in differences)
        rows.append({
            "algorithm": algo,
            "n_instances": len(differences),
            "n_wins": wins,
            "win_rate": wins / len(differences),
            "mean_difference": float(np.mean(differences)),
        })
    return rows


def anytime_auc(evaluations, budget):
    """anytime 曲线在 [0, budget] 的梯形面积,除以 budget 归一(0..1)。"""
    if budget is None or int(budget) <= 0:
        return math.nan
    points = anytime_curve(evaluations, int(budget))
    area = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        area += (y0 + y1) * (x1 - x0) / 2.0
    return area / int(budget)


def catchup_evals(evaluations, target_cv):
    """追平 target_cv 所需的首个 logical_eval_idx;追不上返回 None。"""
    best = float("-inf")
    for row in sorted(evaluations, key=lambda item: int(item.get("logical_eval_idx", 0))):
        value = row.get("cv_c_mean") if row.get("status") == "ok" else None
        if value is not None and math.isfinite(float(value)):
            best = max(best, float(value))
            if best >= float(target_cv):
                return int(row["logical_eval_idx"])
    return None


def _mean_aucs(records, competitors=COMPETING_ALGOS):
    """{(instance, algo): mean anytime AUC}。"""
    grouped = defaultdict(list)
    for row in records:
        if row["algorithm"] not in competitors:
            continue
        evaluations = _read_jsonl(Path(row["seed_dir"]) / "evaluations.jsonl")
        auc = anytime_auc(evaluations, row.get("budget"))
        if math.isfinite(auc):
            grouped[(row["dataset"], row["landmark_tag"], row["modality"],
                     row["algorithm"])].append(auc)
    return {key: float(np.mean(values)) for key, values in grouped.items()}


def mean_rank_table(records, competitors=COMPETING_ALGOS):
    """每 instance 内按 mean best 排名(1=最优,平局平均名次),跨 instance 平均。"""
    from scipy.stats import rankdata
    means = _instance_algo_means(records, competitors)
    aucs = _mean_aucs(records, competitors)
    per_algo = defaultdict(list)
    per_instance = {}
    for instance, scores in sorted(means.items()):
        names = sorted(scores)
        ranks = rankdata([-scores[name] for name in names], method="average")
        per_instance[instance] = dict(zip(names, map(float, ranks)))
        for name, rank in zip(names, ranks):
            per_algo[name].append(float(rank))
    rows = []
    for algo in sorted(per_algo):
        instances = [inst for inst in per_instance if algo in per_instance[inst]]
        rows.append({
            "algorithm": algo,
            "n_instances": len(instances),
            "mean_rank": float(np.mean(per_algo[algo])),
            "mean_auc": float(np.mean([aucs.get((inst, algo), math.nan)
                                       for inst in instances])),
            "n_first": sum(per_instance[inst][algo] == 1 for inst in instances),
        })
    return rows, per_instance


def decide(records, *, delta=DELTA, competitors=COMPETING_ALGOS):
    """Test_6 判定规则(§2):贪心守住即胜 / 平均优势 ≥ delta 换胜者 / 交错则 ambiguous。

    返回 decision dict(schema 写入 decision.json)。确定性:同输入同输出。
    """
    ranks, per_instance = mean_rank_table(records, competitors)
    rank_by_algo = {row["algorithm"]: row for row in ranks}
    auc_by_algo = {row["algorithm"]: row["mean_auc"] for row in ranks}
    present = sorted(rank_by_algo)
    if not present:
        return {"winner": None, "greedy_wins": False, "ambiguous": True,
                "run_seas_ablations": False, "seas_rank": None,
                "best_competitor_advantage": math.nan, "delta": delta,
                "mean_ranks": {}, "mean_aucs": {}, "per_instance_winner": {},
                "n_instances": 0, "reason": "no_competitor_records"}
    # 胜者:平均 rank 最小;平局按平均 anytime AUC,再平局按名字典序
    non_greedy = [name for name in present if name != "A2_greedy"]
    winner = min(present, key=lambda name: (rank_by_algo[name]["mean_rank"],
                                            -auc_by_algo[name], name))
    best_competitor = min(non_greedy, key=lambda name: (rank_by_algo[name]["mean_rank"],
                                                        -auc_by_algo[name], name)) if non_greedy else None
    # 平均优势:胜者对贪心的实例级配对差均值
    differences = []
    means = _instance_algo_means(records, competitors)
    for instance, scores in means.items():
        if best_competitor and best_competitor in scores and "A2_greedy" in scores:
            differences.append(scores[best_competitor] - scores["A2_greedy"])
    best_adv = float(np.mean(differences)) if differences else math.nan

    seas_rank = rank_by_algo.get("SEAS", {}).get("mean_rank")
    run_ablations = bool(seas_rank is not None and seas_rank <= 2.0)

    if best_competitor is None:
        greedy_wins, ambiguous = True, False
        winner = "A2_greedy"
    elif math.isfinite(best_adv) and best_adv >= delta:
        greedy_wins, ambiguous = False, False
        winner = best_competitor
    elif math.isfinite(best_adv) and best_adv > 0:
        # 优势为正但低于 delta:差距过小且实例间交错 → 升级 6 数据集信号
        greedy_wins, ambiguous = False, True
    else:
        greedy_wins, ambiguous = True, False
        winner = "A2_greedy"

    instance_winner = {tuple(instance): min(scores, key=lambda name: (scores[name], _reverse_name(name)))
                       for instance, scores in per_instance.items()}
    return {
        "winner": winner,
        "greedy_wins": greedy_wins,
        "ambiguous": ambiguous,
        "run_seas_ablations": run_ablations,
        "seas_rank": seas_rank,
        "best_competitor": best_competitor,
        "best_competitor_advantage": best_adv,
        "delta": delta,
        "mean_ranks": {name: rank_by_algo[name]["mean_rank"] for name in present},
        "mean_aucs": {name: auc_by_algo[name] for name in present},
        "per_instance_winner": {"/".join(instance): algo for instance, algo in instance_winner.items()},
        "n_instances": len(means),
        "reason": "",
    }


def _read_jsonl(path):
    rows = []
    if not Path(path).exists():
        return rows
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows
