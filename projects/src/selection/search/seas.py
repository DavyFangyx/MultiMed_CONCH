from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .base import Searcher, finish, score
from ..config import DELTA
from ..types import BudgetExhausted


SEAS_NAMES = ("SEAS", "SEAS-no-sem", "SEAS-no-int", "SEAS-no-ei")


def _field_entity(field: str) -> str:
    parts = str(field).replace("[]", "").split(".")
    aliases = {
        "diagnoses": "diagnosis",
        "demographic": "demographic",
        "exposures": "exposure",
        "follow_ups": "follow_up",
        "treatments": "treatment",
        "pathology_details": "pathology_detail",
        "molecular_tests": "molecular_test",
        "other_clinical_attributes": "other_clinical_attribute",
    }
    for part in reversed(parts[:-1]):
        if part in aliases:
            return aliases[part]
    return "case"


def compose_field_texts(fields, template_csv, dictionary_csv) -> tuple[str, ...]:
    """Build label-free semantic text from the three sources required by E2."""
    csv.field_size_limit(max(csv.field_size_limit(), 8 * 1024 * 1024))
    templates = {}
    with Path(template_csv).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            templates[str(row.get("field") or "").strip()] = str(row.get("template") or "").strip()

    by_entity = {}
    by_leaf = {}
    with Path(dictionary_csv).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            leaf = str(row.get("field") or "").strip()
            description = str(row.get("description") or "").strip()
            entity = str(row.get("entity") or "").strip()
            if leaf and description:
                by_entity[(entity, leaf)] = description
                by_leaf.setdefault(leaf, description)

    texts = []
    missing = [field for field in fields if field not in templates]
    if missing:
        raise ValueError(f"Field Bank template missing fields: {missing[:5]}")
    for field in fields:
        leaf = str(field).replace("[]", "").rsplit(".", 1)[-1]
        description = by_entity.get((_field_entity(field), leaf), by_leaf.get(leaf, ""))
        texts.append(
            f"Field path: {field}. GDC field description: {description} "
            f"Field Bank template: {templates[field]}"
        )
    return tuple(texts)


def encode_field_texts(texts, *, checkpoint, batch_size=64, device=None) -> np.ndarray:
    """Encode fixed field texts once with the project's existing CONCH encoder."""
    from discovery.field_bank import _lazy_import_conch

    torch, create_model_from_pretrained, get_tokenizer = _lazy_import_conch()
    # CONCH ViT-B-16 has a 128-token context, with the final position reserved
    # for cls_emb.  The public tokenizer callable does not apply CONCH's
    # project-specific 127+1 padding rule, so long field descriptions could
    # produce 131 tokens and fail inside TextTransformer.build_cls_mask().
    target = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model, _ = create_model_from_pretrained(
        model_cfg="conch_ViT-B-16", checkpoint_path=str(checkpoint)
    )
    model = model.to(target).eval()
    tokenizer = get_tokenizer()
    chunks = []
    with torch.inference_mode():
        for start in range(0, len(texts), int(batch_size)):
            encoded = tokenizer(
                list(texts[start : start + int(batch_size)]),
                max_length=127,
                add_special_tokens=True,
                truncation=True,
                padding="max_length",
                return_tensors="pt",
            )
            # encode_text(..., embed_cls=False) lets TextTransformer append
            # cls_emb internally, so the input itself must remain 127 tokens.
            tokens = encoded["input_ids"].to(target)
            features = model.encode_text(tokens, embed_cls=False)
            features = features / features.norm(dim=-1, keepdim=True).clamp_min(1e-12)
            chunks.append(features.cpu().float().numpy())
    return np.concatenate(chunks, axis=0) if chunks else np.empty((0, 0), dtype=np.float32)


