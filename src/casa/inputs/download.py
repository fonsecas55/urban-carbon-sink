"""Remote data pulls facade (GEE Dynamic World, CDSE Sentinel-2/3, CAMS).

Thin convenience wrappers around the specialised modules — used by callers that
want one fetch at a time without building auth/clients themselves. The monthly
orchestration (multi-source pull, monthly GHI build) lives in `online.py`.
Credentials come from the environment (see `cdse`/`gee`/`cams`).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from casa.inputs.cams import fetch_cams_for_month as _fetch_cams
from casa.inputs.cdse import CdseAuth, ProcessClient
from casa.inputs.cdse import fetch_sentinel2 as _fetch_s2
from casa.inputs.cdse import fetch_sentinel3 as _fetch_s3
from casa.inputs.gee import fetch_dynamic_world as _fetch_dw
from casa.inputs.gee import init_earth_engine as _init_ee

BBox = tuple[float, float, float, float]


def _process_client() -> ProcessClient:
    """Build a CDSE Process API client from environment credentials."""
    return ProcessClient(CdseAuth.from_env().token)


def fetch_sentinel2(bbox: BBox, month: str, out_dir: Path) -> dict[str, Path]:
    """Pull Sentinel-2 L2A B4/B8/B11/B12 for `bbox`/`month` into `out_dir`."""
    return _fetch_s2(bbox, month, out_dir, _process_client())


def fetch_sentinel3(bbox: BBox, month: str, out_dir: Path) -> dict[str, Path]:
    """Pull Sentinel-3 SLSTR LST (day/night) for `bbox`/`month` into `out_dir`."""
    return _fetch_s3(bbox, month, out_dir, _process_client())


def fetch_dynamic_world(bbox: BBox, month: str, out_path: Path) -> Path:
    """Export the GEE Dynamic World label band for `bbox`/`month` to `out_path`."""
    _init_ee()
    return _fetch_dw(bbox, month, out_path)


def fetch_cams(point: tuple[float, float], month: str) -> dict[int, float]:
    """Fetch CAMS solar deviation series at `point` for `month` (12 months)."""
    with tempfile.TemporaryDirectory(prefix="cams_") as td:
        return _fetch_cams(point, month, tmp_dir=Path(td))
