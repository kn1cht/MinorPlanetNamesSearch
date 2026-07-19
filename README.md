# Minor Planet Names Search

Named minor planet search and analysis tool using MPC public data.

## Quick Start

This project intentionally uses only the Python standard library.

```powershell
uv run python -m mpnames init-sample
uv run python -m mpnames serve
```

Open http://127.0.0.1:8765/ after the server starts.

If `uv` is unavailable, use any Python 3.11+:

```powershell
python -m mpnames init-sample
python -m mpnames serve
```

## Real Data Ingestion

Start with a small, polite run:

```powershell
python -m mpnames ingest --mode add --limit 100 --classifier rules
```

`--limit` is applied after the ingest mode chooses which objects need to be
fetched. It limits Identifier API requests, not the final database size.

Ingest modes:

- `add` default: fetch only named objects that are not already in the DB.
- `update`: fetch existing objects too, but skip DB writes when nothing changed.
- `reset`: clear the local DB, then fetch up to `--limit` objects.
- `repair`: fetch objects missing from the DB, plus existing records with missing identifier fields.

Discovery date, observatory/site, and discoverer information is read from
MPC `NumberedMPs.txt` and cached locally at `data/NumberedMPs.txt`. To fill
these fields for an existing database without re-requesting Identifier or Orbit
API records, run:

```powershell
python -m mpnames enrich-discovery
```

Use `--refresh-cache` only when you want to download `NumberedMPs.txt` again.

### Naming Publication Dates (WGSBN Bulletins)

To attach the official publication date and reference for names announced in
WGSBN Bulletins, run:

```powershell
python -m mpnames enrich-naming-publications
```

The importer downloads the official WGSBN JSON archive and joins each record to
the local database by permanent minor-planet number. It records the earliest
Bulletin publication date, reference, and source URL. WGSBN Bulletin coverage
begins in 2021; earlier names require a separate MPC Circulars backfill. Existing
Bulletins are skipped on subsequent runs; use `--refresh` to download them again.

If a named object remains absent from both the MPC name list and Identifier API,
it can be explicitly retained from its WGSBN Bulletin record (rather than
automatically promoting every transient MPC lag):

```powershell
python -m mpnames backfill-wgsbn-only --permid 579513 --permid 511955 --permid 618348 --permid 59880
```

For a full local add run, omit `--limit`. Identifier API requests are batched at
100 names per request or less. By default the importer waits briefly between
Identifier API requests and pauses for 5 seconds after every 10 requests.

```powershell
python -m mpnames ingest --mode add --classifier rules
```

Rate-limit defaults are centralized in `mpnames/settings.py`:

- `IDENTIFIER_BATCH_SIZE`
- `IDENTIFIER_INTER_REQUEST_DELAY_SECONDS`
- `IDENTIFIER_LONG_PAUSE_EVERY_REQUESTS`
- `IDENTIFIER_LONG_PAUSE_SECONDS`
- `ORBIT_INTER_REQUEST_DELAY_SECONDS`
- `ORBIT_LONG_PAUSE_EVERY_REQUESTS`
- `ORBIT_LONG_PAUSE_SECONDS`

You can also override them from the CLI:

```powershell
python -m mpnames ingest --mode add --limit 1000 --batch-size 100 --pause-every 10 --pause-seconds 5 --orbit-pause-every 10 --orbit-pause-seconds 5
```

Long-running commands print progress by default, including MPC list fetches,
Identifier API batch numbers, Orbits API request numbers, long rate-limit pauses, and
classification/write progress. Add `--quiet` to suppress progress output:

```powershell
python -m mpnames ingest --mode add --limit 1000 --classifier rules --quiet
```

Citation categories can be assigned with one of three classifiers:

- `rules`: fast keyword rules only.
- `auto`: use ollama when its HTTP API is available; otherwise fall back to rules.
- `ollama`: use ollama as the primary classifier, with rule fallback if the call fails or returns invalid labels.

