"""SQLite crawl store. Every write is one transaction."""
from __future__ import annotations

import hashlib
import sqlite3
import time
import zlib
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

QUEUED = "queued"
FETCHED = "fetched"
BLOCKED = "blocked"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS urls(
  id INTEGER PRIMARY KEY,
  site TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  depth INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'queued',
  source_id INTEGER
);
CREATE INDEX IF NOT EXISTS urls_frontier ON urls(site, state, depth, id);
CREATE TABLE IF NOT EXISTS pages(
  url_id INTEGER PRIMARY KEY REFERENCES urls(id),
  status INTEGER NOT NULL,
  error TEXT NOT NULL DEFAULT '',
  content_type TEXT NOT NULL DEFAULT '',
  etag TEXT NOT NULL DEFAULT '',
  last_modified TEXT NOT NULL DEFAULT '',
  x_robots_tag TEXT NOT NULL DEFAULT '',
  redirect_to TEXT NOT NULL DEFAULT '',
  body_hash TEXT NOT NULL DEFAULT '',
  body BLOB,
  truncated INTEGER NOT NULL DEFAULT 0,
  fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS robots(
  origin TEXT PRIMARY KEY,
  status INTEGER NOT NULL,
  body BLOB
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

Job = Tuple[int, str, int]


class Store:
    def __init__(self, path: Path, max_urls_per_site: int):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), isolation_level=None)
        # WAL keeps committed work after a kill
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(_SCHEMA)
        self.max_urls_per_site = max_urls_per_site

    def close(self) -> None:
        self.db.close()

    def _insert_urls(self, site: str, urls: Iterable[str], depth: int, source_id) -> int:
        room = self.max_urls_per_site - self.count(site)
        added = 0
        for url in urls:
            if room <= 0:
                break
            cur = self.db.execute(
                "INSERT OR IGNORE INTO urls(site, url, depth, source_id) VALUES(?,?,?,?)",
                (site, url, depth, source_id),
            )
            added += cur.rowcount
            room -= cur.rowcount
        return added

    def add_urls(self, site: str, urls: Iterable[str], depth: int) -> int:
        self.db.execute("BEGIN IMMEDIATE")
        added = self._insert_urls(site, urls, depth, None)
        self.db.execute("COMMIT")
        return added

    def take(self, site: str, limit: int, busy: Iterable[int]) -> List[Job]:
        """Next queued URLs, shallowest first."""
        busy = list(busy)
        marks = ",".join("?" * len(busy))
        rows = self.db.execute(
            f"SELECT id, url, depth FROM urls WHERE site=? AND state=? "
            f"AND id NOT IN ({marks}) ORDER BY depth, id LIMIT ?",
            (site, QUEUED, *busy, limit),
        )
        return rows.fetchall()

    def mark(self, url_id: int, state: str) -> None:
        self.db.execute("UPDATE urls SET state=? WHERE id=?", (state, url_id))

    def save_fetch(self, job: Job, site: str, result, new_urls: Iterable[str]) -> None:
        """Save the page and its links together."""
        url_id, _url, depth = job
        body = result.body
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute(
            "INSERT OR REPLACE INTO pages(url_id, status, error, content_type, etag,"
            " last_modified, x_robots_tag, redirect_to, body_hash, body, truncated,"
            " fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                url_id,
                result.status,
                result.error,
                result.header("content-type"),
                result.header("etag"),
                result.header("last-modified"),
                result.header("x-robots-tag"),
                result.location,
                hashlib.sha256(body).hexdigest() if body else "",
                zlib.compress(body, 6) if body else None,
                int(result.truncated),
                time.time(),
            ),
        )
        self._insert_urls(site, new_urls, depth + 1, url_id)
        self.db.execute("UPDATE urls SET state=? WHERE id=?", (FETCHED, url_id))
        self.db.execute("COMMIT")

    def save_robots(self, origin: str, status: int, body: bytes) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO robots(origin, status, body) VALUES(?,?,?)",
            (origin, status, body),
        )

    def count(self, site: str, state: Optional[str] = None) -> int:
        if state is None:
            row = self.db.execute("SELECT COUNT(*) FROM urls WHERE site=?", (site,))
        else:
            row = self.db.execute(
                "SELECT COUNT(*) FROM urls WHERE site=? AND state=?", (site, state)
            )
        return row.fetchone()[0]

    def get_meta(self, key: str) -> Optional[str]:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, value))

    def body(self, url_id: int) -> bytes:
        row = self.db.execute("SELECT body FROM pages WHERE url_id=?", (url_id,)).fetchone()
        return zlib.decompress(row[0]) if row and row[0] else b""