def load_or_encode_field_semantics(
    fields,
    *,
    template_csv,
    dictionary_csv,
    checkpoint,
    cache_path,
    batch_size=64,
    device=None,
    python_executable=None,
) -> np.ndarray:
    texts = compose_field_texts(fields, template_csv, dictionary_csv)
    cache_path = Path(cache_path)
    meta_path = cache_path.with_suffix(cache_path.suffix + ".json")
    identity = {
        "fields": list(fields),
        "texts": list(texts),
        "checkpoint": str(Path(checkpoint).resolve()),
    }
    if cache_path.exists() and meta_path.exists():
        if json.loads(meta_path.read_text(encoding="utf-8")) == identity:
            matrix = np.load(cache_path)
            if matrix.ndim == 2 and matrix.shape[0] == len(fields):
                return matrix
    if python_executable and Path(python_executable).resolve() != Path(sys.executable).resolve():
        with tempfile.TemporaryDirectory(prefix="e2_semantics_") as temporary:
            text_path = Path(temporary) / "texts.json"
            output_path = Path(temporary) / "embeddings.npy"
            text_path.write_text(json.dumps(list(texts), ensure_ascii=False), encoding="utf-8")
            env = os.environ.copy()
            source_root = str(Path(__file__).resolve().parents[2])
            env["PYTHONPATH"] = source_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
            command = [
                str(python_executable), "-m", "selection.search.seas",
                "--encode-texts-json", str(text_path), "--output", str(output_path),
                "--checkpoint", str(checkpoint), "--batch-size", str(int(batch_size)),
            ]
            if device:
                command.extend(["--device", str(device)])
            completed = subprocess.run(command, env=env, check=False, text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if completed.returncode != 0:
                raise RuntimeError(f"CONCH field semantic encoding failed:\n{completed.stdout[-2000:]}")
            matrix = np.load(output_path)
    else:
        matrix = encode_field_texts(
            texts, checkpoint=checkpoint, batch_size=batch_size, device=device
        )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache_path, matrix)
    meta_path.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return matrix


def cosine_similarity(embeddings, p: int) -> np.ndarray:
    values = np.asarray(embeddings, dtype=float)
    if values.ndim != 2 or values.shape[0] != p:
        raise ValueError(f"semantic embeddings must have shape ({p}, d)")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    normalized = np.divide(values, norms, out=np.zeros_like(values), where=norms > 0)
    similarity = np.clip(normalized @ normalized.T, -1.0, 1.0)
    np.fill_diagonal(similarity, 0.0)
    return similarity


def semantic_interactions(similarity, neighbors=3) -> tuple[tuple[int, int], ...]:
    p = int(similarity.shape[0])
    pairs = set()
    for i in range(p):
        order = sorted((j for j in range(p) if j != i), key=lambda j: (-similarity[i, j], j))
        for j in order[: min(int(neighbors), max(p - 1, 0))]:
            pairs.add(tuple(sorted((i, j))))
    return tuple(sorted(pairs))


@dataclass
class _Posterior:
    mean: np.ndarray
    covariance: np.ndarray

    def predict(self, matrix):
        x = np.asarray(matrix, dtype=float)
        means = x @ self.mean
        variances = np.einsum("ij,jk,ik->i", x, self.covariance, x)
        return means, np.sqrt(np.maximum(variances, 0.0))


class BayesianSubsetSurrogate:
    def __init__(self, p, scores, similarity, *, use_semantics=True, use_interactions=True, noise=DELTA / 2):
        self.p = int(p)
        self.similarity = np.asarray(similarity, dtype=float)
        self.pairs = semantic_interactions(self.similarity) if use_interactions else ()
        means = [0.5]
        means.extend((np.asarray(scores, dtype=float) - 0.5).tolist() if use_semantics else [0.0] * self.p)
        means.extend([-0.01 * self.similarity[i, j] for i, j in self.pairs])
        means.append(0.0)
        self.prior_mean = np.asarray(means, dtype=float)
        self.prior_sd = np.asarray([0.1] + [0.05] * self.p + [0.02] * len(self.pairs) + [0.01])
        self.noise = max(float(noise), 1e-6)

    def features(self, subsets) -> np.ndarray:
        rows = []
        for subset in subsets:
            z = np.zeros(self.p, dtype=float)
            z[list(subset)] = 1.0
            rows.append(np.asarray(
                [1.0, *z, *(z[i] * z[j] for i, j in self.pairs), z.sum()], dtype=float
            ))
        return np.vstack(rows) if rows else np.empty((0, len(self.prior_mean)))

    def fit(self, subsets, values) -> _Posterior:
        x = self.features(subsets)
        y = np.asarray(values, dtype=float)
        prior_precision = np.diag(1.0 / np.square(self.prior_sd))
        precision = prior_precision + (x.T @ x) / (self.noise ** 2)
        rhs = prior_precision @ self.prior_mean + (x.T @ y) / (self.noise ** 2)
        jitter = 1e-10
        for _ in range(8):
            try:
                chol = np.linalg.cholesky(precision + jitter * np.eye(len(precision)))
                mean = np.linalg.solve(chol.T, np.linalg.solve(chol, rhs))
                inverse_chol = np.linalg.solve(chol, np.eye(len(chol)))
                covariance = inverse_chol.T @ inverse_chol
                return _Posterior(mean, covariance)
            except np.linalg.LinAlgError:
                jitter *= 10
        raise np.linalg.LinAlgError("surrogate Cholesky failed after jitter retries")


