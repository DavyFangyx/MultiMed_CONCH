"""S10b: Test_5_q_recompute.py（离线 Q 指标重算）回归测试。

覆盖：
  1. 纯函数 - conf 名解析、label 文件回退解析、runs 发现、pkl / test_result.csv 读取；
  2. cohort 重建 - 逐字镜像 core_utils._extract_survival_metadata（train+val+test 拼接，
     val==test 的重复行保留，因为在线 cohort 就带重复）；
  3. 过滤器 - NaN risk 行、负时间行（只从 IPCW 路径剔除；cohort 仅在测试折确实有
     负时间时才过滤）与在线 core_utils._calculate_metrics 逐行一致；
  4. 镜像等价 - 合成数据上 calculate_metrics_mirror 与 _calculate_metrics 完全一致
     （IBS 支持/不支持、AUC 事件数守卫、NaN risk、负时间四种场景），
     metrics_from_dump（diff=0 路径）同样一致；
  5. 行构造 - make_q_row 的列 / NaN 表示 / abs_diff；
  6. 端到端冒烟 - 若 results/Test_2b/arm_B 里存在离散模型 conf，用 --limit 1 重算
     一圈，断言 cindex 与 test_result.csv 的差 <= 1e-8（工件缺失则 skip）。

环境：需要 sksurv + torch（SurvPGC env）；base 环境整体 skip 不产生假失败。
运行：
  PYTHONPATH=/tmp/s10a_pytest_env \
    /data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python -m pytest tests/test_Test5_q_recompute.py -q
"""

from __future__ import annotations

import importlib.util
import math
import pickle
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sksurv")
pytest.importorskip("torch")

from sksurv.util import Surv  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ANALYZER = ROOT / "Clinic_Analyzer"
SCRIPT = ROOT / "results_display" / "scripts" / "Test_5_q_recompute.py"

if str(ANALYZER) not in sys.path:
    sys.path.insert(0, str(ANALYZER))


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


qrec = _load_by_path("s10b_q_recompute", SCRIPT)

CINDEX_TOLERANCE = qrec.CINDEX_TOLERANCE


@pytest.fixture(scope="module")
def calculate_metrics():
    from utils.core_utils import _calculate_metrics

    return _calculate_metrics


class _DummyFactory:
    """_calculate_metrics only reads dataset_factory.bins."""

    def __init__(self, bins):
        self.bins = np.asarray(bins, dtype=np.float64)


def _dummy_loader():
    return SimpleNamespace(dataset=SimpleNamespace(metadata=None))


# ---------------------------------------------------------------------------
# synthetic data
# ---------------------------------------------------------------------------


def synthetic_cohort(n=240, seed=7):
    """Cohort (censoring-reference) sample: finite IPCW needs G(t) > 0, which a
    uniform + 50% censoring cohort does NOT give (KM hits 0 in the tail);
    exponential competing risks with a much slower censoring clock does."""
    rng = np.random.default_rng(seed)
    event_time = rng.exponential(50.0, n)
    censoring_time = rng.exponential(500.0, n)
    times = np.minimum(event_time, censoring_time) + 0.5
    censorships = (censoring_time < event_time).astype(np.float64)
    censorships[np.argmax(times)] = 1.0  # last observation censored
    return times, censorships


def synthetic_fold(n=80, seed=11, shift=0.0):
    rng = np.random.default_rng(seed)
    event_time = rng.exponential(40.0, n)
    censoring_time = rng.exponential(400.0, n)
    times = np.minimum(event_time, censoring_time) + 0.5 + shift
    censorships = (censoring_time < event_time).astype(np.float64)
    risks = rng.normal(size=n)
    logits = rng.normal(size=(n, 4))
    return times, censorships, risks, logits


def assert_same_metric(actual, expected, rtol=1e-12, atol=1e-12):
    """NaN-aware scalar comparison (pytest.approx rejects NaN on either side)."""
    left, right = float(actual), float(expected)
    if math.isnan(left) or math.isnan(right):
        assert math.isnan(left) and math.isnan(right), (left, right)
    else:
        assert left == pytest.approx(right, rel=rtol, abs=atol), (left, right)


def make_bins():
    # 5 edges -> bins[1:] = 4 bin edges (n_bins=4), same shape as the factory
    return np.array([-0.5, 6.0, 12.0, 25.0, 90.5], dtype=np.float64)


def as_online_inputs(times, censorships, risks, logits):
    """What _summary passes to _calculate_metrics for a discrete model."""
    risk_by_bin = qrec.survival_columns_from_logits(logits)
    return risk_by_bin


# ---------------------------------------------------------------------------
# config / discovery helpers
# ---------------------------------------------------------------------------


def test_parse_conf_name_keeps_landmark_token():
    assert qrec.parse_conf_name("tcga_laml__SURVPGC__landmark_0") == (
        "tcga_laml",
        "SURVPGC__landmark_0",
    )
    assert qrec.parse_conf_name("tcga_acc__INTEGRATIVE_DNN") == (
        "tcga_acc",
        "INTEGRATIVE_DNN",
    )
    assert qrec.parse_conf_name("tcga_laml__Test_3_SURVPGC_TCGA-LAML__landmark_0") == (
        "tcga_laml",
        "Test_3_SURVPGC_TCGA-LAML__landmark_0",
    )


