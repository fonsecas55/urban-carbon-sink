"""Unit tests for casa.pipeline — windowed orchestration over synthetic rasters."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from casa.config import AppConfig, load
from casa.pipeline import RasterInputs, iter_windows, run_region

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
H, W = 48, 64


def _write(path: Path, data: np.ndarray, *, dtype: str, nodata: float | None = None) -> None:
    transform = from_origin(500000.0, 4280000.0, 10.0, 10.0)
    profile = {
        "driver": "GTiff",
        "height": data.shape[0],
        "width": data.shape[1],
        "count": 1,
        "dtype": dtype,
        "crs": "EPSG:32629",
        "transform": transform,
    }
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data.astype(dtype), 1)


def _make_inputs(tmp: Path, landcover: np.ndarray, *, red_nodata: bool = False) -> RasterInputs:
    red = np.full((H, W), 800.0)
    if red_nodata:
        red[0, :] = -9999.0  # one nodata row
    _write(tmp / "red.tif", red, dtype="float32", nodata=-9999.0 if red_nodata else None)
    _write(tmp / "nir.tif", np.full((H, W), 4000.0), dtype="float32")
    _write(tmp / "swir1.tif", np.full((H, W), 1500.0), dtype="float32")
    _write(tmp / "swir2.tif", np.full((H, W), 1000.0), dtype="float32")
    _write(tmp / "tday.tif", np.full((H, W), 30.0), dtype="float32")
    _write(tmp / "tnight.tif", np.full((H, W), 15.0), dtype="float32")
    _write(tmp / "ghi.tif", np.full((H, W), 5.0), dtype="float32")
    _write(tmp / "lc.tif", landcover, dtype="uint8")
    return RasterInputs(
        red=tmp / "red.tif",
        nir=tmp / "nir.tif",
        swir1=tmp / "swir1.tif",
        swir2=tmp / "swir2.tif",
        t_day=tmp / "tday.tif",
        t_night=tmp / "tnight.tif",
        ghi=tmp / "ghi.tif",
        landcover=tmp / "lc.tif",
    )


def _cfg(window_size: int) -> AppConfig:
    base = load(CONFIG_DIR, region="oeiras")
    return base.model_copy(
        update={"pipeline": base.pipeline.model_copy(update={"window_size": window_size})}
    )


def test_iter_windows_tiles_exactly() -> None:
    windows = list(iter_windows(64, 48, 16))
    assert len(windows) == 4 * 3
    total = sum(w.width * w.height for w in windows)
    assert total == 64 * 48


def test_iter_windows_handles_ragged_edge() -> None:
    windows = list(iter_windows(50, 50, 32))
    assert {(w.width, w.height) for w in windows} == {(32, 32), (18, 32), (32, 18), (18, 18)}


def test_windowed_accumulation_is_block_invariant(tmp_path: Path) -> None:
    # ADR-012: regional totals must not depend on window size.
    lc = np.ones((H, W), dtype=np.uint8)  # all trees (DW code 1)
    inputs = _make_inputs(tmp_path, lc)

    whole = run_region(inputs, _cfg(256), "2024-06", tmp_path / "whole.tif")
    tiled = run_region(inputs, _cfg(16), "2024-06", tmp_path / "tiled.tif")

    assert tiled.total_npp_co2_t == pytest.approx(whole.total_npp_co2_t, rel=1e-9)
    assert tiled.total_npp_c_t == pytest.approx(whole.total_npp_c_t, rel=1e-9)
    assert tiled.vegetation_pixels == whole.vegetation_pixels == H * W


def test_co2_is_carbon_times_ratio(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path, np.ones((H, W), dtype=np.uint8))
    result = run_region(inputs, _cfg(64), "2024-06", tmp_path / "out.tif")
    assert result.total_npp_co2_t == pytest.approx(result.total_npp_c_t * 44.0 / 12.0)


def test_non_vegetation_yields_zero(tmp_path: Path) -> None:
    lc = np.zeros((H, W), dtype=np.uint8)  # all water (DW code 0 -> non_vegetation)
    inputs = _make_inputs(tmp_path, lc)
    result = run_region(inputs, _cfg(32), "2024-06", tmp_path / "out.tif")
    assert result.total_npp_co2_t == 0.0
    assert result.vegetation_pixels == 0
    assert result.valid_pixels == H * W  # still valid, just not vegetation


def test_nodata_excluded_from_valid(tmp_path: Path) -> None:
    lc = np.ones((H, W), dtype=np.uint8)
    inputs = _make_inputs(tmp_path, lc, red_nodata=True)
    result = run_region(inputs, _cfg(64), "2024-06", tmp_path / "out.tif")
    assert result.valid_pixels == (H - 1) * W  # one nodata row dropped
    assert result.vegetation_pixels == (H - 1) * W


def test_output_raster_written_with_grid(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path, np.ones((H, W), dtype=np.uint8))
    out = tmp_path / "co2.tif"
    result = run_region(inputs, _cfg(16), "2024-06", out)
    assert out.exists()
    with rasterio.open(out) as ds:
        assert (ds.width, ds.height) == (W, H)
        assert ds.crs.to_epsg() == 32629
        assert ds.count == 1
    assert result.crs == "EPSG:32629"


def test_misaligned_input_raises(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path, np.ones((H, W), dtype=np.uint8))
    _write(tmp_path / "nir.tif", np.full((H, W + 5), 4000.0), dtype="float32")  # wrong width
    with pytest.raises(ValueError, match="pre-aligned"):
        run_region(inputs, _cfg(64), "2024-06", tmp_path / "out.tif")
