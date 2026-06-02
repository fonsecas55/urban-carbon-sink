"""Upsert a release entry into the data-branch `releases.json` manifest.

Stdlib only, so it runs on the host with plain `python3` (no project venv). The
publish step checks out the orphan `data` branch in an isolated worktree and
calls this to add/update the month's entry. Schema: docs/pipeline.md 3.8.

Idempotent: re-running for the same tag/region updates in place (a re-computed
month or a second region appended to an existing tag both work).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def upsert(manifest: dict[str, Any], tag: str, region: str, quality: str) -> dict[str, Any]:
    """Add/update {tag -> regions, data_quality}; keep releases newest-first."""
    releases: list[dict[str, Any]] = manifest.setdefault("releases", [])
    entry = next((r for r in releases if r.get("tag") == tag), None)
    if entry is None:
        entry = {"tag": tag, "regions": [], "data_quality": {}}
        releases.append(entry)
    if region not in entry["regions"]:
        entry["regions"].append(region)
    entry["regions"].sort()
    entry["data_quality"][region] = quality

    releases.sort(key=lambda r: r["tag"], reverse=True)  # YYYY-MM sorts chronologically
    manifest["releases"] = releases
    manifest["latest_tag"] = releases[0]["tag"] if releases else tag
    manifest["updated_at"] = _utc_now()
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True, type=Path, help="Path to releases.json.")
    ap.add_argument("--tag", required=True, help="Release tag, e.g. 2025-04.")
    ap.add_argument("--region", required=True, help="Region key, e.g. oeiras.")
    ap.add_argument("--quality", default="ok", help="data_quality for this region.")
    args = ap.parse_args()

    if args.manifest.exists():
        manifest: dict[str, Any] = json.loads(args.manifest.read_text(encoding="utf-8"))
    else:
        manifest = {"updated_at": "", "latest_tag": "", "releases": []}

    upsert(manifest, args.tag, args.region, args.quality)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"manifest: {args.tag} <- {args.region} ({args.quality}); latest={manifest['latest_tag']}")


if __name__ == "__main__":
    main()
