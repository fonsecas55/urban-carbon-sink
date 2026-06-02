"""One-off validation: run CASA on the real Oeiras 2025-04 scene, compare to report.

NOT part of the package (Bloco B validation, exploratory). Uses the single local
Sentinel-2/3 scene migrated from the legacy repo. Run:

    uv run python tools/validate_oeiras_2025_04.py

Documented caveats — this is INDICATIVE, not an exact reproduction of the report:
- FPAR/WSC percentiles: provisional, computed from THIS single scene over Oeiras
  (the production multi-temporal 5/95 & 2/98 calibration is deferred to Bloco 6).
- Sentinel-3 day/night LST gap: the legacy day/night subsets are empty, so the one
  clean LST raster is used for both -> T_mean = that LST (no diurnal amplitude).
- epsilon_max = Xu 2023 (default), which differs from the report's own table.
- Geometry = real municipal polygon (report used a bounding square).

S2 bands keep their native x10000 reflectance scale: NDVI/SR are scale-invariant,
and casa.wsc.simi divides by 10000 internally, so feeding [0,1] would double-scale.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio

from casa import landcover as lc
from casa.config import FparPercentiles, WscPercentiles, load
from casa.inputs.prepare import SourcePaths, prepare_region_inputs
from casa.ndvi import ndvi as ndvi_fn
from casa.ndvi import simple_ratio
from casa.pipeline import RasterInputs, run_region
from casa.reports import build_report
from casa.wsc import simi as simi_fn

# Legacy INPUTS dir holding the 2025-04 scene. Override via argv[1] or $CASA_LEGACY_INPUTS.
_DEFAULT_LEGACY = r"E:\Obsidian Vault\MAIN_VAULT\PROJETO\CODE\PFC_V3.1\NPP_CALC_PROJ\INPUTS"
LEGACY = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CASA_LEGACY_INPUTS", _DEFAULT_LEGACY))
CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

S2 = LEGACY / "SENTINEL2" / "Sentinel2_Bands.tif"  # bands 1-4 = B04, B08, B11, B12
LST = LEGACY / "SENTINEL3" / "Sentinel3_LST.tif"  # Kelvin
GHI = LEGACY / "SOL" / "GHI.tif"  # kWh/m2/day, global
ESA = LEGACY / "Subset_ESA_WorldCover_10m_2021_v200_N36W012_Map.tif"  # ESA codes

MONTH = "2025-04"
REPORT_TC = 4521.0  # report's monthly mean tC for Oeiras (RELATORIOS/Relatório Final-P33)


def _write_band(path: Path, arr: np.ndarray, profile: dict, nodata: float) -> None:
    prof = profile.copy()
    prof.update(count=1, dtype="float32", nodata=nodata, driver="GTiff")
    prof.pop("photometric", None)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(arr.astype("float32"), 1)


def build_sources(work: Path) -> SourcePaths:
    """Write the transformed source rasters; GHI/ESA are pointed at unchanged."""
    work.mkdir(parents=True, exist_ok=True)

    with rasterio.open(S2) as ds:
        prof = dict(ds.profile)
        for name, band in {"red": 1, "nir": 2, "swir1": 3, "swir2": 4}.items():
            a = np.ma.filled(ds.read(band, masked=True).astype("float32"), np.nan)
            _write_band(work / f"{name}.tif", a, prof, float("nan"))

    with rasterio.open(LST) as ds:
        celsius = np.ma.filled(ds.read(1, masked=True).astype("float32"), np.nan) - 273.15
        for name in ("t_day", "t_night"):  # day/night gap: same LST for both
            _write_band(work / f"{name}.tif", celsius, dict(ds.profile), float("nan"))

    return SourcePaths(
        red=work / "red.tif",
        nir=work / "nir.tif",
        swir1=work / "swir1.tif",
        swir2=work / "swir2.tif",
        t_day=work / "t_day.tif",
        t_night=work / "t_night.tif",
        ghi=GHI,
        landcover=ESA,
    )


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as ds:
        return ds.read(1)


def provisional_percentiles(inputs: RasterInputs) -> tuple[FparPercentiles, WscPercentiles]:
    """Single-scene 5/95 NDVI/SR per class and 2/98 SIMI over in-region vegetation."""
    red, nir = _read(inputs.red), _read(inputs.nir)
    s1, s2 = _read(inputs.swir1), _read(inputs.swir2)
    canon = lc.esa_to_canonical(_read(inputs.landcover))

    nd = ndvi_fn(red, nir)
    sr = simple_ratio(nd)
    si = simi_fn(s1, s2)
    valid = np.isfinite(red) & np.isfinite(nir) & np.isfinite(s1) & np.isfinite(s2)

    labels: dict[str, dict[str, float]] = {}
    for code, label in lc.CANONICAL_LABELS.items():
        if code == lc.NON_VEGETATION:
            continue
        m = valid & (canon == code)
        if int(m.sum()) < 10:
            continue  # too few pixels -> leave at default 0/0 (degenerate, FPAR_MIN)
        nd_lo, nd_hi = np.percentile(nd[m], [5, 95])
        sr_lo, sr_hi = np.percentile(sr[m], [5, 95])
        labels[label] = {
            "ndvi_min": float(nd_lo),
            "ndvi_max": float(max(nd_hi, nd_lo + 1e-6)),
            "sr_min": float(sr_lo),
            "sr_max": float(max(sr_hi, sr_lo + 1e-6)),
        }

    veg = valid & (canon > 0)
    s_lo, s_hi = np.percentile(si[veg], [2, 98])
    wsc = WscPercentiles(simi_min=float(s_lo), simi_max=float(max(s_hi, s_lo + 1e-6)))
    return FparPercentiles.from_labels(labels), wsc


def main() -> None:
    cfg = load(CONFIG_DIR, "oeiras")
    cfg = cfg.model_copy(
        update={"pipeline": cfg.pipeline.model_copy(update={"landcover_source": "esa_worldcover"})}
    )

    work = Path(tempfile.mkdtemp(prefix="oeiras_val_"))
    print(f"work dir: {work}")
    sources = build_sources(work / "src")
    inputs = prepare_region_inputs(cfg, sources, work / "aligned")

    fpar, wsc = provisional_percentiles(inputs)
    cfg = cfg.model_copy(update={"fpar_percentiles": fpar, "wsc_percentiles": wsc})

    result = run_region(inputs, cfg, MONTH, work / "oeiras_npp_co2.tif")
    report = build_report(result, cfg)

    print("\n=== provisional percentiles (single-scene) ===")
    for code, label in lc.CANONICAL_LABELS.items():
        if code == lc.NON_VEGETATION:
            continue
        print(
            f"  {label:18s} NDVI[{fpar.ndvi_min[code]:.3f},{fpar.ndvi_max[code]:.3f}] "
            f"SR[{fpar.sr_min[code]:.2f},{fpar.sr_max[code]:.2f}]"
        )
    print(f"  SIMI 2/98 = [{wsc.simi_min:.4f}, {wsc.simi_max:.4f}]")

    print("\n=== result vs report ===")
    print(f"  grid           {result.width}x{result.height} @ {result.resolution:g} m {result.crs}")
    print(f"  valid pixels   {result.valid_pixels:,}")
    print(f"  vegetation px  {result.vegetation_pixels:,} ({report.vegetation_area_ha:.0f} ha)")
    print(f"  NPP carbon     {result.total_npp_c_t:,.1f} t C / month")
    print(f"  NPP CO2        {result.total_npp_co2_t:,.1f} t CO2 / month")
    print(f"  report (tC)    {REPORT_TC:,.1f}  -> ratio ours/report = {result.total_npp_c_t / REPORT_TC:.2f}")
    print(f"  offset frac    {report.balance.offset_fraction:.4f} of population emissions")


if __name__ == "__main__":
    main()
