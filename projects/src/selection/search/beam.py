from __future__ import annotations

from .base import Searcher, finish, score
from ..types import BudgetExhausted


class BeamSearcher(Searcher):
    name = "A3_beam"
    def __init__(self, width=8): self.width = int(width)

    def run(self, evaluator, bank, rng):
        fields = tuple(bank); beam = [frozenset()]; best, best_score = (), 0.5; reason = "field_space_exhausted"; evaluator.proposal_count = 0
        try:
            for _ in range(len(fields)):
                candidates = {state | {f} for state in beam for f in fields if f not in state}
                if not candidates: break
                scored = []
                for subset in sorted(candidates, key=lambda s: tuple(sorted(s))):
                    evaluator.proposal_count += 1; result = evaluator.evaluate(subset)
                    if score(result) != float("-inf"): scored.append((subset, result))
                if not scored: break
                scored.sort(key=lambda sr: (-score(sr[1]), tuple(sorted(sr[0]))))
                beam = [s for s, _ in scored[:self.width]]
                if score(scored[0][1]) > best_score: best, best_score = tuple(sorted(scored[0][0])), score(scored[0][1])
        except BudgetExhausted: reason = "budget_exhausted"
        return finish(self, evaluator, getattr(evaluator, "seed", 0), best, best_score, reason)


A3BeamSearcher = BeamSearcher
