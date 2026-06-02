"""Region geometry -> raster mask on the target grid.

Replaces the legacy "last pixel" background hack (`fpar[fpar == fpar[-1,-1]]`):
the spatial mask now comes from the region's WKT geometry, rasterised on the
common grid. Pixels outside the region are set to NoData on the continuous
inputs so the pipeline's `valid` mask drops them naturally — no change to the
Bloco 3 contract.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from casa.grid import WGS84, TargetGrid


def resolve_geometry(geometry_wkt: str | None, geometry_path: str | Path | None) -> BaseGeometry:
    """Load the region geometry from inline WKT or a `.wkt` file (lon/lat)."""
    if geometry_wkt:
        return shapely_wkt.loads(geometry_wkt)
    if geometry_path:
        text = Path(geometry_path).read_text(encoding="utf-8")
        return shapely_wkt.loads(text)
    raise ValueError("need geometry_wkt or geometry_path")


def region_mask(geom: BaseGeometry, grid: TargetGrid) -> NDArray[np.bool_]:
    """Boolean mask on `grid`: True inside the region geometry.

    The geometry is assumed lon/lat (EPSG:4326) and is reprojected to the grid
    CRS before rasterising.
    """
    geom_grid = transform_geom(WGS84, grid.crs, mapping(geom))
    mask = geometry_mask([geom_grid], out_shape=grid.shape, transform=grid.transform, invert=True)
    return np.asarray(mask, dtype=bool)


def apply_mask_nodata(
    raster_path: Path, mask: NDArray[np.bool_], nodata: float = float("nan")
) -> None:
    """Set pixels outside `mask` (False) to `nodata`, in place."""
    with rasterio.open(raster_path, "r+") as ds:
        data = ds.read(1)
        data[~mask] = nodata
        ds.write(data, 1)
