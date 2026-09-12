from __future__ import annotations

from abc import ABC, abstractmethod

from ..types import BudgetExhausted, SearchResult


class Searcher(ABC):
    name = "search"
    is_stochastic = False
    uses_univariate_prior = False

    @abstractmethod
    def run(self, evaluator, bank, rng) -> SearchResult:
        raise NotImplementedError

    def _result(self, evaluator, seed, best, recommended=None, reason="budget_exhausted", metadata=None):
        recommended = best if recommended is None else recommended
        return SearchResult(self.name, int(seed), tuple(best), float(getattr(evaluator, "best_score", 0.5)),
                            tuple(recommended), reason, int(evaluator.logical_evals),
                            int(getattr(evaluator, "physical_trains", 0)),
                            int(getattr(evaluator, "proposal_count", evaluator.logical_evals)), metadata or {})


def score(result):
    return result.cv_c_mean if result.status == "ok" and result.cv_c_mean is not None else float("-inf")


def finish(searcher, evaluator, seed, best_subset, best_score, reason, recommended=None, metadata=None):
    evaluator.best_score = max(float(best_score), 0.5)
    return SearchResult(searcher.name, int(seed), tuple(best_subset), float(best_score),
                        tuple(best_subset if recommended is None else recommended), reason,
                        int(evaluator.logical_evals), int(getattr(evaluator, "physical_trains", 0)),
                        int(getattr(evaluator, "proposal_count", evaluator.logical_evals)), metadata or {})
