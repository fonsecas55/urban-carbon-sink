"""Google Earth Engine: service-account auth + Dynamic World monthly pull (ADR-006).

Credentials come from the environment, never from code: `GEE_SERVICE_ACCOUNT_JSON`
holds either the path to the key file or the JSON content itself. Suited to the
WSL/Docker production target (mount the key or inject the secret) and to CI.

Dynamic World fetch (Bloco 6b): synchronous, one request per month, via
`ee.data.computePixels` -> GeoTIFF bytes. We reduce the month's image stack with
`.mode()` (most-frequent class per pixel) and return the raw 0..8 DW label band
in EPSG:4326. The downstream `landcover` module maps it to the canonical schema
(ADR-011).
"""

from __future__ import annotations

import calendar
import json
import math
import os
import tempfile
from pathlib import Path

import ee

ENV_VAR = "GEE_SERVICE_ACCOUNT_JSON"
DYNAMIC_WORLD_COLLECTION = "GOOGLE/DYNAMICWORLD/V1"
DYNAMIC_WORLD_BAND = "label"

BBox = tuple[float, float, float, float]


class GeeError(RuntimeError):
    """Earth Engine authentication failure."""


def _key_file_from_env(value: str) -> tuple[str, str]:
    """Return (service_account_email, key_file_path) from the env value.

    `value` is either a path to a JSON key file or the JSON content itself; in
    the latter case it is written to a temp file (ee wants a file path).
    """
    candidate = Path(value)
    if candidate.is_file():
        key_path = candidate
    else:
        try:
            json.loads(value)  # validate it is JSON before writing
        except json.JSONDecodeError as exc:
            raise GeeError(f"{ENV_VAR} is neither a readable file nor valid JSON") from exc
        tmp = Path(tempfile.mkstemp(suffix=".json", prefix="gee_key_")[1])
        tmp.write_text(value, encoding="utf-8")
        key_path = tmp

    email = json.loads(key_path.read_text(encoding="utf-8")).get("client_email")
    if not email:
        raise GeeError("service-account JSON has no 'client_email'")
    return str(email), str(key_path)


def init_earth_engine() -> None:
    """Initialise Earth Engine with the service account from `GEE_SERVICE_ACCOUNT_JSON`."""
    value = os.environ.get(ENV_VAR)
    if not value:
        raise GeeError(f"set {ENV_VAR} (path to, or content of, the service-account key)")
    email, key_file = _key_file_from_env(value)
    credentials = ee.ServiceAccountCredentials(email, key_file)
    ee.Initialize(credentials)


def _month_window(month: str) -> tuple[str, str]:
    """('YYYY-MM') -> inclusive ISO date range covering the calendar month."""
    try:
        year, mon = (int(p) for p in month.split("-"))
    except ValueError as exc:
        raise GeeError(f"month must be 'YYYY-MM', got {month!r}") from exc
    last = calendar.monthrange(year, mon)[1]
    return f"{year:04d}-{mon:02d}-01", f"{year:04d}-{mon:02d}-{last:02d}"


def _grid_size(bbox: BBox, resolution_m: float) -> tuple[int, int]:
    """Pixel dims for a lon/lat `bbox` at `resolution_m` (local m/degree)."""
    minx, miny, maxx, maxy = bbox
    lat = 0.5 * (miny + maxy)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * abs(math.cos(math.radians(lat)))
    width = max(1, round((maxx - minx) * m_per_deg_lon / resolution_m))
    height = max(1, round((maxy - miny) * m_per_deg_lat / resolution_m))
    return width, height


def fetch_dynamic_world(
    bbox: BBox,
    month: str,
    out_path: Path,
    *,
    resolution_m: float = 10.0,
) -> Path:
    """Export DW monthly mode label band for `bbox`/`month` to `out_path` (GeoTIFF).

    Pure-EE call: `ee.data.computePixels` returns the GeoTIFF synchronously, so
    no batch/export polling is needed. Output is in EPSG:4326 at native 10 m
    equivalent; downstream `prepare` resamples to the target grid with NEAREST.
    """
    start, end = _month_window(month)
    geom = ee.Geometry.Rectangle(list(bbox))
    img = (
        ee.ImageCollection(DYNAMIC_WORLD_COLLECTION)
        .filterDate(start, end)
        .filterBounds(geom)
        .select(DYNAMIC_WORLD_BAND)
        .mode()
        .clip(geom)
    )

    width, height = _grid_size(bbox, resolution_m)
    minx, _miny, _maxx, maxy = bbox
    scale_x = (bbox[2] - bbox[0]) / width
    scale_y = (bbox[3] - bbox[1]) / height
    request: dict[str, object] = {
        "expression": img,
        "fileFormat": "GEO_TIFF",
        "grid": {
            "dimensions": {"width": width, "height": height},
            "affineTransform": {
                "scaleX": scale_x,
                "shearX": 0.0,
                "translateX": minx,
                "shearY": 0.0,
                "scaleY": -scale_y,
                "translateY": maxy,
            },
            "crsCode": "EPSG:4326",
        },
    }
    content: bytes = ee.data.computePixels(request)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(content)
    return out_path
