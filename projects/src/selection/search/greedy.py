from __future__ import annotations

from .base import Searcher, finish, score
from ..stopping import SigStop
from ..types import BudgetExhausted


class GreedySearcher(Searcher):
    name = "A2_greedy"

    def __init__(self, delta=0.005, patience=3): self.delta, self.patience = delta, patience

    def run(self, evaluator, bank, rng):
        fields = tuple(bank); selected = []; best, best_score = (), 0.5; stop = SigStop(self.delta, self.patience)
        prefixes = {0: ()}; stop_path = []
        evaluator.proposal_count = 0; reason = "field_space_exhausted"
        try:
            while len(selected) < len(fields):
                candidates = [frozenset(selected + [f]) for f in fields if f not in selected]
                scored = []
                for subset in candidates:
                    evaluator.proposal_count += 1
                    result = evaluator.evaluate(subset); scored.append((subset, result))
                    current_score = score(result)
                    if current_score > best_score:
                        best, best_score = tuple(result.subset), current_score
                valid = [(s, r) for s, r in scored if score(r) != float("-inf")]
                if not valid: reason = "evaluation_error"; break
                subset, result = sorted(valid, key=lambda sr: (-score(sr[1]), tuple(sorted(sr[0]))))[0]
                added = min(set(subset) - set(selected))
                selected.append(added); current = score(result)
                prefixes[len(selected)] = tuple(result.subset)
                state = stop.update(len(selected), current, result.cv_folds)
                stop_path.append({"k": len(selected), "subset": list(result.subset), **state})
                if state["stopped"]:
                    reason = "sig_stop"
                    ksig = state["k_sig"] or 0
                    recommended = prefixes[ksig]
                    metadata = {**state, "sig_stop_path": stop_path}
                    return finish(self, evaluator, getattr(evaluator, "seed", 0), best, best_score, reason, recommended, metadata)
        except BudgetExhausted:
            reason = "budget_exhausted"
        metadata = {"k_star": stop.k_star, "wilcoxon_fallback": stop.fallback, "sig_stop_path": stop_path}
        return finish(self, evaluator, getattr(evaluator, "seed", 0), best, best_score, reason,
                      prefixes.get(stop.k_star, ()), metadata)


A2GreedySearcher = GreedySearcher
