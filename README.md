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

## Setup

```bash
uv sync
# optional browser backend:
#   uv sync --extra playwright && uv run playwright install chromium
```

## Usage

Run from inside the corporate network (the app must be reachable).

```bash
# Full harvest (resumable — safe to re-run after an interruption)
uv run decomplexer --base-url http://server.mycompany.com/Akty/Servlet/ crawl

# Smoke test first: 5 acts, parse + record but download nothing
uv run decomplexer --base-url <url> crawl --limit 5 --dry-run
# then 5 acts for real
uv run decomplexer --base-url <url> crawl --limit 5

# Incremental: walk newest-first, stop at the first act already in the DB
uv run decomplexer --base-url <url> update

# Re-export the relations map / print counts from the DB
uv run decomplexer export
uv run decomplexer stats
```

Useful global flags: `--data-dir`, `--concurrency`, `--min-delay`, `--fetcher
{httpx,playwright}`, `-v`/`-vv`. The base URL can also be set via the
`ACTS_BASE_URL` env var.

## Output

```
acts_repo_gather/data/
  acts.sqlite                 # acts, attachments, relations
  files/UZ/2026/UZ-139-2026/
      metrics.html            # raw metrics page (for re-parsing later)
      content/<document>
      attachments/<files>
  exports/relations.{csv,json,graphml}
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
| `config.py`            | Runtime config, charset, paths                   |
| `signatures.py`        | Signature normalization (`UZ/139/2026` ⇄ forms)  |
| `fetcher.py`           | `Fetcher` interface + `HttpxFetcher`             |
| `playwright_fetcher.py`| Optional drop-in browser backend                 |
| `parse.py`             | Pure HTML parsers for the 4 page types           |
| `db.py`                | SQLite schema + upserts                           |
| `crawler.py`           | Orchestration, resume, incremental update        |
| `exporters.py`         | Relations map → CSV / JSON / GraphML             |
| `main.py`              | CLI                                              |
