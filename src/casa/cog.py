"""Cloud-Optimized GeoTIFF finalisation (rio-cogeo).

The windowed pipeline writes a plain tiled GeoTIFF; the frontend reads it
browser-side via `georaster`, which needs a *valid* COG (internal overviews +
ordered IFDs). We rewrite the output in place so the published asset is a real
COG, not just a tiled TIFF.

Convention (docs/pipeline.md 3.7) is DEFLATE + BLOCKSIZE=512. The spec wrote
`PREDICTOR=2`, but our rasters are float32 and predictor 2 is the *integer*
horizontal predictor (GDAL rejects/ degrades it on floats); the correct one for
floating-point data is predictor 3, used here.

The pipeline grid is regional UTM (e.g. EPSG:32629 for Oeiras). The browser map
(Leaflet + georaster-layer-for-leaflet) is happiest reading geographic lat/lon,
so we reproject to EPSG:4326 here — once, on the server — rather than forcing the
client to warp UTM->lat/lon per pan/zoom. (Alternative, if alignment/perf ever
needs it: rio-cogeo `web_optimized=True` produces a 3857 tile-aligned COG.)
"""

from __future__ import annotations

from pathlib import Path

import rasterio
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rio_cogeo.cogeo import cog_translate, cog_validate

PREDICTOR_FLOAT = 3  # GDAL floating-point predictor (not 2, which is integer-only)
WEB_CRS = "EPSG:4326"  # geographic lat/lon — the low-friction CRS for georaster-layer


def _reproject_if_needed(path: Path, dst_crs: str) -> Path | None:
    """Reproject `path` to `dst_crs` into a sidecar file; None if already there.

    Bilinear (smooth display); the authoritative totals live in the JSON, so
    resampling the COG for visualisation does not touch the science numbers.
    """
    with rasterio.open(path) as src:
        if src.crs is None or str(src.crs).upper() == dst_crs.upper():
            return None
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        profile = src.profile.copy()
        profile.update(crs=dst_crs, transform=transform, width=width, height=height)
        dst_path = path.with_suffix(".reproj.tif")
        with rasterio.open(dst_path, "w", **profile) as dst:
            reproject(
                source=rasterio.band(src, 1),
                destination=rasterio.band(dst, 1),
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
                src_nodata=src.nodata,
                dst_nodata=src.nodata,
            )
    return dst_path


def to_cog(path: Path, *, dst_crs: str = WEB_CRS, blocksize: int = 512) -> Path:
    """Rewrite `path` in place as a valid web COG: reproject to `dst_crs` (default
    EPSG:4326), then DEFLATE + float predictor + internal overviews."""
    reprojected = _reproject_if_needed(path, dst_crs)
    source = reprojected if reprojected is not None else path

    # Explicit COG creation profile (equivalent to rio-cogeo's "deflate" profile,
    # but spelled out so the float predictor is unambiguous and there is no
    # untyped call into rio_cogeo.profiles).
    profile: dict[str, object] = {
        "driver": "GTiff",
        "interleave": "pixel",
        "tiled": True,
        "blockxsize": blocksize,
        "blockysize": blocksize,
        "compress": "DEFLATE",
        "predictor": PREDICTOR_FLOAT,
    }
    tmp = path.with_suffix(".cogtmp.tif")
    cog_translate(
        str(source),
        str(tmp),
        profile,
        in_memory=False,
        overview_resampling="average",
        quiet=True,
    )
    tmp.replace(path)
    if reprojected is not None:
        reprojected.unlink(missing_ok=True)
    return path


def is_valid_cog(path: Path) -> bool:
    """True if `path` passes rio-cogeo's COG validation (overviews + layout)."""
    valid, _errors, _warnings = cog_validate(str(path), quiet=True)
    return bool(valid)
