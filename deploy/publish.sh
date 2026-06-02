#!/usr/bin/env bash
#
# Publish a successful monthly run to GitHub Releases + the data-branch manifest.
#
# HOST-SIDE on purpose: uses `gh` (authenticated on the ThinkPad) and git, so the
# compute container never holds GitHub credentials. Idempotent — re-running for
# the same tag/region clobbers the assets and updates the manifest in place.
#
# Usage:  publish.sh REGION YYYY-MM [data_quality]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

REGION="${1:?region required}"
MONTH="${2:?month (YYYY-MM) required}"
QUALITY="${3:-ok}"

# --- cron blindagem ---------------------------------------------------------
# cron runs bare: HOME may be unset, so `gh` cannot find ~/.config/gh/hosts.yml
# (gh auth login token) and git cannot find ~/.gitconfig. Force HOME to the
# invoking user's home. If you prefer a token, exporting GH_TOKEN/GITHUB_TOKEN
# (e.g. sourced from a host-only secrets file) overrides the config file path.
export HOME="${HOME:-/home/$(id -un)}"

COG="output/${REGION}_npp_co2.tif"
JSON="output/${REGION}.json"
[ -f "$COG" ] && [ -f "$JSON" ] || { echo "[publish] missing artifacts: $COG / $JSON" >&2; exit 1; }

echo "[publish] release $MONTH <- $REGION ($QUALITY)"

# 1) Release: create if absent, else clobber the two assets (idempotent).
if gh release view "$MONTH" >/dev/null 2>&1; then
    gh release upload "$MONTH" "$COG" "$JSON" --clobber
else
    gh release create "$MONTH" "$COG" "$JSON" \
        --title "$MONTH" --notes "CASA monthly carbon sink - $MONTH"
fi

# 2) Manifest on the orphan `data` branch, edited in an isolated worktree so the
#    main checkout is never disturbed. Detached from origin/data => stateless.
git fetch origin
WT="$(mktemp -d)"
trap 'git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$WT"' EXIT
if ! git rev-parse --verify --quiet origin/data >/dev/null; then
    echo "[publish] origin/data missing - bootstrap it once (see deploy/README.md)" >&2
    exit 1
fi
git worktree add --detach "$WT" origin/data

python3 tools/update_releases_manifest.py \
    --manifest "$WT/releases.json" --tag "$MONTH" --region "$REGION" --quality "$QUALITY"

git -C "$WT" add releases.json
if git -C "$WT" diff --cached --quiet; then
    echo "[publish] manifest unchanged"
else
    git -C "$WT" -c user.name="casa-bot" -c user.email="casa@local" \
        commit -q -m "data: $MONTH ($REGION=$QUALITY)"
    git -C "$WT" push origin HEAD:data
fi
echo "[publish] done"
