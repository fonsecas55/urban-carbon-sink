"""Unit tests for casa.inputs.mask — geometry -> grid mask and NoData masking."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from shapely.geometry import Polygon

from casa.grid import TargetGrid, target_grid_from_bbox
from casa.inputs.mask import apply_mask_nodata, region_mask

# Small lon/lat box near Oeiras.
MINX, MINY, MAXX, MAXY = -9.300, 38.700, -9.296, 38.703


def _rectangle() -> Polygon:
    return Polygon([(MINX, MINY), (MAXX, MINY), (MAXX, MAXY), (MINX, MAXY)])


def _triangle() -> Polygon:
    # Right triangle = half the rectangle (lower-left), spanning the full bbox.
    return Polygon([(MINX, MINY), (MAXX, MINY), (MINX, MAXY)])


def test_rectangle_fills_its_own_bbox(tmp_path: Path) -> None:
    geom = _rectangle()
    grid = target_grid_from_bbox(geom.bounds)
    mask = region_mask(geom, grid)
    assert mask.shape == grid.shape
    # A rectangle covers most of its bbox grid; outward snapping + the lon/lat ->
    # UTM reprojection leave a thin unmasked border, so it is not exactly 1.0.
    assert mask.mean() > 0.85


def test_triangle_covers_about_half() -> None:
    geom = _triangle()
    grid = target_grid_from_bbox(geom.bounds)
    mask = region_mask(geom, grid)
    assert 0.0 < mask.mean() < 1.0
    assert mask.mean() == pytest.approx(0.5, abs=0.1)


def test_geometry_outside_grid_is_all_false() -> None:
    geom = _rectangle()
    far_grid = target_grid_from_bbox((10.0, 50.0, 10.02, 50.02))  # nowhere near Oeiras
    mask = region_mask(geom, far_grid)
    assert not mask.any()


def test_apply_mask_nodata_zeroes_outside(tmp_path: Path) -> None:
    grid: TargetGrid = target_grid_from_bbox(_rectangle().bounds)
    path = tmp_path / "band.tif"
    profile = {
        "driver": "GTiff",
        "height": grid.height,
        "width": grid.width,
        "count": 1,
        "dtype": "float32",
        "crs": grid.crs,
        "transform": grid.transform,
        "nodata": float("nan"),
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.full(grid.shape, 5.0, dtype="float32"), 1)

    mask = np.zeros(grid.shape, dtype=bool)
    mask[: grid.height // 2, :] = True  # keep top half
    apply_mask_nodata(path, mask, float("nan"))

    with rasterio.open(path) as ds:
        out = ds.read(1)
    assert np.allclose(out[mask], 5.0)
    assert np.all(np.isnan(out[~mask]))