def test_resolve_label_file_walks_up_to_labels_dir(tmp_path):
    conf = tmp_path / "arm_B" / "runs" / "tcga_x__SURVPGC__landmark_0" / "mlp_clinic_flatten"
    conf.mkdir(parents=True)
    labels = tmp_path / "arm_B" / "labels"
    labels.mkdir(parents=True)
    label = labels / "tcga_x__landmark_0.csv"
    label.write_text("case_id\n")

    experiment = {"label_file": "/gone/A_manual_landmark/labels/tcga_x__landmark_0.csv"}
    assert (
        qrec.resolve_label_file(experiment, conf.parent, conf)
        == label
    )


def test_resolve_label_file_returns_none_when_missing(tmp_path):
    conf = tmp_path / "conf" / "modality"
    conf.mkdir(parents=True)
    assert qrec.resolve_label_file({"label_file": "/gone/labels/x.csv"}, conf.parent, conf) is None


def test_discover_run_dirs(tmp_path):
    for conf_name, modality in (
        ("tcga_a__SURVPGC__landmark_0", "mlp_clinic_flatten"),
        ("tcga_a__SURVPGC__landmark_0", "clinic_cox"),
        ("tcga_b__MMSURV__landmark_0", "mlp_clinic_flatten"),
    ):
        run = tmp_path / "runs" / conf_name / modality
        run.mkdir(parents=True)
        (run / "split_0_results.pkl").write_bytes(b"")
    refs = qrec.discover_run_dirs([tmp_path], qrec.DEFAULT_MODALITIES)
    assert [(r.study, r.scheme, r.modality) for r in refs] == [
        ("tcga_a", "SURVPGC__landmark_0", "clinic_cox"),
        ("tcga_a", "SURVPGC__landmark_0", "mlp_clinic_flatten"),
        ("tcga_b", "MMSURV__landmark_0", "mlp_clinic_flatten"),
    ]
    # modality filter
    refs = qrec.discover_run_dirs([tmp_path], ("clinic_cox",))
    assert len(refs) == 1 and refs[0].modality == "clinic_cox"


def test_list_folds_ignores_val_pkls(tmp_path):
    for name in ("split_0_results.pkl", "split_1_results.pkl", "split_1_results_val.pkl"):
        (tmp_path / name).write_bytes(b"")
    assert qrec.list_folds(tmp_path) == [0, 1]


# ---------------------------------------------------------------------------
# artifact readers
# ---------------------------------------------------------------------------


def test_load_fold_pkl_roundtrip(tmp_path):
    patients = {
        "TCGA-XX-0001": {
            "time": 12.0,
            "risk": -1.5,
            "censorship": 0.0,
            "clinical": [],
            "logits": np.array([0.1, 0.2, 0.3, 0.4]),
        },
        "TCGA-XX-0002": {
            "time": 30.0,
            "risk": 0.5,
            "censorship": 1.0,
            "clinical": [],
            "logits": np.array([-0.1, 0.0, 0.1, 0.2]),
        },
    }
    path = tmp_path / "split_0_results.pkl"
    with path.open("wb") as handle:
        pickle.dump(patients, handle)
    loaded = qrec.load_fold_pkl(path)
    assert loaded["case_ids"] == ["TCGA-XX-0001", "TCGA-XX-0002"]
    np.testing.assert_allclose(loaded["times"], [12.0, 30.0])
    np.testing.assert_allclose(loaded["risks"], [-1.5, 0.5])
    assert loaded["logits"].shape == (2, 4)


def test_load_fold_pkl_without_logits(tmp_path):
    patients = {"TCGA-XX-0001": {"time": 1.0, "risk": 0.1, "censorship": 0.0, "clinical": []}}
    path = tmp_path / "split_0_results.pkl"
    with path.open("wb") as handle:
        pickle.dump(patients, handle)
    assert qrec.load_fold_pkl(path)["logits"] is None


def test_load_csv_cindex_by_fold(tmp_path):
    frame = pd.DataFrame(
        {
            "test_cindex": [0.5, 0.6],
            "test_IBS": [0.0, 0.0],
            "test_iauc": [0.0, 0.0],
        }
    )
    path = tmp_path / "test_result.csv"
    frame.to_csv(path)
    assert qrec.load_csv_cindex_by_fold(path) == {0: 0.5, 1: 0.6}
    assert qrec.load_csv_cindex_by_fold(tmp_path / "nope.csv") == {}


# ---------------------------------------------------------------------------
# cohort reconstruction
# ---------------------------------------------------------------------------


def test_cohort_arrays_from_splits_csv_mirrors_online_concat(tmp_path):
    label = pd.DataFrame(
        {
            "case_id": ["TCGA-A1-0001", "TCGA-A1-0002", "TCGA-A1-0003", "TCGA-A1-0004"],
            "slide_id": [
                "TCGA-A1-0001.svs",
                "TCGA-A1-0002.svs",
                "TCGA-A1-0003.svs",
                "TCGA-A1-0004.svs",
            ],
            "survival_months": [5.0, 10.0, 20.0, 40.0],
            "censorship": [0.0, 1.0, 0.0, 1.0],
        }
    )
    splits = pd.DataFrame(
        {
            "train": ["TCGA-A1-0001.svs", "TCGA-A1-0002.svs"],
            "val": ["TCGA-A1-0003.svs", None],
            "test": ["TCGA-A1-0003.svs", None],  # val == test, like the real runs
        }
    )
    csv_path = tmp_path / "splits_0.csv"
    splits.to_csv(csv_path)
    times, censorships = qrec.cohort_arrays_from_splits_csv(
        csv_path, label, "survival_months", "censorship"
    )
    # train(2) + val(1) + test(1): the val/test case is counted twice (online
    # _extract_survival_metadata concatenates without dedup)
    np.testing.assert_allclose(times, [5.0, 10.0, 20.0, 20.0])
    np.testing.assert_allclose(censorships, [0.0, 1.0, 0.0, 0.0])
    surv = qrec.build_surv(times, censorships)
    np.testing.assert_array_equal(surv["event"], [True, False, True, True])


