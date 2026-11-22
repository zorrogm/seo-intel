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
  redirect_kind TEXT NOT NULL DEFAULT '',
  body_hash TEXT NOT NULL DEFAULT '',
  body BLOB,
  truncated INTEGER NOT NULL DEFAULT 0,
  rendered_body BLOB,
  render_hash TEXT NOT NULL DEFAULT '',
  fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS robots(
  origin TEXT PRIMARY KEY,
  status INTEGER NOT NULL,
  body BLOB
);
CREATE TABLE IF NOT EXISTS parsed(
  url_id INTEGER PRIMARY KEY REFERENCES urls(id),
  body_hash TEXT NOT NULL,
  data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS traps(
  site TEXT NOT NULL,
  kind TEXT NOT NULL,
  pattern TEXT NOT NULL,
  example TEXT NOT NULL,
  blocked INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(site, kind, pattern)
);
CREATE TABLE IF NOT EXISTS changes(
  run INTEGER NOT NULL,
  site TEXT NOT NULL,
  url TEXT NOT NULL,
  kind TEXT NOT NULL,
  old TEXT NOT NULL DEFAULT '',
  new TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(run, url, kind)
);
CREATE TABLE IF NOT EXISTS renders(
  url_id INTEGER PRIMARY KEY REFERENCES urls(id),
  reason TEXT NOT NULL,
  raw_words INTEGER NOT NULL,
  rendered_words INTEGER NOT NULL,
  differs INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS live_checks(
  url TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  checked_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

Job = Tuple[int, str, int]
_ADDED_COLUMNS = (
    ("redirect_kind", "TEXT NOT NULL DEFAULT ''"),
    ("rendered_body", "BLOB"),
    ("render_hash", "TEXT NOT NULL DEFAULT ''"),
)


class Store:
    def __init__(self, path: Path, max_urls_per_site: int):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), isolation_level=None)
        # WAL keeps committed work after a kill
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(_SCHEMA)
        # Older stores gain the newer columns
        have = {row[1] for row in self.db.execute("PRAGMA table_info(pages)")}
        for name, kind in _ADDED_COLUMNS:
            if name not in have:
                self.db.execute(f"ALTER TABLE pages ADD COLUMN {name} {kind}")
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

    def take(self, site: str, limit: int, busy: Iterable[int], min_id: int = 0) -> List[Job]:
        """Next queued URLs, shallowest first."""
        busy = list(busy)
        marks = ",".join("?" * len(busy))
        rows = self.db.execute(
            f"SELECT id, url, depth FROM urls WHERE site=? AND state=? AND id>=? "
            f"AND id NOT IN ({marks}) ORDER BY depth, id LIMIT ?",
            (site, QUEUED, min_id, *busy, limit),
        )
        return rows.fetchall()

    def mark(self, url_id: int, state: str) -> None:
        self.db.execute("UPDATE urls SET state=? WHERE id=?", (state, url_id))

    def save_fetch(self, job: Job, site: str, result, new_urls: Iterable[str],
                   redirect_kind: str = "") -> None:
        """Save the page and its links together."""
        url_id, _url, depth = job
        body = result.body
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute(
            "INSERT OR REPLACE INTO pages(url_id, status, error, content_type, etag,"
            " last_modified, x_robots_tag, redirect_to, redirect_kind, body_hash, body,"
            " truncated, fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                url_id,
                result.status,
                result.error,
                result.header("content-type"),
                result.header("etag"),
                result.header("last-modified"),
                result.header("x-robots-tag"),
                result.location,
                redirect_kind,
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
        """Rendered HTML when we have it, else raw."""
        row = self.db.execute(
            "SELECT COALESCE(rendered_body, body) FROM pages WHERE url_id=?", (url_id,)
        ).fetchone()
        return zlib.decompress(row[0]) if row and row[0] else b""

    def raw_body(self, url_id: int) -> bytes:
        row = self.db.execute("SELECT body FROM pages WHERE url_id=?", (url_id,)).fetchone()
        return zlib.decompress(row[0]) if row and row[0] else b""

    def save_render(self, url_id: int, html: bytes, reason: str, raw_words: int,
                    rendered_words: int, differs: bool) -> None:
        """Record a render; keep its HTML if it differs."""
        self.db.execute("BEGIN IMMEDIATE")
        if differs:
            self.db.execute(
                "UPDATE pages SET rendered_body=?, render_hash=? WHERE url_id=?",
                (zlib.compress(html, 6), hashlib.sha256(html).hexdigest(), url_id),
            )
        self.db.execute(
            "INSERT OR REPLACE INTO renders(url_id, reason, raw_words, rendered_words, differs)"
            " VALUES(?,?,?,?,?)", (url_id, reason, raw_words, rendered_words, int(differs)),
        )
        self.db.execute("COMMIT")

    def flag_render(self, url_id: int, reason: str, raw_words: int) -> None:
        """Needs rendering, but the budget ran out."""
        self.db.execute(
            "INSERT OR IGNORE INTO renders(url_id, reason, raw_words, rendered_words, differs)"
            " VALUES(?,?,?,-1,1)", (url_id, reason, raw_words),
        )

    def renders(self, site: str) -> List[Tuple]:
        return self.db.execute(
            "SELECT u.url, r.reason, r.raw_words, r.rendered_words, r.differs FROM renders r"
            " JOIN urls u ON u.id = r.url_id WHERE u.site=? ORDER BY u.url", (site,)
        ).fetchall()

    def fetched_rows(self, site: str) -> List[Tuple]:
        """Every fetched page of a site, by URL."""
        return self.db.execute(
            "SELECT u.id, u.url, p.status, p.redirect_to, p.x_robots_tag,"
            " CASE WHEN p.render_hash != '' THEN p.render_hash ELSE p.body_hash END,"
            " p.redirect_kind"
            " FROM urls u JOIN pages p ON p.url_id = u.id WHERE u.site=? ORDER BY u.url",
            (site,),
        ).fetchall()

    def get_parsed(self, url_id: int, body_hash: str) -> Optional[bytes]:
        row = self.db.execute(
            "SELECT data FROM parsed WHERE url_id=? AND body_hash=?", (url_id, body_hash)
        ).fetchone()
        return zlib.decompress(row[0]) if row else None

    def save_parsed(self, url_id: int, body_hash: str, data: bytes) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO parsed(url_id, body_hash, data) VALUES(?,?,?)",
            (url_id, body_hash, zlib.compress(data, 6)),
        )

    def url_id(self, url: str) -> Optional[int]:
        row = self.db.execute("SELECT id FROM urls WHERE url=?", (url,)).fetchone()
        return row[0] if row else None

    def site_urls(self, site: str) -> List[str]:
        rows = self.db.execute("SELECT url FROM urls WHERE site=? ORDER BY id", (site,))
        return [row[0] for row in rows]

    def max_id(self) -> int:
        return self.db.execute("SELECT COALESCE(MAX(id), 0) FROM urls").fetchone()[0]

    def add_trap(self, site: str, kind: str, pattern: str, example: str) -> None:
        self.db.execute(
            "INSERT INTO traps(site, kind, pattern, example) VALUES(?,?,?,?)"
            " ON CONFLICT(site, kind, pattern) DO UPDATE SET blocked = blocked + 1",
            (site, kind, pattern, example),
        )

    def traps(self, site: str) -> List[Tuple]:
        return self.db.execute(
            "SELECT kind, pattern, example, blocked FROM traps WHERE site=?"
            " ORDER BY kind, pattern", (site,)
        ).fetchall()

    def revalidation_rows(self, site: str) -> List[Tuple]:
        """Fetched pages, most important first."""
        return self.db.execute(
            "SELECT u.id, u.url, u.depth, p.status, p.etag, p.last_modified, p.body_hash,"
            " p.redirect_to FROM urls u JOIN pages p ON p.url_id = u.id"
            " WHERE u.site=? ORDER BY u.depth, u.url", (site,)
        ).fetchall()

    def add_change(self, run: int, site: str, url: str, kind: str, old: str = "",
                   new: str = "") -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO changes(run, site, url, kind, old, new) VALUES(?,?,?,?,?,?)",
            (run, site, url, kind, old, new),
        )

    def changes(self, run: int) -> List[Tuple]:
        return self.db.execute(
            "SELECT site, url, kind, old, new FROM changes WHERE run=? ORDER BY site, kind, url",
            (run,),
        ).fetchall()

    def save_live(self, url: str, data: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO live_checks(url, data, checked_at) VALUES(?,?,?)",
            (url, data, time.time()),
        )

    def recent_live(self, max_age_seconds: float) -> List[Tuple[str, str]]:
        return self.db.execute(
            "SELECT url, data FROM live_checks WHERE checked_at >= ? ORDER BY url",
            (time.time() - max_age_seconds,),
        ).fetchall()
