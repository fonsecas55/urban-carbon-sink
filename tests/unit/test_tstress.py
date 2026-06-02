"""Unit tests for casa.tstress."""

from __future__ import annotations

import numpy as np

from casa.tstress import t_eps1, t_eps2, t_mean


def test_t_mean() -> None:
    got = t_mean(np.array([30.0]), np.array([10.0]))
    np.testing.assert_allclose(got, 20.0)


def test_t_eps1_formula() -> None:
    # 0.8 + 0.02*25 - 0.0005*25^2 = 0.9875
    np.testing.assert_allclose(t_eps1(np.array([25.0])), 0.9875)


def test_t_eps2_peaks_near_t_opt() -> None:
    t_opt = 25.0
    near = t_eps2(np.array([t_opt]), np.array([t_opt]))
    hot = t_eps2(np.array([t_opt + 20]), np.array([t_opt]))
    cold = t_eps2(np.array([t_opt - 20]), np.array([t_opt]))
    assert near[0] > hot[0]
    assert near[0] > cold[0]


def test_t_eps2_is_finite_and_bounded() -> None:
    t_opt = np.full(200, 24.0)
    t = np.linspace(-30, 60, 200)
    got = t_eps2(t, t_opt)
    assert np.all(np.isfinite(got))
    assert got.min() >= 0.0
    assert got.max() <= 1.2  # 1.184 scaling ceiling


def test_t_opt_is_a_parameter_not_scene_mean() -> None:
    # Same T_mean, different climatological T_opt -> different stress.
    tm = np.array([18.0, 18.0])
    a = t_eps2(tm[:1], np.array([15.0]))
    b = t_eps2(tm[:1], np.array([30.0]))
    assert a[0] != b[0]
