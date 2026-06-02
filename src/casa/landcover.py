"""Canonical land-cover schema and source adapters (ADR-011).

The CASA pipeline never sees Dynamic World or ESA WorldCover codes directly:
adapters convert each source to a 6-class canonical schema (UInt8). Swapping
the source (DW <-> ESA fallback) leaves `emax` and the epsilon_max tables
untouched.

Canonical codes:
    0  non_vegetation   (masked: epsilon_max = 0)
    1  trees
    2  shrub_and_scrub
    3  grass
    4  crops
    5  flooded_vegetation

Defensive contract (ADR-011): any unmapped value, NoData or NaN falls back to
0 (non_vegetation). Adapters never raise in production.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

NON_VEGETATION = 0
TREES = 1
SHRUB_AND_SCRUB = 2
GRASS = 3
CROPS = 4
FLOODED_VEGETATION = 5

CANONICAL_LABELS: dict[int, str] = {
    NON_VEGETATION: "non_vegetation",
    TREES: "trees",
    SHRUB_AND_SCRUB: "shrub_and_scrub",
    GRASS: "grass",
    CROPS: "crops",
    FLOODED_VEGETATION: "flooded_vegetation",
}

# Dynamic World V1 'label' band integer codes -> canonical.
# DW: 0 water, 1 trees, 2 grass, 3 flooded_vegetation, 4 crops,
#     5 shrub_and_scrub, 6 built, 7 bare, 8 snow_and_ice.
_DW_TO_CANONICAL: dict[int, int] = {
    1: TREES,
    5: SHRUB_AND_SCRUB,
    2: GRASS,
    4: CROPS,
    3: FLOODED_VEGETATION,
}

# ESA WorldCover 2021 class codes -> canonical.
_ESA_TO_CANONICAL: dict[int, int] = {
    10: TREES,
    20: SHRUB_AND_SCRUB,
    30: GRASS,
    40: CROPS,
    90: FLOODED_VEGETATION,
    95: FLOODED_VEGETATION,
}


def _apply_mapping(source: NDArray[np.generic], mapping: dict[int, int]) -> NDArray[np.uint8]:
    """Vectorised map source codes -> canonical; everything else -> 0.

    NaN/NoData collapse to 0 because the cast to an integer comparison never
    matches a mapping key.
    """
    src = np.asarray(source)
    out = np.zeros(src.shape, dtype=np.uint8)
    for code, canonical in mapping.items():
        out[src == code] = canonical
    return out


def dw_to_canonical(dw: NDArray[np.generic]) -> NDArray[np.uint8]:
    """Dynamic World label codes -> canonical schema. Unmapped -> non_vegetation."""
    return _apply_mapping(dw, _DW_TO_CANONICAL)


def esa_to_canonical(esa: NDArray[np.generic]) -> NDArray[np.uint8]:
    """ESA WorldCover 2021 codes -> canonical schema. Unmapped -> non_vegetation."""
    return _apply_mapping(esa, _ESA_TO_CANONICAL)


def default_fraction(canonical: NDArray[np.uint8]) -> float:
    """Fraction of pixels that landed in code 0 (non_vegetation).

    High values can signal a dataset version with classes not yet mapped —
    callers may log a warning above a threshold (ADR-011: > 5%).
    """
    canonical = np.asarray(canonical)
    if canonical.size == 0:
        return 0.0
    return float(np.count_nonzero(canonical == NON_VEGETATION) / canonical.size)
