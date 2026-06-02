"""Unit tests for casa.cli — version, list-regions, and run --dry-run."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from casa.cli import app

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "casa" in result.stdout


def test_list_regions_includes_oeiras() -> None:
    result = runner.invoke(app, ["list-regions", "--config-dir", str(CONFIG_DIR)])
    assert result.exit_code == 0
    assert "oeiras" in result.stdout


def test_run_dry_run_reports_grid(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--region",
            "oeiras",
            "--month",
            "2024-06",
            "--source-dir",
            str(tmp_path),
            "--config-dir",
            str(CONFIG_DIR),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "grid:" in result.stdout
    assert "EPSG:32629" in result.stdout


def test_run_rejects_both_source_dir_and_online(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run", "--region", "oeiras", "--month", "2024-06",
            "--source-dir", str(tmp_path), "--online",
            "--base-ghi", str(tmp_path / "ghi.tif"),
            "--config-dir", str(CONFIG_DIR), "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "exactly one of" in result.stdout + (result.stderr or "")


def test_run_rejects_neither_source_dir_nor_online() -> None:
    result = runner.invoke(
        app,
        [
            "run", "--region", "oeiras", "--month", "2024-06",
            "--config-dir", str(CONFIG_DIR), "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "exactly one of" in result.stdout + (result.stderr or "")


def test_run_online_requires_base_ghi() -> None:
    result = runner.invoke(
        app,
        [
            "run", "--region", "oeiras", "--month", "2024-06",
            "--online", "--config-dir", str(CONFIG_DIR), "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "base-ghi" in result.stdout + (result.stderr or "")


def test_run_online_dry_run_reports_mode(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run", "--region", "oeiras", "--month", "2025-04",
            "--online", "--base-ghi", str(tmp_path / "ghi.tif"),
            "--config-dir", str(CONFIG_DIR), "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert "mode=online" in result.stdout
