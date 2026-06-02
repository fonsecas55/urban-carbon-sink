"""Copernicus Data Space (CDSE) Sentinel Hub client — auth + Process API.

Raw `requests` against the CDSE Sentinel Hub Process API (ADR-003): keeps the
dependency footprint light and the whole HTTP flow (OAuth token, bearer header,
retry/backoff, GeoTIFF response) fakeable at the HTTP layer in tests.

Credentials come only from the environment (never hard-coded): `CDSE_CLIENT_ID`,
`CDSE_CLIENT_SECRET`. Endpoints are module constants. Paths are pathlib-based so
the code runs unchanged on the Linux/WSL production target.

Scope (Bloco 6a): Sentinel-2 L2A (B4/B8/B11/B12) and Sentinel-3 SLSTR LST
(day + night). Dynamic World (GEE) and CAMS are Bloco 6b.
"""

from __future__ import annotations

import calendar
import math
import os
import time
from collections.abc import Callable
from pathlib import Path

import rasterio
import requests

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

# Sentinel Hub collection identifiers (CDSE deployment).
S2_L2A = "sentinel-2-l2a"
S3_SLSTR = "sentinel-3-slstr"

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_EXPIRY_MARGIN_S = 60.0
_TIMEOUT_S = 60.0

BBox = tuple[float, float, float, float]
TokenProvider = Callable[[], str]

# --- Evalscripts (Sentinel Hub v3) -----------------------------------------

# Sentinel-2 L2A: four reflectance bands, native x10000 scale (DN), so the
# pipeline's wsc.simi (which divides by 10000) and ndvi see the expected units.
#
# Default SIMPLE mosaicking (no `mosaicking` key): `evaluatePixel` receives a
# single sample, so `s.B04` is a scalar. `dataFilter.mosaickingOrder=leastCC`
# selects the least-cloudy scene in the month. Declaring `mosaicking: "ORBIT"`
# here while reading `s.B04` as a scalar yields an all-zero output (with ORBIT,
# the argument is an array of samples) — that mismatch produced empty S2 tiles.
EVALSCRIPT_S2 = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["B04", "B08", "B11", "B12"], units: "DN"}],
    output: {bands: 4, sampleType: "INT16"}
  };
}
function evaluatePixel(s) { return [s.B04, s.B08, s.B11, s.B12]; }
"""

# Sentinel-3 SLSTR thermal input as degrees Celsius, single band.
#
# The CDSE Sentinel Hub `sentinel-3-slstr` collection is Level-1 RBT: it exposes
# no ready-made LST band, only the thermal brightness-temperature channels
# S7/S8/S9 (+F1/F2), in Kelvin. We use S8 (~10.85 um nadir), the standard split-
# window LST window channel, as the thermal proxy. This is a documented
# approximation: brightness temperature has no emissivity correction and
# underestimates true LST by ~1-5 K. A split-window (S8,S9) refinement is a
# follow-up. Conversion K -> C happens at the source so the .tif files in raw/
# are already in the unit `casa.tstress` expects — no hidden state downstream.
EVALSCRIPT_S3_LST = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["S8"]}],
    output: {bands: 1, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(s) { return [s.S8 - 273.15]; }
"""


class CdseError(RuntimeError):
    """CDSE auth or Process API failure."""


def _crs_url(epsg: int) -> str:
    return f"http://www.opengis.net/def/crs/EPSG/0/{epsg}"


def _month_interval(month: str) -> tuple[str, str]:
    """('YYYY-MM') -> ISO8601 (from, to) covering the whole month, UTC."""
    year, mon = (int(p) for p in month.split("-"))
    last = calendar.monthrange(year, mon)[1]
    return f"{year:04d}-{mon:02d}-01T00:00:00Z", f"{year:04d}-{mon:02d}-{last:02d}T23:59:59Z"


