"""Integration: raw sources (lon/lat) -> prepare -> windowed pipeline -> totals.

Exercises the full offline path the `casa run` CLI drives: synthetic source
rasters in EPSG:4326 at a coarse resolution are warped onto the region's UTM
10 m grid, masked by the region geometry, and consumed by `run_region`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon

from casa.config import AppConfig, load
from casa.grid import target_grid_from_bbox
from casa.inputs.prepare import SourcePaths, prepare_region_inputs
from casa.pipeline import run_region

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

# Tiny lon/lat box near Oeiras; triangle geometry covers ~half of it.
MINX, MINY, MAXX, MAXY = -9.300, 38.700, -9.296, 38.703
TRIANGLE = Polygon([(MINX, MINY), (MAXX, MINY), (MINX, MAXY)])

# Constant source values mirror tests/unit/test_pipeline.py.
_CONTINUOUS = {
    "red": 800.0,
    "nir": 4000.0,
    "swir1": 1500.0,
    "swir2": 1000.0,
    "t_day": 30.0,
    "t_night": 15.0,
    "ghi": 5.0,
}
SW = SH = 8  # coarse source grid


def _write_ll(path: Path, value: float, *, dtype: str) -> None:
    transform = from_origin(MINX, MAXY, (MAXX - MINX) / SW, (MAXY - MINY) / SH)
    profile = {
        "driver": "GTiff",
        "height": SH,
        "width": SW,
        "count": 1,
        "dtype": dtype,
        "crs": "EPSG:4326",
        "transform": transform,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.full((SH, SW), value, dtype=dtype), 1)


def _make_sources(src_dir: Path) -> SourcePaths:
    src_dir.mkdir(parents=True, exist_ok=True)
    for name, value in _CONTINUOUS.items():
        _write_ll(src_dir / f"{name}.tif", value, dtype="float32")
    _write_ll(src_dir / "landcover.tif", 1.0, dtype="uint8")  # DW code 1 = trees
    return SourcePaths(**{name: src_dir / f"{name}.tif" for name in (*_CONTINUOUS, "landcover")})


def _cfg() -> AppConfig:
    base = load(CONFIG_DIR, region="oeiras")
    region = base.region.model_copy(update={"geometry_wkt": TRIANGLE.wkt})
    return base.model_copy(update={"region": region})


def test_prepare_aligns_all_bands_to_common_grid(tmp_path: Path) -> None:
    cfg = _cfg()
    sources = _make_sources(tmp_path / "src")
    inputs = prepare_region_inputs(cfg, sources, tmp_path / "aligned")
    grid = target_grid_from_bbox(TRIANGLE.bounds)

    for path in (inputs.red, inputs.nir, inputs.landcover, inputs.t_day, inputs.ghi):
        with rasterio.open(path) as ds:
            assert (ds.width, ds.height) == (grid.width, grid.height)
            assert ds.crs == grid.crs
            assert ds.transform == grid.transform


def test_end_to_end_run_region(tmp_path: Path) -> None:
    cfg = _cfg()
    sources = _make_sources(tmp_path / "src")
    inputs = prepare_region_inputs(cfg, sources, tmp_path / "aligned")
    grid = target_grid_from_bbox(TRIANGLE.bounds)

    result = run_region(inputs, cfg, "2024-06", tmp_path / "oeiras_npp_co2.tif")

    assert np.isfinite(result.total_npp_co2_t)
    assert result.total_npp_co2_t > 0.0
    # Triangle masks out roughly half the bbox -> not every pixel is valid.
    assert 0 < result.valid_pixels < grid.width * grid.height
    assert result.vegetation_pixels == result.valid_pixels  # all trees where valid
    assert (tmp_path / "oeiras_npp_co2.tif").exists()
