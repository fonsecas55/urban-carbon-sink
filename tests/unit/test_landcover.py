"""Unit tests for casa.landcover (ADR-011 canonical schema + adapters)."""

from __future__ import annotations

import numpy as np

from casa import landcover as lc


def test_dw_mapping_all_classes() -> None:
    # DW: 0 water,1 trees,2 grass,3 flooded_veg,4 crops,5 shrub,6 built,7 bare,8 snow
    dw = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8], dtype=np.uint8)
    got = lc.dw_to_canonical(dw)
    expected = np.array(
        [
            lc.NON_VEGETATION,  # water
            lc.TREES,
            lc.GRASS,
            lc.FLOODED_VEGETATION,
            lc.CROPS,
            lc.SHRUB_AND_SCRUB,
            lc.NON_VEGETATION,  # built
            lc.NON_VEGETATION,  # bare
            lc.NON_VEGETATION,  # snow
        ],
        dtype=np.uint8,
    )
    np.testing.assert_array_equal(got, expected)


def test_esa_mapping_all_classes() -> None:
    esa = np.array([10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100])
    got = lc.esa_to_canonical(esa)
    expected = np.array(
        [
            lc.TREES,
            lc.SHRUB_AND_SCRUB,
            lc.GRASS,
            lc.CROPS,
            lc.NON_VEGETATION,  # 50 built
            lc.NON_VEGETATION,  # 60 bare
            lc.NON_VEGETATION,  # 70 snow
            lc.NON_VEGETATION,  # 80 water
            lc.FLOODED_VEGETATION,  # 90 herbaceous wetland
            lc.FLOODED_VEGETATION,  # 95 mangroves
            lc.NON_VEGETATION,  # 100 moss/lichen
        ],
        dtype=np.uint8,
    )
    np.testing.assert_array_equal(got, expected)


def test_unmapped_value_falls_back_to_non_vegetation() -> None:
    # ADR-011 defensive contract: never raise, default to 0.
    assert lc.dw_to_canonical(np.array([999]))[0] == lc.NON_VEGETATION
    assert lc.esa_to_canonical(np.array([255]))[0] == lc.NON_VEGETATION


def test_output_is_uint8() -> None:
    assert lc.dw_to_canonical(np.array([1, 2])).dtype == np.uint8


def test_default_fraction() -> None:
    canonical = np.array([0, 0, 1, 2], dtype=np.uint8)
    assert lc.default_fraction(canonical) == 0.5
    assert lc.default_fraction(np.array([], dtype=np.uint8)) == 0.0
