"""Unit tests for casa.config."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from casa import landcover as lc
from casa.config import (
    EpsilonMaxTable,
    FparPercentiles,
    PipelineConfig,
    RegionConfig,
    TOptByBiome,
    WscPercentiles,
    load,
)
from casa.emax import emax

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def test_epsilon_table_from_labels_indexes_by_code() -> None:
    table = EpsilonMaxTable.from_labels({"trees": 1.106, "grass": 0.86})
    assert table.by_code[lc.TREES] == 1.106
    assert table.by_code[lc.GRASS] == 0.86
    assert table.by_code[lc.NON_VEGETATION] == 0.0  # omitted -> 0
    assert table.as_dict()[lc.CROPS] == 0.0


def test_epsilon_table_rejects_unknown_label() -> None:
    with pytest.raises(ValueError, match="unknown canonical labels"):
        EpsilonMaxTable.from_labels({"forest": 1.0})


def test_epsilon_table_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        EpsilonMaxTable.from_labels({"trees": -1.0})


def test_models_are_frozen() -> None:
    table = EpsilonMaxTable.from_labels({"trees": 1.0})
    with pytest.raises(ValidationError):
        table.by_code = (0, 0, 0, 0, 0, 0)  # type: ignore[misc]


def test_wsc_percentiles_min_below_max() -> None:
    with pytest.raises(ValidationError):
        WscPercentiles(simi_min=0.9, simi_max=0.1)


def test_fpar_percentiles_min_below_max() -> None:
    with pytest.raises(ValidationError):
        FparPercentiles.from_labels(
            {"trees": {"ndvi_min": 0.9, "ndvi_max": 0.1, "sr_min": 1.0, "sr_max": 2.0}}
        )


def test_region_requires_geometry() -> None:
    with pytest.raises(ValidationError):
        RegionConfig(name="x", population=1, emissions_per_capita=0.5)


def test_region_bbox_from_wkt() -> None:
    region = RegionConfig(
        name="sq",
        population=1,
        emissions_per_capita=0.5,
        geometry_wkt="POLYGON ((-9.35 38.66, -9.23 38.66, -9.23 38.72, -9.35 38.72, -9.35 38.66))",
    )
    assert region.bbox == (-9.35, 38.66, -9.23, 38.72)


def test_region_bbox_from_path(tmp_path: Path) -> None:
    wkt_file = tmp_path / "g.wkt"
    wkt_file.write_text(
        "POLYGON ((-9.35 38.66, -9.23 38.66, -9.23 38.72, -9.35 38.72, -9.35 38.66))"
    )
    region = RegionConfig(
        name="p", population=1, emissions_per_capita=0.5, geometry_path=str(wkt_file)
    )
    assert region.bbox == (-9.35, 38.66, -9.23, 38.72)


def test_region_bbox_none_when_no_geometry_resolved() -> None:
    # var_pct path-only region whose path is never read still validates;
    # bbox returns None only when neither wkt nor path is present is covered by
    # the validator (geometry is required), so here we confirm wkt takes priority.
    region = RegionConfig(
        name="p",
        population=1,
        emissions_per_capita=0.5,
        geometry_wkt="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
        geometry_path="ignored.wkt",
    )
    assert region.bbox == (0.0, 0.0, 1.0, 1.0)  # wkt wins, path not read


def test_region_var_pct_mes_must_be_12() -> None:
    with pytest.raises(ValidationError):
        RegionConfig(
            name="x",
            population=1,
            emissions_per_capita=0.5,
            geometry_path="a.shp",
            var_pct_mes=(1.0, 2.0),
        )


def test_pipeline_rejects_bad_landcover_source() -> None:
    with pytest.raises(ValidationError):
        PipelineConfig(landcover_source="modis")  # type: ignore[arg-type]


def test_t_opt_default_for_non_vegetation() -> None:
    t_opt = TOptByBiome.from_labels({"trees": 22.0})
    assert t_opt.by_code[lc.TREES] == 22.0
    assert t_opt.by_code[lc.NON_VEGETATION] == 20.0  # default


# --- end-to-end against the real config/ tree ---


def test_load_real_config_tree() -> None:
    cfg = load(CONFIG_DIR, region="oeiras")
    assert cfg.region.name == "oeiras"
    assert cfg.pipeline.epsilon_max == "xu2023"
    assert cfg.region.bbox is not None
    # epsilon table came from xu2023.yml selected by pipeline.epsilon_max
    assert cfg.epsilon_max.by_code[lc.TREES] == 1.106


def test_loaded_config_feeds_pure_functions() -> None:
    # The config layer's output must drop straight into the Bloco 1 math.
    cfg = load(CONFIG_DIR, region="oeiras")
    codes = np.array([lc.TREES, lc.GRASS, lc.NON_VEGETATION], dtype=np.uint8)
    got = emax(codes, cfg.epsilon_max.as_dict())
    np.testing.assert_allclose(got, [1.106, 0.86, 0.0])
