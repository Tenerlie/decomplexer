# decomplexer

Harvester for the legacy company acts repository (the ancient
`server.mycompany.com/Akty/Servlet/Control` Java app). It mirrors every act —
the metadata, the act document, all attachments, and the web of relations
between acts — into a clean local tree + SQLite DB, and supports cheap
incremental re-runs.

## Why it works without a browser

Every page is plain server-rendered HTML (frames are just URLs, forms are plain
POSTs, the only JavaScript is cosmetic), and the site needs no login on the
intranet. So the default backend is `httpx` + `lxml` — far faster and lighter
than driving a browser for ~30k requests. A `playwright` backend is available as
a drop-in fallback behind the same `Fetcher` interface if the live site ever
turns out to need a real browser; switching is a single `--fetcher` flag and
changes nothing else.

Parsing never uses positional XPath (which shatters on this malformed legacy
markup). It anchors on stable markers instead: form `name=`, `show=`/`file=`
query params, and the metrics **label text**.

## Backends

- **`playwright` (use this for the live site).** Drives real Google Chrome to
  click the search/pagination buttons, then reuses the browser's session cookies
  with httpx for the act pages and file downloads. The live servlet rejects a
  plain scripted form POST (it 404s), so the browser step is required.
- **`httpx` (default; offline/tests only).** Pure HTTP. Works against the bundled
  fixture server and the test suite, but **not** the live servlet.

## Setup

```bash
uv sync                       # base (httpx + tests)
uv sync --extra playwright    # add the browser backend for the live site
```

No `playwright install` is needed — the browser backend launches your installed
**Google Chrome** (`channel="chrome"`), so nothing is downloaded through the
proxy. Edge works too: `--browser-channel msedge`.

## Usage (live site)

Run from inside the corporate network, with the **playwright** backend:

```bash
# Smoke test first: 5 acts, parse + record, download nothing
uv run decomplexer --base-url https://server.mycompany.com/Akty/Servlet/ \
    --fetcher playwright crawl --limit 5 --dry-run

# Full harvest (resumable — safe to re-run after an interruption)
uv run decomplexer --base-url <url> --fetcher playwright crawl

# Incremental: walk newest-first, stop at the first act already in the DB
uv run decomplexer --base-url <url> --fetcher playwright update

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
    --fetcher playwright --data-dir C:\acts crawl --limit 5 --dry-run
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
| `fetcher.py`           | `Fetcher` interface + `HttpxFetcher`             |
| `playwright_fetcher.py`| Optional drop-in browser backend                 |
| `parse.py`             | Pure HTML parsers for the 4 page types           |
| `db.py`                | SQLite schema + upserts                           |
| `crawler.py`           | Orchestration, resume, incremental update        |
| `exporters.py`         | Relations map → CSV / JSON / GraphML             |
| `main.py`              | CLI                                              |
