"""Offline input preparation: raw source rasters -> grid-aligned `RasterInputs`.

Given a region config and a set of raw source rasters (any CRS/resolution), this
builds the region's target grid, warps every band onto it, masks out pixels
outside the region geometry, and returns the `RasterInputs` the pipeline
consumes. The remote pull (GEE/CDSE) that produces the raw sources lives in
`download.py` and is deferred to Bloco 6; this layer is fully offline/testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from casa.config import AppConfig
from casa.grid import target_grid_from_bbox
from casa.inputs.mask import apply_mask_nodata, region_mask, resolve_geometry
from casa.inputs.regrid import BILINEAR, NEAREST, align_to_grid
from casa.pipeline import RasterInputs

NAN = float("nan")


@dataclass(frozen=True)
class SourcePaths:
    """Raw, unaligned source rasters (any CRS/resolution) for one region/month."""

    red: Path  # Sentinel-2 B4
    nir: Path  # B8
    swir1: Path  # B11
    swir2: Path  # B12
    t_day: Path  # Sentinel-3 LST day (degrees C)
    t_night: Path  # Sentinel-3 LST night (degrees C)
    ghi: Path  # Global Solar Atlas GHI (kWh/m2/day)
    landcover: Path  # Dynamic World / ESA WorldCover codes


def prepare_region_inputs(cfg: AppConfig, sources: SourcePaths, out_dir: Path) -> RasterInputs:
    """Align all sources to the region grid, mask outside the geometry, return paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    geom = resolve_geometry(cfg.region.geometry_wkt, cfg.region.geometry_path)
    grid = target_grid_from_bbox(geom.bounds)
    mask = region_mask(geom, grid)

    continuous = {
        "red": sources.red,
        "nir": sources.nir,
        "swir1": sources.swir1,
        "swir2": sources.swir2,
        "t_day": sources.t_day,
        "t_night": sources.t_night,
        "ghi": sources.ghi,
    }
    aligned: dict[str, Path] = {}
    for name, src in continuous.items():
        dst = out_dir / f"{name}.tif"
        align_to_grid(src, grid, dst, resampling=BILINEAR, dtype="float32", nodata=NAN)
        apply_mask_nodata(dst, mask, NAN)
        aligned[name] = dst

    # Land-cover stays categorical (nearest, uint8) and unmasked: out-of-region
    # pixels are already dropped because the continuous bands are NoData there.
    lc_dst = out_dir / "landcover.tif"
    align_to_grid(sources.landcover, grid, lc_dst, resampling=NEAREST, dtype="uint8", nodata=None)

    return RasterInputs(
        red=aligned["red"],
        nir=aligned["nir"],
        swir1=aligned["swir1"],
        swir2=aligned["swir2"],
        t_day=aligned["t_day"],
        t_night=aligned["t_night"],
        ghi=aligned["ghi"],
        landcover=lc_dst,
    )
