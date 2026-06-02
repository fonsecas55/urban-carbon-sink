"""Unit tests for casa.inputs.regrid — warping a source onto the target grid."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.transform import from_origin

from casa.grid import TargetGrid
from casa.inputs.regrid import BILINEAR, NEAREST, align_to_grid

# 400 m x 400 m extent in UTM 29N; target = 40x40 @ 10 m, source = 4x4 @ 100 m.
LEFT, TOP = 500000.0, 4280000.0
RES = 10.0
N = 40


def _grid() -> TargetGrid:
    transform = Affine.translation(LEFT, TOP) * Affine.scale(RES, -RES)
    return TargetGrid(
        crs=CRS.from_epsg(32629), transform=transform, width=N, height=N, resolution=RES
    )


def _write_source(path: Path, data: np.ndarray, *, dtype: str) -> None:
    h, w = data.shape
    transform = from_origin(LEFT, TOP, 400.0 / w, 400.0 / h)
    profile = {
        "driver": "GTiff",
        "height": h,
        "width": w,
        "count": 1,
        "dtype": dtype,
        "crs": "EPSG:32629",
        "transform": transform,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data.astype(dtype), 1)


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as ds:
        return ds.read(1)


def test_output_matches_grid_exactly(tmp_path: Path) -> None:
    grid = _grid()
    _write_source(tmp_path / "src.tif", np.full((4, 4), 800.0), dtype="float32")
    align_to_grid(tmp_path / "src.tif", grid, tmp_path / "out.tif", resampling=BILINEAR)
    with rasterio.open(tmp_path / "out.tif") as ds:
        assert (ds.width, ds.height) == (N, N)
        assert ds.crs.to_epsg() == 32629
        assert ds.transform == grid.transform


def test_bilinear_preserves_constant_field(tmp_path: Path) -> None:
    grid = _grid()
    _write_source(tmp_path / "src.tif", np.full((4, 4), 800.0), dtype="float32")
    align_to_grid(tmp_path / "src.tif", grid, tmp_path / "out.tif", resampling=BILINEAR)
    out = _read(tmp_path / "out.tif")
    finite = out[np.isfinite(out)]
    assert finite.size > 0
    assert np.allclose(finite, 800.0)


def test_bilinear_does_not_overshoot(tmp_path: Path) -> None:
    grid = _grid()
    ramp = np.arange(16, dtype="float32").reshape(4, 4) * 20.0  # 0..300
    _write_source(tmp_path / "src.tif", ramp, dtype="float32")
    align_to_grid(tmp_path / "src.tif", grid, tmp_path / "out.tif", resampling=BILINEAR)
    out = _read(tmp_path / "out.tif")
    finite = out[np.isfinite(out)]
    assert finite.min() >= ramp.min() - 1e-3
    assert finite.max() <= ramp.max() + 1e-3


def test_nearest_preserves_categorical_codes(tmp_path: Path) -> None:
    grid = _grid()
    codes = np.array([[0, 1, 5, 4], [1, 1, 0, 5], [4, 5, 1, 0], [0, 0, 4, 1]], dtype="uint8")
    _write_source(tmp_path / "lc.tif", codes, dtype="uint8")
    align_to_grid(
        tmp_path / "lc.tif",
        grid,
        tmp_path / "out.tif",
        resampling=NEAREST,
        dtype="uint8",
        nodata=None,
    )
    out = _read(tmp_path / "out.tif")
    assert out.dtype == np.uint8
    assert set(np.unique(out)).issubset(set(np.unique(codes)))


def test_windowed_write_matches_single_shot(tmp_path: Path) -> None:
    grid = _grid()
    ramp = np.arange(16, dtype="float32").reshape(4, 4) * 20.0
    _write_source(tmp_path / "src.tif", ramp, dtype="float32")
    align_to_grid(tmp_path / "src.tif", grid, tmp_path / "whole.tif", window_size=N)
    align_to_grid(tmp_path / "src.tif", grid, tmp_path / "tiled.tif", window_size=8)
    np.testing.assert_array_equal(_read(tmp_path / "whole.tif"), _read(tmp_path / "tiled.tif"))
