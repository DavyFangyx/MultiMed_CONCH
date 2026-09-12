from __future__ import annotations

from .base import Searcher, finish, score
from ..types import BudgetExhausted


class GeneticSearcher(Searcher):
    name = "A5_genetic"
    def __init__(self, population_size=20): self.population_size = int(population_size)
    def run(self, evaluator, bank, rng):
        fields = tuple(bank); p = len(fields); evaluator.proposal_count = 0; proposed = set(); best, best_score = (), .5
        if not fields:
            return finish(self,evaluator,getattr(evaluator,"seed",0),(),.5,"field_space_exhausted")
        population = [frozenset(rng.choice(fields, size=int(rng.integers(1,p+1)), replace=False).tolist()) for _ in range(self.population_size)]
        reason = "candidate_pool_exhausted"
        try:
            while len(proposed) < (2 ** p - 1):
                scored=[]
                for subset in population:
                    if subset in proposed: continue
                    proposed.add(subset); evaluator.proposal_count += 1; result=evaluator.evaluate(subset)
                    if score(result)!=float("-inf"): scored.append((subset,score(result)))
                if not scored: break
                scored.sort(key=lambda x: -x[1])
                if scored[0][1] > best_score: best,best_score=tuple(sorted(scored[0][0])),scored[0][1]
                elites=[s for s,_ in scored[:2]]
                population=list(elites)
                while len(population)<self.population_size:
                    parents=rng.choice(scored[:max(3,min(len(scored),self.population_size))],size=2,replace=True)
                    mask=rng.random(p)<.5; child=frozenset(f for i,f in enumerate(fields) if (f in parents[0][0] if mask[i] else f in parents[1][0]))
                    child=frozenset(f for f in fields if f in child and rng.random()>=1/p)
                    if not child: child=frozenset([rng.choice(fields)])
                    population.append(child)
        except BudgetExhausted: reason="budget_exhausted"
        return finish(self,evaluator,getattr(evaluator,"seed",0),best,best_score,reason)


A5GeneticSearcher = GeneticSearcher
