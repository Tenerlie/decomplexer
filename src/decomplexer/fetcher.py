from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import urljoin

import httpx

from . import site
from .config import CHARSET, Config

log = logging.getLogger("decomplexer")

@runtime_checkable
class Fetcher(Protocol):
    def open_search(self) -> str: ...
    def next_page(self) -> str | None: ...
    def get(self, url: str) -> str: ...
    def download(self, url: str, dest: Path) -> str: ...
    def close(self) -> None: ...

class FetchError(RuntimeError):
    pass

class _RateLimiter:

    def __init__(self, min_delay: float) -> None:
        self._min_delay = min_delay
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self._min_delay <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            start = now if sleep_for <= 0 else self._next_allowed
            self._next_allowed = start + self._min_delay
        if sleep_for > 0:
            time.sleep(sleep_for)

class HttpxFetcher:

    def __init__(self, config: Config) -> None:
        self._cfg = config
        self._limiter = _RateLimiter(config.min_delay)
        self._client = httpx.Client(
            timeout=config.timeout,
            follow_redirects=True,
            headers={"User-Agent": "decomplexer/0.1 (acts-harvester)"},
        )

    def open_search(self) -> str:
        try:
            self.get(site.SEARCH_PAGE)
        except FetchError as exc:
            log.debug("search warm-up failed: %s", exc)
        return self.post(site.CONTROL, site.SEARCH_DEFAULTS)

    def next_page(self) -> str | None:
        return self.post(site.CONTROL, site.NEXT_PAGE_DATA)

    def get(self, url: str) -> str:
        return self._text(self._request("GET", url))

    def post(self, url: str, data: dict[str, str]) -> str:
        return self._text(self._request("POST", url, data=data))

    def set_cookies(self, cookies: dict[str, str]) -> None:
        self._client.cookies.update(cookies)

    def set_header(self, name: str, value: str) -> None:
        self._client.headers[name] = value

    def download(self, url: str, dest: Path) -> str:
        dest.parent.mkdir(parents=True, exist_ok=True)
        full = self._resolve(url)
        last_exc: Exception | None = None
        for attempt in range(self._cfg.max_retries):
            self._limiter.wait()
            try:
                with self._client.stream("GET", full) as resp:
                    resp.raise_for_status()
                    server_name = _content_disposition_filename(
                        resp.headers.get("content-disposition", "")
                    )
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with tmp.open("wb") as fh:
                        for chunk in resp.iter_bytes():
                            fh.write(chunk)
                    final = dest if not server_name else dest.with_name(server_name)
                    tmp.replace(final)
                    return final.name
            except (httpx.HTTPError,) as exc:
                last_exc = exc
                self._sleep_backoff(attempt)
        raise FetchError(f"download failed for {full}: {last_exc}")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpxFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _resolve(self, url: str) -> str:
        if url.startswith(("http://", "https://")):
            return url
        return urljoin(self._cfg.base_url, url)

    def _request(self, method: str, url: str, data: dict[str, str] | None = None) -> httpx.Response:
        full = self._resolve(url)
        last_exc: Exception | None = None
        for attempt in range(self._cfg.max_retries):
            self._limiter.wait()
            try:
                resp = self._client.request(method, full, data=data)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code not in (429, 500, 502, 503, 504):
                    raise FetchError(f"{method} {full} -> {exc.response.status_code}") from exc
                last_exc = exc
                self._sleep_backoff(attempt)
            except httpx.HTTPError as exc:
                last_exc = exc
                self._sleep_backoff(attempt)
        raise FetchError(f"{method} {full} failed after retries: {last_exc}")

    def _sleep_backoff(self, attempt: int) -> None:
        time.sleep(self._cfg.backoff_base ** attempt)

    @staticmethod
    def _text(resp: httpx.Response) -> str:
        return resp.content.decode(CHARSET, errors="replace")

def _content_disposition_filename(header: str) -> str | None:
    if not header:
        return None
    for part in header.split(";"):
        part = part.strip()
        if part.lower().startswith("filename="):
            name = part[len("filename="):].strip().strip('"')
            return name or None
    return None

def build_fetcher(config: Config) -> Fetcher:
    if config.fetcher == "playwright":
        from .playwright_fetcher import HybridFetcher

        return HybridFetcher(config)
    return HttpxFetcher(config)