def test_cohort_arrays_falls_back_to_slide_prefix(tmp_path):
    # real TCGA case ids are 12 chars, so slide_id[:12] is the case id
    label = pd.DataFrame(
        {
            "case_id": ["TCGA-A1-0001", "TCGA-A1-0002"],
            "slide_id": ["other-name", "another"],
            "survival_months": [3.0, 7.0],
            "censorship": [0.0, 1.0],
        }
    )
    csv_path = tmp_path / "splits_0.csv"
    pd.DataFrame(
        {
            "train": ["TCGA-A1-0001.svs"],
            "val": ["TCGA-A1-0002.svs"],
            "test": ["TCGA-A1-0002.svs"],
        }
    ).to_csv(csv_path)
    times, _ = qrec.cohort_arrays_from_splits_csv(csv_path, label, "survival_months", "censorship")
    np.testing.assert_allclose(times, [3.0, 7.0, 7.0])


# ---------------------------------------------------------------------------
# filters
# ---------------------------------------------------------------------------


def test_drop_nan_risk_rows_removes_rows_everywhere():
    times = np.array([1.0, 2.0, 3.0])
    cens = np.array([0.0, 1.0, 0.0])
    risks = np.array([0.5, np.nan, -0.5])
    by_bin = np.arange(12.0).reshape(3, 4)
    out = qrec.drop_nan_risk_rows(times, cens, risks, risk_by_bin=by_bin)
    np.testing.assert_allclose(out["times"], [1.0, 3.0])
    np.testing.assert_allclose(out["censorships"], [0.0, 0.0])
    np.testing.assert_allclose(out["risks"], [0.5, -0.5])
    np.testing.assert_allclose(out["risk_by_bin"], by_bin[[0, 2]])
    assert out["n_nan_rows"] == 1


def test_drop_negative_time_rows_cohort_filter_is_conditional():
    filtered = qrec.drop_nan_risk_rows(
        np.array([-2.0, 4.0, 8.0]), np.array([0.0, 1.0, 0.0]), np.array([0.1, 0.2, 0.3])
    )
    cohort_times = np.array([-1.0, 5.0, 9.0])
    cohort_events = np.array([True, False, True])
    out = qrec.drop_negative_time_rows(
        filtered, cohort_times=cohort_times, cohort_events=cohort_events
    )
    assert out["n_negative_rows"] == 1
    assert out["cohort_neg_filtered"] is True
    np.testing.assert_allclose(out["cohort_times"], [5.0, 9.0])
    np.testing.assert_array_equal(out["cohort_events"], [False, True])

    # no negative test time -> the cohort must NOT be filtered (online semantics)
    filtered = qrec.drop_nan_risk_rows(
        np.array([4.0, 8.0]), np.array([0.0, 1.0]), np.array([0.1, 0.2])
    )
    out = qrec.drop_negative_time_rows(
        filtered, cohort_times=cohort_times, cohort_events=cohort_events
    )
    assert out["cohort_neg_filtered"] is False
    np.testing.assert_allclose(out["cohort_times"], cohort_times)


def test_apply_metric_filters_is_nan_then_negative():
    times = np.array([-1.0, 2.0, 3.0])
    cens = np.array([0.0, 1.0, 0.0])
    risks = np.array([0.5, np.nan, 0.3])
    out = qrec.apply_metric_filters(times, cens, risks)
    # row 1 dropped as NaN risk, then row 0 dropped as negative time
    np.testing.assert_allclose(out["times"], [3.0])
    np.testing.assert_allclose(out["risks"], [0.3])
    assert out["n_nan_rows"] == 1 and out["n_negative_rows"] == 1


# ---------------------------------------------------------------------------
# curve rebuild / risk
# ---------------------------------------------------------------------------


def test_risk_from_logits_matches_online_formula():
    logits = np.array([[0.1, -0.4, 0.7, 0.2], [-0.3, 0.0, 0.5, -0.9]])
    survival = qrec.survival_columns_from_logits(logits)
    np.testing.assert_allclose(qrec.risk_from_logits(logits), -survival.sum(axis=1))
    # and the curve rebuild uses the shared online functions
    edges = make_bins()[1:]
    grid = qrec.IBS_GRID_MONTHS
    np.testing.assert_allclose(
        qrec.interpolate_survival(survival, edges, grid),
        qrec.interpolate_survival(qrec.survival_columns_from_logits(logits), edges, grid),
    )


# ---------------------------------------------------------------------------
# mirror equivalence with the online _calculate_metrics
# ---------------------------------------------------------------------------


