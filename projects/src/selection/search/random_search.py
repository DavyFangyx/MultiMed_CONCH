from __future__ import annotations

from .base import Searcher, finish, score
from ..types import BudgetExhausted


class RandomSearcher(Searcher):
    name, is_stochastic = "A1_random", True

    def run(self, evaluator, bank, rng) :
        fields = tuple(bank); proposed = set(); best, best_score = (), 0.5
        evaluator.proposal_count = 0
        try:
            while len(proposed) < (2 ** len(fields) - 1):
                k = int(rng.integers(1, len(fields) + 1))
                subset = frozenset(rng.choice(fields, size=k, replace=False).tolist())
                evaluator.proposal_count += 1
                if subset in proposed: continue
                proposed.add(subset)
                result = evaluator.evaluate(subset)
                if score(result) > best_score: best, best_score = tuple(sorted(subset)), score(result)
        except (BudgetExhausted, ValueError):
            reason = "budget_exhausted" if evaluator.logical_evals >= evaluator.budget else "candidate_pool_exhausted"
        return finish(self, evaluator, getattr(evaluator, "seed", 0), best, best_score, reason)


A1RandomSearcher = RandomSearcher