To reclassify an existing database without downloading MPC data again:

```powershell
python -m mpnames reclassify --classifier ollama
```

Person roles and entity gender are stored separately from the primary citation
category. They can be classified from existing citation text without downloading
MPC data again:

```powershell
python -m mpnames classify-person-facets --classifier rules
```

The role facets are multi-valued (`Scientist`, `Cultural/Public Figure`, and
`Discoverer-relative/Friend`). Gender is a separate single facet (`Female`,
`Male`, `Unknown`, `Non-person`, or `Multiple/Mixed`). `Female`, `Male`, and
`Multiple/Mixed` are assigned only with explicit citation evidence; names and
external biographical knowledge are never used as a proxy. Each facet saves its
supporting citation excerpt, classifier source, and confidence. Mythological and
fictional entities may receive an explicit gender facet while retaining their
primary `Mythology` or `Character` category. Use `--classifier ollama` with a
specific `--ollama-model` for evidence-quoting local-LLM review; the default
rules classifier is the conservative full-dataset baseline.

You can pin a specific local model:

```powershell
python -m mpnames reclassify --classifier ollama --ollama-model llama3.1
```

MPC sources used:

- https://www.minorplanetcenter.net/iau/lists/MPNames.html
- https://www.minorplanetcenter.net/iau/lists/NumberedMPs.txt
- https://data.minorplanetcenter.net/api/query-identifier
- https://data.minorplanetcenter.net/api/get-orb
- https://www.wgsbn-iau.org/documentation.html

## Commands

```powershell
python -m mpnames init-sample
python -m mpnames ingest --mode add --limit 100 --classifier rules
python -m mpnames enrich-discovery
python -m mpnames enrich-naming-publications
python -m mpnames backfill-wgsbn-only --permid 579513
python -m mpnames classify-person-facets --classifier rules
python -m mpnames serve --host 127.0.0.1 --port 8765
python -m mpnames ollama-status
python -m unittest discover -s tests
```

Run `python -m mpnames reclassify --classifier ollama` only when local LLM
capacity is available.

Data is stored in `data/mpnames.sqlite3` by default.

## Web Deployment (Cloudflare Pages & D1)

This project features a dual-architecture that allows the exact same frontend (`web/`) to be served by either the local Python server or Cloudflare Pages (via Cloudflare Workers and D1).

### Architecture

1. **Local Python Environment**: Optimized for data ingestion, processing, and fast local testing. Uses the local `data/mpnames.sqlite3` database.
2. **Cloudflare Pages Environment**: Optimized for global, serverless web hosting. Uses TypeScript APIs (`functions/api/*.ts`) and Cloudflare D1 as the database.

### Workflow

1. **Ingest & Process Data Locally**:
   Use the Python CLI to download, parse, and classify minor planets.
   ```powershell
   python -m mpnames ingest --mode add --classifier rules
   ```

2. **Test Locally (Python)**:
   Launch the local Flask server to verify the UI and data using local SQLite.
   ```powershell
   python -m mpnames serve
   ```
   Open `http://localhost:5000` to preview.

3. **Sync Database to Cloudflare D1**:
   When you're ready to publish the updated database, push the local SQLite data to Cloudflare D1. This script automatically generates an optimized SQL dump (handling FTS5 virtual tables and dependencies) and uploads it to the `mpnames-db` remote database.
   ```powershell
   npm run push-db
   ```
   *(Note: This process may take a few minutes for a full database)*

4. **Test Locally (Cloudflare Emulator)**:
   To test the Cloudflare Pages environment locally using Wrangler's miniflare emulator and your local D1 configuration:
   ```powershell
   npm run dev
   ```

5. **Deploy to Cloudflare Pages (Production)**:
   Build and deploy the frontend and serverless APIs to the live website (`mpnames.pages.dev`).
   ```powershell
   npm run deploy
   ```