def _run_online(calculate_metrics, times, cens, risks, logits, cohort_times, cohort_cens):
    factory = _DummyFactory(make_bins())
    cohort = qrec.build_surv(cohort_times, cohort_cens)
    risk_by_bin = as_online_inputs(times, cens, risks, logits)
    return calculate_metrics(
        SimpleNamespace(),
        _dummy_loader(),
        factory,
        cohort,
        risks,
        cens,
        times,
        risk_by_bin,
    )


def _run_mirror(times, cens, risks, logits, cohort_times, cohort_cens):
    cohort = qrec.build_surv(cohort_times, cohort_cens)
    return qrec.calculate_metrics_mirror(
        make_bins()[1:],
        cohort,
        times,
        cens,
        risks,
        risk_by_bin=as_online_inputs(times, cens, risks, logits),
    )


def test_mirror_matches_online_supported_fold(calculate_metrics):
    cohort_times, cohort_cens = synthetic_cohort()
    times, cens, risks, logits = synthetic_fold()
    online = _run_online(calculate_metrics, times, cens, risks, logits, cohort_times, cohort_cens)
    mirror = _run_mirror(times, cens, risks, logits, cohort_times, cohort_cens)
    assert_same_metric(mirror[0], online[0], rtol=0, atol=0)  # c-index
    assert_same_metric(mirror[1], online[1])  # ipcw
    np.testing.assert_allclose(mirror[2], online[2], rtol=1e-12, atol=1e-12)  # BS
    assert_same_metric(mirror[3], online[3])  # IBS
    assert_same_metric(mirror[4], online[4])  # iauc
    np.testing.assert_allclose(mirror[5], online[5], rtol=1e-12, atol=1e-12)
    # the supported fold must actually exercise the numbers (not the NaN paths)
    assert math.isfinite(float(mirror[3])) and math.isfinite(float(mirror[4]))


def test_mirror_matches_online_when_ibs_unsupported(calculate_metrics):
    cohort_times, cohort_cens = synthetic_cohort()
    times, cens, risks, logits = synthetic_fold(shift=3.0)  # test_min > 1 -> IBS nan
    online = _run_online(calculate_metrics, times, cens, risks, logits, cohort_times, cohort_cens)
    mirror = _run_mirror(times, cens, risks, logits, cohort_times, cohort_cens)
    assert math.isnan(online[3]) and math.isnan(mirror[3])
    assert online[2] == 0.0 and mirror[2] == 0.0
    assert_same_metric(mirror[4], online[4])
    np.testing.assert_allclose(mirror[5], online[5], rtol=1e-12, atol=1e-12)


def test_mirror_matches_online_with_nan_and_negative_rows(calculate_metrics):
    cohort_times, cohort_cens = synthetic_cohort()
    cohort_times = cohort_times.copy()
    cohort_times[0] = -0.5  # cohort negative quirk
    times, cens, risks, logits = synthetic_fold()
    times = times.copy()
    times[3] = -1.0  # negative test time -> cohort gets filtered too
    risks = risks.copy()
    risks[5] = np.nan
    online = _run_online(calculate_metrics, times, cens, risks, logits, cohort_times, cohort_cens)
    mirror = _run_mirror(times, cens, risks, logits, cohort_times, cohort_cens)
    assert_same_metric(mirror[0], online[0], rtol=0, atol=0)
    assert_same_metric(mirror[1], online[1])
    np.testing.assert_allclose(mirror[2], online[2], rtol=1e-12, atol=1e-12)
    assert_same_metric(mirror[3], online[3])
    assert_same_metric(mirror[4], online[4])


def test_mirror_landmark_event_guard_matches_online(calculate_metrics):
    # tiny fold -> fewer events than MIN_EVENTS_FOR_AUC -> both sides must NaN
    rng = np.random.default_rng(3)
    n = 12
    times = np.concatenate([rng.uniform(0.5, 23.0, 3), rng.uniform(24.5, 40.0, n - 3)])
    cens = np.zeros(n)  # every row an event, but only 3 of them by 24mo
    risks = rng.normal(size=n)
    logits = rng.normal(size=(n, 4))
    cohort_times, cohort_cens = synthetic_cohort()
    online = _run_online(calculate_metrics, times, cens, risks, logits, cohort_times, cohort_cens)
    mirror = _run_mirror(times, cens, risks, logits, cohort_times, cohort_cens)
    assert_same_metric(mirror[4], online[4])
    np.testing.assert_allclose(mirror[5], online[5], rtol=1e-12, atol=1e-12)
    assert math.isnan(float(mirror[5][0])) and math.isnan(float(mirror[5][1]))
    assert math.isnan(float(mirror[4]))


