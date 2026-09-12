from __future__ import annotations

import math
import numpy as np
from .base import Searcher, finish, score
from ..types import BudgetExhausted


class AnnealingSearcher(Searcher):
    name = "A4_anneal"
    def run(self, evaluator, bank, rng):
        fields = tuple(bank); p = len(fields); evaluator.proposal_count = 0; history = []; proposed = set(); best, best_score = (), .5
        if not fields:
            return finish(self, evaluator, getattr(evaluator, "seed", 0), (), .5, "field_space_exhausted")
        current = frozenset(rng.choice(fields, size=int(rng.integers(1, p + 1)), replace=False).tolist())
        temp = 1e-3; no_improve = 0; reason = "budget_exhausted"
        attempts = 0
        try:
            cur_result = evaluator.evaluate(current); cur_score = score(cur_result); history.append(cur_score)
            if cur_score > best_score: best, best_score = tuple(sorted(current)), cur_score
            while True:
                attempts += 1
                if attempts > max(1000, 20 * (2 ** p)):
                    reason = "candidate_pool_exhausted"
                    break
                # Use a valid one-flip or swap proposal.
                if rng.random() < .2 and current and len(current) < p:
                    out = rng.choice(list(current)); inn = rng.choice([f for f in fields if f not in current]); proposal = frozenset((set(current)-{out})|{inn})
                else:
                    f = rng.choice(fields); proposal = frozenset((set(current)-{f}) if f in current and len(current)>1 else (set(current)|{f}))
                if proposal in proposed: continue
                proposed.add(proposal); evaluator.proposal_count += 1
                result = evaluator.evaluate(proposal); value = score(result)
                if value == float("-inf"): continue
                delta = value - cur_score; history.append(abs(delta));
                if len(history) == 51: temp = np.median(history[1:]) / math.log(2) or 1e-3
                accept = delta >= 0 or rng.random() < math.exp(min(0.0, delta / max(temp, 1e-12)))
                if accept: current, cur_score = proposal, value
                if value > best_score: best, best_score, no_improve = tuple(sorted(proposal)), value, 0
                else: no_improve += 1
                temp *= .995
                if no_improve >= 200:
                    current = best; no_improve = 0
        except BudgetExhausted: pass
        return finish(self, evaluator, getattr(evaluator, "seed", 0), best, best_score, reason)


A4AnnealingSearcher = AnnealingSearcher
