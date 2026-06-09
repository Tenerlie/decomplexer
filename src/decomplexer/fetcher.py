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
            log.debug("rate-limit: sleeping %.0f ms before next request", sleep_for * 1000)
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
        log.info("ENTRY: opening search at %s", site.SEARCH_PAGE)
        try:
            self.get(site.SEARCH_PAGE)
        except FetchError as exc:
            log.debug("search warm-up GET failed (non-fatal): %s", exc)
        log.info("submitting search form (POST %s)", site.CONTROL)
        return self.post(site.CONTROL, site.SEARCH_DEFAULTS)

    def next_page(self) -> str | None:
        log.info("requesting next results page (POST %s)", site.CONTROL)
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
        log.info("DOWNLOAD %s -> %s", full, dest)
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
                    written = 0
                    with tmp.open("wb") as fh:
                        for chunk in resp.iter_bytes():
                            written += len(chunk)
                            fh.write(chunk)
                    final = dest if not server_name else dest.with_name(server_name)
                    tmp.replace(final)
                    if server_name:
                        log.debug("server named the file %r via Content-Disposition", server_name)
                    log.info("DOWNLOAD ok: %d bytes -> %s", written, final.name)
                    return final.name
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("download attempt %d/%d for %s failed: %s",
                            attempt + 1, self._cfg.max_retries, full, exc)
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
            started = time.monotonic()
            try:
                resp = self._client.request(method, full, data=data)
                elapsed_ms = (time.monotonic() - started) * 1000
                resp.raise_for_status()
                log.info("%s %s -> %d (%d bytes, %.0f ms)",
                         method, full, resp.status_code, len(resp.content), elapsed_ms)
                return resp
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code if exc.response is not None else "?"
                if exc.response is not None and exc.response.status_code not in (429, 500, 502, 503, 504):
                    log.warning("%s %s -> %s (not retried)", method, full, code)
                    raise FetchError(f"{method} {full} -> {code}") from exc
                last_exc = exc
                log.warning("%s %s -> %s (attempt %d/%d, retrying)",
                            method, full, code, attempt + 1, self._cfg.max_retries)
                self._sleep_backoff(attempt)
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("%s %s failed: %s (attempt %d/%d, retrying)",
                            method, full, exc, attempt + 1, self._cfg.max_retries)
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

        log.debug("using playwright (hybrid) fetcher")
        return HybridFetcher(config)
    log.debug("using httpx fetcher")
    return HttpxFetcher(config)