def _size_uniform_subset(p, rng) -> frozenset[int]:
    k = int(rng.integers(1, p + 1))
    return frozenset(int(i) for i in rng.choice(p, size=k, replace=False))


def _expected_improvement(means, stds, incumbent):
    from scipy.special import ndtr

    improvement = np.asarray(means) - float(incumbent)
    z = np.divide(improvement, stds, out=np.zeros_like(improvement), where=stds > 0)
    density = np.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    return np.where(stds > 0, improvement * ndtr(z) + stds * density, np.maximum(improvement, 0.0))


class SEASSearcher(Searcher):
    name = "SEAS"
    is_stochastic = True
    uses_univariate_prior = True

    def __init__(self, variant="SEAS", batch_size=8):
        if variant not in SEAS_NAMES:
            raise ValueError(f"unknown SEAS variant: {variant}")
        self.name = variant
        self.batch_size = int(batch_size)

    @staticmethod
    def _pool(p, proposed, ranked, rng):
        pool = set()
        for subset, _ in ranked[:5]:
            for i in range(p):
                candidate = subset ^ {i}
                if candidate:
                    pool.add(frozenset(candidate))
        attempts = 0
        random_subsets = set()
        while attempts < 4000 and len(random_subsets) < 200:
            random_subsets.add(_size_uniform_subset(p, rng))
            attempts += 1
        pool.update(random_subsets)
        if ranked:
            best = ranked[0][0]
            swaps = [
                frozenset((set(best) - {out}) | {incoming})
                for out in sorted(best)
                for incoming in range(p)
                if incoming not in best
            ]
            if len(swaps) > 100:
                chosen = rng.choice(len(swaps), size=100, replace=False)
                swaps = [swaps[int(i)] for i in chosen]
            pool.update(swaps)
        return sorted(pool - proposed, key=lambda value: (len(value), tuple(sorted(value))))

    def run(self, evaluator, bank, rng):
        fields = tuple(bank)
        p = len(fields)
        evaluator.proposal_count = 0
        if not p:
            return finish(self, evaluator, getattr(evaluator, "seed", 0), (), 0.5, "field_space_exhausted")
        scores = getattr(evaluator, "univariate_scores", None)
        embeddings = getattr(evaluator, "semantic_embeddings", None)
        if scores is None or len(scores) != p:
            raise ValueError("SEAS requires one univariate score per field")
        no_sem = self.name == "SEAS-no-sem"
        similarity = np.zeros((p, p), dtype=float) if no_sem or self.name == "SEAS-no-int" else cosine_similarity(embeddings, p)
        surrogate = BayesianSubsetSurrogate(
            p,
            scores,
            similarity,
            use_semantics=not no_sem,
            use_interactions=not no_sem and self.name != "SEAS-no-int",
        )
        evaluator.precharge(scores)
        evaluator.proposal_count = p
        observed = [frozenset((i,)) for i in range(p)]
        values = [float(value) for value in scores]
        proposed = set(observed)
        best_idx = max(range(p), key=lambda i: (values[i], -i))
        best, best_score = observed[best_idx], values[best_idx]
        new_observations = 0
        initial_random_count = 0
        next_noise_update = 20
        reason = "budget_exhausted"

        def update_noise():
            nonlocal next_noise_update
            if new_observations < next_noise_update:
                return
            fitted = surrogate.fit(observed, values)
            residuals = np.asarray(values) - surrogate.features(observed) @ fitted.mean
            surrogate.noise = max(float(np.sqrt(np.mean(np.square(residuals)))), 1e-6)
            while next_noise_update <= new_observations:
                next_noise_update += 20

        def evaluate_indices(subset):
            nonlocal best, best_score, new_observations
            evaluator.proposal_count += 1
            proposed.add(subset)
            result = evaluator.evaluate(frozenset(fields[i] for i in subset))
            value = score(result)
            if value != float("-inf"):
                observed.append(subset)
                values.append(value)
                new_observations += 1
                if value > best_score or (value == best_score and (len(subset), tuple(sorted(subset))) < (len(best), tuple(sorted(best)))):
                    best, best_score = subset, value
            return value

        try:
            initial_target = min(20, max(evaluator.budget - evaluator.logical_evals, 0))
            initial = []
            attempts = 0
            while len(initial) < initial_target and attempts < 10000:
                candidate = _size_uniform_subset(p, rng)
                attempts += 1
                if candidate not in proposed and candidate not in initial:
                    initial.append(candidate)
            for candidate in initial:
                evaluate_indices(candidate)
                initial_random_count += 1
            update_noise()

            while evaluator.logical_evals < evaluator.budget:
                ranked = sorted(zip(observed, values), key=lambda item: (-item[1], len(item[0]), tuple(sorted(item[0]))))
                pool = self._pool(p, proposed, ranked, rng)
                if not pool:
                    reason = "candidate_pool_exhausted"
                    break
                remaining = evaluator.budget - evaluator.logical_evals
                q = min(self.batch_size, remaining, len(pool))
                fantasy_subsets = list(observed)
                fantasy_values = list(values)
                available = list(pool)
                batch = []
                for _ in range(q):
                    posterior = surrogate.fit(fantasy_subsets, fantasy_values)
                    features = surrogate.features(available)
                    means, stds = posterior.predict(features)
                    acquisition = means if self.name == "SEAS-no-ei" else _expected_improvement(means, stds, max(fantasy_values))
                    pick = min(range(len(available)), key=lambda i: (-float(acquisition[i]), len(available[i]), tuple(sorted(available[i]))))
                    candidate = available.pop(pick)
                    batch.append(candidate)
                    fantasy_subsets.append(candidate)
                    fantasy_values.append(float(means[pick]))
                for candidate in batch:
                    evaluate_indices(candidate)
                update_noise()
        except BudgetExhausted:
            reason = "budget_exhausted"

        metadata = {
            "variant": self.name,
            "interaction_count": len(surrogate.pairs),
            "observation_noise": surrogate.noise,
            "initial_random_count": initial_random_count,
        }
        best_names = tuple(sorted(
            (fields[i] for i in best),
            key=lambda name: evaluator.field_indices[evaluator.fields.index(name)],
        ))
        return finish(self, evaluator, getattr(evaluator, "seed", 0), best_names, best_score, reason, metadata=metadata)


class SEASNoSemSearcher(SEASSearcher):
    name = "SEAS-no-sem"
    def __init__(self):
        super().__init__(self.name)


class SEASNoIntSearcher(SEASSearcher):
    name = "SEAS-no-int"
    def __init__(self):
        super().__init__(self.name)


class SEASNoEISearcher(SEASSearcher):
    name = "SEAS-no-ei"
    def __init__(self):
        super().__init__(self.name)


def _encoding_main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Internal CONCH field-text encoder")
    parser.add_argument("--encode-texts-json", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default=None)
    args = parser.parse_args(argv)
    texts = json.loads(Path(args.encode_texts_json).read_text(encoding="utf-8"))
    matrix = encode_field_texts(
        texts, checkpoint=args.checkpoint, batch_size=args.batch_size, device=args.device
    )
    np.save(args.output, matrix)


if __name__ == "__main__":
    _encoding_main()
