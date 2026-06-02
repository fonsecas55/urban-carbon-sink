"""Synthetic tests for casa.cog — finalise a tiled TIFF into a valid COG."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from casa.cog import is_valid_cog, to_cog


def _write_plain_tiff(path: Path, *, size: int = 600) -> None:
    """A tiled float32 GeoTIFF WITHOUT overviews — i.e. not yet a valid COG."""
    profile = {
        "driver": "GTiff",
        "height": size,
        "width": size,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:32629",
        "transform": from_origin(500000, 4200000, 10, 10),
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    rng = np.random.default_rng(0)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(rng.random((size, size), dtype="float32"), 1)


def test_plain_tiff_has_no_overviews(tmp_path: Path) -> None:
    src = tmp_path / "plain.tif"
    _write_plain_tiff(src)
    with rasterio.open(src) as ds:
        assert ds.overviews(1) == []  # the tiled pipeline output is NOT a real COG yet


def test_to_cog_produces_valid_cog_in_place(tmp_path: Path) -> None:
    src = tmp_path / "out.tif"
    _write_plain_tiff(src)  # EPSG:32629 (UTM)

    out = to_cog(src)

    assert out == src
    assert is_valid_cog(src) is True
    with rasterio.open(src) as ds:
        assert ds.overviews(1)  # overviews were built (the real-COG differentiator)
        assert ds.profile["dtype"] == "float32"
        assert ds.compression is not None  # DEFLATE applied
        assert ds.crs.to_epsg() == 4326  # reprojected UTM -> lat/lon for the web map


def test_to_cog_is_noop_crs_when_already_4326(tmp_path: Path) -> None:
    src = tmp_path / "geo.tif"
    profile = {
        "driver": "GTiff",
        "height": 256,
        "width": 256,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_origin(-9.35, 38.75, 0.001, 0.001),
        "tiled": True,
        "blockxsize": 128,
        "blockysize": 128,
    }
    rng = np.random.default_rng(1)
    with rasterio.open(src, "w", **profile) as dst:
        dst.write(rng.random((256, 256), dtype="float32"), 1)

    to_cog(src)

    assert is_valid_cog(src) is True
    with rasterio.open(src) as ds:
        assert ds.crs.to_epsg() == 4326  # already geographic -> not reprojected