def test_metrics_from_dump_matches_direct_mirror_and_online(calculate_metrics):
    cohort_times, cohort_cens = synthetic_cohort()
    times, cens, risks, logits = synthetic_fold()
    dump = {
        "edges": make_bins()[1:],
        "all_risk_scores": risks,
        "all_censorships": cens,
        "all_event_times": times,
        "all_risk_by_bin_scores": as_online_inputs(times, cens, risks, logits),
        "train_survival_risks": None,
        "survival_train_time": cohort_times,
        "survival_train_event": (1.0 - cohort_cens) > 0.5,
        "metrics": {},
    }
    from_dump = qrec.metrics_from_dump(dump)
    direct = qrec.fold_q_metrics(
        make_bins()[1:],
        qrec.build_surv(cohort_times, cohort_cens),
        times,
        cens,
        risks,
        risk_by_bin=as_online_inputs(times, cens, risks, logits),
    )
    online = _run_online(calculate_metrics, times, cens, risks, logits, cohort_times, cohort_cens)
    assert_same_metric(from_dump["cindex"], online[0], rtol=0, atol=0)
    assert_same_metric(from_dump["cindex"], direct["cindex"], rtol=0, atol=0)
    for key in ("ibs", "iauc", "auc24", "auc60"):
        assert_same_metric(from_dump[key], direct[key], rtol=0, atol=0)
    assert from_dump["n_events_24"] == direct["n_events_24"]
    assert_same_metric(from_dump["ibs"], online[3])
    assert_same_metric(from_dump["iauc"], online[4])
    assert math.isfinite(float(from_dump["ibs"])) and math.isfinite(float(from_dump["iauc"]))


def test_fold_q_metrics_reports_events_and_landmarks(calculate_metrics):
    cohort_times, cohort_cens = synthetic_cohort()
    times, cens, risks, logits = synthetic_fold()
    metrics = qrec.fold_q_metrics(
        make_bins()[1:],
        qrec.build_surv(cohort_times, cohort_cens),
        times,
        cens,
        risks,
        risk_by_bin=as_online_inputs(times, cens, risks, logits),
    )
    events = (1.0 - cens) > 0.5
    assert metrics["n_events_24"] == int((events & (times <= 24)).sum())
    assert metrics["n_events_60"] == int((events & (times <= 60)).sum())
    iauc_list = np.asarray(metrics["iauc_list"], dtype=np.float64)
    assert_same_metric(metrics["auc24"], iauc_list[0], rtol=0, atol=0)
    assert_same_metric(metrics["auc60"], iauc_list[1], rtol=0, atol=0)
    finite = iauc_list[np.isfinite(iauc_list)]
    if finite.size:
        assert metrics["iauc"] == pytest.approx(float(finite.mean()))
    else:
        assert math.isnan(metrics["iauc"])


# ---------------------------------------------------------------------------
# row construction
# ---------------------------------------------------------------------------


def test_make_q_row_columns_and_nan_formatting():
    metrics = {
        "cindex": 0.625,
        "ibs": float("nan"),
        "iauc": 0.75,
        "auc24": 0.7,
        "auc60": 0.8,
        "n_events_24": 12,
        "n_events_60": 18,
    }
    row = qrec.make_q_row(
        study="tcga_x",
        scheme="SURVPGC__landmark_0",
        modality="mlp_clinic_flatten",
        fold=2,
        metrics=metrics,
        cindex_csv=0.625,
        source="pkl_recompute",
    )
    assert list(row.keys()) == qrec.Q_COLUMNS
    assert row["ibs"] == ""
    assert row["auc24"] == "0.7"
    assert row["abs_diff"] == "0.0"
    assert row["source"] == "pkl_recompute"

    missing = qrec.make_q_row(
        study="tcga_x",
        scheme="S",
        modality="m",
        fold=0,
        metrics=metrics,
        cindex_csv=None,
        source="metrics_input_dump",
    )
    assert missing["cindex_csv"] == "" and missing["abs_diff"] == ""


# ---------------------------------------------------------------------------
# end-to-end smoke on an existing discrete conf (skips when artifacts absent)
# ---------------------------------------------------------------------------

SMOKE_ROOT = ROOT / "results" / "Test_2b" / "arm_B"


@pytest.mark.skipif(
    not any(SMOKE_ROOT.rglob("split_0_results.pkl")), reason="no Test_2b/arm_B artifacts"
)
def test_recompute_end_to_end_discrete_conf(tmp_path):
    rows = qrec.recompute(
        roots=[SMOKE_ROOT],
        out_path=tmp_path / "q_metrics.csv",
        modalities=["mlp_clinic_flatten"],
        folds=[0],
        limit=1,
        cox_device="cpu",
        quiet=True,
    )
    assert rows, "recompute produced no rows"
    out_csv = tmp_path / "q_metrics.csv"
    assert out_csv.is_file()
    frame = pd.read_csv(out_csv)
    assert list(frame.columns) == qrec.Q_COLUMNS
    assert len(frame) == len(rows)
    for row in rows:
        if row["cindex_csv"] == "":
            continue
        assert float(row["abs_diff"]) <= CINDEX_TOLERANCE, row


