"""Unit tests for casa.npp (final integration + unit conversions)."""

from __future__ import annotations

import numpy as np

from casa.npp import CO2_PER_C, PAR_FRACTION, density_to_tonnes, npp, npp_c_to_co2


def test_npp_product() -> None:
    got = npp(
        sol=np.array([100.0]),
        fpar=np.array([0.5]),
        emax=np.array([1.0]),
        t_eps1=np.array([0.9]),
        t_eps2=np.array([0.8]),
        wsc=np.array([1.0]),
    )
    expected = PAR_FRACTION * 100.0 * 0.5 * 1.0 * 0.9 * 0.8 * 1.0
    np.testing.assert_allclose(got, expected)


def test_npp_zero_where_emax_zero() -> None:
    # Non-vegetation (emax=0) must zero out NPP regardless of other terms.
    got = npp(
        sol=np.array([200.0]),
        fpar=np.array([0.9]),
        emax=np.array([0.0]),
        t_eps1=np.array([1.0]),
        t_eps2=np.array([1.0]),
        wsc=np.array([1.0]),
    )
    assert got[0] == 0.0


def test_npp_scene_constant_t_eps1_broadcasts() -> None:
    got = npp(
        sol=np.array([100.0, 100.0]),
        fpar=np.array([0.5, 0.5]),
        emax=np.array([1.0, 1.0]),
        t_eps1=0.9,  # scalar, scene-constant
        t_eps2=np.array([0.8, 0.8]),
        wsc=np.array([1.0, 1.0]),
    )
    assert got.shape == (2,)


def test_co2_conversion() -> None:
    np.testing.assert_allclose(npp_c_to_co2(np.array([12.0])), 12.0 * CO2_PER_C)


def test_density_to_tonnes_includes_pixel_area() -> None:
    # 1e6 g C/m2/month over a 10x10 m pixel (100 m2) = 100 tonnes/pixel.
    # This is the factor the legacy NPP_RESULT.py:54 dropped (divided by 1e6
    # without multiplying by area).
    got = density_to_tonnes(np.array([1e6]), area_pixel_m2=100.0)
    np.testing.assert_allclose(got, 100.0)


def test_density_to_tonnes_sum_is_regional_total() -> None:
    # Pipeline accumulates this array's sum across windows.
    density = np.full((10, 10), 500.0)  # g/m2/month
    tonnes = density_to_tonnes(density, area_pixel_m2=100.0)
    total = tonnes.sum()
    np.testing.assert_allclose(total, 100 * 500.0 * 100.0 / 1e6)
