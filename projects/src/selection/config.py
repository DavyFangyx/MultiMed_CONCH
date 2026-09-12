from __future__ import annotations

DELTA = 0.005
PATIENCE = 3
DEFAULT_SEED = 0
N_FOLDS = 5
MODALITY = "mlp_clinic_flatten"
ENCODING = "prompt"
LANDMARK_TAGS = ("landmark_0", "landmark_365", "landmark_730", "landmark_none")
K_GRID_VALUES = (1, 3, 5, 8, 12, 20)


def budget_for(p: int) -> int:
    p = int(p)
    if p < 0:
        raise ValueError("p must be non-negative")
    return p * (p + 1) // 2


def parse_seeds(raw=None) -> list[int]:
    if raw is None or raw == "":
        return [DEFAULT_SEED]
    values = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    result = []
    for value in values:
        text = str(value).strip()
        if not text or not text.lstrip("-").isdigit():
            raise ValueError("seed must be an integer or comma-separated integers")
        seed = int(text)
        if seed not in result:
            result.append(seed)
    if not result:
        raise ValueError("seed must not be empty")
    return result


def k_grid(p: int) -> list[int]:
    p = int(p)
    return sorted({min(k, p) for k in (*K_GRID_VALUES, p) if p > 0})
