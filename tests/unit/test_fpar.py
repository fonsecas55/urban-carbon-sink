"""Unit tests for casa.fpar."""

from __future__ import annotations

import numpy as np

from casa.fpar import FPAR_MAX, FPAR_MIN, fpar

# Per-class bounds indexed by canonical code (length 6). Class 1 (trees) used here.
NDVI_MIN = np.array([0.0, 0.1, 0.1, 0.1, 0.1, 0.1])
NDVI_MAX = np.array([0.0, 0.9, 0.9, 0.9, 0.9, 0.9])
SR_MIN = np.array([0.0, 1.0, 1.0, 1.0, 1.0, 1.0])
SR_MAX = np.array([0.0, 20.0, 20.0, 20.0, 20.0, 20.0])


def _fpar(ndvi: np.ndarray, codes: np.ndarray) -> np.ndarray:
    return fpar(ndvi, codes, NDVI_MIN, NDVI_MAX, SR_MIN, SR_MAX)


def test_fpar_within_bounds() -> None:
    rng = np.random.default_rng(1)
    ndvi = rng.uniform(-0.2, 0.95, 500)
    codes = np.ones(500, dtype=np.uint8)
    got = _fpar(ndvi, codes)
    assert got.min() >= FPAR_MIN - 1e-9
    assert got.max() <= FPAR_MAX + 1e-9


def test_fpar_monotonic_in_ndvi() -> None:
    ndvi = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    codes = np.ones_like(ndvi, dtype=np.uint8)
    got = _fpar(ndvi, codes)
    assert np.all(np.diff(got) > 0)


def test_fpar_clamps_below_min_ndvi() -> None:
    # NDVI below the class minimum clamps to FPAR_MIN on the NDVI branch.
    ndvi = np.array([-0.5])
    codes = np.ones(1, dtype=np.uint8)
    got = _fpar(ndvi, codes)
    assert got[0] >= FPAR_MIN - 1e-9


def test_fpar_degenerate_class_zero() -> None:
    # Non-vegetation rows are min==max==0 -> fraction 0 -> FPAR_MIN, no NaN.
    ndvi = np.array([0.5])
    codes = np.zeros(1, dtype=np.uint8)
    got = _fpar(ndvi, codes)
    assert np.isfinite(got).all()
    np.testing.assert_allclose(got, FPAR_MIN)


def test_fpar_per_class_selection() -> None:
    # Two classes with different bounds must yield different FPAR for same NDVI.
    ndvi_min = np.array([0.0, 0.0, 0.5, 0.0, 0.0, 0.0])
    ndvi_max = np.array([0.0, 1.0, 1.0, 0.0, 0.0, 0.0])
    sr_min = np.array([0.0, 1.0, 1.0, 0.0, 0.0, 0.0])
    sr_max = np.array([0.0, 20.0, 20.0, 0.0, 0.0, 0.0])
    ndvi = np.array([0.5, 0.5])
    codes = np.array([1, 2], dtype=np.uint8)
    got = fpar(ndvi, codes, ndvi_min, ndvi_max, sr_min, sr_max)
    assert got[0] != got[1]
