from __future__ import annotations

import numpy as np
from .base import Searcher, finish, score
from ..types import BudgetExhausted


class AntColonySearcher(Searcher):
    name, uses_univariate_prior = "A6_aco", True
    def __init__(self, ants=10, rho=.1): self.ants, self.rho = int(ants), float(rho)
    def run(self, evaluator, bank, rng):
        fields=tuple(bank); p=len(fields); tau=np.ones(p); eta=np.ones(p); best,best_score=(),.5; proposed=set(); evaluator.proposal_count=0; reason="budget_exhausted"
        if not fields:
            return finish(self,evaluator,getattr(evaluator,"seed",0),(),.5,"field_space_exhausted")
        prior=getattr(evaluator,"univariate_scores",None)
        if hasattr(evaluator, "precharge") and evaluator.logical_evals == 0:
            evaluator.precharge(prior)
            evaluator.proposal_count = p
        if prior is not None:
            raw=np.maximum(np.asarray(prior,dtype=float)-.5,0); eta=np.ones(p) if raw.max(initial=0)==raw.min(initial=0) else (raw-raw.min())/(raw.max()-raw.min())
        try:
            while len(proposed) < (2 ** p - 1):
                round_scores=[]
                for _ in range(self.ants):
                    k=int(rng.integers(1,p+1)); available=list(range(p)); chosen=[]
                    for _ in range(k):
                        prob=tau[available]*eta[available]**2; prob=prob/prob.sum() if prob.sum()>0 else np.ones(len(available))/len(available); pick=int(rng.choice(available,p=prob)); chosen.append(pick); available.remove(pick)
                    subset=frozenset(fields[i] for i in chosen)
                    if subset in proposed: continue
                    proposed.add(subset); evaluator.proposal_count+=1; result=evaluator.evaluate(subset); val=score(result)
                    if val!=float("-inf"): round_scores.append((subset,val))
                    if val>best_score: best,best_score=tuple(sorted(subset)),val
                if round_scores:
                    tau *= 1-self.rho; winner=max(round_scores,key=lambda x:x[1]);
                    for f in winner[0]: tau[fields.index(f)]=min(10.,tau[fields.index(f)]+max(winner[1]-.5,0))
                    tau=np.clip(tau,.01,10.)
                elif evaluator.logical_evals>=evaluator.budget: break
        except BudgetExhausted: pass
        return finish(self,evaluator,getattr(evaluator,"seed",0),best,best_score,reason)


A6AntColonySearcher = AntColonySearcher
