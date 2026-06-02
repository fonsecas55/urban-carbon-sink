"""Unit tests for casa.emax."""

from __future__ import annotations

import numpy as np

from casa import landcover as lc
from casa.emax import emax, table_to_array

# Xu 2023 / BPLUT defaults, canonical code -> g C/MJ.
XU2023 = {
    lc.NON_VEGETATION: 0.0,
    lc.TREES: 1.106,
    lc.SHRUB_AND_SCRUB: 1.061,
    lc.GRASS: 0.86,
    lc.CROPS: 1.044,
    lc.FLOODED_VEGETATION: 0.86,
}


def test_table_to_array_length_and_values() -> None:
    arr = table_to_array(XU2023)
    assert arr.shape == (6,)
    assert arr[lc.TREES] == 1.106
    assert arr[lc.NON_VEGETATION] == 0.0


def test_emax_lookup() -> None:
    codes = np.array([lc.TREES, lc.GRASS, lc.NON_VEGETATION, lc.CROPS], dtype=np.uint8)
    got = emax(codes, XU2023)
    np.testing.assert_allclose(got, [1.106, 0.86, 0.0, 1.044])


def test_emax_non_vegetation_is_zero() -> None:
    codes = np.zeros((3, 3), dtype=np.uint8)
    got = emax(codes, XU2023)
    assert np.all(got == 0.0)


def test_missing_code_defaults_zero() -> None:
    partial = {lc.TREES: 1.106}
    got = emax(np.array([lc.GRASS], dtype=np.uint8), partial)
    assert got[0] == 0.0
