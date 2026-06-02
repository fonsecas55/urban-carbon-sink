"""Unit tests for casa.sol."""

from __future__ import annotations

import numpy as np

from casa.sol import KWH_TO_MJ, sol


def test_sol_basic_conversion() -> None:
    # 5 kWh/m2/day, no monthly deviation, 30 days.
    got = sol(np.array([5.0]), var_pct_mes=0.0, n_dias=30)
    np.testing.assert_allclose(got, 5.0 * KWH_TO_MJ * 30)


def test_sol_monthly_deviation() -> None:
    base = sol(np.array([4.0]), var_pct_mes=0.0, n_dias=31)
    plus = sol(np.array([4.0]), var_pct_mes=10.0, n_dias=31)
    np.testing.assert_allclose(plus, base * 1.1)


def test_sol_preserves_shape() -> None:
    ghi = np.ones((4, 4)) * 3.0
    got = sol(ghi, var_pct_mes=-5.0, n_dias=28)
    assert got.shape == (4, 4)
