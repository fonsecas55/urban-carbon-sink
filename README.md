# Urban Carbon Sink

A stateless data pipeline that estimates the **monthly CO₂ sequestration of urban
vegetation** in Oeiras (Portugal) from satellite imagery, using the CASA
(Carnegie–Ames–Stanford Approach) Net Primary Productivity model.

Each month a disposable container pulls Sentinel-2/3, Google Dynamic World and
CAMS solar data, runs the geoprocessing, and publishes a Cloud-Optimized GeoTIFF
plus a JSON summary to GitHub Releases — no always-on server, no runtime
infrastructure.

## Architecture

```mermaid
flowchart TD
subgraph Data Sources [External APIs]
CDSE["Copernicus CDSE\n(S2 Multispectral & S3 Thermal S8)"]
GEE["Google Earth Engine\n(Dynamic World)"]
CAMS["ECMWF CAMS API\n(Solar Radiation / var_pct)"]
end

subgraph Local Host [Linux Server]
Cron["Cron Job\n(Monthly Scheduling)"]
Wrapper["run_monthly.sh\n(Orchestration & Error Handling)"]

subgraph Volumes & Security
  Secrets["Secrets\n(.env, gee_key.json :ro)"]
  DirOut["/output Directory\n(UID mapped)"]
end
end

subgraph Docker [Stateless Container]
CLI["CASA CLI (Python 3.12)\n(Pinned uv environment)"]
Math["Geoprocessing Engine\n(rasterio, xu2023 εmax, LST, FPAR)"]
Notify["Notify Module\n(Clean exit/failure trapping)"]
end

subgraph Telemetry
Discord["Discord Webhook\n✅ Success / ❌ Failure"]
end

subgraph Distribution & Frontend [WIP]
GH_Rel["GitHub Releases\n(Object Storage / Free CDN)"]
GH_Data["Orphan 'data' Branch\n(releases.json API index)"]
Vercel["Next.js Frontend\n(MapLibre/Leaflet WebGIS)"]
end

%% Core Relationships
Cron -->|Trigger| Wrapper
Wrapper -->|docker compose run --rm| CLI
Secrets -.->|Runtime Injection| CLI

CDSE -->|Download APIs| CLI
GEE -->|Classification| CLI
CAMS -->|Seasonal Data| CLI

CLI -->|Matrix Calculus| Math
Math -->|Writes oeiras_npp_co2.tif & oeiras.json| DirOut

Math -->|Status| Notify
Notify -->|HTTP Payload| Discord

%% Future Relationships
DirOut -.->|gh release upload YYYY-MM| GH_Rel
Wrapper -.->|Commit Index| GH_Data
GH_Data -.->|Fetch API| Vercel
GH_Rel -.->|COG Tiles Consumption| Vercel

classDef done fill:#1a1a1a,stroke:#3fb950,stroke-width:2px,color:#e6edf3
classDef pending fill:#1a1a1a,stroke:#d29922,stroke-width:2px,stroke-dasharray: 5 5,color:#e6edf3

class CDSE,GEE,CAMS,Cron,Wrapper,Secrets,DirOut,CLI,Math,Notify,Discord done
class GH_Rel,GH_Data,Vercel pending
```

## Engineering Principles

- **Stateless / Ephemeral** — the runtime is a `python:3.12-slim` container that
  is created on a schedule, does its work, writes its artifacts to a bind-mounted
  directory, and exits (`docker compose run --rm`). Nothing runs 24/7.
- **Reproducible** — the full dependency graph is pinned in `uv.lock` and
  installed with `uv sync --frozen`; the same locked, universal lockfile drives
  both local development and the production image. A given input month yields a
  byte-identical computation regardless of host.
- **Secure by Design** — no credentials are ever baked into the image. The `.env`
  and the read-only service-account key are injected only at runtime
  (`env_file` + `:ro` bind mount), and `.dockerignore` keeps them out of the
  build context. The container runs non-root; GitHub credentials live only on the
  host, never inside the container.
- **Automated** — a single host cron entry triggers the month's run; results are
  pushed to **GitHub Releases** (used as free, CDN-backed object storage) and a
  Discord webhook reports success or failure, so the pipeline needs no human
  babysitting.

## The model

CASA NPP per pixel:

```
NPP = PAR_fraction · SOL · FPAR · ε_max · T_ε1 · T_ε2 · W_ε
```

Inputs are derived from Sentinel-2 reflectance (NDVI → FPAR; SWIR → water
stress), Sentinel-3 SLSTR S8 brightness temperature (thermal stress), Dynamic
World land cover (per-class ε_max from the traceable Xu et al. 2023 / MODIS
BPLUT table), and a CAMS-derived seasonal solar factor. NPP is converted to CO₂
(× 44/12) and integrated over the municipal geometry. See [`docs/`](docs/) for
the model derivation and the architecture decision records.

## Running Locally

Prerequisites: Docker, a `.env` (from `.env.example`), and a Google Earth Engine
service-account key.

```bash
# 1. credentials
cp .env.example .env                 # fill in CDSE / CAMS / Discord values
# place your GEE service-account key at ./gee_key.json (git-ignored, mounted :ro)

# 2. build the pinned image
docker compose build

# 3a. compute only (no publishing)
docker compose run --rm casa run --online -r oeiras -m 2025-04 \
  --base-ghi data/sol/ghi_base.tif --out output

# 3b. full monthly run via the wrapper (compute + Discord + GitHub Release)
./deploy/run_monthly.sh oeiras 2025-04
```

Outputs land in `output/`: `oeiras_npp_co2.tif` (Cloud-Optimized GeoTIFF, CO₂
density) and `oeiras.json` (totals + carbon balance). Scheduling and the
publishing setup (`gh auth`, the orphan `data` branch) are documented in
[`deploy/README.md`](deploy/README.md).

## Tests

```bash
uv sync --extra dev
uv run pytest -q          # unit + integration (synthetic fixtures, no network)
uv run ruff check src tests
uv run mypy
```

## License

MIT — see [LICENSE](LICENSE).
