"""Smoke tests — verify package is importable and CLI is wired."""

from __future__ import annotations


def test_import_package() -> None:
    import casa

    assert casa.__version__


def test_cli_help_runs() -> None:
    from typer.testing import CliRunner

    from casa.cli import app

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "CASA" in result.stdout


def test_cli_version_runs() -> None:
    from typer.testing import CliRunner

    from casa import __version__
    from casa.cli import app

    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
