from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

CHARSET = "iso-8859-2"

DEFAULT_BASE_URL = "http://server.mycompany.com/Akty/Servlet/"

_SERVLET_PATH = "/Akty/Servlet/"

def normalize_base_url(value: str) -> str:
    value = value.strip()
    had_scheme = "://" in value
    if not had_scheme:
        value = "http://" + value
    parts = urlsplit(value)
    path = parts.path
    if not had_scheme and path in ("", "/"):
        path = _SERVLET_PATH
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))

def _default_base_url() -> str:
    return normalize_base_url(os.environ.get("ACTS_BASE_URL", DEFAULT_BASE_URL))

def _default_data_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data"

@dataclass(slots=True)
class Config:
    base_url: str = field(default_factory=_default_base_url)
    data_dir: Path = field(default_factory=_default_data_dir)

    concurrency: int = 3
    min_delay: float = 0.3
    timeout: float = 60.0
    max_retries: int = 4
    backoff_base: float = 1.5

    fetcher: str = "httpx"
    browser_channel: str = "chrome"
    browser_executable_path: str | None = None
    headless: bool = True

    log_file: Path | None = None

    limit: int | None = None
    dry_run: bool = False

    @property
    def control_url(self) -> str:
        return self.base_url.rstrip("/") + "/Control"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "acts.sqlite"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def resolved_log_file(self) -> Path:
        return self.log_file or (self.logs_dir / "decomplexer.log")

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.files_dir, self.exports_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)
