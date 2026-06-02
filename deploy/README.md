# Deploy — monthly Cron on the HomeLab (Bloco 7)

Stateless monthly pipeline: the host cron spins a disposable container that
computes CASA, writes `output/<region>.json` + a valid COG, alerts Discord, then
the **host** publishes the artifacts to a GitHub Release and updates the
`data`-branch manifest.

```
cron → run_monthly.sh ─┬─ docker compose run --rm casa run --online … --notify   (compute, in container)
                       └─ publish.sh REGION MONTH                                 (deliver, on host: gh + git)
```

## One-time setup on the ThinkPad (WSL)

1. **Image + secrets** (see `../docker-compose.yml`):
   ```bash
   echo 'DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/XXX/YYY' >> .env
   docker compose build
   ```

2. **`gh` auth** — publishing runs on the host as your user:
   ```bash
   gh auth login          # GitHub.com → HTTPS → authenticate
   gh auth status         # confirm fonsecas55 with repo scope
   ```

3. **Bootstrap the orphan `data` branch once** (the manifest lives here; it never
   triggers a Vercel rebuild). Done in a throwaway clone so the main working tree
   is never touched (and a dirty tree does not block it):
   ```bash
   tmp=$(mktemp -d)
   git clone "$(git remote get-url origin)" "$tmp/boot"
   git -C "$tmp/boot" switch --orphan data
   printf '{"updated_at":"","latest_tag":"","releases":[]}\n' > "$tmp/boot/releases.json"
   git -C "$tmp/boot" add releases.json
   git -C "$tmp/boot" -c user.name="casa-bot" -c user.email="casa@local" \
       commit -m "data: init manifest"
   git -C "$tmp/boot" push -u origin data
   rm -rf "$tmp"
   ```
   (`-c user.name/email` inline mirrors what `publish.sh` does, so this works even
   with no global git identity set — as on a fresh ThinkPad.)

4. **Install the cron** (from the repo root):
   ```bash
   crontab deploy/crontab && crontab -l
   sudo service cron status    # must be running
   ```

## The cron-blindness gotcha

cron runs with a bare environment — no `~/.bashrc`, and `HOME` is not guaranteed.
`gh` reads its token from `~/.config/gh/hosts.yml`, so a missing `HOME` makes it
blind. `publish.sh` forces `export HOME="${HOME:-/home/$(id -un)}"`.

Token alternative: export `GH_TOKEN` (or `GITHUB_TOKEN`) before `gh` runs and it
overrides the config-file path entirely — handy if you keep the token in a
host-only secrets file sourced by the wrapper.

The compute container has the **same** issue for its own UID (no `/etc/passwd`
entry); compose sets `HOME=/tmp` for it.

## Manual run / test

```bash
./deploy/run_monthly.sh oeiras 2025-04      # compute + Discord + publish
# bare cron-env simulation (catches PATH/HOME problems the cron would hit):
env -i SHELL=/bin/bash PATH=/usr/local/bin:/usr/bin:/bin HOME="$HOME" \
  "$PWD/deploy/run_monthly.sh" oeiras 2025-04
```

Verify after: a `:white_check_mark:` in Discord, a release `2025-04` with
`oeiras_npp_co2.tif` + `oeiras.json`, and `releases.json` updated on `data`
(`https://raw.githubusercontent.com/fonsecas55/co2-CASA/data/releases.json`).
