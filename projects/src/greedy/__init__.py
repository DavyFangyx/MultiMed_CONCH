
"""Nested-CV greedy forward selection scheduler (stage C, 4.2-4.5)."""

from .evaluator import CachedEvaluator, EvaluatorLike, StubEvaluator, extract_c_index
from .protocol import run_nested_greedy
from .search import greedy_forward

from .clinic_evaluator import ClinicSubsetEvaluator
from .splits import FoldSplit, load_analyzer_split_dir
from .stability import plot_selection_frequency, selection_frequency, write_selection_frequency
from .stability import cindex_curve_frame, plot_cindex_curve, write_cindex_curve
from .stopping import apply_stopping_rules

__all__ = [
    "CachedEvaluator",
    "EvaluatorLike",
    "FoldSplit",

    "ClinicSubsetEvaluator",
    "StubEvaluator",
    "apply_stopping_rules",
    "extract_c_index",
    "greedy_forward",
    "load_analyzer_split_dir",
    "run_nested_greedy",
    "selection_frequency",
    "write_selection_frequency",
    "plot_selection_frequency",
    "cindex_curve_frame",
    "write_cindex_curve",
    "plot_cindex_curve",
]
