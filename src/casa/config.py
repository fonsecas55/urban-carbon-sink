"""Configuration layer: YAML -> validated, immutable Pydantic models.

This layer LOADS and VALIDATES config and converts it into the plain
arrays/scalars the pure math modules (`fpar`, `wsc`, `emax`, ...) consume as
arguments. The math modules never read YAML — the I/O boundary stays here.

Design choices:
- All models are `frozen=True`: no function can mutate loaded scientific
  parameters mid-pipeline (e.g. inside the window loop).
- Per-class numeric tables are stored as length-6 tuples indexed by canonical
  land-cover code (ADR-011), so they are genuinely immutable (a frozen model
  with a dict field would still allow in-place dict mutation).
- `RegionConfig.bbox` is a computed field derived from the WKT geometry,
  giving the (minx, miny, maxx, maxy) the orchestrator needs to crop Sentinel
  Hub / GEE windows in Bloco 3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator
from shapely import wkt as shapely_wkt

from casa import landcover as lc

N_CANONICAL = len(lc.CANONICAL_LABELS)
_LABEL_TO_CODE: dict[str, int] = {label: code for code, label in lc.CANONICAL_LABELS.items()}

BBox = tuple[float, float, float, float]


class _Frozen(BaseModel):
    """Immutable base — blocks accidental attribute reassignment at runtime."""

    model_config = ConfigDict(frozen=True)


def _read_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping, got {type(data).__name__}")
    return data


def _by_code_from_labels(mapping: dict[str, float], *, default: float = 0.0) -> tuple[float, ...]:
    """Build a length-6 tuple indexed by canonical code from a label->value map.

    Unknown labels raise (catches typos / dataset drift early). Missing
    canonical labels fall back to `default` (0.0 = masked non-vegetation).
    """
    unknown = set(mapping) - set(_LABEL_TO_CODE)
    if unknown:
        raise ValueError(f"unknown canonical labels: {sorted(unknown)}")
    out = [default] * N_CANONICAL
    for label, value in mapping.items():
        out[_LABEL_TO_CODE[label]] = float(value)
    return tuple(out)


class EpsilonMaxTable(_Frozen):
    """Maximum light-use efficiency (g C/MJ) per canonical class."""

    by_code: tuple[float, ...] = Field(min_length=N_CANONICAL, max_length=N_CANONICAL)

    @field_validator("by_code")
    @classmethod
    def _non_negative(cls, v: tuple[float, ...]) -> tuple[float, ...]:
        if any(x < 0 for x in v):
            raise ValueError("epsilon_max values must be >= 0")
        return v

    @classmethod
    def from_labels(cls, mapping: dict[str, float]) -> EpsilonMaxTable:
        return cls(by_code=_by_code_from_labels(mapping))

    def as_dict(self) -> dict[int, float]:
        """Code -> epsilon_max, the form `casa.emax.emax` consumes."""
        return {code: self.by_code[code] for code in range(N_CANONICAL)}


class FparPercentiles(_Frozen):
    """Per-class NDVI/SR bounds (5th/95th percentiles) for FPAR rescaling.

    Each tuple is indexed by canonical code. `casa.fpar.fpar` indexes these by
    the per-pixel class. Non-vegetation (code 0) stays at 0/0 (degenerate span
    -> FPAR_MIN, masked downstream by epsilon_max = 0).
    """

    ndvi_min: tuple[float, ...] = Field(min_length=N_CANONICAL, max_length=N_CANONICAL)
    ndvi_max: tuple[float, ...] = Field(min_length=N_CANONICAL, max_length=N_CANONICAL)
    sr_min: tuple[float, ...] = Field(min_length=N_CANONICAL, max_length=N_CANONICAL)
    sr_max: tuple[float, ...] = Field(min_length=N_CANONICAL, max_length=N_CANONICAL)

    @model_validator(mode="after")
    def _min_below_max(self) -> FparPercentiles:
        for code in range(N_CANONICAL):
            if self.ndvi_max[code] < self.ndvi_min[code]:
                raise ValueError(f"ndvi_max < ndvi_min for class {code}")
            if self.sr_max[code] < self.sr_min[code]:
                raise ValueError(f"sr_max < sr_min for class {code}")
        return self

    @classmethod
    def from_labels(cls, mapping: dict[str, dict[str, float]]) -> FparPercentiles:
        def col(key: str) -> tuple[float, ...]:
            return _by_code_from_labels({lbl: row[key] for lbl, row in mapping.items()})

        return cls(
            ndvi_min=col("ndvi_min"),
            ndvi_max=col("ndvi_max"),
            sr_min=col("sr_min"),
            sr_max=col("sr_max"),
        )


class WscPercentiles(_Frozen):
    """Global SIMI bounds (2nd/98th percentiles) for WSC normalisation."""

    simi_min: float
    simi_max: float

    @model_validator(mode="after")
    def _min_below_max(self) -> WscPercentiles:
        if self.simi_max <= self.simi_min:
            raise ValueError("simi_max must be > simi_min")
        return self


class TOptByBiome(_Frozen):
    """Climatological optimal growth temperature (degrees C) per canonical class."""

    by_code: tuple[float, ...] = Field(min_length=N_CANONICAL, max_length=N_CANONICAL)

    @classmethod
    def from_labels(cls, mapping: dict[str, float], *, default: float = 20.0) -> TOptByBiome:
        return cls(by_code=_by_code_from_labels(mapping, default=default))


class RegionConfig(_Frozen):
    """Per-region parameters (ADR-009). Geometry as inline WKT or a file path."""

    name: str
    population: int
    emissions_per_capita: float  # t CO2 / inhabitant / month
    geometry_wkt: str | None = None
    geometry_path: str | None = None
    cams_point: tuple[float, float] | None = None  # (lon, lat)
    var_pct_mes: tuple[float, ...] | None = None  # 12 monthly deviations vs annual mean

    @model_validator(mode="after")
    def _check(self) -> RegionConfig:
        if not self.geometry_wkt and not self.geometry_path:
            raise ValueError(f"region '{self.name}': need geometry_wkt or geometry_path")
        if self.var_pct_mes is not None and len(self.var_pct_mes) != 12:
            raise ValueError(f"region '{self.name}': var_pct_mes must have 12 values")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bbox(self) -> BBox | None:
        """(minx, miny, maxx, maxy) from the geometry (inline WKT or file); None if neither.

        Needed by the orchestrator to derive the target grid and crop Sentinel
        Hub / GEE windows. `geometry_path` is resolved to an absolute path by
        `load()`, so reading it here is deterministic regardless of cwd.
        """
        if self.geometry_wkt:
            geom = shapely_wkt.loads(self.geometry_wkt)
        elif self.geometry_path:
            geom = shapely_wkt.loads(Path(self.geometry_path).read_text(encoding="utf-8"))
        else:
            return None
        b = geom.bounds
        return (float(b[0]), float(b[1]), float(b[2]), float(b[3]))


class PipelineConfig(_Frozen):
    """Global pipeline knobs (ADR-009, ADR-012)."""

    window_size: int = 1024
    landcover_source: Literal["dynamic_world", "esa_worldcover"] = "dynamic_world"
    epsilon_max: str = "xu2023"  # name of the table file under config/epsilon_max/
    par_fraction: float = 0.5


class AppConfig(_Frozen):
    """Fully resolved configuration for one (region, pipeline) run."""

    pipeline: PipelineConfig
    region: RegionConfig
    epsilon_max: EpsilonMaxTable
    fpar_percentiles: FparPercentiles
    wsc_percentiles: WscPercentiles
    t_opt: TOptByBiome


def load_pipeline(path: Path) -> PipelineConfig:
    return PipelineConfig(**_read_yaml(path))


def load_region(path: Path) -> RegionConfig:
    return RegionConfig(**_read_yaml(path))


def load_epsilon_max(path: Path) -> EpsilonMaxTable:
    return EpsilonMaxTable.from_labels(_read_yaml(path))


def load_fpar_percentiles(path: Path) -> FparPercentiles:
    return FparPercentiles.from_labels(_read_yaml(path))


def load_wsc_percentiles(path: Path) -> WscPercentiles:
    return WscPercentiles(**_read_yaml(path))


def load_t_opt(path: Path) -> TOptByBiome:
    return TOptByBiome.from_labels(_read_yaml(path))


def load(config_dir: Path, region: str) -> AppConfig:
    """Resolve the full config tree for a region, fail-fast on any invalid file.

    The active epsilon_max table is selected by `pipeline.epsilon_max`.
    """
    config_dir = Path(config_dir)
    pipeline = load_pipeline(config_dir / "pipeline.yml")
    region_cfg = load_region(config_dir / "regions" / f"{region}.yml")
    if region_cfg.geometry_path is not None and not Path(region_cfg.geometry_path).is_absolute():
        # Resolve relative to the repo root (config tree's parent), not the cwd.
        resolved = config_dir.parent / region_cfg.geometry_path
        region_cfg = region_cfg.model_copy(update={"geometry_path": str(resolved)})
    return AppConfig(
        pipeline=pipeline,
        region=region_cfg,
        epsilon_max=load_epsilon_max(config_dir / "epsilon_max" / f"{pipeline.epsilon_max}.yml"),
        fpar_percentiles=load_fpar_percentiles(config_dir / "fpar_percentiles.yml"),
        wsc_percentiles=load_wsc_percentiles(config_dir / "wsc_percentiles.yml"),
        t_opt=load_t_opt(config_dir / "t_opt_by_biome.yml"),
    )
