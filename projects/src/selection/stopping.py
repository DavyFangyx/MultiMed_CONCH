from __future__ import annotations

import math


def paired_wilcoxon_greater(current, best) -> tuple[float, bool]:
    diffs = [float(a) - float(b) for a, b in zip(current, best)]
    if not diffs or all(x == 0 for x in diffs):
        return 1.0, False
    try:
        from scipy.stats import wilcoxon
        value = float(wilcoxon(diffs, alternative="greater", zero_method="wilcox").pvalue)
        if not math.isfinite(value):
            return 1.0, True
        return value, False
    except Exception:
        return 1.0, True


class SigStop:
    def __init__(self, delta=0.005, patience=3):
        self.delta, self.patience = float(delta), int(patience)
        self.k_star, self.best_mean, self.best_folds = 0, 0.5, (0.5,) * 5
        self.count = 0
        self.fallback = False

    def update(self, k: int, mean: float, folds) -> dict:
        gain = float(mean) - self.best_mean
        p, fallback = paired_wilcoxon_greater(folds, self.best_folds)
        self.fallback |= fallback
        meaningful = gain >= self.delta and p < 0.05
        no_improvement = gain < self.delta and p >= 0.05
        if meaningful:
            self.k_star, self.best_mean, self.best_folds, self.count = int(k), float(mean), tuple(folds), 0
        elif no_improvement:
            self.count += 1
        else:
            self.count = 0
        stopped = self.count >= self.patience
        return {"gain": gain, "p": p, "wilcoxon_fallback": fallback, "stopped": stopped,
                "k_sig": max(int(k) - self.patience, 0) if stopped else None}
