from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import exporters
from .config import Config
from .crawler import Crawler
from .db import Database
from .fetcher import build_fetcher

def _build_config(args: argparse.Namespace) -> Config:
    cfg = Config()
    if args.base_url:
        cfg.base_url = args.base_url
    if args.data_dir:
        cfg.data_dir = Path(args.data_dir)
    if args.fetcher:
        cfg.fetcher = args.fetcher
    if args.browser_channel:
        cfg.browser_channel = args.browser_channel
    if args.browser_exe:
        cfg.browser_executable_path = args.browser_exe
    if getattr(args, "headful", False):
        cfg.headless = False
    if args.concurrency is not None:
        cfg.concurrency = args.concurrency
    if args.min_delay is not None:
        cfg.min_delay = args.min_delay
    if getattr(args, "limit", None) is not None:
        cfg.limit = args.limit
    if getattr(args, "dry_run", False):
        cfg.dry_run = True
    cfg.ensure_dirs()
    return cfg

def _run_crawl(cfg: Config, *, update: bool) -> None:
    fetcher = build_fetcher(cfg)
    try:
        with Database(cfg.db_path) as database:
            crawler = Crawler(cfg, fetcher, database)
            if update:
                crawler.update()
            else:
                crawler.crawl()
            stats = database.stats()
            exporters.export_all(database, cfg.exports_dir)
    finally:
        fetcher.close()
    logging.getLogger("decomplexer").info("Done. %s", stats)

def _run_export(cfg: Config) -> None:
    with Database(cfg.db_path) as database:
        paths = exporters.export_all(database, cfg.exports_dir)
    for kind, path in paths.items():
        print(f"{kind}: {path}")

def _run_stats(cfg: Config) -> None:
    with Database(cfg.db_path) as database:
        for k, v in database.stats().items():
            print(f"{k}: {v}")

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="decomplexer", description=__doc__)
    parser.add_argument("--base-url", help="Servlet base URL (overrides default/env)")
    parser.add_argument("--data-dir", help="Output directory for DB and files")
    parser.add_argument("--fetcher", choices=["httpx", "playwright"],
                        help="Network backend (playwright = Chrome clicks + httpx downloads)")
    parser.add_argument("--browser-channel",
                        help="Playwright browser channel: chrome (default) or msedge")
    parser.add_argument("--browser-exe",
                        help="Full path to the browser binary (if channel can't find it)")
    parser.add_argument("--headful", action="store_true",
                        help="Show the browser window (playwright backend; for debugging)")
    parser.add_argument("--concurrency", type=int, help="Parallel per-act workers (crawl)")
    parser.add_argument("--min-delay", type=float, help="Min seconds between requests")
    parser.add_argument("-v", "--verbose", action="count", default=0)

    sub = parser.add_subparsers(dest="command", required=True)

    p_crawl = sub.add_parser("crawl", help="Full harvest (resumable)")
    p_crawl.add_argument("--limit", type=int, help="Cap acts processed (smoke test)")
    p_crawl.add_argument("--dry-run", action="store_true", help="Parse + record, download nothing")

    p_update = sub.add_parser("update", help="Incremental: stop at first known act")
    p_update.add_argument("--limit", type=int, help="Cap acts processed")
    p_update.add_argument("--dry-run", action="store_true")

    sub.add_parser("export", help="(Re)write the relations map from the DB")
    sub.add_parser("stats", help="Print DB counts")

    args = parser.parse_args(argv)

    level = logging.WARNING - 10 * min(args.verbose, 2)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")

    cfg = _build_config(args)

    if args.command == "crawl":
        _run_crawl(cfg, update=False)
    elif args.command == "update":
        _run_crawl(cfg, update=True)
    elif args.command == "export":
        _run_export(cfg)
    elif args.command == "stats":
        _run_stats(cfg)
    return 0

if __name__ == "__main__":
    sys.exit(main())
