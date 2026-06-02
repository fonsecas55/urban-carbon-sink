"""Reproject/resample an arbitrary source raster onto a region's target grid.

The pipeline (`casa.pipeline.run_region`) assumes every input raster already
shares the common target grid (CRS/transform/shape). This module is what
produces them: it wraps each source in a lazy `WarpedVRT` on the target grid and
writes the result windowed, so peak RAM stays bounded even for the Sentinel-3
LST 1 km -> 10 m upsample (ADR-012, pipeline.md sec. 3.5).

Continuous bands use bilinear resampling (float32, NaN NoData); categorical
land-cover uses nearest, preserving the integer Dynamic World / ESA codes that
`casa.landcover` later maps to the canonical schema.
"""

from __future__ import annotations

from pathlib import Path

import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

from casa.grid import TargetGrid
from casa.pipeline import iter_windows

BILINEAR = Resampling.bilinear
NEAREST = Resampling.nearest


def align_to_grid(
    src_path: Path,
    grid: TargetGrid,
    dst_path: Path,
    *,
    resampling: Resampling = BILINEAR,
    dtype: str = "float32",
    nodata: float | None = float("nan"),
    window_size: int = 1024,
) -> Path:
    """Warp `src_path` onto `grid` and write a tiled GeoTIFF to `dst_path`.

    The output matches the grid exactly (CRS/transform/width/height), so the
    pipeline's pre-alignment check passes. Reading and writing happen per window
    to cap memory regardless of region size.
    """
    vrt_kwargs: dict[str, object] = {
        "crs": grid.crs,
        "transform": grid.transform,
        "width": grid.width,
        "height": grid.height,
        "resampling": resampling,
        "dtype": dtype,
    }
    if nodata is not None:
        vrt_kwargs["nodata"] = nodata

    profile: dict[str, object] = {
        "driver": "GTiff",
        "crs": grid.crs,
        "transform": grid.transform,
        "width": grid.width,
        "height": grid.height,
        "count": 1,
        "dtype": dtype,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
    }
    if nodata is not None:
        profile["nodata"] = nodata

    with (
        rasterio.open(src_path) as src,
        WarpedVRT(src, **vrt_kwargs) as vrt,
        rasterio.open(dst_path, "w", **profile) as dst,
    ):
        for win in iter_windows(grid.width, grid.height, window_size):
            dst.write(vrt.read(1, window=win), 1, window=win)

    return dst_path
