#!/usr/bin/env bash
#
# Monthly CASA run (Bloco 7) — invoked by the host (WSL) cron on day 1.
#
# Stateless: spins the disposable container for the PREVIOUS month, then alerts
# Discord on success (in-process via `casa run --notify`) or on failure (via
# `casa notify`, since a crashed run cannot notify itself). Secrets stay in the
# container's env_file/bind mounts — never touched here in bash.
#
# Usage:  run_monthly.sh [REGION] [YYYY-MM]
#   REGION   defaults to "oeiras"
#   YYYY-MM  defaults to the previous calendar month
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

REGION="${1:-oeiras}"
MONTH="${2:-$(date -d 'last month' +%Y-%m)}"

# Run the container as the invoking host user so the bind-mounted output/ stays
# owned by us (the image's default UID 1000 may differ from the host user).
RUN_USER="$(id -u):$(id -g)"

mkdir -p output
echo "[$(date -Is)] CASA start: region=$REGION month=$MONTH (user $RUN_USER)"

if docker compose run --rm --user "$RUN_USER" casa \
      run --online -r "$REGION" -m "$MONTH" \
      --base-ghi data/sol/ghi_base.tif --out output --notify; then
    echo "[$(date -Is)] CASA ok: region=$REGION month=$MONTH"
else
    code=$?
    echo "[$(date -Is)] CASA FAIL (exit $code): region=$REGION month=$MONTH" >&2
    # Best-effort failure alert; never let a notify problem mask the real exit.
    docker compose run --rm --user "$RUN_USER" casa \
        notify -r "$REGION" -m "$MONTH" \
        --error "monthly run exited $code (see host cron log)" || true
    exit "$code"
fi

# Compute succeeded (and the :white_check_mark: already fired). Publish the COG +
# JSON to a GitHub Release and update the data-branch manifest. Publish is a
# separate concern (delivery, not science): on failure, alert but keep the local
# artifact and a distinct non-zero exit so the cron log flags it.
# The data_quality (ok|degraded) is computed by the pipeline from the S3 thermal;
# pass it through so cloud-corrupted months land as "degraded" in the manifest.
QUALITY=$(python3 -c "import json;print(json.load(open('output/$REGION.json')).get('data_quality','ok'))" 2>/dev/null || echo ok)
echo "[$(date -Is)] data_quality=$QUALITY"
if ! "$REPO_DIR/deploy/publish.sh" "$REGION" "$MONTH" "$QUALITY"; then
    echo "[$(date -Is)] PUBLISH FAIL: region=$REGION month=$MONTH" >&2
    docker compose run --rm --user "$RUN_USER" casa \
        notify -r "$REGION" -m "$MONTH" \
        --error "compute OK but publish to GitHub failed (artifact is on disk)" || true
    exit 2
fi
echo "[$(date -Is)] published: region=$REGION month=$MONTH"
