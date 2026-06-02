"""Discord webhook notification for the monthly Cron (Bloco 7).

Side-effect-narrow: format a message, then POST it. The webhook URL comes from
the environment (`DISCORD_WEBHOOK_URL`, injected via the container's env_file),
never from code. The format_* functions are isolated so swapping Discord for
Telegram is a payload change, not a rewrite.

The success notification is fired in-process by `casa run --notify`; the failure
notification is fired by the Cron wrapper via `casa notify` when the run exits
non-zero (a crashing `casa run` cannot notify itself).
"""

from __future__ import annotations

import os
from typing import Any

import requests

WEBHOOK_ENV = "DISCORD_WEBHOOK_URL"
_TIMEOUT_S = 15.0


class NotifyError(RuntimeError):
    """Webhook misconfiguration or delivery failure."""


def webhook_url_from_env() -> str:
    """Read the webhook URL from the environment; fail fast if unset."""
    url = os.environ.get(WEBHOOK_ENV)
    if not url:
        raise NotifyError(f"set {WEBHOOK_ENV} to enable notifications")
    return url


def format_success(report: dict[str, Any]) -> str:
    """Compose a success message from a region report dict (the written JSON)."""
    region = report.get("region", "?")
    month = report.get("month", "?")
    totals = report.get("totals", {})
    balance = report.get("balance", {})
    co2 = float(totals.get("npp_co2_t", 0.0))
    offset = float(balance.get("offset_fraction", 0.0))
    veg_ha = float(report.get("vegetation_area_ha", 0.0))
    degraded = report.get("data_quality") == "degraded"
    head = ":warning:" if degraded else ":white_check_mark:"
    tail = "\n:warning: data_quality=degraded (cloud-contaminated S3 thermal)" if degraded else ""
    return (
        f"{head} **{region} {month}** - sequestro calculado\n"
        f"- CO2 absorvido: **{co2:,.0f} tCO2**\n"
        f"- Offset das emissoes: **{offset * 100:.1f}%**\n"
        f"- Vegetacao: {veg_ha:,.0f} ha"
        f"{tail}"
    )


def format_failure(region: str, month: str, error: str) -> str:
    """Compose a failure alert; the error text is truncated to stay webhook-safe."""
    return (
        f":x: **{region} {month}** - pipeline FALHOU\n"
        f"```\n{error[:1500]}\n```"
    )


def post_webhook(content: str, *, url: str | None = None) -> None:
    """POST `content` to the Discord webhook. Raises NotifyError on non-2xx."""
    target = url if url is not None else webhook_url_from_env()
    resp = requests.post(target, json={"content": content}, timeout=_TIMEOUT_S)
    # Discord replies 204 No Content on success; accept any 2xx.
    if not 200 <= resp.status_code < 300:
        raise NotifyError(f"webhook POST failed: {resp.status_code} {resp.text[:200]}")
