"""Windowed orchestrator: ties Bloco 1 math to Bloco 2 config over raster I/O.

Geography and windowing live HERE; the math modules only ever see pure arrays
(ADR-017). Inputs are assumed already on the common target grid — the pipeline
reads the grid from the reference band (red) and asserts the others match.

The window loop is sequential (ADR-012/ADR-017): partial NPP/CO2 sums are
accumulated per window so peak RAM stays bounded regardless of region size.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.windows import Window

from casa import landcover as lc
from casa.config import AppConfig
from casa.emax import emax
from casa.fpar import fpar
from casa.ndvi import ndvi
from casa.npp import density_to_tonnes, npp, npp_c_to_co2
from casa.sol import sol
from casa.tstress import t_eps1, t_eps2, t_mean
from casa.wsc import wsc

FloatArray = NDArray[np.floating]


@dataclass(frozen=True)
class RasterInputs:
    """Paths to the per-band rasters, all already on the common grid."""

    red: Path  # Sentinel-2 B4
    nir: Path  # B8
    swir1: Path  # B11
    swir2: Path  # B12
    t_day: Path  # Sentinel-3 LST day (degrees C)
    t_night: Path  # Sentinel-3 LST night (degrees C)
    ghi: Path  # Global Solar Atlas GHI (kWh/m2/day)
    landcover: Path  # Dynamic World / ESA WorldCover codes


@dataclass(frozen=True)
class RegionResult:
    """Accumulated totals for one region/month run."""

    region: str
    month: str
    crs: str
    width: int
    height: int
    resolution: float
    total_npp_c_t: float
    total_npp_co2_t: float
    valid_pixels: int
    vegetation_pixels: int
    t_day_mean: float  # mean daytime LST (C) over valid px; quality signal (cloud-cold S3)
    output_path: Path


def iter_windows(width: int, height: int, block: int) -> Iterator[Window]:
    """Yield row-major `block`x`block` windows tiling a width x height raster."""
    for row in range(0, height, block):
        h = min(block, height - row)
        for col in range(0, width, block):
            w = min(block, width - col)
            yield Window(col, row, w, h)


def _days_in_month(month: str) -> int:
    year, mon = (int(p) for p in month.split("-"))
    return calendar.monthrange(year, mon)[1]


def _to_canonical(codes: NDArray[np.generic], source: str) -> NDArray[np.uint8]:
    if source == "dynamic_world":
        return lc.dw_to_canonical(codes)
    return lc.esa_to_canonical(codes)


def _compute_window(
    red: FloatArray,
    nir: FloatArray,
    swir1: FloatArray,
    swir2: FloatArray,
    t_day: FloatArray,
    t_night: FloatArray,
    ghi: FloatArray,
    canonical: NDArray[np.uint8],
    cfg: AppConfig,
    var_pct: float,
    n_dias: int,
) -> tuple[FloatArray, FloatArray, NDArray[np.bool_], NDArray[np.bool_]]:
    """Run the full CASA chain on one window's arrays.

    Returns (npp_c_density, npp_co2_density, valid_mask, vegetation_mask). NPP is
    zeroed on invalid (NoData) pixels so partial sums stay finite.
    """
    fp = cfg.fpar_percentiles
    nd = ndvi(red, nir)
    emax_arr = emax(canonical, cfg.epsilon_max.as_dict())
    fpar_arr = fpar(
        nd,
        canonical,
        np.asarray(fp.ndvi_min),
        np.asarray(fp.ndvi_max),
        np.asarray(fp.sr_min),
        np.asarray(fp.sr_max),
    )
    wsc_arr = wsc(swir1, swir2, cfg.wsc_percentiles.simi_min, cfg.wsc_percentiles.simi_max)

    t_opt_pix = np.asarray(cfg.t_opt.by_code, dtype=np.float64)[canonical]
    te1 = t_eps1(t_opt_pix)
    te2 = t_eps2(t_mean(t_day, t_night), t_opt_pix)
    sol_arr = sol(ghi, var_pct, n_dias)

    npp_c = npp(sol_arr, fpar_arr, emax_arr, te1, te2, wsc_arr, par_fraction=cfg.pipeline.par_fraction)

    valid = (
        np.isfinite(red)
        & np.isfinite(nir)
        & np.isfinite(swir1)
        & np.isfinite(swir2)
        & np.isfinite(t_day)
        & np.isfinite(t_night)
        & np.isfinite(ghi)
    )
    npp_c = np.where(valid, npp_c, 0.0)
    npp_co2 = npp_c_to_co2(npp_c)
    veg = valid & (emax_arr > 0.0)
    return npp_c, npp_co2, valid, veg


def _read_window(ds: rasterio.DatasetReader, window: Window) -> FloatArray:
    """Read one band/window as float64 with NoData -> NaN."""
    arr = ds.read(1, window=window, masked=True)
    return np.ma.filled(arr.astype(np.float64), np.nan)


def run_region(
    inputs: RasterInputs,
    cfg: AppConfig,
    month: str,
    output_path: Path,
    *,
    var_pct: float | None = None,
) -> RegionResult:
    """Process one region/month, writing a CO2-density GeoTIFF and returning totals.

    `var_pct` is the month's solar deviation (%) fed to the single SOL term. The
    online path passes the CAMS-derived value; when None (offline), it falls back
    to the region's static `var_pct_mes` config (0 if unset).
    """
    if var_pct is None:
        var_pct = 0.0 if cfg.region.var_pct_mes is None else cfg.region.var_pct_mes[int(month[5:7]) - 1]
    n_dias = _days_in_month(month)
    block = cfg.pipeline.window_size
    source = cfg.pipeline.landcover_source

    total_c = 0.0
    total_co2 = 0.0
    valid_px = 0
    veg_px = 0
    t_day_sum = 0.0  # accumulated over valid px, divided by valid_px at the end

    with ExitStack() as stack:
        ref = stack.enter_context(rasterio.open(inputs.red))
        width, height = ref.width, ref.height
        resolution = abs(ref.transform.a)
        area = resolution * resolution

        paths = [
            inputs.nir,
            inputs.swir1,
            inputs.swir2,
            inputs.t_day,
            inputs.t_night,
            inputs.ghi,
            inputs.landcover,
        ]
        others = [stack.enter_context(rasterio.open(p)) for p in paths]
        for ds in others:
            if (ds.width, ds.height) != (width, height):
                raise ValueError(
                    f"input {ds.name} is {ds.width}x{ds.height}, expected {width}x{height} "
                    "(inputs must be pre-aligned to the common grid, ADR-017)"
                )
        nir_ds, swir1_ds, swir2_ds, tday_ds, tnight_ds, ghi_ds, lc_ds = others

        out_profile = ref.profile.copy()
        out_profile.update(
            dtype="float32",
            count=1,
            nodata=float("nan"),
            compress="deflate",
            tiled=True,
            blockxsize=512,
            blockysize=512,
        )
        dst = stack.enter_context(rasterio.open(output_path, "w", **out_profile))

        for win in iter_windows(width, height, block):
            red = _read_window(ref, win)
            nir = _read_window(nir_ds, win)
            swir1 = _read_window(swir1_ds, win)
            swir2 = _read_window(swir2_ds, win)
            t_day = _read_window(tday_ds, win)
            t_night = _read_window(tnight_ds, win)
            ghi = _read_window(ghi_ds, win)
            canonical = _to_canonical(lc_ds.read(1, window=win), source)

            npp_c, npp_co2, valid, veg = _compute_window(
                red, nir, swir1, swir2, t_day, t_night, ghi, canonical, cfg, var_pct, n_dias
            )

            total_c += float(density_to_tonnes(npp_c, area).sum())
            total_co2 += float(density_to_tonnes(npp_co2, area).sum())
            valid_px += int(valid.sum())
            veg_px += int(veg.sum())
            t_day_sum += float(t_day[valid].sum())  # valid implies t_day finite

            out = np.where(valid, npp_co2, np.nan).astype(np.float32)
            dst.write(out, 1, window=win)

        crs_str = str(ref.crs)

    t_day_mean = t_day_sum / valid_px if valid_px else float("nan")

    return RegionResult(
        region=cfg.region.name,
        month=month,
        crs=crs_str,
        width=width,
        height=height,
        resolution=resolution,
        total_npp_c_t=total_c,
        total_npp_co2_t=total_co2,
        valid_pixels=valid_px,
        vegetation_pixels=veg_px,
        t_day_mean=t_day_mean,
        output_path=output_path,
    )
