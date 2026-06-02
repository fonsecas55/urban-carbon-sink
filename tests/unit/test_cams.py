"""Synthetic tests for casa.inputs.cams — no live CAMS, no cdsapi installed needed."""

from __future__ import annotations

import calendar
from pathlib import Path

import pytest

from casa.inputs.cams import (
    DATASET,
    CamsError,
    _build_request,
    _parse_daily_ghi,
    fetch_cams_for_month,
    fetch_cams_var_pct,
)


def _synthetic_csv(year: int, monthly_ghi: list[float]) -> str:
    """CAMS-shaped semicolon CSV: every day of `year` carries monthly_ghi[m-1]."""
    lines = ["# CAMS Solar Radiation Time-Series (synthetic for tests)"]
    lines.append(
        "Observation period;TOA;Clear sky GHI;Clear sky BHI;Clear sky DHI;"
        "Clear sky BNI;GHI;BHI;DHI;BNI;Reliability"
    )
    for month in range(1, 13):
        ghi = monthly_ghi[month - 1]
        for day in range(1, calendar.monthrange(year, month)[1] + 1):
            period = f"{year:04d}-{month:02d}-{day:02d}T00:00:00.0/PT1D"
            lines.append(f"{period};0;0;0;0;0;{ghi};0;0;0;1")
    return "\n".join(lines) + "\n"


class _FakeClient:
    """Records `retrieve` calls and writes a fixed CSV payload to `target`."""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object], str]] = []

    def retrieve(self, name: str, request: dict[str, object], target: str) -> None:
        self.calls.append((name, request, target))
        Path(target).write_text(self.payload, encoding="utf-8")


# --- request shape ----------------------------------------------------------


def test_build_request_has_required_fields() -> None:
    req = _build_request((-9.30, 38.70), 2024)
    assert req["sky_type"] == "observed_cloud"
    assert req["time_step"] == "1day"
    assert req["format"] == "csv"
    assert req["date"] == ["2024-01-01/2024-12-31"]
    assert req["location"] == {"latitude": 38.70, "longitude": -9.30}


# --- CSV parser -------------------------------------------------------------


def test_parse_csv_aggregates_by_month() -> None:
    csv_text = _synthetic_csv(2024, [100.0] * 12)
    sums, counts = _parse_daily_ghi(csv_text, 2024)
    expected_counts = [calendar.monthrange(2024, m)[1] for m in range(1, 13)]
    assert counts == expected_counts
    assert all(abs(s - 100.0 * c) < 1e-9 for s, c in zip(sums, expected_counts, strict=True))


def test_parse_csv_skips_other_years() -> None:
    csv_text = _synthetic_csv(2024, [50.0] * 12)
    csv_text += "2023-06-15T00:00:00.0/PT1D;0;0;0;0;0;999;0;0;0;1\n"
    sums, counts = _parse_daily_ghi(csv_text, 2024)
    assert sum(counts) == 366  # 2024 is leap
    assert all(abs(s - 50.0 * c) < 1e-9 for s, c in zip(sums, counts, strict=True))


def test_parse_csv_raises_without_ghi_column() -> None:
    bad = "# comment\nObservation period;Foo;Bar\n2024-01-01T00:00:00/PT1D;1;2\n"
    with pytest.raises(CamsError, match="GHI"):
        _parse_daily_ghi(bad, 2024)


def test_parse_csv_raises_without_header() -> None:
    bad = "# only comments\n# nothing else\n"
    with pytest.raises(CamsError, match="header"):
        _parse_daily_ghi(bad, 2024)


