from __future__ import annotations

import logging
from pathlib import Path

from .config import Config
from .fetcher import HttpxFetcher
from . import site

log = logging.getLogger("decomplexer")

class HybridFetcher:
    def __init__(self, config: Config) -> None:
        from playwright.sync_api import sync_playwright

        self._cfg = config
        self._http = HttpxFetcher(config)

        self._pw = sync_playwright().start()
        launch_kwargs: dict = {"headless": config.headless}
        if config.browser_executable_path:
            launch_kwargs["executable_path"] = config.browser_executable_path
        else:
            launch_kwargs["channel"] = config.browser_channel or "chrome"
        self._browser = self._pw.chromium.launch(**launch_kwargs)
        self._ctx = self._browser.new_context()
        self._page = self._ctx.new_page()

    def open_search(self) -> str:
        url = self._http._resolve(site.SEARCH_PAGE)
        self._page.goto(url, wait_until="load")
        with self._page.expect_navigation(wait_until="load"):
            self._page.click(site.SEARCH_SUBMIT)
        self._sync_session()
        return self._page.content()

    def next_page(self) -> str | None:
        btn = self._page.query_selector(site.NEXT_BUTTON)
        if btn is None:
            return None
        with self._page.expect_navigation(wait_until="load"):
            btn.click()
        self._sync_session()
        return self._page.content()

    def get(self, url: str) -> str:
        return self._http.get(url)

    def download(self, url: str, dest: Path) -> str:
        return self._http.download(url, dest)

    def close(self) -> None:
        try:
            self._ctx.close()
            self._browser.close()
            self._pw.stop()
        finally:
            self._http.close()

    def __enter__(self) -> "HybridFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _sync_session(self) -> None:
        cookies = {c["name"]: c["value"] for c in self._ctx.cookies()}
        if cookies:
            self._http.set_cookies(cookies)
        try:
            ua = self._page.evaluate("() => navigator.userAgent")
            if ua:
                self._http.set_header("User-Agent", ua)
        except Exception as exc:
            log.debug("could not read User-Agent: %s", exc)
