from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode, urljoin

from .config import Config

class PlaywrightFetcher:
    def __init__(self, config: Config) -> None:
        from playwright.sync_api import sync_playwright

        self._cfg = config
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._ctx = self._browser.new_context(user_agent="decomplexer/0.1 (acts-harvester)")
        self._page = self._ctx.new_page()

    def _resolve(self, url: str) -> str:
        if url.startswith(("http://", "https://")):
            return url
        return urljoin(self._cfg.base_url, url)

    def get(self, url: str) -> str:
        self._page.goto(self._resolve(url), wait_until="domcontentloaded")
        return self._page.content()

    def post(self, url: str, data: dict[str, str]) -> str:
        target = self._resolve(url)
        body = urlencode(data)
        self._page.evaluate(
            """async ([target, body]) => {
                const r = await fetch(target, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body,
                    credentials: 'include',
                });
                const t = await r.text();
                document.open(); document.write(t); document.close();
            }""",
            [target, body],
        )
        return self._page.content()

    def download(self, url: str, dest: Path) -> str:
        dest.parent.mkdir(parents=True, exist_ok=True)
        resp = self._ctx.request.get(self._resolve(url))
        dest.write_bytes(resp.body())
        return dest.name

    def close(self) -> None:
        self._ctx.close()
        self._browser.close()
        self._pw.stop()

    def __enter__(self) -> "PlaywrightFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
