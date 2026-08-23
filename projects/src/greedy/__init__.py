
"""Nested-CV greedy forward selection scheduler (stage C, 4.2-4.5)."""

from .evaluator import CachedEvaluator, EvaluatorLike, StubEvaluator, extract_c_index
from .protocol import run_nested_greedy
from .search import greedy_forward

from .clinic_evaluator import ClinicSubsetEvaluator
from .splits import FoldSplit, NestedSplitConfig, build_nested_splits, load_nested_splits, save_nested_splits
from .stability import plot_selection_frequency, selection_frequency, write_selection_frequency
from .stopping import apply_stopping_rules

__all__ = [
    "CachedEvaluator",
    "EvaluatorLike",
    "FoldSplit",

    "ClinicSubsetEvaluator",
    "NestedSplitConfig",
    "StubEvaluator",
    "apply_stopping_rules",
    "build_nested_splits",
    "extract_c_index",
    "greedy_forward",
    "load_nested_splits",
    "run_nested_greedy",
    "save_nested_splits",
    "selection_frequency",
    "write_selection_frequency",
    "plot_selection_frequency",
]
