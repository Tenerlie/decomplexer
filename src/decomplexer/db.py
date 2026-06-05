from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Iterable

STATE_DISCOVERED = "discovered"
STATE_METRICS_DONE = "metrics_done"
STATE_FILES_DONE = "files_done"

SOURCE_RESULTS = "results"
SOURCE_METRICS = "metrics"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS acts (
    signature           TEXT PRIMARY KEY,
    id_aktu             TEXT,
    rodzaj              TEXT,
    title               TEXT,
    status              TEXT,
    data_uchwalenia     TEXT,
    data_wejscia        TEXT,
    data_wygasniecia    TEXT,
    podmiot             TEXT,
    organ               TEXT,
    kategoria           TEXT,
    uwagi               TEXT,
    content_local_path  TEXT,
    attachment_count    INTEGER DEFAULT 0,
    raw_metrics_json    TEXT,
    state               TEXT NOT NULL DEFAULT 'discovered',
    scraped_at          REAL
);

CREATE TABLE IF NOT EXISTS attachments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    act_signature   TEXT NOT NULL REFERENCES acts(signature),
    idx             INTEGER,
    filename        TEXT NOT NULL,
    display_name    TEXT,
    description     TEXT,
    file_url        TEXT,
    ext             TEXT,
    local_path      TEXT,
    downloaded      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(act_signature, filename)
);

CREATE TABLE IF NOT EXISTS relations (
    from_sig    TEXT NOT NULL,
    to_sig      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    source      TEXT NOT NULL,
    raw         TEXT,
    UNIQUE(from_sig, to_sig, kind, source)
);

CREATE INDEX IF NOT EXISTS idx_relations_from ON relations(from_sig);
CREATE INDEX IF NOT EXISTS idx_relations_to ON relations(to_sig);
CREATE INDEX IF NOT EXISTS idx_acts_state ON acts(state);
"""

_ACT_COLUMNS = (
    "id_aktu", "rodzaj", "title", "status", "data_uchwalenia", "data_wejscia",
    "data_wygasniecia", "podmiot", "organ", "kategoria", "uwagi",
    "content_local_path", "attachment_count", "raw_metrics_json",
)

class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.conn.commit()
        self.close()

    def has_act(self, signature: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM acts WHERE signature = ?", (signature,))
        return cur.fetchone() is not None

    def get_state(self, signature: str) -> str | None:
        cur = self.conn.execute("SELECT state FROM acts WHERE signature = ?", (signature,))
        row = cur.fetchone()
        return row["state"] if row else None

    def upsert_act(self, signature: str, *, state: str | None = None, **fields) -> None:
        cols = {k: v for k, v in fields.items() if k in _ACT_COLUMNS and v is not None}
        cols["scraped_at"] = time.time()
        if state is not None:
            cols["state"] = state

        names = ["signature", *cols.keys()]
        placeholders = ", ".join("?" for _ in names)
        values = [signature, *cols.values()]
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols)
        sql = (
            f"INSERT INTO acts ({', '.join(names)}) VALUES ({placeholders}) "
            f"ON CONFLICT(signature) DO UPDATE SET {updates}"
        )
        self.conn.execute(sql, values)
        self.conn.commit()

    def set_state(self, signature: str, state: str) -> None:
        self.conn.execute("UPDATE acts SET state = ? WHERE signature = ?", (state, signature))
        self.conn.commit()

    def acts_needing_files(self) -> list[str]:
        cur = self.conn.execute(
            "SELECT signature FROM acts WHERE state != ? ORDER BY signature", (STATE_FILES_DONE,)
        )
        return [r["signature"] for r in cur.fetchall()]

    def upsert_attachment(self, act_signature: str, *, idx: int, filename: str,
                          display_name: str, description: str, file_url: str,
                          ext: str) -> None:
        self.conn.execute(
            """
            INSERT INTO attachments
                (act_signature, idx, filename, display_name, description, file_url, ext)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(act_signature, filename) DO UPDATE SET
                idx=excluded.idx, display_name=excluded.display_name,
                description=excluded.description, file_url=excluded.file_url,
                ext=excluded.ext
            """,
            (act_signature, idx, filename, display_name, description, file_url, ext),
        )
        self.conn.commit()

    def mark_downloaded(self, act_signature: str, filename: str, local_path: str) -> None:
        self.conn.execute(
            "UPDATE attachments SET downloaded = 1, local_path = ? "
            "WHERE act_signature = ? AND filename = ?",
            (local_path, act_signature, filename),
        )
        self.conn.commit()

    def attachments_for(self, act_signature: str) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM attachments WHERE act_signature = ? ORDER BY idx", (act_signature,)
        )
        return cur.fetchall()

    def add_relation(self, from_sig: str, to_sig: str, kind: str, source: str,
                     raw: str = "") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO relations (from_sig, to_sig, kind, source, raw) "
            "VALUES (?, ?, ?, ?, ?)",
            (from_sig, to_sig, kind, source, raw),
        )
        self.conn.commit()

    def add_relations(self, rows: Iterable[tuple[str, str, str, str, str]]) -> None:
        self.conn.executemany(
            "INSERT OR IGNORE INTO relations (from_sig, to_sig, kind, source, raw) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def all_relations(self) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT from_sig, to_sig, kind, source, raw FROM relations "
            "ORDER BY from_sig, to_sig, kind"
        )
        return cur.fetchall()

    def stats(self) -> dict[str, int]:
        c = self.conn
        return {
            "acts": c.execute("SELECT COUNT(*) FROM acts").fetchone()[0],
            "acts_files_done": c.execute(
                "SELECT COUNT(*) FROM acts WHERE state = ?", (STATE_FILES_DONE,)
            ).fetchone()[0],
            "attachments": c.execute("SELECT COUNT(*) FROM attachments").fetchone()[0],
            "attachments_downloaded": c.execute(
                "SELECT COUNT(*) FROM attachments WHERE downloaded = 1"
            ).fetchone()[0],
            "relations": c.execute("SELECT COUNT(*) FROM relations").fetchone()[0],
        }

def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)