def test_parse_csv_real_cams_comment_header() -> None:
    """Real CAMS v4 names columns on a COMMENT line; GHI is the all-sky column.

    Regression for the live payload: the header is `# Observation period;...;GHI;...`
    (commented), and an enumerated `# 7. GHI.` descriptor line must not be
    mistaken for it. GHI must come from the exact `GHI` column (index 6), never
    `TOA` (index 1) or `Clear sky GHI` (index 2).
    """
    csv_text = (
        "# Coding: utf-8\n"
        "# File format version: 2\n"
        "# Columns:\n"
        "# 7. GHI. Global irradiation on horizontal plane at ground level (Wh/m2)\n"
        "# Observation period;TOA;Clear sky GHI;Clear sky BHI;Clear sky DHI;"
        "Clear sky BNI;GHI;BHI;DHI;BNI;Reliability\n"
        "2024-01-01T00:00:00.0/2024-01-02T00:00:00.0;4049.5;2718.4;2094.2;624.1;"
        "5799.8;2525.6;1752.2;773.3;4815.6;0.98\n"
        "2024-02-15T00:00:00.0/2024-02-16T00:00:00.0;0;0;0;0;0;3000.0;0;0;0;1\n"
    )
    sums, counts = _parse_daily_ghi(csv_text, 2024)
    assert counts[0] == 1 and counts[1] == 1
    assert abs(sums[0] - 2525.6) < 1e-6  # all-sky GHI (idx 6), not TOA/Clear sky
    assert abs(sums[1] - 3000.0) < 1e-6


# --- fetch_cams_var_pct -----------------------------------------------------


def test_fetch_cams_var_pct_happy(tmp_path: Path) -> None:
    """6 winter months @ 80, 6 summer months @ 120 -> mean ~100, signs flip."""
    monthly = [80.0] * 6 + [120.0] * 6
    client = _FakeClient(_synthetic_csv(2024, monthly))

    out = fetch_cams_var_pct((-9.30, 38.70), 2024, tmp_dir=tmp_path, client=client)

    assert set(out) == set(range(1, 13))
    assert client.calls[0][0] == DATASET
    # Days-weighted reconstruction of the annual mean must be exact.
    days = [calendar.monthrange(2024, m)[1] for m in range(1, 13)]
    weighted = sum((out[m] + 100.0) * days[m - 1] for m in range(1, 13))
    assert abs(weighted / sum(days) - 100.0) < 1e-9
    # Sign check (winter under, summer over).
    assert all(out[m] < 0 for m in range(1, 7))
    assert all(out[m] > 0 for m in range(7, 13))


def test_fetch_cams_var_pct_constant_year_is_zero(tmp_path: Path) -> None:
    """Constant GHI year -> var_pct == 0 every month."""
    client = _FakeClient(_synthetic_csv(2024, [42.0] * 12))
    out = fetch_cams_var_pct((0.0, 0.0), 2024, tmp_dir=tmp_path, client=client)
    assert all(abs(v) < 1e-9 for v in out.values())


def test_fetch_cams_var_pct_raises_on_missing_month(tmp_path: Path) -> None:
    csv_text = _synthetic_csv(2024, [100.0] * 12)
    filtered = "\n".join(line for line in csv_text.splitlines() if "2024-03" not in line)
    client = _FakeClient(filtered + "\n")
    with pytest.raises(CamsError, match=r"months with no data .*\[3\]"):
        fetch_cams_var_pct((0.0, 0.0), 2024, tmp_dir=tmp_path, client=client)


# --- facade -----------------------------------------------------------------


def test_fetch_cams_for_month_uses_previous_year(tmp_path: Path) -> None:
    client = _FakeClient(_synthetic_csv(2024, [100.0] * 12))
    out = fetch_cams_for_month((-9.30, 38.70), "2025-04", tmp_dir=tmp_path, client=client)
    assert set(out) == set(range(1, 13))
    assert client.calls[0][1]["date"] == ["2024-01-01/2024-12-31"]


def test_fetch_cams_for_month_bad_format(tmp_path: Path) -> None:
    with pytest.raises(CamsError, match="YYYY-MM"):
        fetch_cams_for_month((0.0, 0.0), "not-a-month", tmp_dir=tmp_path, client=_FakeClient(""))


# --- credential discovery ---------------------------------------------------


def test_client_from_env_requires_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CDSAPI_KEY", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # ~/.cdsapirc absent
    with pytest.raises(CamsError, match="CDSAPI_KEY"):
        fetch_cams_var_pct((0.0, 0.0), 2024, tmp_dir=tmp_path)
