"""S10a: Clinic_Analyzer 生存指标层（IBS / landmark AUC）回归测试。

对照目标（Clinic_Analyzer/utils/survival_metrics.py 从 SurvPGC_github_init 逐字移植）：
  1. 逐函数等价 - 同一进程内按路径加载两个模块，断言
     interpolate_survival / survival_columns_from_logits / breslow_survival /
     compute_ibs / compute_landmark_aucs 及常量完全一致；
  2. 已知值锚点 - interpolate_survival 的 S(0)=1 / 越过最后边界为 0、线性插值中点，
     breslow_survival 的可手算例子（无事件时恒为 1），
     compute_ibs / compute_landmark_aucs 与直接调用 sksurv 的结果一致；
  3. 守卫语义 - 折随访不足（test_min > 1 或 test_max < 60）时 IBS 为 NaN（不是 0），
     landmark 越界或事件数 < MIN_EVENTS_FOR_AUC 时对应 AUC 为 NaN；
     不可用值一律 NaN，不再静默降级为 0；
  4. 控制流门槛 - 负时间行（BRCA quirk）只从指标路径剔除，
     c-index 保持逐位不变（它参与最优 epoch / optuna 决策），
     且负时间行本身不构成可比对，剔除前后指标完全一致。

环境：需要 sksurv（Clinic_Analyzer 跑在 conda env SurvPGC 下）。
base 3.13 环境没有 sksurv，本文件整体 skip（不产生假失败）。
运行（pytest 仅在 base 环境里，故借 PYTHONPATH 注入）：
  PYTHONPATH=/tmp/s10a_pytest_env \
    /data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python -m pytest tests/test_survival_metrics.py -q
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sksurv")
pytest.importorskip("torch")

from sksurv.metrics import (  # noqa: E402
    cumulative_dynamic_auc,
    integrated_brier_score,
)
from sksurv.util import Surv  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ANALYZER = ROOT / "Clinic_Analyzer"
SURVPGC_METRICS = Path(
    "/data/fangyuxuan/projects/medical_dl/SurvPGC_github_init/utils/survival_metrics.py"
)

if str(ANALYZER) not in sys.path:
    sys.path.insert(0, str(ANALYZER))

# core_utils 实际引用的那个模块实例（utils.survival_metrics），
# 用它做等价性/已知值断言才有意义。
from utils import survival_metrics as clinic_metrics  # noqa: E402


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


orig_metrics = (
    _load_by_path("s10a_survpgc_survival_metrics", SURVPGC_METRICS)
    if SURVPGC_METRICS.exists()
    else None
)
requires_original = pytest.mark.skipif(
    orig_metrics is None, reason=f"SurvPGC 参考实现不存在: {SURVPGC_METRICS}"
)


@pytest.fixture(scope="module")
def calculate_metrics():
    """Clinic_Analyzer/utils/core_utils.py::_calculate_metrics（需要 torch/transformers）。"""
    try:
        from utils.core_utils import _calculate_metrics
    except Exception as exc:  # pragma: no cover - 环境缺失时跳过
        pytest.skip(f"Clinic_Analyzer/utils/core_utils.py 不可导入: {exc}")
    return _calculate_metrics


@pytest.fixture(scope="module")
def core_utils_module():
    try:
        from utils import core_utils
    except Exception as exc:  # pragma: no cover - 环境缺失时跳过
        pytest.skip(f"Clinic_Analyzer/utils/core_utils.py 不可导入: {exc}")
    return core_utils


# --------------------------------------------------------------------------- #
# 合成数据
# --------------------------------------------------------------------------- #

# dataset_factory.bins: [min-eps, q1, q2, q3, max+eps]（4 桶），edges = bins[1:]
DEFAULT_BINS = np.array([-0.0001, 6.0, 24.0, 48.0, 60.0001])
EDGES = DEFAULT_BINS[1:]


def _cohort(seed: int = 101, n: int = 600) -> Surv:
    rng = np.random.default_rng(seed)
    times = rng.uniform(0.1, 90.0, size=n)
    events = rng.random(n) < 0.5
    return Surv.from_arrays(event=events, time=times)


def _make_fold(n: int, seed: int, t_lo: float, t_hi: float, event_frac: float = 0.6):
    """随机折: (times, events, survival_columns, risk)。"""
    rng = np.random.default_rng(seed)
    times = rng.uniform(t_lo, t_hi, size=n)
    events = rng.random(n) < event_frac
    hazards = rng.uniform(0.01, 0.08, size=(n, 4))
    survival = np.cumprod(1.0 - hazards, axis=1)
    risk = -survival.sum(axis=1)
    return times, events, survival, risk


def _call_metrics(
    calculate_metrics,
    times,
    events,
    bin_scores,
    risk,
    cohort,
    train_survival_risks=None,
    bins=DEFAULT_BINS,
):
    """按 _calculate_metrics 的签名喂合成数据（args/loader 已不使用）。"""
    return calculate_metrics(
        None,
        None,
        types.SimpleNamespace(bins=np.asarray(bins, dtype=np.float64)),
        cohort,
        np.asarray(risk, dtype=np.float64),
        (~np.asarray(events, dtype=bool)).astype(np.float64),  # 1 = 删失
        np.asarray(times, dtype=np.float64),
        None if bin_scores is None else np.asarray(bin_scores, dtype=np.float64),
        train_survival_risks,
    )


def _test_surv(times, events) -> Surv:
    return Surv.from_arrays(
        event=np.asarray(events, dtype=bool), time=np.asarray(times, dtype=np.float64)
    )


# --------------------------------------------------------------------------- #
# 1. 与 SurvPGC 参考实现逐函数等价
# --------------------------------------------------------------------------- #


@requires_original
def test_constants_match_original():
    assert np.array_equal(clinic_metrics.IBS_GRID_MONTHS, orig_metrics.IBS_GRID_MONTHS)
    assert clinic_metrics.IBS_GRID_MONTHS[0] == 1.0
    assert clinic_metrics.IBS_GRID_MONTHS[-1] == 60.0
    assert clinic_metrics.AUC_LANDMARK_MONTHS == orig_metrics.AUC_LANDMARK_MONTHS
    assert clinic_metrics.AUC_LANDMARK_MONTHS == [24.0, 60.0]
    assert clinic_metrics.MIN_EVENTS_FOR_AUC == orig_metrics.MIN_EVENTS_FOR_AUC
    assert clinic_metrics.MIN_EVENTS_FOR_AUC == {24.0: 5, 60.0: 6}


@requires_original
def test_survival_columns_from_logits_matches_original():
    rng = np.random.default_rng(0)
    logits = rng.normal(size=(17, 4)) * 2.0
    assert np.allclose(
        clinic_metrics.survival_columns_from_logits(logits),
        orig_metrics.survival_columns_from_logits(logits),
        equal_nan=True,
    )


@requires_original
def test_interpolate_survival_matches_original():
    rng = np.random.default_rng(1)
    columns = np.sort(rng.random((13, 4)), axis=1)[:, ::-1]  # 单调不增的 S(edge_j)
    times = np.array([0.0, 0.5, 6.0, 12.0, 30.5, 48.0, 59.0, 60.0, 61.0, 100.0])
    assert np.allclose(
        clinic_metrics.interpolate_survival(columns, EDGES, times),
        orig_metrics.interpolate_survival(columns, EDGES, times),
        equal_nan=True,
    )


@requires_original
def test_breslow_survival_matches_original():
    rng = np.random.default_rng(2)
    train_times = rng.uniform(0.1, 70.0, size=200)
    train_events = rng.random(200) < 0.6
    train_risks = rng.normal(size=200)
    risks = rng.normal(size=50)
    times = np.array([0.0, 1.0, 12.0, 24.0, 47.5, 60.0, 90.0])
    assert np.allclose(
        clinic_metrics.breslow_survival(train_times, train_events, train_risks, risks, times),
        orig_metrics.breslow_survival(train_times, train_events, train_risks, risks, times),
        equal_nan=True,
    )


@requires_original
def test_compute_ibs_and_landmark_aucs_match_original():
    cohort = _cohort(seed=3)
    times, events, columns, _ = _make_fold(200, seed=4, t_lo=0.4, t_hi=62.0)
    test_surv = _test_surv(times, events)
    estimate_grid = clinic_metrics.interpolate_survival(columns, EDGES, clinic_metrics.IBS_GRID_MONTHS)
    estimate_landmarks = 1.0 - clinic_metrics.interpolate_survival(
        columns, EDGES, np.asarray(clinic_metrics.AUC_LANDMARK_MONTHS)
    )
    assert clinic_metrics.compute_ibs(cohort, test_surv, estimate_grid) == orig_metrics.compute_ibs(
        cohort, test_surv, estimate_grid
    )
    assert clinic_metrics.compute_landmark_aucs(
        cohort, test_surv, estimate_landmarks
    ) == orig_metrics.compute_landmark_aucs(cohort, test_surv, estimate_landmarks)


# --------------------------------------------------------------------------- #
# 2. 已知值锚点
# --------------------------------------------------------------------------- #


def test_survival_columns_from_logits_known_value():
    logits = np.zeros((1, 4))
    assert np.allclose(
        clinic_metrics.survival_columns_from_logits(logits)[0],
        [0.5, 0.25, 0.125, 0.0625],
    )


def test_interpolate_survival_anchors_and_linear_segments():
    columns = np.array([[0.9, 0.7, 0.5, 0.4]])
    edges = np.array([10.0, 20.0, 30.0, 40.0])
    times = np.array([0.0, 5.0, 10.0, 15.0, 40.0, 50.0])
    out = clinic_metrics.interpolate_survival(columns, edges, times)
    # S(0)=1（左锚点）；10-20 中点线性插值；末边界之后为 0
    assert np.allclose(out[0], [1.0, 0.95, 0.9, 0.8, 0.4, 0.0])


def test_breslow_survival_hand_example():
    # 事件时刻 1、3；风险全 0 -> exp(risk)=1
    #   t=1: 风险集 {1,2,3} -> h0 = 1/3
    #   t=3: 风险集 {3}     -> h0 = 1   => H0 = [1/3, 4/3]
    train_times = np.array([1.0, 2.0, 3.0])
    train_events = np.array([True, False, True])
    train_risks = np.zeros(3)
    times = np.array([0.5, 1.0, 2.0, 3.0, 4.0])
    h0_at_times = np.array([0.0, 1.0 / 3.0, 5.0 / 6.0, 4.0 / 3.0, 4.0 / 3.0])

    out = clinic_metrics.breslow_survival(
        train_times, train_events, train_risks, np.zeros(1), times
    )
    assert np.allclose(out[0], np.exp(-h0_at_times))  # S = exp(-H0 * exp(0))

    out2 = clinic_metrics.breslow_survival(
        train_times, train_events, train_risks, np.array([np.log(2.0)]), times
    )
    assert np.allclose(out2[0], np.exp(-2.0 * h0_at_times))  # exp(risk) = 2


def test_breslow_survival_without_events_is_flat_one():
    out = clinic_metrics.breslow_survival(
        np.array([1.0, 2.0]),
        np.array([False, False]),
        np.array([0.3, -0.7]),
        np.array([0.0, 1.0]),
        np.array([0.0, 1.0, 5.0]),
    )
    assert np.allclose(out, np.ones((2, 3)))


def test_compute_ibs_matches_sksurv_direct():
    cohort = _cohort(seed=5)
    times, events, columns, _ = _make_fold(250, seed=6, t_lo=0.4, t_hi=62.0)
    test_surv = _test_surv(times, events)
    estimate = clinic_metrics.interpolate_survival(columns, EDGES, clinic_metrics.IBS_GRID_MONTHS)
    expected = float(
        integrated_brier_score(cohort, test_surv, estimate, clinic_metrics.IBS_GRID_MONTHS)
    )
    assert np.isfinite(expected)  # 合成数据下 IPCW 权重不发散
    assert clinic_metrics.compute_ibs(cohort, test_surv, estimate) == pytest.approx(expected)


def test_compute_landmark_aucs_matches_sksurv_direct():
    cohort = _cohort(seed=7)
    times, events, columns, _ = _make_fold(250, seed=8, t_lo=0.4, t_hi=62.0)
    test_surv = _test_surv(times, events)
    estimate = 1.0 - clinic_metrics.interpolate_survival(
        columns, EDGES, np.asarray(clinic_metrics.AUC_LANDMARK_MONTHS)
    )
    expected, _ = cumulative_dynamic_auc(
        cohort, test_surv, estimate, list(clinic_metrics.AUC_LANDMARK_MONTHS)
    )
    got = clinic_metrics.compute_landmark_aucs(cohort, test_surv, estimate)
    assert got == pytest.approx([float(v) for v in expected])


# --------------------------------------------------------------------------- #
# 3. _calculate_metrics 守卫语义（NaN，不是 0）
# --------------------------------------------------------------------------- #


def test_discrete_supported_fold_matches_module_helpers(calculate_metrics):
    cohort = _cohort(seed=11)
    times, events, columns, risk = _make_fold(400, seed=12, t_lo=0.4, t_hi=62.0)
    c_index, _, BS, IBS, iauc, iauc_list = _call_metrics(
        calculate_metrics, times, events, columns, risk, cohort
    )

    test_surv = _test_surv(times, events)
    estimate_grid = clinic_metrics.interpolate_survival(
        columns, EDGES, clinic_metrics.IBS_GRID_MONTHS
    )
    estimate_landmarks = 1.0 - clinic_metrics.interpolate_survival(
        columns, EDGES, np.asarray(clinic_metrics.AUC_LANDMARK_MONTHS)
    )
    expected_aucs = clinic_metrics.compute_landmark_aucs(
        cohort, test_surv, estimate_landmarks, list(clinic_metrics.AUC_LANDMARK_MONTHS)
    )

    assert np.isfinite(c_index) and 0.0 <= c_index <= 1.0
    assert np.asarray(BS).shape == (len(clinic_metrics.IBS_GRID_MONTHS),)
    assert np.isfinite(IBS)
    assert IBS == pytest.approx(
        clinic_metrics.compute_ibs(cohort, test_surv, estimate_grid)
    )
    assert iauc_list == pytest.approx(expected_aucs)
    assert np.all(np.isfinite(iauc_list))
    assert iauc == pytest.approx(np.mean(expected_aucs))


def test_ibs_is_nan_when_fold_max_below_grid(calculate_metrics):
    cohort = _cohort(seed=13)
    times, events, columns, risk = _make_fold(300, seed=14, t_lo=0.4, t_hi=40.0)
    c_index, _, BS, IBS, iauc, iauc_list = _call_metrics(
        calculate_metrics, times, events, columns, risk, cohort
    )

    assert np.isfinite(c_index)
    assert np.isnan(IBS) and IBS != 0.0  # 不可用 -> NaN，绝不静默归零
    assert float(BS) == 0.0
    # 24 月 landmark 仍在随访区间内且有足够事件 -> 可用；60 月越界 -> NaN
    assert np.isfinite(iauc_list[0])
    assert np.isnan(iauc_list[1])
    assert iauc == pytest.approx(iauc_list[0])


def test_ibs_is_nan_when_fold_min_above_one(calculate_metrics):
    cohort = _cohort(seed=15)
    times, events, columns, risk = _make_fold(300, seed=16, t_lo=3.0, t_hi=62.0)
    _, _, _, IBS, iauc, iauc_list = _call_metrics(
        calculate_metrics, times, events, columns, risk, cohort
    )

    assert np.isnan(IBS)
    assert np.all(np.isfinite(iauc_list))  # 24/60 都在 [3, 62] 内且事件充足
    assert iauc == pytest.approx(np.mean(iauc_list))


def test_auc_nan_when_landmark_events_below_minimum(calculate_metrics):
    cohort = _cohort(seed=17)
    # test_min <= 1 且 test_max > 60 -> IBS 可算；
    # 但 24 月内仅 4 个事件 (< MIN_EVENTS_FOR_AUC[24]=5)，60 月内 12 个事件 (>= 6)
    times = np.concatenate(
        [
            np.array([0.5, 0.8]),  # 删失，保证 test_min <= 1
            np.array([8.0, 15.0, 20.0, 22.0]),  # 4 个早期事件
            np.array([26.0, 30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 59.0]),  # 8 个晚期事件
            np.linspace(24.5, 61.5, 30),  # 晚期删失
        ]
    )
    events = np.concatenate(
        [np.zeros(2, dtype=bool), np.ones(4, dtype=bool), np.ones(8, dtype=bool), np.zeros(30, dtype=bool)]
    )
    rng = np.random.default_rng(18)
    columns = np.cumprod(1.0 - rng.uniform(0.01, 0.08, size=(len(times), 4)), axis=1)
    risk = -columns.sum(axis=1)

    _, _, _, IBS, iauc, iauc_list = _call_metrics(
        calculate_metrics, times, events, columns, risk, cohort
    )

    assert np.isfinite(IBS)
    assert np.isnan(iauc_list[0])  # 事件数不足 -> NaN（不是 0）
    assert np.isfinite(iauc_list[1])
    assert iauc == pytest.approx(iauc_list[1])


def test_auc_all_nan_when_no_landmark_available(calculate_metrics):
    cohort = _cohort(seed=19)
    # 随访上限 20 月：24 / 60 两个 landmark 都越界 -> 全部 NaN
    times, events, columns, risk = _make_fold(200, seed=20, t_lo=0.4, t_hi=20.0)
    _, _, _, IBS, iauc, iauc_list = _call_metrics(
        calculate_metrics, times, events, columns, risk, cohort
    )

    assert np.isnan(IBS)
    assert np.all(np.isnan(iauc_list))
    assert np.isnan(iauc)  # 无任何可用 landmark -> NaN（不是 0）


def test_cox_breslow_path_uses_train_risks(calculate_metrics):
    cohort = _cohort(seed=21)
    times, events, _, risk = _make_fold(400, seed=22, t_lo=0.4, t_hi=62.0)
    train_times, train_events, _, train_risk = _make_fold(500, seed=23, t_lo=0.2, t_hi=70.0)

    _, _, BS, IBS, iauc, iauc_list = _call_metrics(
        calculate_metrics,
        times,
        events,
        None,  # cox: 没有逐桶生存列
        risk,
        cohort,
        train_survival_risks=(train_times, train_events, train_risk),
    )

    test_surv = _test_surv(times, events)
    estimate_grid = clinic_metrics.breslow_survival(
        train_times, train_events, train_risk, risk, clinic_metrics.IBS_GRID_MONTHS
    )
    assert np.asarray(BS).shape == (len(clinic_metrics.IBS_GRID_MONTHS),)
    assert np.isfinite(IBS)
    assert IBS == pytest.approx(
        clinic_metrics.compute_ibs(cohort, test_surv, estimate_grid)
    )
    assert np.all(np.isfinite(iauc_list))
    assert iauc == pytest.approx(np.mean(iauc_list))


def test_no_estimate_keeps_legacy_zeros(calculate_metrics):
    """既无逐桶列也无 train risks（如 hgcn_train.py 调用方）时保持旧版 0 契约。"""
    cohort = _cohort(seed=24)
    times, events, _, risk = _make_fold(200, seed=25, t_lo=0.4, t_hi=62.0)
    _, _, BS, IBS, iauc, iauc_list = _call_metrics(
        calculate_metrics, times, events, None, risk, cohort
    )
    assert float(BS) == 0.0
    assert float(IBS) == 0.0
    assert float(iauc) == 0.0
    assert float(iauc_list) == 0.0


def test_missing_survival_train_keeps_legacy_zeros(calculate_metrics):
    times, events, columns, risk = _make_fold(200, seed=26, t_lo=0.4, t_hi=62.0)
    _, _, BS, IBS, iauc, iauc_list = _call_metrics(
        calculate_metrics, times, events, columns, risk, None
    )
    assert float(BS) == 0.0
    assert float(IBS) == 0.0
    assert float(iauc) == 0.0
    assert float(iauc_list) == 0.0


# --------------------------------------------------------------------------- #
# 4. 负时间行：只从指标路径剔除，c-index 逐位不变（S10a 控制流门槛）
# --------------------------------------------------------------------------- #


def test_negative_time_rows_change_neither_cindex_nor_metrics(calculate_metrics):
    cohort = _cohort(seed=27, n=500)
    times, events, columns, risk = _make_fold(300, seed=28, t_lo=0.4, t_hi=62.0)

    # 模拟 BRCA quirk：全局最小时间 + 删失（两条同一病例的 slide）
    neg_times = np.array([-0.22996057818659657, -0.22996057818659657])
    neg_events = np.array([False, False])
    times_full = np.concatenate([neg_times, times])
    events_full = np.concatenate([neg_events, events])
    columns_full = np.concatenate([columns[:2], columns], axis=0)
    risk_full = np.concatenate([risk[:2] + 5.0, risk])  # 风险刻意最差，仍不应影响 c-index

    cohort_times = cohort["time"]
    cohort_events = cohort["event"]
    cohort_neg = np.concatenate([neg_times, cohort_times])
    cohort_full = Surv.from_arrays(
        event=np.concatenate([neg_events, cohort_events]),
        time=cohort_neg,
    )

    full = _call_metrics(
        calculate_metrics, times_full, events_full, columns_full, risk_full, cohort_full
    )
    trimmed = _call_metrics(
        calculate_metrics, times, events, columns, risk, cohort
    )

    assert full[0] == pytest.approx(trimmed[0])  # c-index：参与训练决策，必须不变
    assert np.isclose(full[1], trimmed[1], equal_nan=True)  # c_index_ipcw
    assert np.isclose(full[3], trimmed[3], equal_nan=True)  # IBS
    assert np.isclose(full[4], trimmed[4], equal_nan=True)  # iauc
    assert np.allclose(full[5], trimmed[5], equal_nan=True)  # iauc_list


# --------------------------------------------------------------------------- #
# 5. _summary 把 train_survival_risks 透传给 _calculate_metrics
# --------------------------------------------------------------------------- #


def test_summary_forwards_train_survival_risks(core_utils_module, monkeypatch):
    import torch

    captured = {}

    def fake_calculate_metrics(
        args, loader, dataset_factory, survival_train,
        all_risk_scores, all_censorships, all_event_times, all_risk_by_bin_scores,
        train_survival_risks=None,
    ):
        captured["train_survival_risks"] = train_survival_risks
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    monkeypatch.setattr(core_utils_module, "_calculate_metrics", fake_calculate_metrics)

    class _FakeDataset:
        def __init__(self):
            self.metadata = pd.DataFrame(
                {"slide_id": ["TCGA-XX-0001-01Z-00-DX1.abcdef.svs"]}
            )

        def __len__(self):
            return 1

    class _FakeLoader:
        def __init__(self):
            self.dataset = _FakeDataset()

        def __iter__(self):
            batch = (
                torch.zeros(1, 1),      # data_WSI
                torch.zeros(1, 4),      # data_clinic
                torch.zeros(1, 4),      # y_disc
                torch.tensor([24.0]),   # event_time
                torch.tensor([0.0]),    # censor
                ["clinical"],           # clinical_data_list
                None,
            )
            return iter([batch])

    class _FakeModel(torch.nn.Module):
        def forward(self, x_path=None, x_clinic=None, return_attn=False):
            return torch.zeros(1, 4)

    loader = _FakeLoader()
    dataset_factory = types.SimpleNamespace(bins=DEFAULT_BINS)
    sentinel = (np.array([1.0, 2.0]), np.array([True, False]), np.array([0.5, -0.5]))

    core_utils_module._summary(
        types.SimpleNamespace(bag_loss="nll_surv", return_attn=False),
        dataset_factory,
        _FakeModel(),
        "mlp_clinic_mean",
        loader,
        lambda h, y, t, c: torch.tensor(0.5),
        None,
        sentinel,
    )
    assert captured["train_survival_risks"] is sentinel

    # 不显式传参时保持 None（val 调用与 cox 之外的模型走原来的早退路径）
    core_utils_module._summary(
        types.SimpleNamespace(bag_loss="nll_surv", return_attn=False),
        dataset_factory,
        _FakeModel(),
        "mlp_clinic_mean",
        loader,
        lambda h, y, t, c: torch.tensor(0.5),
        None,
    )
    assert captured["train_survival_risks"] is None

    # cox_surv 分支：逐桶生存列为 None，同样透传 train risks
    core_utils_module._summary(
        types.SimpleNamespace(bag_loss="cox_surv", return_attn=False),
        dataset_factory,
        _FakeModel(),
        "clinic_cox",
        loader,
        lambda h, t, c: torch.tensor(0.5),
        None,
        sentinel,
    )
    assert captured["train_survival_risks"] is sentinel
