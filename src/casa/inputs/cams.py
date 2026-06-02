"""CAMS Solar Radiation Time-Series (ADS) — monthly variability factors.

The CASA `sol` module multiplies the Global Solar Atlas baseline by a monthly
deviation factor `var_pct_mes[m]`. We obtain `var_pct_mes` from CAMS Solar
Radiation Time-Series via the ADS API (`cdsapi`): one full calendar year of
daily GHI for a regional reference point, aggregated to monthly means, then
expressed as percentage deviation vs the days-weighted annual mean.

Design choices (Bloco 6b):
- We pull the previous full calendar year. CAMS Solar TS has ~5-day NRT lag,
  so the current year is partial mid-cycle; mixing partial months into the
  baseline biases `var_pct_mes`. Yearly cache-friendly call (12 values).
- CSV format on the wire — Python stdlib `csv` only, no `netCDF4`/`xarray`.
- Credentials come from the environment only (`CDSAPI_KEY` or `~/.cdsapirc`).
  `cdsapi` import is lazy so test doubles don't require it installed.
- The HTTP layer is hidden behind a `_Retriever` Protocol so tests substitute a
  fake client that writes a synthetic CSV into the target path.

Output unit: dimensionless % (the GHI unit cancels in `monthly/annual - 1`).
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import Protocol, cast

DATASET = "cams-solar-radiation-timeseries"


class CamsError(RuntimeError):
    """CAMS pull or CSV parsing failure."""


class _Retriever(Protocol):
    """The single `cdsapi.Client` method we use — Protocol for testability."""

    def retrieve(self, name: str, request: dict[str, object], target: str) -> object: ...


def _client_from_env() -> _Retriever:
    """Build a real `cdsapi.Client`; fail fast if no credentials are configured."""
    if not (os.environ.get("CDSAPI_KEY") or (Path.home() / ".cdsapirc").exists()):
        raise CamsError(
            "CAMS pull requires either CDSAPI_KEY env var or a ~/.cdsapirc file"
        )
    import cdsapi  # lazy: keeps the unit tests independent of cdsapi being installed

    # cdsapi is untyped; we declare structural conformance via the _Retriever Protocol.
    return cast(_Retriever, cdsapi.Client())


def _build_request(point: tuple[float, float], year: int) -> dict[str, object]:
    """ADS request payload for a one-year daily GHI series at `point`."""
    lon, lat = point
    return {
        "sky_type": "observed_cloud",
        "location": {"latitude": lat, "longitude": lon},
        "altitude": ["-999."],
        "date": [f"{year}-01-01/{year}-12-31"],
        "time_step": "1day",
        "time_reference": "universal_time",
        "format": "csv",
    }


def _parse_daily_ghi(csv_text: str, year: int) -> tuple[list[float], list[int]]:
    """Aggregate daily GHI rows by month -> (sum_per_month[12], count_per_month[12]).

    CAMS CSV is semicolon-delimited. The real CAMS v4 product names its columns
    on a *comment* line (`# Observation period;TOA;...;GHI;...;Reliability`), so
    the header is identified by content, not position: the first row that — once
    leading `#`/spaces are stripped from each cell — contains both
    `Observation period` and `GHI` as exact columns, whether commented or not.
    Everything before it (metadata comments, the enumerated `# N. <col>`
    descriptors) is ignored. The all-sky `GHI` column is matched exactly, never
    `Clear sky GHI` or `TOA`. Rows outside `year` or with non-parsable fields
    are skipped silently — coverage is enforced by the caller via `count_per_month`.
    """
    sums = [0.0] * 12
    counts = [0] * 12
    period_idx = ghi_idx = -1
    header_found = False
    for row in csv.reader(io.StringIO(csv_text), delimiter=";"):
        if not row:
            continue
        if not header_found:
            cleaned = [c.lstrip("#").strip() for c in row]
            if "Observation period" in cleaned and "GHI" in cleaned:
                period_idx = cleaned.index("Observation period")
                ghi_idx = cleaned.index("GHI")
                header_found = True
            continue
        if row[0].lstrip().startswith("#"):
            continue
        if len(row) <= max(period_idx, ghi_idx):
            continue
        try:
            ymd = row[period_idx].split("T", 1)[0]
            y_s, m_s, _ = ymd.split("-")
            if int(y_s) != year:
                continue
            month_idx = int(m_s) - 1
            ghi = float(row[ghi_idx])
        except (ValueError, IndexError):
            continue
        sums[month_idx] += ghi
        counts[month_idx] += 1
    if not header_found:
        raise CamsError(
            "CAMS CSV: no 'Observation period' / 'GHI' column header found "
            "(file empty, truncated, or unexpected format)"
        )
    return sums, counts


def fetch_cams_var_pct(
    point: tuple[float, float],
    year: int,
    *,
    tmp_dir: Path,
    client: _Retriever | None = None,
) -> dict[int, float]:
    """Monthly % deviation of daily GHI vs annual mean for `year` at `point`.

    Returns a 12-entry dict {month: var_pct}, with month in 1..12. Raises
    `CamsError` if any month has zero data rows after parsing (incomplete year).
    """
    cli = client if client is not None else _client_from_env()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / f"cams_{year}_{point[0]:.4f}_{point[1]:.4f}.csv"

    cli.retrieve(DATASET, _build_request(point, year), str(target))

    sums, counts = _parse_daily_ghi(target.read_text(encoding="utf-8"), year)

    missing = [i + 1 for i, c in enumerate(counts) if c == 0]
    if missing:
        raise CamsError(f"CAMS CSV: months with no data for {year}: {missing}")

    total_ghi = sum(sums)
    total_days = sum(counts)
    if total_days == 0 or total_ghi == 0.0:
        raise CamsError(f"CAMS CSV: no usable GHI values for {year}")
    annual_mean = total_ghi / total_days

    return {
        m + 1: 100.0 * ((sums[m] / counts[m]) / annual_mean - 1.0) for m in range(12)
    }


def fetch_cams_for_month(
    point: tuple[float, float],
    month: str,
    *,
    tmp_dir: Path,
    client: _Retriever | None = None,
) -> dict[int, float]:
    """Facade matching `download.fetch_cams(point, month)`.

    Uses the calendar year before `month` as the baseline (avoids partial-year
    NRT artefacts). Always returns the full 12-month dict so the orchestrator
    can pick `var_pct_mes[int(month.split('-')[1])]`.
    """
    try:
        year = int(month.split("-")[0]) - 1
    except (ValueError, IndexError) as exc:
        raise CamsError(f"month must be 'YYYY-MM', got {month!r}") from exc
    return fetch_cams_var_pct(point, year, tmp_dir=tmp_dir, client=client)
