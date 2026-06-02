"""Synthetic tests for casa.inputs.cdse — OAuth + Process API, no real network."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
import requests

from casa.inputs.cdse import (
    EVALSCRIPT_S3_LST,
    PROCESS_URL,
    TOKEN_URL,
    CdseAuth,
    CdseError,
    ProcessClient,
    fetch_sentinel2,
    fetch_sentinel3,
)


def _geotiff_bytes(bands: int, dtype: str, *, h: int = 4, w: int = 4) -> bytes:
    """Build an in-memory multi-band GeoTIFF; band i is filled with value i."""
    profile = {
        "driver": "GTiff",
        "height": h,
        "width": w,
        "count": bands,
        "dtype": dtype,
        "crs": "EPSG:4326",
        "transform": rasterio.transform.from_origin(-9.35, 38.72, 0.001, 0.001),
    }
    with rasterio.MemoryFile() as mem:
        with mem.open(**profile) as ds:
            for i in range(1, bands + 1):
                ds.write(np.full((h, w), i, dtype=dtype), i)
        return bytes(mem.read())


# --- CdseAuth ---------------------------------------------------------------


def test_from_env_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CDSE_CLIENT_ID", raising=False)
    monkeypatch.delenv("CDSE_CLIENT_SECRET", raising=False)
    with pytest.raises(CdseError, match="CDSE_CLIENT_ID"):
        CdseAuth.from_env()


def test_token_is_cached_until_expiry(requests_mock) -> None:
    now = [1000.0]
    requests_mock.post(TOKEN_URL, json={"access_token": "tok-1", "expires_in": 600})
    auth = CdseAuth("id", "secret", clock=lambda: now[0])

    assert auth.token() == "tok-1"
    assert auth.token() == "tok-1"  # second call served from cache
    assert requests_mock.call_count == 1


def test_token_refreshes_after_expiry(requests_mock) -> None:
    now = [1000.0]
    requests_mock.post(
        TOKEN_URL,
        [
            {"json": {"access_token": "tok-1", "expires_in": 600}},
            {"json": {"access_token": "tok-2", "expires_in": 600}},
        ],
    )
    auth = CdseAuth("id", "secret", clock=lambda: now[0])
    assert auth.token() == "tok-1"
    now[0] += 1000.0  # past expiry (600 - 60 margin)
    assert auth.token() == "tok-2"
    assert requests_mock.call_count == 2


def test_token_401_raises(requests_mock) -> None:
    requests_mock.post(TOKEN_URL, status_code=401, json={"error": "invalid_client"})
    auth = CdseAuth("id", "bad")
    with pytest.raises(CdseError, match="401"):
        auth.token()


# --- ProcessClient ----------------------------------------------------------


def test_process_attaches_bearer_and_returns_bytes(requests_mock) -> None:
    payload = _geotiff_bytes(1, "float32")
    requests_mock.post(PROCESS_URL, content=payload)
    client = ProcessClient(lambda: "test-token")

    out = client.process(
        bbox=(-9.35, 38.66, -9.23, 38.72),
        epsg=4326,
        collection="sentinel-2-l2a",
        evalscript="//VERSION=3",
        width=4,
        height=4,
        time_interval=("2025-04-01T00:00:00Z", "2025-04-30T23:59:59Z"),
    )
    assert out == payload
    assert requests_mock.last_request.headers["Authorization"] == "Bearer test-token"
    body = requests_mock.last_request.json()
    assert body["input"]["bounds"]["bbox"] == [-9.35, 38.66, -9.23, 38.72]
    assert body["input"]["data"][0]["dataFilter"]["timeRange"]["from"].startswith("2025-04-01")


def test_process_retries_then_succeeds(requests_mock) -> None:
    payload = _geotiff_bytes(1, "float32")
    requests_mock.post(PROCESS_URL, [{"status_code": 429}, {"content": payload, "status_code": 200}])
    client = ProcessClient(lambda: "t", sleep=lambda _s: None)
    out = client.process(
        bbox=(0, 0, 1, 1),
        epsg=4326,
        collection="sentinel-2-l2a",
        evalscript="x",
        width=2,
        height=2,
        time_interval=("a", "b"),
    )
    assert out == payload
    assert requests_mock.call_count == 2


def test_process_raises_on_client_error(requests_mock) -> None:
    requests_mock.post(PROCESS_URL, status_code=400, json={"error": "bad evalscript"})
    client = ProcessClient(lambda: "t", sleep=lambda _s: None)
    with pytest.raises(requests.HTTPError):
        client.process(
            bbox=(0, 0, 1, 1),
            epsg=4326,
            collection="sentinel-2-l2a",
            evalscript="x",
            width=2,
            height=2,
            time_interval=("a", "b"),
        )


# --- fetch helpers ----------------------------------------------------------


def test_fetch_sentinel2_splits_into_four_bands(tmp_path: Path, requests_mock) -> None:
    requests_mock.post(PROCESS_URL, content=_geotiff_bytes(4, "int16"))
    client = ProcessClient(lambda: "t")
    out = fetch_sentinel2((-9.35, 38.66, -9.23, 38.72), "2025-04", tmp_path, client)

    assert set(out) == {"red", "nir", "swir1", "swir2"}
    for path in out.values():
        with rasterio.open(path) as ds:
            assert ds.count == 1
    # leastCC / cloud filter propagated
    df = requests_mock.last_request.json()["input"]["data"][0]["dataFilter"]
    assert df["maxCloudCoverage"] == 30


def test_fetch_sentinel3_writes_day_and_night(tmp_path: Path, requests_mock) -> None:
    requests_mock.post(PROCESS_URL, content=_geotiff_bytes(1, "float32"))
    client = ProcessClient(lambda: "t")
    out = fetch_sentinel3((-9.35, 38.66, -9.23, 38.72), "2025-04", tmp_path, client)

    assert set(out) == {"t_day", "t_night"}
    assert (tmp_path / "t_day.tif").exists() and (tmp_path / "t_night.tif").exists()
    orbits = [r.json()["input"]["data"][0]["dataFilter"]["orbitDirection"] for r in requests_mock.request_history]
    assert orbits == ["DESCENDING", "ASCENDING"]
    # Evalscript posted to Sentinel Hub must be the Celsius-converting one.
    assert "- 273.15" in requests_mock.request_history[0].json()["evalscript"]


def test_evalscript_s3_lst_converts_kelvin_to_celsius() -> None:
    """Thermal .tif lands in degrees C (tstress unit) — conversion at the source.

    SLSTR L1 RBT has no LST band; S8 brightness temperature is the thermal proxy.
    """
    assert "s.S8 - 273.15" in EVALSCRIPT_S3_LST
