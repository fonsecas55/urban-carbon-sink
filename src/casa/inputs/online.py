"""Online orchestration: pull S2 + S3 + Dynamic World + CAMS + GHI for one region/month.

Used by the monthly Cron and by `casa run --online`. Pure orchestration: each
remote pull is delegated to its specialised module so the seams stay narrow and
individually mockable. Returns a `SourcePaths` ready for `prepare`.

`base_ghi_path` (Global Solar Atlas GHI baseline, kWh/m2/day, georeferenced) is
required from the caller — the CLI defaults to a path under `data/`, tests inject
a synthetic raster.
"""

from __future__ import annotations

import calendar
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds
from rasterio.windows import transform as window_transform

from casa.config import AppConfig
from casa.inputs.cams import fetch_cams_for_month
from casa.inputs.cdse import CdseAuth, ProcessClient, fetch_sentinel2, fetch_sentinel3
from casa.inputs.gee import fetch_dynamic_world, init_earth_engine
from casa.inputs.prepare import SourcePaths

BBox = tuple[float, float, float, float]


class OnlineError(RuntimeError):
    """Online download orchestration failure."""


@dataclass(frozen=True)
class DownloadResult:
    """What `download_region` resolves: raw input paths plus the month's solar
    deviation. `var_pct` is the CAMS-derived (or config-override) monthly
    deviation that `pipeline.run_region` feeds to the single SOL application."""

    sources: SourcePaths
    var_pct: float


def _process_client() -> ProcessClient:
    return ProcessClient(CdseAuth.from_env().token)


def _n_days(month: str) -> int:
    year, mon = (int(p) for p in month.split("-"))
    return calendar.monthrange(year, mon)[1]


def _resolve_var_pct(cfg: AppConfig, month: str, *, tmp_dir: Path) -> float:
    """`var_pct_mes` for `month`: config override wins, else live CAMS pull."""
    try:
        month_idx_0 = int(month.split("-")[1]) - 1
    except (ValueError, IndexError) as exc:
        raise OnlineError(f"month must be 'YYYY-MM', got {month!r}") from exc

    if cfg.region.var_pct_mes is not None:
        return float(cfg.region.var_pct_mes[month_idx_0])
    if cfg.region.cams_point is None:
        raise OnlineError(
            f"region '{cfg.region.name}' has neither var_pct_mes nor cams_point — "
            f"cannot derive the monthly solar deviation"
        )
    var_pct = fetch_cams_for_month(cfg.region.cams_point, month, tmp_dir=tmp_dir)
    return var_pct[month_idx_0 + 1]


def _crop_ghi_to_bbox(
    base_ghi_path: Path,
    bbox: BBox,
    out_path: Path,
) -> Path:
    """Crop `base_ghi_path` (daily GHI, kWh/m2/day) to `bbox`, preserving units.

    Only a crop: the CASA SOL term (kWh/m2/day -> MJ/m2/month, with the monthly
    `var_pct` and day count) is applied ONCE downstream by `pipeline.run_region`,
    so this helper must leave the data as raw daily GHI to honour the
    `RasterInputs.ghi` contract. Applying `sol` here too caused a double SOL
    (~108x inflation). Source is reprojected on read only if its CRS differs from
    EPSG:4326 (typical for Global Solar Atlas tiles); the output keeps the base
    CRS so downstream `align_to_grid` warps it once into the region target grid.
    """
    with rasterio.open(base_ghi_path) as src:
        if src.crs is None:
            raise OnlineError(f"{base_ghi_path}: missing CRS")
        if str(src.crs).upper() == "EPSG:4326":
            bounds_in_crs = bbox
        else:
            bounds_in_crs = transform_bounds("EPSG:4326", src.crs, *bbox)
        window = from_bounds(*bounds_in_crs, src.transform)
        data = src.read(1, window=window, boundless=True)
        nodata = src.nodata
        profile = src.profile.copy()
        profile.update(
            transform=window_transform(window, src.transform),
            width=data.shape[1],
            height=data.shape[0],
            dtype="float32",
            count=1,
            nodata=float("nan"),
        )

    data_f = data.astype(np.float32)
    if nodata is not None:
        data_f[data == nodata] = np.nan

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data_f, 1)
    return out_path


def download_region(
    cfg: AppConfig,
    month: str,
    out_dir: Path,
    *,
    base_ghi_path: Path,
    esa_fallback_path: Path | None = None,
    process_client: ProcessClient | None = None,
    init_ee: bool = True,
) -> DownloadResult:
    """Pull every raw input for `cfg.region`/`month` into `out_dir/raw/`.

    Parameters:
    - `base_ghi_path`: Global Solar Atlas baseline (georeferenced, kWh/m2/day).
    - `esa_fallback_path`: required when `pipeline.landcover_source == "esa_worldcover"`.
    - `process_client`: inject a CDSE Process API client for tests; else built
      from `CDSE_CLIENT_ID`/`CDSE_CLIENT_SECRET` env vars.
    - `init_ee`: set False in tests; else `gee.init_earth_engine()` runs once
      before the Dynamic World fetch.
    """
    bbox = cfg.region.bbox
    if bbox is None:
        raise OnlineError(f"region '{cfg.region.name}' has no resolvable bbox")
    raw_dir = Path(out_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    client = process_client if process_client is not None else _process_client()
    s2 = fetch_sentinel2(bbox, month, raw_dir, client)
    s3 = fetch_sentinel3(bbox, month, raw_dir, client)

    if cfg.pipeline.landcover_source == "dynamic_world":
        if init_ee:
            init_earth_engine()
        lc_path = fetch_dynamic_world(bbox, month, raw_dir / "landcover.tif")
    else:
        if esa_fallback_path is None or not Path(esa_fallback_path).exists():
            raise OnlineError(
                "landcover_source=esa_worldcover but no fallback raster was provided"
            )
        lc_path = raw_dir / "landcover.tif"
        shutil.copyfile(esa_fallback_path, lc_path)

    var_pct_mes = _resolve_var_pct(cfg, month, tmp_dir=raw_dir / "cams")
    ghi_path = _crop_ghi_to_bbox(base_ghi_path, bbox, raw_dir / "ghi.tif")

    sources = SourcePaths(
        red=s2["red"],
        nir=s2["nir"],
        swir1=s2["swir1"],
        swir2=s2["swir2"],
        t_day=s3["t_day"],
        t_night=s3["t_night"],
        ghi=ghi_path,
        landcover=lc_path,
    )
    return DownloadResult(sources=sources, var_pct=var_pct_mes)
