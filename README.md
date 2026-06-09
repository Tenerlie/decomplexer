# decomplexer

Harvester for the legacy company acts repository (the ancient
`server.mycompany.com/Akty/Servlet/Control` Java app). It mirrors every act —
the metadata, the act document, all attachments, and the web of relations
between acts — into a clean local tree + SQLite DB, and supports cheap
incremental re-runs.

## How it works (the hybrid model)

The live servlet **rejects a scripted form POST** (it 404s outside a real
browser), so a plain HTTP client cannot start a search on its own. The default
**`playwright`** backend therefore drives real Google Chrome to *click* the
"Szukaj" and ">>> następne" buttons, then hands the browser's session cookies to
`httpx` for everything else — the ~30k act-page fetches and file downloads, which
are ordinary GETs the cookie is enough for. So the browser does only the few
stateful clicks; httpx does the heavy lifting.

Parsing never uses positional XPath (which shatters on this malformed legacy
markup). It anchors on stable markers instead: form `name=`, `show=`/`file=`
query params, and the metrics **label text**.

A run always starts by loading `Control?todo=szukajAkt` **directly** — bare
`Control` is never probed first, because on this ancient app it always 404s.

## Backends

- **`playwright` — default; the only backend that works against the live site.**
  Real Google Chrome clicks search/pagination; httpx (carrying the browser's
  session) fetches act pages and streams downloads.
- **`httpx` — offline/tests only (`--fetcher httpx`).** Pure HTTP. Drives the
  bundled fixture server and the whole test suite, but **not** the live servlet.

## Setup

```bash
uv sync --extra playwright    # default backend — needed for the live site
uv sync                       # base only (httpx fixture server + tests)
```

No `playwright install` is needed — the browser backend launches your installed
**Google Chrome** (`channel="chrome"`), so nothing is downloaded through the
proxy. Edge works too: `--browser-channel msedge`.

## Usage (live site)

Run from inside the corporate network. Playwright is the default, so no
`--fetcher` flag is needed:

```bash
# Smoke test first: 5 acts, parse + record, download nothing
uv run decomplexer --base-url https://server.mycompany.com/Akty/Servlet/ \
    crawl --limit 5 --dry-run

# Full harvest (resumable — safe to re-run after an interruption)
uv run decomplexer --base-url <url> crawl

# Incremental: walk newest-first, stop at the first act already in the DB
uv run decomplexer --base-url <url> update

# Re-export the relations map / print counts from the DB (no network)
uv run decomplexer export
uv run decomplexer stats
```

Useful global flags: `--data-dir`, `--concurrency`, `--min-delay`,
`--browser-channel {chrome,msedge}`, `--browser-exe <path>`, `--headful`
(show the window), `-v`/`-vv`, `--log-file <path>`, `--no-file-log`.

### Setting the domain

The host lives in exactly one place. To point at the real server, in order of
precedence: pass `--base-url`, set the `ACTS_BASE_URL` env var, or edit the
single `DEFAULT_BASE_URL` constant in `config.py` (marked `← SET THE REAL DOMAIN
HERE`). A bare host is accepted and expanded — `--base-url server.real.com`
becomes `http://server.real.com/Akty/Servlet/`. No other module contains a host
literal, so swapping domains is a one-line change.

### Logging

Logging is sacred here: **every** URL loaded, button clicked, and file
downloaded is logged. The console honours `-v`/`-vv` (default = warnings only),
while a persistent, rotating audit file at `<data-dir>/logs/decomplexer.log`
**always** records the full DEBUG-level detail — so even a quiet run is fully
reconstructable afterwards. Override the path with `--log-file`, or turn the
file off with `--no-file-log`.

## Running on Windows (production)

This is the prod target. PowerShell:

```powershell
uv sync --extra playwright
$env:NO_PROXY = "server.mycompany.com"   # httpx half must reach the intranet direct
uv run decomplexer --base-url https://server.mycompany.com/Akty/Servlet/ `
    --data-dir C:\acts crawl --limit 5 --dry-run
```

Notes:
- **Proxy.** Chrome uses the system proxy automatically (same as your browser),
  so the search/pagination clicks just work. The httpx half (act pages +
  downloads) honours `HTTPS_PROXY`/`NO_PROXY` — set `NO_PROXY` to include the
  acts host so those go direct.
- **Browser.** Defaults to installed Chrome. If it isn't found, use
  `--browser-channel msedge` or `--browser-exe "C:\Path\to\chrome.exe"`.
- **Paths.** Keep `--data-dir` short (e.g. `C:\acts`) to stay clear of the
  260-char path limit; downloaded filenames are sanitised for Windows.
- **TLS.** If httpx hits a corporate-CA error, set `$env:SSL_CERT_FILE` to the
  CA `.pem` (or run the harvest from a box where the CA is trusted).

## Output

```
acts_repo_gather/data/
  acts.sqlite                 # acts, attachments, relations
  files/UZ/2026/UZ-139-2026/
      metrics.html            # raw metrics page (for re-parsing later)
      content/<document>
      attachments/<files>
  exports/relations.{csv,json,graphml}
  logs/decomplexer.log        # full audit trail (every URL/click/download)
```

### Database

- `acts` — one row per act incl. `id_aktu`, all metrics, `attachment_count`,
  `content_local_path`, and a `state` (`discovered` → `metrics_done` →
  `files_done`) that drives resume and the incremental stop condition.
- `attachments` — one row per attachment (filename, description, url, local path,
  downloaded flag).
- `relations` — directed edge list (`from_sig`, `to_sig`, `kind`, `source`).
  `kind` ∈ {`zmieniajacy`, `zmieniany`, `looses_power`}; `source` ∈ {`results`,
  `metrics`}.

## Development

```bash
uv run pytest          # parser unit tests + offline end-to-end integration
```

`tests/fixture_server.py` serves the files in `../pages/` as a stand-in for the
real servlet (ISO-8859-2 encoded, two result pages, frameset, metrics, dummy
downloads), so the whole crawl loop is exercised without network access.

## Layout

| Module                 | Responsibility                                   |
|------------------------|--------------------------------------------------|
| `config.py`            | Runtime config, charset, paths, the single host  |
| `logsetup.py`          | Dual-sink logging (console + rotating audit file)|
| `signatures.py`        | Signature normalization (`UZ/139/2026` ⇄ forms)  |
| `fetcher.py`           | `Fetcher` interface + `HttpxFetcher` (offline)   |
| `playwright_fetcher.py`| Default backend: Chrome clicks + httpx downloads |
| `parse.py`             | Pure HTML parsers for the 4 page types           |
| `db.py`                | SQLite schema + upserts                           |
| `crawler.py`           | Orchestration, resume, incremental update        |
| `exporters.py`         | Relations map → CSV / JSON / GraphML             |
| `main.py`              | CLI                                              |
