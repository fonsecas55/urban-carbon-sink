"""Unit tests for casa.reports — pipeline result + config -> JSON for the frontend."""

from __future__ import annotations

import json
from pathlib import Path

from casa.config import AppConfig, load
from casa.pipeline import RegionResult
from casa.reports import RegionReport, build_report, write_report

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _cfg() -> AppConfig:
    return load(CONFIG_DIR, region="oeiras")


def _result(
    *, npp_c: float = 1000.0, npp_co2: float = 3666.6667, t_day_mean: float = 18.0
) -> RegionResult:
    return RegionResult(
        region="oeiras",
        month="2024-06",
        crs="EPSG:32629",
        width=64,
        height=48,
        resolution=10.0,
        total_npp_c_t=npp_c,
        total_npp_co2_t=npp_co2,
        valid_pixels=64 * 48,
        vegetation_pixels=64 * 48,
        t_day_mean=t_day_mean,
        output_path=Path("co2.tif"),
    )


def test_vegetation_area_uses_pixel_area() -> None:
    result = _result()
    report = build_report(result, _cfg())
    # 3072 pixels * 100 m2 / 1e4 = 30.72 ha
    assert report.vegetation_area_ha == 64 * 48 * 100.0 / 1e4


def test_balance_is_emissions_minus_absorbed() -> None:
    cfg = _cfg()
    result = _result(npp_co2=5000.0)
    report = build_report(result, cfg)
    expected_emissions = cfg.region.population * cfg.region.emissions_per_capita
    assert report.balance.total_emissions_t_co2 == expected_emissions
    assert report.balance.net_co2_balance_t == expected_emissions - 5000.0


def test_offset_fraction_is_absorbed_over_emissions() -> None:
    cfg = _cfg()
    result = _result(npp_co2=5000.0)
    report = build_report(result, cfg)
    expected_emissions = cfg.region.population * cfg.region.emissions_per_capita
    assert report.balance.offset_fraction == 5000.0 / expected_emissions


def test_offset_fraction_zero_when_no_emissions() -> None:
    cfg = _cfg().model_copy(
        update={"region": _cfg().region.model_copy(update={"emissions_per_capita": 0.0})}
    )
    report = build_report(_result(), cfg)
    assert report.balance.total_emissions_t_co2 == 0.0
    assert report.balance.offset_fraction == 0.0


def test_provenance_records_config_sources() -> None:
    cfg = _cfg()
    report = build_report(_result(), cfg, generated_at="2026-05-29T00:00:00+00:00")
    assert report.provenance.model == "CASA"
    assert report.provenance.epsilon_max_table == cfg.pipeline.epsilon_max
    assert report.provenance.landcover_source == cfg.pipeline.landcover_source
    assert report.provenance.generated_at == "2026-05-29T00:00:00+00:00"


def test_output_cog_is_basename_only() -> None:
    result = _result()
    report = build_report(result, _cfg())
    assert report.output_cog == "co2.tif"
    assert "/" not in report.output_cog and "\\" not in report.output_cog


def test_data_quality_ok_for_plausible_lst() -> None:
    report = build_report(_result(t_day_mean=16.1), _cfg())
    assert report.data_quality == "ok"


def test_data_quality_degraded_for_cloud_cold_lst() -> None:
    # cloud-top thermal (e.g. the Oct 2025 -23.6 C scene) -> degraded, not a fake 0
    report = build_report(_result(t_day_mean=-23.6), _cfg())
    assert report.data_quality == "degraded"


def test_data_quality_degraded_for_nan_lst() -> None:
    report = build_report(_result(t_day_mean=float("nan")), _cfg())
    assert report.data_quality == "degraded"


def test_bbox_comes_from_region_geometry() -> None:
    cfg = _cfg()
    report = build_report(_result(), cfg)
    assert report.bbox_lonlat == cfg.region.bbox


def test_write_report_round_trips(tmp_path: Path) -> None:
    report = build_report(_result(), _cfg(), generated_at="2026-05-29T00:00:00+00:00")
    path = tmp_path / "report.json"
    write_report(report, path)
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    reparsed = RegionReport.model_validate(loaded)
    assert reparsed == report
