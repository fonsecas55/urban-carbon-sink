"""Unit tests for casa.wsc."""

from __future__ import annotations

import numpy as np

from casa.wsc import simi, wsc


def test_simi_scaling() -> None:
    # B11=B12=10000 -> reflectance 1.0 each -> 0.7071*sqrt(2) ~= 1.0
    got = simi(np.array([10000.0]), np.array([10000.0]))
    np.testing.assert_allclose(got, 0.7071 * np.sqrt(2.0))


def test_wsc_within_physical_band() -> None:
    rng = np.random.default_rng(2)
    b11 = rng.uniform(0, 10000, 1000)
    b12 = rng.uniform(0, 10000, 1000)
    got = wsc(b11, b12, simi_min=0.0, simi_max=1.0)
    assert got.min() >= 0.5 - 1e-9
    assert got.max() <= 1.0 + 1e-9


def test_wsc_decreases_with_water_stress() -> None:
    # Higher SIMI (drier) -> lower WSC.
    dry = wsc(np.array([9000.0]), np.array([9000.0]), simi_min=0.0, simi_max=1.0)
    wet = wsc(np.array([1000.0]), np.array([1000.0]), simi_min=0.0, simi_max=1.0)
    assert dry[0] < wet[0]


def test_wsc_clamps_out_of_sample() -> None:
    # SIMI above simi_max clamps NSIMI to 1 -> WSC = 0.5, never below.
    got = wsc(np.array([10000.0]), np.array([10000.0]), simi_min=0.0, simi_max=0.1)
    np.testing.assert_allclose(got, 0.5)


def test_wsc_degenerate_span() -> None:
    got = wsc(np.array([5000.0]), np.array([5000.0]), simi_min=0.3, simi_max=0.3)
    assert np.isfinite(got).all()
    np.testing.assert_allclose(got, 1.0)