class CdseAuth:
    """OAuth2 client-credentials token provider with in-memory caching."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        token_url: str = TOKEN_URL,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._session = session or requests.Session()
        self._clock = clock
        self._token: str | None = None
        self._expiry = 0.0

    @classmethod
    def from_env(cls, **kwargs: object) -> CdseAuth:
        cid = os.environ.get("CDSE_CLIENT_ID")
        secret = os.environ.get("CDSE_CLIENT_SECRET")
        if not cid or not secret:
            raise CdseError("set CDSE_CLIENT_ID and CDSE_CLIENT_SECRET in the environment")
        return cls(cid, secret, **kwargs)  # type: ignore[arg-type]

    def token(self) -> str:
        """Return a valid bearer token, fetching/refreshing only when needed."""
        if self._token is not None and self._clock() < self._expiry:
            return self._token
        resp = self._session.post(
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=_TIMEOUT_S,
        )
        if resp.status_code == 401:
            raise CdseError("CDSE token request rejected (401): check client credentials")
        resp.raise_for_status()
        payload = resp.json()
        self._token = str(payload["access_token"])
        self._expiry = self._clock() + float(payload.get("expires_in", 600)) - _EXPIRY_MARGIN_S
        return self._token


class ProcessClient:
    """Thin Sentinel Hub Process API client (one synchronous request per call)."""

    def __init__(
        self,
        token_provider: TokenProvider,
        *,
        process_url: str = PROCESS_URL,
        session: requests.Session | None = None,
        max_retries: int = 3,
        backoff_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token = token_provider
        self._url = process_url
        self._session = session or requests.Session()
        self._max_retries = max_retries
        self._backoff = backoff_s
        self._sleep = sleep

    def process(
        self,
        *,
        bbox: BBox,
        epsg: int,
        collection: str,
        evalscript: str,
        width: int,
        height: int,
        time_interval: tuple[str, str],
        data_filter: dict[str, object] | None = None,
    ) -> bytes:
        """POST one Process request, return the GeoTIFF bytes. Retries 429/5xx."""
        time_from, time_to = time_interval
        df: dict[str, object] = {"timeRange": {"from": time_from, "to": time_to}}
        if data_filter:
            df.update(data_filter)
        body = {
            "input": {
                "bounds": {"bbox": list(bbox), "properties": {"crs": _crs_url(epsg)}},
                "data": [{"type": collection, "dataFilter": df}],
            },
            "output": {
                "width": width,
                "height": height,
                "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
            },
            "evalscript": evalscript,
        }
        last: requests.Response | None = None
        for attempt in range(self._max_retries):
            resp = self._session.post(
                self._url,
                json=body,
                headers={"Authorization": f"Bearer {self._token()}"},
                timeout=_TIMEOUT_S,
            )
            last = resp
            if resp.status_code in _RETRY_STATUS and attempt < self._max_retries - 1:
                self._sleep(self._backoff * (2**attempt))
                continue
            resp.raise_for_status()
            return resp.content
        assert last is not None
        last.raise_for_status()
        return last.content


def _grid_size(bbox: BBox, resolution_m: float) -> tuple[int, int]:
    """Approximate width/height in pixels for a lon/lat bbox at `resolution_m`.

    Uses a local metres-per-degree approximation good enough to size the request
    (the authoritative grid is rebuilt by casa.grid downstream)."""
    minx, miny, maxx, maxy = bbox
    lat = 0.5 * (miny + maxy)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * abs(math.cos(math.radians(lat)))
    width = max(1, round((maxx - minx) * m_per_deg_lon / resolution_m))
    height = max(1, round((maxy - miny) * m_per_deg_lat / resolution_m))
    return width, height


def _write_bands(content: bytes, out_dir: Path, names: list[str]) -> dict[str, Path]:
    """Split a multi-band GeoTIFF (in memory) into one single-band file per name."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    with rasterio.MemoryFile(content) as mem, mem.open() as src:
        profile = src.profile
        for i, name in enumerate(names, start=1):
            profile_i = profile.copy()
            profile_i.update(count=1, driver="GTiff")
            dst_path = out_dir / f"{name}.tif"
            with rasterio.open(dst_path, "w", **profile_i) as dst:
                dst.write(src.read(i), 1)
            written[name] = dst_path
    return written


def fetch_sentinel2(
    bbox: BBox, month: str, out_dir: Path, client: ProcessClient, *, resolution_m: float = 10.0
) -> dict[str, Path]:
    """Fetch S2 L2A B4/B8/B11/B12 (lon/lat bbox, month) -> red/nir/swir1/swir2.tif."""
    width, height = _grid_size(bbox, resolution_m)
    content = client.process(
        bbox=bbox,
        epsg=4326,
        collection=S2_L2A,
        evalscript=EVALSCRIPT_S2,
        width=width,
        height=height,
        time_interval=_month_interval(month),
        data_filter={"maxCloudCoverage": 30, "mosaickingOrder": "leastCC"},
    )
    return _write_bands(content, Path(out_dir), ["red", "nir", "swir1", "swir2"])


def fetch_sentinel3(
    bbox: BBox, month: str, out_dir: Path, client: ProcessClient, *, resolution_m: float = 1000.0
) -> dict[str, Path]:
    """Fetch S3 SLSTR thermal (S8 BT) day + night (lon/lat bbox, month) -> t_day/t_night.tif.

    Output is in degrees Celsius (the evalscript subtracts 273.15 from the
    Kelvin S8 brightness temperature so `casa.tstress` consumes the files
    directly). See `EVALSCRIPT_S3_LST` for the BT-as-LST approximation.

    Day/night are separated by orbit direction (descending ~= daytime ~10:00 LT,
    ascending ~= nighttime ~22:00 LT). The exact mapping must be confirmed against
    a live response; here it wires the mechanism (two requests, two outputs).
    """
    width, height = _grid_size(bbox, resolution_m)
    interval = _month_interval(month)
    written: dict[str, Path] = {}
    for name, orbit in (("t_day", "DESCENDING"), ("t_night", "ASCENDING")):
        content = client.process(
            bbox=bbox,
            epsg=4326,
            collection=S3_SLSTR,
            evalscript=EVALSCRIPT_S3_LST,
            width=width,
            height=height,
            time_interval=interval,
            data_filter={"orbitDirection": orbit},
        )
        written.update(_write_bands(content, Path(out_dir), [name]))
    return written
