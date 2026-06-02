"""Common target grid for a region: bbox (lon/lat) -> UTM, snapped to 10 m.

Pure geometry math (pyproj / rasterio.warp), no file I/O. The input-prep layer
(`inputs/`) reprojects and resamples each source onto this grid; the pipeline
then trusts the aligned rasters (ADR-017).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform_bounds

BBox = tuple[float, float, float, float]

DEFAULT_RESOLUTION_M = 10.0
WGS84 = "EPSG:4326"


def utm_epsg_from_lonlat(lon: float, lat: float) -> int:
    """EPSG code of the UTM zone containing (lon, lat)."""
    zone = math.floor((lon + 180.0) / 6.0) + 1
    zone = min(max(zone, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


@dataclass(frozen=True)
class TargetGrid:
    """Immutable description of the common processing grid."""

    crs: CRS
    transform: Affine
    width: int
    height: int
    resolution: float

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)

    @property
    def pixel_area_m2(self) -> float:
        return self.resolution * self.resolution

    @property
    def bounds(self) -> BBox:
        """(minx, miny, maxx, maxy) in the target CRS."""
        minx = self.transform.c
        maxy = self.transform.f
        maxx = minx + self.width * self.resolution
        miny = maxy - self.height * self.resolution
        return (minx, miny, maxx, maxy)


def target_grid_from_bbox(
    bbox_lonlat: BBox,
    resolution: float = DEFAULT_RESOLUTION_M,
    src_crs: str = WGS84,
) -> TargetGrid:
    """Build the UTM, north-up, `resolution`-metre grid covering a lon/lat bbox.

    Bounds are reprojected to the bbox-centre UTM zone and snapped outward to a
    whole number of pixels so the grid fully contains the region.
    """
    minx, miny, maxx, maxy = bbox_lonlat
    if maxx <= minx or maxy <= miny:
        raise ValueError(f"degenerate bbox: {bbox_lonlat}")

    centre_lon = 0.5 * (minx + maxx)
    centre_lat = 0.5 * (miny + maxy)
    dst_crs = CRS.from_epsg(utm_epsg_from_lonlat(centre_lon, centre_lat))

    left, bottom, right, top = transform_bounds(
        CRS.from_string(src_crs), dst_crs, minx, miny, maxx, maxy
    )

    left = math.floor(left / resolution) * resolution
    bottom = math.floor(bottom / resolution) * resolution
    right = math.ceil(right / resolution) * resolution
    top = math.ceil(top / resolution) * resolution

    width = round((right - left) / resolution)
    height = round((top - bottom) / resolution)
    transform = Affine.translation(left, top) * Affine.scale(resolution, -resolution)

    return TargetGrid(
        crs=dst_crs,
        transform=transform,
        width=width,
        height=height,
        resolution=resolution,
    )
