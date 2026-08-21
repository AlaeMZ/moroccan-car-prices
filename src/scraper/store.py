"""Persist parsed listings to SQLite. Idempotent: re-running never duplicates."""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from src.scraper.parse import RawListing

DB_PATH = Path("data/raw/listings.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id        TEXT PRIMARY KEY,
    url               TEXT,
    scraped_at        TEXT,
    title             TEXT,
    description       TEXT,
    price_mad         INTEGER,
    price_text        TEXT,
    brand             TEXT,
    model             TEXT,
    year              TEXT,
    mileage_raw       REAL,
    mileage_unit      TEXT,
    fuel              TEXT,
    transmission      TEXT,
    doors             TEXT,
    fiscal_power      TEXT,
    condition         TEXT,
    origin            TEXT,
    first_owner       TEXT,
    city              TEXT,
    area              TEXT,
    seller_type       TEXT,
    seller_active_ads INTEGER,
    is_premium        INTEGER,
    is_urgent         INTEGER,
    list_time         TEXT,
    n_photos          INTEGER,
    equipment         TEXT,
    parse_errors      TEXT
);

CREATE TABLE IF NOT EXISTS seen_urls (
    url        TEXT PRIMARY KEY,
    discovered TEXT,
    fetched    INTEGER DEFAULT 0
);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, listing: RawListing) -> None:
    d = asdict(listing)
    d["parse_errors"] = json.dumps(d["parse_errors"])
    cols = ", ".join(d)
    placeholders = ", ".join(f":{k}" for k in d)
    conn.execute(
        f"INSERT OR REPLACE INTO listings ({cols}) VALUES ({placeholders})", d
    )


def add_urls(conn: sqlite3.Connection, urls: list[str], discovered: str) -> int:
    """Register discovered URLs. Returns how many were new."""
    before = conn.execute("SELECT COUNT(*) FROM seen_urls").fetchone()[0]
    conn.executemany(
        "INSERT OR IGNORE INTO seen_urls (url, discovered) VALUES (?, ?)",
        [(u, discovered) for u in urls],
    )
    after = conn.execute("SELECT COUNT(*) FROM seen_urls").fetchone()[0]
    return after - before


def pending_urls(conn: sqlite3.Connection, limit: int = 1000) -> list[str]:
    rows = conn.execute(
        "SELECT url FROM seen_urls WHERE fetched = 0 LIMIT ?", (limit,)
    ).fetchall()
    return [r[0] for r in rows]


def mark_fetched(conn: sqlite3.Connection, url: str) -> None:
    conn.execute("UPDATE seen_urls SET fetched = 1 WHERE url = ?", (url,))


def stats(conn: sqlite3.Connection) -> dict:
    q = lambda sql: conn.execute(sql).fetchone()[0]
    return {
        "listings": q("SELECT COUNT(*) FROM listings"),
        "with_price": q("SELECT COUNT(*) FROM listings WHERE price_mad IS NOT NULL"),
        "urls_known": q("SELECT COUNT(*) FROM seen_urls"),
        "urls_pending": q("SELECT COUNT(*) FROM seen_urls WHERE fetched = 0"),
    }


if __name__ == "__main__":
    import glob
    from src.scraper.parse import parse_listing

    conn = connect()
    n = 0
    for path in sorted(glob.glob("data/raw/html/*.html")):
        html = open(path, encoding="utf-8").read()
        listing = parse_listing(html, url=path)
        if listing and listing.listing_id:
            upsert(conn, listing)
            n += 1
    conn.commit()
    print(f"stored {n} listings")
    print(stats(conn))