"""Synthetic tests for casa.notify — no real webhook (requests-mock)."""

from __future__ import annotations

import pytest

from casa.notify import (
    NotifyError,
    format_failure,
    format_success,
    post_webhook,
    webhook_url_from_env,
)

_URL = "https://discord.test/webhook/abc"


def test_format_success_carries_region_co2_and_offset() -> None:
    report = {
        "region": "oeiras",
        "month": "2025-04",
        "totals": {"npp_co2_t": 7317.78},
        "balance": {"offset_fraction": 0.0477},
        "vegetation_area_ha": 1567.0,
    }
    msg = format_success(report)
    assert "oeiras" in msg and "2025-04" in msg
    assert "7,318 tCO2" in msg  # thousands-separated, no double-counting
    assert "4.8%" in msg


def test_format_success_tolerates_missing_keys() -> None:
    msg = format_success({})
    assert "?" in msg and "tCO2" in msg  # never raises on a partial dict


def test_format_failure_includes_truncated_error() -> None:
    msg = format_failure("oeiras", "2025-04", "CdseError: boom")
    assert "FALHOU" in msg and "CdseError: boom" in msg


def test_webhook_url_from_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    with pytest.raises(NotifyError, match="DISCORD_WEBHOOK_URL"):
        webhook_url_from_env()


def test_webhook_url_from_env_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", _URL)
    assert webhook_url_from_env() == _URL


def test_post_webhook_sends_content(requests_mock) -> None:  # type: ignore[no-untyped-def]
    requests_mock.post(_URL, status_code=204)
    post_webhook("hello", url=_URL)
    assert requests_mock.last_request.json() == {"content": "hello"}


def test_post_webhook_raises_on_non_2xx(requests_mock) -> None:  # type: ignore[no-untyped-def]
    requests_mock.post(_URL, status_code=400, text="bad request")
    with pytest.raises(NotifyError, match="failed"):
        post_webhook("hello", url=_URL)
