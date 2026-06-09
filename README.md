## Setup

```bash
uv sync --extra playwright    # default backend — needed for the live site
uv sync                       # base only (httpx fixture server + tests)
```

Set the target host in `config.py` (`DEFAULT_BASE_URL`); override per-run with
`ACTS_BASE_URL` or `--base-url` if needed. No `playwright install` is required —
it launches your installed Google Chrome (Edge: `--browser-channel msedge`).

## Usage

Run from inside the corporate network:

```bash
uv run decomplexer crawl --limit 5 --dry-run   # smoke test: 5 acts, no downloads
uv run decomplexer crawl                        # full harvest (resumable)
uv run decomplexer update                       # re-walk + flag acts no longer in force
uv run decomplexer export                       # rewrite the relations map from the DB
uv run decomplexer stats                        # DB counts
uv run decomplexer prune                        # files of not-in-force acts (dry run)
uv run decomplexer prune --apply                # ...actually delete them
```

`crawl`/`update` take `--keep-raw` to also save each act's raw `metrics.html`
(off by default — parsed values are always in the DB).

Other flags: `--data-dir`, `--concurrency`, `--min-delay`, `--insecure` (skip TLS
verification for the self-signed cert), `--browser-channel {chrome,msedge}`,
`--browser-exe <path>`, `--headful`, `-v`/`-vv`, `--log-file`, `--no-file-log`.

## Logging

Every URL loaded, button clicked, and file downloaded is logged. The console
honours `-v`/`-vv` (default = warnings only); a rotating audit file at
`<data-dir>/logs/decomplexer.log` always holds full DEBUG detail. Override with
`--log-file`, disable with `--no-file-log`.

## Running on Windows (production)

```powershell
uv sync --extra playwright
$env:NO_PROXY = "server.mycompany.com"   # httpx half must reach the intranet direct
uv run decomplexer --data-dir C:\acts crawl --limit 5 --dry-run
```

- **Proxy.** Chrome uses the system proxy automatically. The httpx half honours
  `HTTPS_PROXY`/`NO_PROXY` — add the acts host to `NO_PROXY` so it goes direct.
- **Browser.** Defaults to installed Chrome; else `--browser-channel msedge` or
  `--browser-exe "C:\Path\to\chrome.exe"`.
- **Paths.** Keep `--data-dir` short (e.g. `C:\acts`) to stay under the 260-char
  limit; downloaded filenames are sanitised for Windows.
- **TLS.** The box serves HTTPS with a self-signed cert. Blunt fix: `--insecure`.
  Tidy fix: point `$env:SSL_CERT_FILE` at the CA `.pem` and leave verification on.

## Output

```
acts_repo_gather/data/
  acts.sqlite                 # acts, attachments, relations
  files/UZ/2026/UZ-139-2026/
      metrics.html            # raw metrics page — only with --keep-raw
      content/<document>
      attachments/<files>
  exports/relations.{csv,json,graphml}
  logs/decomplexer.log        # full audit trail
  prune_not_in_force.py       # standalone helper, dropped here automatically
```

DB file paths are stored relative to the data dir, so the folder stays portable.

### Database

- `acts` — one row per act incl. `id_aktu`, all metrics, `attachment_count`,
  `content_local_path`, a `state` (`discovered` → `metrics_done` → `files_done`)
  that drives resume, and `obowiazuje` (1 = in force, 0 = dropped out, with
  `obowiazuje_changed_at`).
- `attachments` — one row per attachment (filename, display name, description,
  url, relative local path, downloaded flag).
- `relations` — directed edges (`from_sig`, `to_sig`, `kind`, `source`).
  `kind` ∈ {`zmieniajacy`, `zmieniany`, `looses_power`}; `source` ∈ {`results`,
  `metrics`}.

## Layout

| Module                 | Responsibility                                   |
|------------------------|--------------------------------------------------|
| `config.py`            | Runtime config, charset, paths, the single host  |
| `logsetup.py`          | Dual-sink logging (console + rotating audit file)|
| `signatures.py`        | Signature normalization (`UZ/139/2026` ⇄ forms)  |
| `fetcher.py`           | `Fetcher` interface + `HttpxFetcher` (offline)   |
| `playwright_fetcher.py`| Default backend: Chrome clicks + httpx downloads |
| `parse.py`             | Pure HTML parsers for the 4 page types           |
| `db.py`                | SQLite schema + upserts, in-force flag            |
| `crawler.py`           | Orchestration, resume, update + reconcile        |
| `exporters.py`         | Relations map → CSV / JSON / GraphML             |
| `prune.py`             | Delete files of not-in-force acts (also standalone)|
| `main.py`              | CLI                                              |