@pytest.mark.skipif(
    not any(SMOKE_ROOT.rglob("split_0_results.pkl")), reason="no Test_2b/arm_B artifacts"
)
def test_recompute_prefers_metrics_input_dump(tmp_path):
    """A fold with fold{fold}_metrics_input.pkl must take the diff=0 dump path
    and agree with the pkl path / test_result.csv self-check."""
    import shutil

    ref = qrec.discover_run_dirs([SMOKE_ROOT], ["mlp_clinic_flatten"])[0]
    conf = qrec.prepare_conf(ref, extra_label_dirs=[SMOKE_ROOT / "labels"])
    factory = conf["factory"]
    artifacts = qrec.load_fold_pkl(ref.modality_dir / "split_0_results.pkl")
    cohort_surv, cohort_times, _ = qrec.cohort_surv_from_splits_csv(
        factory, ref.modality_dir / "splits_0.csv"
    )
    dump = {
        "modality": ref.modality,
        "bag_loss": conf["experiment"].get("bag_loss"),
        "edges": qrec.edges_from_factory(factory),
        "all_risk_scores": artifacts["risks"],
        "all_censorships": artifacts["censorships"],
        "all_event_times": artifacts["times"],
        "all_risk_by_bin_scores": None
        if artifacts["logits"] is None
        else qrec.survival_columns_from_logits(artifacts["logits"]),
        "train_survival_risks": None,
        "survival_train_time": cohort_times,
        "survival_train_event": np.asarray(cohort_surv["event"], dtype=bool),
        "slide_ids": [],
        "metrics": {},
    }
    work = tmp_path / "runs" / ref.conf_dir.name / ref.modality
    work.mkdir(parents=True)
    shutil.copy(ref.modality_dir / "experiment.txt", work / "experiment.txt")
    effective = ref.modality_dir / "effective_config.txt"
    if effective.is_file():
        shutil.copy(effective, work / "effective_config.txt")
    # discovery keys on the real fold artifacts, which coexist with the dump
    for artifact in ("split_0_results.pkl", "splits_0.csv", "test_result.csv"):
        source = ref.modality_dir / artifact
        if source.is_file():
            shutil.copy(source, work / artifact)
    with (work / qrec.DUMP_NAME_TEMPLATE.format(fold=0)).open("wb") as handle:
        pickle.dump(dump, handle)

    rows = qrec.recompute(
        roots=[tmp_path],
        out_path=tmp_path / "q_metrics.csv",
        modalities=[ref.modality],
        folds=[0],
        labels_dirs=[SMOKE_ROOT / "labels"],
        quiet=True,
    )
    assert len(rows) == 1
    row = rows[0]
    assert (row["study"], row["scheme"], row["modality"], row["fold"]) == (
        ref.study,
        ref.scheme,
        ref.modality,
        0,
    )
    assert row["source"] == "metrics_input_dump"
    assert row["abs_diff"] != "" and float(row["abs_diff"]) <= CINDEX_TOLERANCE


# ---------------------------------------------------------------------------
# S10d: cox test-side risk reconstruction (1-row pkl collapse + tie-flip repair)
# ---------------------------------------------------------------------------


def test_pick_cox_reconstruction_policy():
    """auto policy: never perturb a fast result that already matches."""
    fast = {"cindex": 0.4533333333333333}
    online = {"cindex": 0.46}
    # no recorded online value -> keep the fast result untouched
    metrics, adopted = qrec.pick_cox_reconstruction(fast, online, None)
    assert metrics is fast and adopted is False
    # fast already within tolerance -> keep it, the online value is not consulted
    metrics, adopted = qrec.pick_cox_reconstruction(fast, online, 0.4533333333333333)
    assert metrics is fast and adopted is False
    # fast disagrees, online strictly closer -> adopt online
    metrics, adopted = qrec.pick_cox_reconstruction(fast, online, 0.46)
    assert metrics is online and adopted is True
    # fast disagrees, online no closer -> keep fast (ties keep the cheap path)
    metrics, adopted = qrec.pick_cox_reconstruction(fast, {"cindex": 0.45}, 0.46)
    assert metrics is fast and adopted is False


def test_cindex_tie_flip_at_tied_tol_boundary():
    """The S10d mechanism: a comparable pair whose risk gap straddles sksurv's
    tied_tol=1e-8 contributes 0.5 (tied) or 0/1 (ordered), moving the c-index."""
    times = np.array([1.0, 2.0, 3.0, 4.0])
    censorships = np.array([0.0, 0.0, 1.0, 1.0])  # rows 0/1 are events
    base = np.array([0.5, 0.4, 0.3, 0.2])

    tied = base.copy()
    tied[1] = tied[0] + 5e-9  # gap 5e-9 <= 1e-8 -> tied pair
    untied = base.copy()
    untied[1] = untied[0] + 1.2e-8  # gap 1.2e-8 > 1e-8 -> ordered, discordant

    ci_tied = qrec.cindex_from_risk(times, censorships, tied)
    ci_untied = qrec.cindex_from_risk(times, censorships, untied)
    # 5 comparable pairs: 4 ordered + one tied (0.5) vs 4 ordered + one wrong (0)
    assert ci_tied == pytest.approx(4.5 / 5)
    assert ci_untied == pytest.approx(4.0 / 5)
    # the two risk vectors differ by ~7e-9, i.e. a couple of float32 ULP at 0.5
    assert abs(untied[1] - tied[1]) < 1e-8
    assert ci_tied != ci_untied


class _CoxFactoryStub:
    """Just enough factory for compute_fold_from_artifacts' cox branch."""

    def __init__(self, patients_df, bins):
        self.patients_df = patients_df
        self.label_data = patients_df
        self.label_col = "survival_months"
        self.censorship_var = "censorship"
        self.bins = np.asarray(bins, dtype=np.float64)


