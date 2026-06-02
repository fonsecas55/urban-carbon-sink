"""Synthetic tests for casa.inputs.online — orchestration with all fetchers mocked."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from casa.config import AppConfig, load
from casa.inputs import online
from casa.inputs.online import (
    OnlineError,
    _crop_ghi_to_bbox,
    _n_days,
    _resolve_var_pct,
    download_region,
)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _write_base_ghi(path: Path, value: float = 5.0) -> None:
    """5 kWh/m2/day constant GHI over a 1deg x 1deg EPSG:4326 raster covering Oeiras."""
    transform = from_origin(-10.0, 39.5, 0.05, 0.05)
    profile = {
        "driver": "GTiff",
        "height": 20,
        "width": 20,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": transform,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.full((20, 20), value, dtype=np.float32), 1)


def _cfg_oeiras(
    *,
    landcover_source: str = "dynamic_world",
    cams_point: tuple[float, float] | None = None,
    var_pct_mes: tuple[float, ...] | None = None,
) -> AppConfig:
    base = load(CONFIG_DIR, region="oeiras")
    region = base.region.model_copy(update={"cams_point": cams_point, "var_pct_mes": var_pct_mes})
    pipeline = base.pipeline.model_copy(update={"landcover_source": landcover_source})
    return base.model_copy(update={"region": region, "pipeline": pipeline})


# --- _n_days ----------------------------------------------------------------


def test_n_days_handles_february_leap() -> None:
    assert _n_days("2024-02") == 29
    assert _n_days("2025-02") == 28
    assert _n_days("2025-04") == 30
    assert _n_days("2025-01") == 31


# --- _resolve_var_pct -------------------------------------------------------


def test_resolve_var_pct_uses_static_override(tmp_path: Path) -> None:
    override = tuple(float(i) for i in range(12))  # month i+1 -> i
    cfg = _cfg_oeiras(var_pct_mes=override)
    got = _resolve_var_pct(cfg, "2025-04", tmp_dir=tmp_path)
    assert got == 3.0  # April -> index 3 -> value 3.0


def test_resolve_var_pct_calls_cams_when_no_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: dict[str, object] = {}

    def fake_cams(point, month, *, tmp_dir, client=None):  # type: ignore[no-untyped-def]
        called["point"] = point
        called["month"] = month
        return {m: float(m * 10) for m in range(1, 13)}

    monkeypatch.setattr(online, "fetch_cams_for_month", fake_cams)
    cfg = _cfg_oeiras(cams_point=(-9.30, 38.70))

    got = _resolve_var_pct(cfg, "2025-04", tmp_dir=tmp_path)
    assert got == 40.0
    assert called["point"] == (-9.30, 38.70)
    assert called["month"] == "2025-04"


def test_resolve_var_pct_raises_without_source(tmp_path: Path) -> None:
    cfg = _cfg_oeiras()  # no override, no cams_point
    with pytest.raises(OnlineError, match="neither var_pct_mes nor cams_point"):
        _resolve_var_pct(cfg, "2025-04", tmp_dir=tmp_path)


def test_resolve_var_pct_bad_month_format(tmp_path: Path) -> None:
    cfg = _cfg_oeiras(var_pct_mes=(0.0,) * 12)
    with pytest.raises(OnlineError, match="YYYY-MM"):
        _resolve_var_pct(cfg, "bad", tmp_dir=tmp_path)


# --- _crop_ghi_to_bbox ------------------------------------------------------


def test_crop_ghi_preserves_daily_units(tmp_path: Path) -> None:
    """Crop only: raw daily GHI (kWh/m2/day) is preserved, NOT pre-SOL'd.

    The SOL term (x3.6, day count, var_pct) is applied once downstream by
    pipeline.run_region; applying it here too caused a double-SOL (~108x).
    """
    base = tmp_path / "ghi_base.tif"
    _write_base_ghi(base, value=5.0)
    bbox = (-9.35, 38.66, -9.23, 38.72)

    out = _crop_ghi_to_bbox(base, bbox, tmp_path / "ghi.tif")

    with rasterio.open(out) as ds:
        data = ds.read(1)
        assert ds.crs.to_string() == "EPSG:4326"
        np.testing.assert_allclose(data[~np.isnan(data)], 5.0, rtol=1e-5)


# --- download_region --------------------------------------------------------


def _stub_fetchers(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[object]]:
    """Stub all remote fetchers and return per-call records."""
    rec: dict[str, list[object]] = {"s2": [], "s3": [], "dw": [], "cams": [], "init_ee": []}

    def fake_s2(bbox, month, out_dir, client):  # type: ignore[no-untyped-def]
        rec["s2"].append((bbox, month, str(out_dir)))
        return {n: Path(out_dir) / f"{n}.tif" for n in ("red", "nir", "swir1", "swir2")}

    def fake_s3(bbox, month, out_dir, client):  # type: ignore[no-untyped-def]
        rec["s3"].append((bbox, month, str(out_dir)))
        return {n: Path(out_dir) / f"{n}.tif" for n in ("t_day", "t_night")}

    def fake_dw(bbox, month, out_path):  # type: ignore[no-untyped-def]
        rec["dw"].append((bbox, month, str(out_path)))
        Path(out_path).write_bytes(b"DW")
        return Path(out_path)

    def fake_cams(point, month, *, tmp_dir, client=None):  # type: ignore[no-untyped-def]
        rec["cams"].append((point, month, str(tmp_dir)))
        return {m: 0.0 for m in range(1, 13)}

    def fake_init_ee():  # type: ignore[no-untyped-def]
        rec["init_ee"].append(True)

    monkeypatch.setattr(online, "fetch_sentinel2", fake_s2)
    monkeypatch.setattr(online, "fetch_sentinel3", fake_s3)
    monkeypatch.setattr(online, "fetch_dynamic_world", fake_dw)
    monkeypatch.setattr(online, "fetch_cams_for_month", fake_cams)
    monkeypatch.setattr(online, "init_earth_engine", fake_init_ee)
    return rec


def test_download_region_dw_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = _stub_fetchers(monkeypatch)
    base = tmp_path / "ghi_base.tif"
    _write_base_ghi(base)
    cfg = _cfg_oeiras(cams_point=(-9.30, 38.70))

    result = download_region(
        cfg,
        "2025-04",
        tmp_path / "out",
        base_ghi_path=base,
        process_client=object(),  # dummy: stubbed fetchers don't use it
    )
    sp = result.sources

    # S2/S3/DW called once each; init_ee called (default True)
    assert len(rec["s2"]) == 1
    assert len(rec["s3"]) == 1
    assert len(rec["dw"]) == 1
    assert rec["init_ee"] == [True]
    # CAMS path used (no override on cfg) and its var_pct surfaced on the result
    assert len(rec["cams"]) == 1
    assert result.var_pct == 0.0  # fake_cams returns 0.0 for every month
    # SourcePaths is complete and paths are inside out/raw
    raw = tmp_path / "out" / "raw"
    assert sp.red == raw / "red.tif"
    assert sp.t_day == raw / "t_day.tif"
    assert sp.landcover == raw / "landcover.tif"
    assert sp.ghi == raw / "ghi.tif"
    assert sp.ghi.exists()  # _crop_ghi_to_bbox wrote a real file


def test_download_region_skips_init_ee_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _stub_fetchers(monkeypatch)
    base = tmp_path / "ghi_base.tif"
    _write_base_ghi(base)
    cfg = _cfg_oeiras(var_pct_mes=(0.0,) * 12)

    download_region(
        cfg, "2025-04", tmp_path / "out",
        base_ghi_path=base, process_client=object(), init_ee=False,
    )
    assert rec["init_ee"] == []
    # var_pct override consumed -> no CAMS call
    assert rec["cams"] == []


def test_download_region_esa_fallback_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = _stub_fetchers(monkeypatch)
    base = tmp_path / "ghi_base.tif"
    _write_base_ghi(base)
    fallback = tmp_path / "esa.tif"
    fallback.write_bytes(b"ESA-RASTER-BYTES")
    cfg = _cfg_oeiras(landcover_source="esa_worldcover", var_pct_mes=(0.0,) * 12)

    result = download_region(
        cfg, "2025-04", tmp_path / "out",
        base_ghi_path=base, esa_fallback_path=fallback,
        process_client=object(), init_ee=False,
    )
    # DW NOT called; ESA fallback copied verbatim
    assert rec["dw"] == []
    assert result.sources.landcover.read_bytes() == b"ESA-RASTER-BYTES"


def test_download_region_esa_without_fallback_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_fetchers(monkeypatch)
    base = tmp_path / "ghi_base.tif"
    _write_base_ghi(base)
    cfg = _cfg_oeiras(landcover_source="esa_worldcover", var_pct_mes=(0.0,) * 12)

    with pytest.raises(OnlineError, match="esa_worldcover"):
        download_region(
            cfg, "2025-04", tmp_path / "out",
            base_ghi_path=base, esa_fallback_path=None,
            process_client=object(), init_ee=False,
        )
