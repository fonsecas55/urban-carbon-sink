"""Unit tests for casa.grid."""

from __future__ import annotations

import pytest

from casa.grid import target_grid_from_bbox, utm_epsg_from_lonlat

OEIRAS_BBOX = (-9.35, 38.66, -9.23, 38.72)


def test_utm_zone_oeiras_is_29n() -> None:
    # Oeiras (lon ~-9.3, lat ~38.7) -> UTM 29N -> EPSG:32629.
    assert utm_epsg_from_lonlat(-9.30, 38.69) == 32629


def test_utm_southern_hemisphere() -> None:
    # Same zone, south of equator -> 327xx.
    assert utm_epsg_from_lonlat(-9.30, -38.69) == 32729


def test_grid_crs_is_utm() -> None:
    grid = target_grid_from_bbox(OEIRAS_BBOX)
    assert grid.crs.to_epsg() == 32629


def test_grid_resolution_and_north_up() -> None:
    grid = target_grid_from_bbox(OEIRAS_BBOX, resolution=10.0)
    assert grid.resolution == 10.0
    assert grid.transform.a == 10.0  # +x east
    assert grid.transform.e == -10.0  # -y (north-up)
    assert grid.pixel_area_m2 == 100.0


def test_grid_covers_bbox() -> None:
    # ~12 km wide, ~6.7 km tall at this latitude -> hundreds of 10 m pixels.
    grid = target_grid_from_bbox(OEIRAS_BBOX)
    assert grid.width > 1000
    assert grid.height > 500
    assert grid.shape == (grid.height, grid.width)


def test_grid_bounds_are_pixel_aligned() -> None:
    grid = target_grid_from_bbox(OEIRAS_BBOX)
    minx, miny, maxx, maxy = grid.bounds
    assert (maxx - minx) == pytest.approx(grid.width * grid.resolution)
    assert (maxy - miny) == pytest.approx(grid.height * grid.resolution)
    # snapped to the resolution grid
    assert minx % grid.resolution == pytest.approx(0.0)
    assert maxy % grid.resolution == pytest.approx(0.0)


def test_degenerate_bbox_raises() -> None:
    with pytest.raises(ValueError, match="degenerate"):
        target_grid_from_bbox((1.0, 1.0, 1.0, 2.0))
