from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db, parse, signatures
from .config import Config
from .fetcher import Fetcher
from .parse import Metrics, ResultRow

log = logging.getLogger("decomplexer")

_MAX_PAGES = 10_000

@dataclass(slots=True)
class ActPayload:
    row: ResultRow
    id_aktu: str | None = None
    metrics: Metrics | None = None
    metrics_html: str = ""
    content_local_path: str | None = None
    attachment_paths: dict[str, str] = field(default_factory=dict)
    error: str | None = None

class Crawler:
    def __init__(self, config: Config, fetcher: Fetcher, database: db.Database) -> None:
        self.cfg = config
        self.fetcher = fetcher
        self.db = database
        self._processed = 0

    def crawl(self) -> None:
        self._walk_and_scrape(seen=set())

    def update(self) -> None:
        seen: set[str] = set()
        complete = self._walk_and_scrape(seen)
        if complete:
            self._reconcile(seen)
        else:
            log.warning("Walk did not complete (limit or error); skipping in-force "
                        "reconciliation to avoid false revocations.")

    def _walk_and_scrape(self, seen: set[str]) -> bool:
        try:
            html = self.fetcher.open_search()
        except Exception as exc:
            log.error("Search failed; aborting walk: %s", exc)
            return False

        for page_no in range(1, _MAX_PAGES + 1):
            page = parse.parse_results_page(html)
            log.info("Page %d: %d acts (total=%s)", page_no, len(page.rows), page.total)

            rows = [r for r in page.rows if not self._limit_reached()]
            for r in rows:
                seen.add(r.signature)
            self._record_result_rows(rows)
            todo = [r for r in rows
                    if self.db.get_state(r.signature) != db.STATE_FILES_DONE]
            self._scrape_concurrent(todo)

            if self._limit_reached():
                log.info("Reached --limit; stopping (walk incomplete).")
                return False
            if not page.rows or not page.has_next:
                return True
            try:
                html = self.fetcher.next_page()
            except Exception as exc:
                log.error("Pagination failed after page %d: %s", page_no, exc)
                return False
            if html is None:
                return True

        log.warning("Hit _MAX_PAGES safety valve; walk treated as incomplete.")
        return False

    def _reconcile(self, seen: set[str]) -> None:
        if not seen:
            log.warning("In-force walk returned no acts; skipping reconciliation.")
            return
        dropped = self.db.in_force_signatures() - seen
        for sig in sorted(dropped):
            self.db.set_obowiazuje(sig, 0)
            log.info("Act %s: no longer in the in-force results -> obowiazuje=0", sig)
        log.info("Reconciliation: %d in force this run, %d newly lost force.",
                 len(seen), len(dropped))

    def _record_result_rows(self, rows: list[ResultRow]) -> None:
        for row in rows:
            self.db.upsert_act(
                row.signature,
                title=row.title or None,
                status=row.status or None,
                obowiazuje=1 if (row.status or "").lower() == "o" else 0,
                data_uchwalenia=row.data_uchwalenia or None,
                data_wygasniecia=row.data_wygasniecia or None,
                state=None if self.db.has_act(row.signature) else db.STATE_DISCOVERED,
            )
            for rel in row.relations:
                self.db.add_relation(row.signature, rel.to_sig, rel.kind,
                                     db.SOURCE_RESULTS, rel.raw)

    def _scrape_concurrent(self, rows: list[ResultRow]) -> None:
        if not rows:
            return
        workers = max(1, self.cfg.concurrency)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._fetch_payload, r): r for r in rows}
            for fut in as_completed(futures):
                payload = fut.result()
                self._persist_payload(payload)
                self._processed += 1

    def _fetch_payload(self, row: ResultRow) -> ActPayload:
        payload = ActPayload(row=row)
        try:
            show = row.show or signatures.to_url(row.signature)
            status = row.status or "o"
            log.info("Act %s: fetching frameset (show=%s, status=%s)",
                     row.signature, show, status)
            frameset = self.fetcher.get(f"Control?show={show}&status={status}")
            metryke_url = parse.parse_act_frameset(frameset)
            if not metryke_url:
                payload.error = "no pokazMetryke frame found"
                log.warning("Act %s: no pokazMetryke frame in frameset", row.signature)
                return payload

            payload.id_aktu = _query_param(metryke_url, "IdAktu")
            log.debug("Act %s: IdAktu=%s, metrics at %s",
                      row.signature, payload.id_aktu, metryke_url)
            metrics_html = self.fetcher.get(metryke_url)
            payload.metrics_html = metrics_html
            payload.metrics = parse.parse_metrics(metrics_html)

            adir = self._act_dir(row.signature)
            if self.cfg.keep_raw:
                adir.mkdir(parents=True, exist_ok=True)
                (adir / "metrics.html").write_text(metrics_html, encoding="utf-8")
                log.debug("Act %s: kept raw metrics.html (--keep-raw)", row.signature)

            if self.cfg.dry_run:
                log.debug("Act %s: dry-run, skipping downloads", row.signature)
            else:
                self._download_files(payload, adir)
        except Exception as exc:
            payload.error = str(exc)
            log.warning("Act %s failed: %s", row.signature, exc)
        return payload

    def _download_files(self, payload: ActPayload, adir: Path) -> None:
        m = payload.metrics
        if m is None:
            return
        sig = payload.row.signature
        if m.content_file:
            dest = adir / "content" / _safe_name(m.content_file.filename)
            if dest.exists():
                log.debug("Act %s: content already on disk, skipping %s", sig, dest.name)
                payload.content_local_path = self._rel(dest)
            else:
                name = self.fetcher.download(m.content_file.url, dest)
                payload.content_local_path = self._rel(dest.with_name(name))
        log.debug("Act %s: %d attachment(s) to fetch", sig, len(m.attachments))
        for att in m.attachments:
            dest = adir / "attachments" / _safe_name(att.filename)
            if dest.exists():
                log.debug("Act %s: attachment already on disk, skipping %s", sig, dest.name)
                payload.attachment_paths[att.filename] = self._rel(dest)
            else:
                name = self.fetcher.download(att.url, dest)
                payload.attachment_paths[att.filename] = self._rel(dest.with_name(name))

    def _persist_payload(self, payload: ActPayload) -> None:
        row = payload.row
        m = payload.metrics
        if m is None:
            log.debug("Act %s: no metrics, left at 'discovered' for retry", row.signature)
            return

        f = m.fields
        self.db.upsert_act(
            row.signature,
            id_aktu=payload.id_aktu,
            rodzaj=f.get("rodzaj"),
            title=f.get("title") or row.title or None,
            data_uchwalenia=f.get("data_uchwalenia") or row.data_uchwalenia or None,
            data_wejscia=f.get("data_wejscia"),
            data_wygasniecia=f.get("data_wygasniecia") or row.data_wygasniecia or None,
            podmiot=f.get("podmiot"),
            organ=f.get("organ"),
            kategoria=f.get("kategoria"),
            uwagi=f.get("uwagi"),
            content_local_path=payload.content_local_path,
            attachment_count=len(m.attachments),
            raw_metrics_json=db.dumps(f),
            state=db.STATE_METRICS_DONE,
        )
        for rel in m.relations:
            self.db.add_relation(row.signature, rel.to_sig, rel.kind,
                                 db.SOURCE_METRICS, rel.raw)
        for att in m.attachments:
            self.db.upsert_attachment(
                row.signature, idx=att.idx, filename=att.filename,
                display_name=att.display_name, description=att.description,
                file_url=att.url, ext=att.ext,
            )
            local = payload.attachment_paths.get(att.filename)
            if local:
                self.db.mark_downloaded(row.signature, att.filename, local)

        log.info("Act %s: metrics_done (%d attachments, %d relations)",
                 row.signature, len(m.attachments), len(m.relations))

        if payload.error:
            return

        if self.cfg.dry_run:
            return

        self.db.set_state(row.signature, db.STATE_FILES_DONE)
        log.info("Act %s: files_done", row.signature)

    def _act_dir(self, signature: str) -> Path:
        return (
            self.cfg.files_dir
            / signatures.letters_of(signature)
            / signatures.year_of(signature)
            / signatures.to_slug(signature)
        )

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.cfg.data_dir))
        except ValueError:
            return str(path)

    def _limit_reached(self) -> bool:
        return self.cfg.limit is not None and self._processed >= self.cfg.limit

def _query_param(url: str, key: str) -> str | None:
    vals = parse_qs(urlparse(url).query).get(key)
    return vals[0] if vals else None

_ILLEGAL_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

def _safe_name(filename: str) -> str:
    name = _ILLEGAL_FS.sub("_", filename or "").rstrip(" .")
    return name or "file"
