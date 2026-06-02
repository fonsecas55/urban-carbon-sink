#!/usr/bin/env python3
"""Backfill: reproject already-published COG release assets to EPSG:4326, in place.

The first month-batch was published before `to_cog` reprojected to 4326, so those
COG assets sit in the regional UTM grid. This re-fetches each release's COG,
reprojects it with `casa.cog.to_cog` (NO recompute -> zero Sentinel/GEE/CAMS API
quota; pure local CPU), and re-uploads with `gh release upload --clobber`.

Idempotent: a COG already in EPSG:4326 is skipped. Only the COG asset is touched
-- the JSON and the data-branch manifest are unchanged by a reprojection.

Run where `gh` is authenticated and the casa env is installed (repo root):
    uv run python tools/backfill_reproject_cogs.py [--region oeiras]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

import rasterio

from casa.cog import to_cog

_TAG_RE = re.compile(r"^\d{4}-\d{2}$")  # YYYY-MM release tags only


def _gh(*args: str) -> str:
    """Run a gh subcommand, returning stdout (raises on non-zero)."""
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True
    ).stdout


def _release_tags() -> list[str]:
    out = _gh("release", "list", "--json", "tagName", "--limit", "1000")
    tags = [str(r["tagName"]) for r in json.loads(out)]
    return sorted(t for t in tags if _TAG_RE.match(t))


def _crs_epsg(path: Path) -> int | None:
    with rasterio.open(path) as ds:
        return ds.crs.to_epsg() if ds.crs else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", default="oeiras", help="Region key (asset prefix).")
    args = ap.parse_args()
    asset = f"{args.region}_npp_co2.tif"

    tags = _release_tags()
    print(f"{len(tags)} release tag(s): {', '.join(tags) or '(none)'}")
    reprojected = 0
    for tag in tags:
        with tempfile.TemporaryDirectory() as d:
            local = Path(d) / asset
            try:
                _gh("release", "download", tag, "-p", asset, "-D", d, "--clobber")
            except subprocess.CalledProcessError:
                print(f"  {tag}: no '{asset}' asset -> skip")
                continue
            epsg = _crs_epsg(local)
            if epsg == 4326:
                print(f"  {tag}: already EPSG:4326 -> skip")
                continue
            to_cog(local)  # reproject UTM -> 4326 + re-COG (overviews), in place
            if _crs_epsg(local) != 4326:
                raise RuntimeError(f"{tag}: reprojection did not yield EPSG:4326")
            _gh("release", "upload", tag, str(local), "--clobber")
            print(f"  {tag}: {epsg} -> 4326, re-uploaded")
            reprojected += 1
    print(f"done: {reprojected} reprojected, {len(tags) - reprojected} skipped")


if __name__ == "__main__":
    main()
