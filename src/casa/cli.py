"""Command-line interface for the Urban Carbon Sink pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from casa import __version__, config
from casa.cog import to_cog
from casa.grid import target_grid_from_bbox
from casa.inputs.mask import resolve_geometry
from casa.inputs.prepare import SourcePaths, prepare_region_inputs
from casa.pipeline import run_region
from casa.reports import build_report, write_report

app = typer.Typer(
    help="CASA-based monthly CO2 absorption pipeline for urban vegetation.",
    add_completion=False,
    no_args_is_help=True,
)

# Expected raw source filenames inside --source-dir (offline mode).
_SOURCE_FILES = {
    "red": "red.tif",
    "nir": "nir.tif",
    "swir1": "swir1.tif",
    "swir2": "swir2.tif",
    "t_day": "t_day.tif",
    "t_night": "t_night.tif",
    "ghi": "ghi.tif",
    "landcover": "landcover.tif",
}


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(f"casa {__version__}")


@app.command()
def run(
    region: str = typer.Option(..., "--region", "-r", help="Region key, e.g. 'oeiras'."),
    month: str = typer.Option(..., "--month", "-m", help="Month in YYYY-MM format."),
    source_dir: Path | None = typer.Option(
        None, "--source-dir", "-s", help="Dir with raw source rasters (offline mode)."
    ),
    online_mode: bool = typer.Option(
        False, "--online", help="Pull S2/S3/DW/CAMS/GHI live before running."
    ),
    base_ghi: Path | None = typer.Option(
        None, "--base-ghi", help="GHI baseline raster (kWh/m2/day), required with --online."
    ),
    esa_fallback: Path | None = typer.Option(
        None, "--esa-fallback",
        help="ESA WorldCover raster, required with --online when pipeline.landcover_source=esa_worldcover.",
    ),
    out_dir: Path = typer.Option(Path("out"), "--out", "-o", help="Output directory."),
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config tree root."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Resolve config + grid and exit without computing."
    ),
    notify: bool = typer.Option(
        False, "--notify", help="On success, post a summary to DISCORD_WEBHOOK_URL."
    ),
) -> None:
    """Run the CASA pipeline for a single region and month.

    Two input modes (mutually exclusive):
    - `--source-dir DIR`: offline; reads red/nir/swir1/swir2/t_day/t_night/ghi/
      landcover .tif files from DIR.
    - `--online`: pulls S2/S3 from CDSE, Dynamic World from GEE, CAMS solar
      deviation, and crops the GHI baseline (`--base-ghi`) for the target month.
    """
    if online_mode == (source_dir is not None):
        raise typer.BadParameter("pass exactly one of --source-dir or --online")
    if online_mode and base_ghi is None:
        raise typer.BadParameter("--online requires --base-ghi (GHI baseline raster)")

    cfg = config.load(config_dir, region)
    geom = resolve_geometry(cfg.region.geometry_wkt, cfg.region.geometry_path)
    grid = target_grid_from_bbox(geom.bounds)

    if dry_run:
        typer.echo(f"region={region} month={month}")
        typer.echo(f"grid: {grid.width}x{grid.height} @ {grid.resolution:g} m, CRS={grid.crs}")
        typer.echo(f"mode={'online' if online_mode else f'offline ({source_dir})'}")
        raise typer.Exit(code=0)

    out_dir.mkdir(parents=True, exist_ok=True)

    var_pct: float | None = None
    if online_mode:
        from casa.inputs.online import download_region

        assert base_ghi is not None  # narrowed by the BadParameter check above
        downloaded = download_region(
            cfg, month, out_dir,
            base_ghi_path=base_ghi,
            esa_fallback_path=esa_fallback,
        )
        sources = downloaded.sources
        var_pct = downloaded.var_pct
    else:
        assert source_dir is not None  # narrowed by the BadParameter check above
        sources = SourcePaths(**{key: source_dir / name for key, name in _SOURCE_FILES.items()})

    inputs = prepare_region_inputs(cfg, sources, out_dir / "aligned")
    cog_path = out_dir / f"{region}_npp_co2.tif"
    result = run_region(inputs, cfg, month, cog_path, var_pct=var_pct)
    to_cog(cog_path)  # finalise as a valid COG for browser-side reading

    report = build_report(result, cfg)
    write_report(report, out_dir / f"{region}.json")

    typer.echo(
        f"wrote {cog_path.name} + {region}.json | "
        f"CO2 absorbed {result.total_npp_co2_t:,.1f} t over {result.vegetation_pixels} veg px"
    )

    if notify:
        from casa import notify as notify_mod

        try:
            report_dict = json.loads((out_dir / f"{region}.json").read_text(encoding="utf-8"))
            notify_mod.post_webhook(notify_mod.format_success(report_dict))
        except notify_mod.NotifyError as exc:
            # Best-effort: the science already succeeded; don't fail the run.
            typer.echo(f"notify skipped: {exc}", err=True)


@app.command()
def notify(
    region: str = typer.Option(..., "--region", "-r", help="Region key."),
    month: str = typer.Option(..., "--month", "-m", help="Month in YYYY-MM format."),
    error: str = typer.Option("", "--error", help="Error text to include in the alert."),
) -> None:
    """Post a FAILURE alert to DISCORD_WEBHOOK_URL (used by the Cron wrapper)."""
    from casa import notify as notify_mod

    notify_mod.post_webhook(notify_mod.format_failure(region, month, error or "unknown error"))


@app.command("list-regions")
def list_regions(
    config_dir: Path = typer.Option(Path("config"), "--config-dir", help="Config tree root."),
) -> None:
    """List configured regions from config/regions/*.yml."""
    regions_dir = config_dir / "regions"
    names = sorted(p.stem for p in regions_dir.glob("*.yml")) if regions_dir.is_dir() else []
    if not names:
        typer.echo("no regions configured.")
        return
    for name in names:
        typer.echo(name)


if __name__ == "__main__":
    app()
