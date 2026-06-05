from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

CHARSET = "iso-8859-2"

DEFAULT_BASE_URL = "http://server.mycompany.com/Akty/Servlet/"

def _default_data_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data"

@dataclass(slots=True)
class Config:
    base_url: str = field(default_factory=lambda: os.environ.get("ACTS_BASE_URL", DEFAULT_BASE_URL))
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

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.files_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)
