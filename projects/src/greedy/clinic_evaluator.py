"""Real subset evaluator: slice Field Bank → Clinic_Analyzer → read c-index."""

from __future__ import annotations

from pathlib import Path

from common.paths import PROJECT_ROOT, dataset_field_bank_dir, dataset_greedy_dir

from .clinic import evaluate_clinic_dir
from .embeddings import materialize_subset_embeddings_with_python, subset_embedding_dir, subset_scheme_name

from .splits import write_analyzer_split_dir


DEFAULT_CONCH_PYTHON = Path("/data/fangyuxuan/miniconda3/envs/conch/bin/python")
DEFAULT_SURVPGC_PYTHON = Path("/data/fangyuxuan/miniconda3/envs/SurvPGC/bin/python")


class ClinicSubsetEvaluator:
    def __init__(
        self,
        dataset: str,
        fields: list[str],
        splits,
        *,
        field_bank_dir: Path | str | None = None,
        embeddings_root: Path | str | None = None,
        work_dir: Path | str | None = None,
        modality: str = "mlp_clinic_flatten",
        seed: int = 0,
        for_test: bool = False,
        max_epochs: int | None = None,
        conch_python: Path | str | None = None,
        analyzer_python: Path | str | None = None,
        analyzer_dir: Path | str | None = None,
        extra_args: list[str] | None = None,
        overwrite_embeddings: bool = False,
        split_dir: Path | str | None = None,
    ):
        self.dataset = dataset
        self.fields = list(fields)
        if splits is None:
            self.splits = []
        elif isinstance(splits, (list, tuple)):
            self.splits = list(splits)
        else:
            self.splits = [splits]
        self.split = self.splits[0] if self.splits else splits
        self.field_bank_dir = Path(field_bank_dir or dataset_field_bank_dir(dataset))
        self.embeddings_root = Path(embeddings_root or (PROJECT_ROOT / "outputs"))
        self.work_dir = Path(work_dir or dataset_greedy_dir(dataset))
        self.modality = modality
        self.seed = int(seed)
        self.for_test = bool(for_test)
        self.max_epochs = max_epochs
        self.conch_python = Path(conch_python or DEFAULT_CONCH_PYTHON)
        self.analyzer_python = Path(analyzer_python or DEFAULT_SURVPGC_PYTHON)
        self.analyzer_dir = analyzer_dir
        self.extra_args = list(extra_args or [])
        self.overwrite_embeddings = bool(overwrite_embeddings)
        self.split_dir = Path(split_dir) if split_dir is not None else None

    def evaluate(self, subset_idx) -> dict:
        idx = [int(i) for i in list(subset_idx)]
        if not idx:
            return {
                "c_index_mean": 0.5,
                "c_index_std": 0.0,
                "per_fold": [0.5],
                "subset_idx": [],
                "scheme": "G0_empty",
                "empty": True,
            }

        scheme = subset_scheme_name(idx)
        clinic_dir = subset_embedding_dir(self.dataset, scheme, self.embeddings_root)
        materialize_subset_embeddings_with_python(
            self.conch_python,
            self.field_bank_dir,
            idx,
            clinic_dir,
            fields=self.fields,
            overwrite=self.overwrite_embeddings,
        )

        k = max(len(self.splits), 1)
        run_tag = scheme
        job_log = self.work_dir / "jobs" / f"{run_tag}.json"
        split_dir = self.split_dir or (self.work_dir / "analyzer_splits")
        if self.split_dir is None and self.splits:
            write_analyzer_split_dir(split_dir, self.splits)
        payload = evaluate_clinic_dir(
            clinic_dir,
            dataset=self.dataset,
            scheme=run_tag,
            modality=self.modality,
            exp_group="greedy",
            python_exe=self.analyzer_python,
            analyzer_dir=self.analyzer_dir,
            k=k,
            k_start=0,
            k_end=k,
            split_dir=split_dir,
            max_epochs=self.max_epochs,
            seed=self.seed,
            extra_args=self.extra_args,
            prefer_val=not self.for_test,
            reuse=True,
            job_log=job_log,
        )
        payload["subset_idx"] = idx
        payload["scheme"] = scheme
        payload["clinic_dir"] = str(clinic_dir)
        payload["n_params"] = len(idx)
        return payload


def make_clinic_evaluator_factory(
    dataset: str,
    fields: list[str],
    field_bank_dir: Path | str,
    work_dir: Path | str,
    modality: str = "mlp_clinic_flatten",
    max_epochs: int | None = None,
    conch_python: Path | str | None = None,
    analyzer_python: Path | str | None = None,
    extra_args: list[str] | None = None,
    split_dir: Path | str | None = None,
):
    def factory(split, seed=0, for_test=False):
        return ClinicSubsetEvaluator(
            dataset=dataset,
            fields=fields,
            splits=split,
            field_bank_dir=field_bank_dir,
            work_dir=work_dir,
            modality=modality,
            seed=seed,
            for_test=for_test,
            max_epochs=max_epochs,
            conch_python=conch_python,
            analyzer_python=analyzer_python,
            extra_args=extra_args,
            split_dir=split_dir,
        )

    return factory
