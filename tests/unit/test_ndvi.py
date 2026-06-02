"""Unit tests for casa.ndvi."""

from __future__ import annotations

import numpy as np

from casa.ndvi import ndvi, simple_ratio


def test_ndvi_known_values() -> None:
    red = np.array([0.1, 0.2, 0.5])
    nir = np.array([0.5, 0.2, 0.1])
    got = ndvi(red, nir)
    expected = np.array([(0.5 - 0.1) / 0.6, 0.0, (0.1 - 0.5) / 0.6])
    np.testing.assert_allclose(got, expected)


def test_ndvi_scale_invariant() -> None:
    red = np.array([1000.0, 2000.0])
    nir = np.array([5000.0, 2000.0])
    np.testing.assert_allclose(ndvi(red, nir), ndvi(red / 10000, nir / 10000))


def test_ndvi_zero_denominator_is_zero_not_nan() -> None:
    got = ndvi(np.array([0.0]), np.array([0.0]))
    assert got[0] == 0.0
    assert not np.isnan(got).any()


def test_ndvi_range() -> None:
    rng = np.random.default_rng(0)
    red = rng.uniform(0, 1, 1000)
    nir = rng.uniform(0, 1, 1000)
    got = ndvi(red, nir)
    assert got.min() >= -1.0 and got.max() <= 1.0


def test_simple_ratio_monotonic_and_finite() -> None:
    nd = np.array([-0.5, 0.0, 0.5, 1.0])  # 1.0 must not blow up
    sr = simple_ratio(nd)
    assert np.all(np.isfinite(sr))
    assert np.all(np.diff(sr) > 0)
    assert sr[1] == 1.0  # SR(NDVI=0) = 1
