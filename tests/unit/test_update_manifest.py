"""Unit tests for tools/update_releases_manifest.py (loaded by path; not a pkg)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "update_releases_manifest.py"
_spec = importlib.util.spec_from_file_location("update_releases_manifest", _TOOL)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
upsert = _mod.upsert


def _empty() -> dict[str, Any]:
    return {"updated_at": "", "latest_tag": "", "releases": []}


def test_upsert_adds_first_entry() -> None:
    m = upsert(_empty(), "2025-04", "oeiras", "ok")
    assert m["latest_tag"] == "2025-04"
    assert m["releases"] == [{"tag": "2025-04", "regions": ["oeiras"], "data_quality": {"oeiras": "ok"}}]
    assert m["updated_at"]  # stamped


def test_upsert_second_region_same_tag_is_appended_sorted() -> None:
    m = upsert(_empty(), "2025-04", "oeiras", "ok")
    m = upsert(m, "2025-04", "lisboa", "degraded")
    (entry,) = m["releases"]
    assert entry["regions"] == ["lisboa", "oeiras"]
    assert entry["data_quality"] == {"oeiras": "ok", "lisboa": "degraded"}


def test_upsert_same_region_twice_does_not_duplicate() -> None:
    m = upsert(_empty(), "2025-04", "oeiras", "ok")
    m = upsert(m, "2025-04", "oeiras", "degraded")  # re-run updates quality in place
    (entry,) = m["releases"]
    assert entry["regions"] == ["oeiras"]
    assert entry["data_quality"]["oeiras"] == "degraded"


def test_upsert_orders_releases_newest_first_and_tracks_latest() -> None:
    m = upsert(_empty(), "2025-03", "oeiras", "ok")
    m = upsert(m, "2025-04", "oeiras", "ok")
    m = upsert(m, "2025-01", "oeiras", "ok")  # backfill an older month
    assert [r["tag"] for r in m["releases"]] == ["2025-04", "2025-03", "2025-01"]
    assert m["latest_tag"] == "2025-04"  # backfill does not move latest