def _cox_fold_artifacts(tmp_path):
    """Synthetic cox fold: 1-row pkl (the online full-batch collapse) + csv."""
    times, censorships, risks, _ = synthetic_fold(n=80, seed=11)
    cohort_times, cohort_censorships = synthetic_cohort(n=240)
    patients = pd.DataFrame(
        {"survival_months": cohort_times, "censorship": cohort_censorships}
    )
    factory = _CoxFactoryStub(patients, bins=np.linspace(0.0, 100.0, 5))

    modality_dir = tmp_path / "runs" / "tcga_x__COXSPLIT__landmark_0" / "clinic_cox"
    modality_dir.mkdir(parents=True)
    ref = qrec.RunRef(
        root=tmp_path,
        conf_dir=modality_dir.parent,
        modality_dir=modality_dir,
        study="tcga_x",
        scheme="COXSPLIT__landmark_0",
        modality="clinic_cox",
    )
    # the online loader collapses patient_results to one row per batch: 1 row here
    with (modality_dir / "split_0_results.pkl").open("wb") as handle:
        pickle.dump(
            {"TCGA-XX-0000": {"time": 1.0, "risk": 0.1, "censorship": 0.0}}, handle
        )

    # the tie-flip pair: an event row and a longer-surviving comparable row
    i = int(np.flatnonzero(censorships == 0)[0])
    j = int(np.flatnonzero(times > times[i])[0])
    risks_pp = risks.copy()
    risks_pp[i] = 0.5
    risks_pp[j] = 0.5 + 5e-9  # tied (<= tied_tol)
    risks_online = risks_pp.copy()
    risks_online[j] = 0.5 + 1.2e-8  # untied (> tied_tol): the online GPU bits
    return ref, factory, times, censorships, risks_pp, risks_online


def test_cox_auto_repair_adopts_online_batch_when_tie_flips(monkeypatch, tmp_path):
    ref, factory, times, censorships, risks_pp, risks_online = _cox_fold_artifacts(tmp_path)
    ci_pp = qrec.cindex_from_risk(times, censorships, risks_pp)
    ci_online = qrec.cindex_from_risk(times, censorships, risks_online)
    assert ci_pp != ci_online

    conf = {"factory": factory, "experiment": {"bag_loss": "cox_surv"}}
    calls = []

    def fake_collect(
        ref, conf, fold, cox_device="cpu",
        test_batch_mode=qrec.COX_TEST_BATCH_PER_PATIENT,
    ):
        calls.append(test_batch_mode)
        train = (np.array([1.0, 2.0]), np.array([True, False]), np.array([0.1, 0.2]))
        risks = risks_online if test_batch_mode == qrec.COX_TEST_BATCH_ONLINE else risks_pp
        return train, (times, censorships, risks)

    monkeypatch.setattr(qrec, "collect_cox_fold", fake_collect)

    # auto + disagreeing csv -> per-patient first, then the online reconstruction
    metrics, source = qrec.compute_fold_from_artifacts(
        ref, conf, 0, cox_test_batch="auto", cindex_csv=ci_online
    )
    assert calls == [qrec.COX_TEST_BATCH_PER_PATIENT, qrec.COX_TEST_BATCH_ONLINE]
    assert source == qrec.SOURCE_PKL_COX_ONLINE
    assert metrics["cindex"] == pytest.approx(ci_online, abs=1e-12)

    # auto + csv that the per-patient run already reproduces -> untouched
    calls.clear()
    metrics, source = qrec.compute_fold_from_artifacts(
        ref, conf, 0, cox_test_batch="auto", cindex_csv=ci_pp
    )
    assert calls == [qrec.COX_TEST_BATCH_PER_PATIENT]
    assert source == qrec.SOURCE_PKL_RECOMPUTE
    assert metrics["cindex"] == pytest.approx(ci_pp, abs=1e-12)

    # forced per-patient never repairs, even when the csv disagrees
    calls.clear()
    metrics, source = qrec.compute_fold_from_artifacts(
        ref, conf, 0, cox_test_batch="per_patient", cindex_csv=ci_online
    )
    assert calls == [qrec.COX_TEST_BATCH_PER_PATIENT]
    assert source == qrec.SOURCE_PKL_RECOMPUTE
    assert metrics["cindex"] == pytest.approx(ci_pp, abs=1e-12)


def test_cox_auto_repair_reads_csv_when_cindex_not_passed(monkeypatch, tmp_path):
    """The default path (no explicit cindex_csv) must read test_result.csv."""
    ref, factory, times, censorships, risks_pp, risks_online = _cox_fold_artifacts(tmp_path)
    ci_online = qrec.cindex_from_risk(times, censorships, risks_online)
    with (ref.modality_dir / "test_result.csv").open("w", encoding="utf-8") as handle:
        handle.write(",test_cindex\n0,%r\n" % ci_online)

    conf = {"factory": factory, "experiment": {"bag_loss": "cox_surv"}}

    def fake_collect(
        ref, conf, fold, cox_device="cpu",
        test_batch_mode=qrec.COX_TEST_BATCH_PER_PATIENT,
    ):
        train = (np.array([1.0, 2.0]), np.array([True, False]), np.array([0.1, 0.2]))
        risks = risks_online if test_batch_mode == qrec.COX_TEST_BATCH_ONLINE else risks_pp
        return train, (times, censorships, risks)

    monkeypatch.setattr(qrec, "collect_cox_fold", fake_collect)
    metrics, source = qrec.compute_fold_from_artifacts(ref, conf, 0)
    assert source == qrec.SOURCE_PKL_COX_ONLINE
    assert metrics["cindex"] == pytest.approx(ci_online, abs=1e-12)


