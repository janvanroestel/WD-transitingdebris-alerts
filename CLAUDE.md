# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GitHub Pages site displaying interactive Plotly light curves for 6 white dwarfs with transiting debris, using ZTF forced photometry and alert data. A daily GitHub Actions cron job fetches new alerts from Kowalski and rebuilds the site.

## Build Commands

```bash
python scripts/process_forcedphot.py   # Parse ztffps/ files → data/forcedphot/*.json
python scripts/fetch_alerts.py         # Query Kowalski → data/alerts/*.json
python scripts/build_site.py           # Generate docs/index.html from JSON data
```

## Architecture

- **`objects.csv`** — Target list (headerless CSV): `name, ZTF_id, RA(sexagesimal), Dec(sexagesimal), magnitude`
- **`ztffps/`** — Raw ZTF forced photometry files (3 formats: v3.8, v3.9, v6.0 — differ in column naming)
- **`scripts/process_forcedphot.py`** — Parses ztffps files, matches to objects by coordinate proximity, converts difference flux to total magnitude (`mag = zpdiff - 2.5*log10(F_ref + F_diff)`), outputs per-object JSON
- **`scripts/fetch_alerts.py`** — Queries Kowalski cone search for each object, writes per-object alert JSON. Auth via env vars (`KOWALSKI_USERNAME/PASSWORD/HOST`) or local `~/mysecrets/secrets.json`
- **`scripts/build_site.py`** — Generates single-page static site with Plotly plots (one per object, scrollable). Loads Plotly.js from CDN
- **`data/forcedphot/{name}.json`** — Processed forced photometry (jd, mag, mag_unc, filter)
- **`data/alerts/{ztf_id}.json`** — Alert photometry (jd, mag, mag_unc, filter, objectId)
- **`docs/index.html`** — Generated static site served by GitHub Pages
- **`.github/workflows/update.yml`** — Daily cron (06:00 UTC) + manual dispatch: fetch alerts → process forced phot → build site → commit

## Key Dependencies

`penquins` (Kowalski client), `astropy` (coordinates, JD conversion), `pandas`, `numpy`, `plotly`

## Secrets

Kowalski credentials: env vars `KOWALSKI_USERNAME`, `KOWALSKI_PASSWORD`, `KOWALSKI_HOST` (used in GitHub Actions), or `~/mysecrets/secrets.json` (local dev).
