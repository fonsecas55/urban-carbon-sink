"""Synthetic tests for casa.inputs.gee — service-account init + Dynamic World, fake ee."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from casa.inputs import gee


class _FakeEe:
    """Records ServiceAccountCredentials / Initialize calls in place of ee."""

    def __init__(self) -> None:
        self.cred_args: tuple[str, str] | None = None
        self.initialized_with: object = "NOT_CALLED"

    def ServiceAccountCredentials(self, email: str, key_file: str) -> str:  # noqa: N802
        self.cred_args = (email, key_file)
        return "fake-credentials"

    def Initialize(self, credentials: object) -> None:  # noqa: N802
        self.initialized_with = credentials


@pytest.fixture
def fake_ee(monkeypatch: pytest.MonkeyPatch) -> _FakeEe:
    fake = _FakeEe()
    monkeypatch.setattr(gee, "ee", fake)
    return fake


def test_requires_env(monkeypatch: pytest.MonkeyPatch, fake_ee: _FakeEe) -> None:
    monkeypatch.delenv(gee.ENV_VAR, raising=False)
    with pytest.raises(gee.GeeError, match=gee.ENV_VAR):
        gee.init_earth_engine()


def test_init_from_key_file_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_ee: _FakeEe
) -> None:
    key = tmp_path / "sa.json"
    key.write_text(json.dumps({"client_email": "cron@proj.iam.gserviceaccount.com"}))
    monkeypatch.setenv(gee.ENV_VAR, str(key))

    gee.init_earth_engine()

    assert fake_ee.cred_args == ("cron@proj.iam.gserviceaccount.com", str(key))
    assert fake_ee.initialized_with == "fake-credentials"


def test_init_from_json_content(monkeypatch: pytest.MonkeyPatch, fake_ee: _FakeEe) -> None:
    content = json.dumps({"client_email": "cron@proj.iam.gserviceaccount.com", "private_key": "x"})
    monkeypatch.setenv(gee.ENV_VAR, content)

    gee.init_earth_engine()

    assert fake_ee.cred_args is not None
    email, key_file = fake_ee.cred_args
    assert email == "cron@proj.iam.gserviceaccount.com"
    assert Path(key_file).read_text(encoding="utf-8") == content


def test_invalid_env_raises(monkeypatch: pytest.MonkeyPatch, fake_ee: _FakeEe) -> None:
    monkeypatch.setenv(gee.ENV_VAR, "not-a-path-and-not-json{")
    with pytest.raises(gee.GeeError):
        gee.init_earth_engine()


# --- fetch_dynamic_world ----------------------------------------------------


def _fake_dw_ee(payload: bytes) -> tuple[SimpleNamespace, dict[str, object]]:
    """Fluent fake of the ee surface fetch_dynamic_world touches.

    Records the dataset, dates, band, reducer, and the computePixels request
    body so tests can assert each step of the chain.
    """
    records: dict[str, object] = {}

    class _Expr:
        def filterDate(self, start: str, end: str) -> _Expr:  # noqa: N802
            records["dates"] = (start, end)
            return self

        def filterBounds(self, geom: object) -> _Expr:  # noqa: N802
            records["bounds"] = geom
            return self

        def select(self, band: str) -> _Expr:
            records["band"] = band
            return self

        def mode(self) -> _Expr:
            records["agg"] = "mode"
            return self

        def clip(self, geom: object) -> _Expr:
            records["clipped_to"] = geom
            return self

    def _image_collection(name: str) -> _Expr:
        records["dataset"] = name
        return _Expr()

    def _rectangle(coords: list[float]) -> tuple[str, tuple[float, ...]]:
        return ("rect", tuple(coords))

    def _compute(req: dict[str, object]) -> bytes:
        records["request"] = req
        return payload

    fake = SimpleNamespace(
        ImageCollection=_image_collection,
        Geometry=SimpleNamespace(Rectangle=_rectangle),
        data=SimpleNamespace(computePixels=_compute),
    )
    return fake, records


def test_dw_writes_payload_and_calls_correct_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"FAKE-GEOTIFF-BYTES"
    fake, rec = _fake_dw_ee(payload)
    monkeypatch.setattr(gee, "ee", fake)

    out = gee.fetch_dynamic_world((-9.35, 38.66, -9.23, 38.72), "2025-04", tmp_path / "dw.tif")

    assert out == tmp_path / "dw.tif"
    assert out.read_bytes() == payload
    assert rec["dataset"] == gee.DYNAMIC_WORLD_COLLECTION
    assert rec["band"] == gee.DYNAMIC_WORLD_BAND
    assert rec["agg"] == "mode"
    assert rec["dates"] == ("2025-04-01", "2025-04-30")
    assert rec["bounds"] == ("rect", (-9.35, 38.66, -9.23, 38.72))


def test_dw_request_grid_is_well_formed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, rec = _fake_dw_ee(b"x")
    monkeypatch.setattr(gee, "ee", fake)

    gee.fetch_dynamic_world((-9.30, 38.68, -9.20, 38.74), "2025-02", tmp_path / "dw.tif")

    req = rec["request"]
    assert isinstance(req, dict)
    assert req["fileFormat"] == "GEO_TIFF"
    grid = req["grid"]
    assert isinstance(grid, dict)
    assert grid["crsCode"] == "EPSG:4326"
    dims = grid["dimensions"]
    assert dims["width"] > 0 and dims["height"] > 0  # type: ignore[index]
    aff = grid["affineTransform"]
    # Origin at top-left (translateX=minx, translateY=maxy); scaleY negative.
    assert aff["translateX"] == -9.30  # type: ignore[index]
    assert aff["translateY"] == 38.74  # type: ignore[index]
    assert aff["scaleY"] < 0  # type: ignore[index, operator]
    # February 2025 has 28 days.
    assert rec["dates"] == ("2025-02-01", "2025-02-28")


def test_dw_bad_month_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake, _ = _fake_dw_ee(b"x")
    monkeypatch.setattr(gee, "ee", fake)
    with pytest.raises(gee.GeeError, match="YYYY-MM"):
        gee.fetch_dynamic_world((0.0, 0.0, 1.0, 1.0), "not-a-month", tmp_path / "dw.tif")