def test_collect_cox_fold_pkl_gate_requires_full_row_coverage(monkeypatch, tmp_path):
    """The pkl risks are used only when they cover EVERY test-split row."""
    import torch
    from types import SimpleNamespace

    import utils.core_utils as core_utils

    modality_dir = tmp_path / "runs" / "tcga_x__COXSPLIT__landmark_0" / "clinic_cox"
    modality_dir.mkdir(parents=True)
    ref = qrec.RunRef(
        root=tmp_path,
        conf_dir=modality_dir.parent,
        modality_dir=modality_dir,
        study="tcga_x",
        scheme="COXSPLIT__landmark_0",
        modality="clinic_cox",
    )

    class _Model:
        def to(self, device):
            return self

        def eval(self):
            return self

    class _Loader:
        def __init__(self, split):
            self.split = split

    class _Factory:
        def __init__(self):
            self.train, self.val, self.test = ["a"], ["b"], ["c1", "c2", "c3"]

        def return_splits(self, args, csv_path=None, fold=0):
            return self.train, self.val, self.test

    conf = {
        "factory": _Factory(),
        "experiment": {"bag_loss": "cox_surv"},
        "label_col": "survival_months",
        "n_bins": 4,
    }
    torch.save(
        torch.nn.Linear(1, 1, bias=False).state_dict(),
        modality_dir / "s_0_checkpoint.pt",
    )

    train_rows = (
        np.array([1.0, 2.0]),
        np.array([True, False]),
        np.array([0.1, 0.2]),
    )
    loader_splits = []

    def fake_split_rows(args, model, loader):
        return (
            np.array([2.0, 3.0, 4.0]),
            np.zeros(3),
            np.array([0.1, 0.2, 0.3]),
        )

    def fake_get_split_loader(args, split, **kwargs):
        loader_splits.append(split)
        return _Loader(split)

    monkeypatch.setattr(
        qrec,
        "_build_cox_args",
        lambda *a, **k: SimpleNamespace(
            device="cpu", bag_loss="cox_surv", modality="clinic_cox"
        ),
    )
    monkeypatch.setattr(qrec, "_build_cox_model", lambda args, state_dict=None: _Model())
    monkeypatch.setattr(qrec, "_cox_train_csv", lambda ref, conf, fold: tmp_path / "splits.csv")
    monkeypatch.setattr(core_utils, "_init_loss_function", lambda args: None)
    monkeypatch.setattr(core_utils, "_get_split_loader", fake_get_split_loader)
    monkeypatch.setattr(
        core_utils,
        "_collect_train_survival_risks",
        lambda args, model, loader, loss_fn: train_rows,
    )
    monkeypatch.setattr(qrec, "_collect_split_rows", fake_split_rows)

    def write_pkl(n_rows):
        patients = {
            f"TCGA-XX-{i:04d}": {"time": 1.0 + i, "risk": 0.1 * i, "censorship": 0.0}
            for i in range(n_rows)
        }
        with (modality_dir / "split_0_results.pkl").open("wb") as handle:
            pickle.dump(patients, handle)

    # 1-row pkl (the observed cox layout) cannot cover a 3-row split -> forward
    write_pkl(1)
    _, test_forward = qrec.collect_cox_fold(ref, conf, 0)
    assert loader_splits == [["a"], ["c1", "c2", "c3"]]
    assert test_forward is not None

    # a pkl covering every test row is preferred over any forward
    loader_splits.clear()
    write_pkl(3)
    _, test_forward = qrec.collect_cox_fold(ref, conf, 0)
    assert loader_splits == [["a"]]
    assert test_forward is None


def test_merge_rows_replaces_by_key_and_keeps_order():
    existing = [
        {"study": "a", "scheme": "s", "modality": "m", "fold": "0", "cindex_csv": "0.5"},
        {"study": "a", "scheme": "s", "modality": "m", "fold": "1", "cindex_csv": "0.6"},
    ]
    new = [
        {"study": "a", "scheme": "s", "modality": "m", "fold": 1, "cindex_csv": "0.61"},
        {"study": "b", "scheme": "s2", "modality": "m", "fold": 0, "cindex_csv": "0.7"},
    ]
    merged, n_replaced, n_appended = qrec.merge_rows(existing, new)
    assert (n_replaced, n_appended) == (1, 1)
    assert len(merged) == 3
    assert [row["fold"] for row in merged] == ["0", 1, 0]
    assert merged[1]["cindex_csv"] == "0.61"
    # re-merging the same rows never duplicates
    again, n_replaced, n_appended = qrec.merge_rows(merged, new)
    assert (n_replaced, n_appended) == (2, 0)
    assert len(again) == 3


@pytest.mark.skipif(
    not any(SMOKE_ROOT.rglob("split_0_results.pkl")), reason="no Test_2b/arm_B artifacts"
)
def test_recompute_merge_into_existing_csv_has_no_duplicate_rows(tmp_path):
    out_csv = tmp_path / "q_metrics.csv"
    kwargs = dict(
        roots=[SMOKE_ROOT],
        out_path=out_csv,
        modalities=["mlp_clinic_flatten"],
        folds=[0],
        limit=1,
        cox_device="cpu",
        quiet=True,
    )
    first = qrec.recompute(**kwargs)
    assert first
    second = qrec.recompute(merge=True, **kwargs)
    assert len(second) == len(first)
    keys = [(row["study"], row["scheme"], row["modality"], row["fold"]) for row in second]
    assert len(keys) == len(set(keys))
    assert len(qrec.read_q_rows(out_csv)) == len(first)
