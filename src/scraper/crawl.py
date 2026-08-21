"""Crawl Avito search-result pages and extract listing summaries.

Search pages embed ~38 listings in __NEXT_DATA__ under
props.pageProps.componentProps.ads.ads — so one request yields 38 records
instead of 38 separate detail fetches.
"""

import json
import re
import time
import random
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

import httpx

from src.scraper.fetch import fetch

SEARCH_URL = "https://www.avito.ma/fr/maroc/voitures_d_occasion-à_vendre?o={page}"

# "200,000 km" / "113 km" / "1 500 km"  -> integer km
MILEAGE_RE = re.compile(r"([\d\s.,]+)\s*km", re.IGNORECASE)


@dataclass
class SearchListing:
    listing_id: str
    url: str
    scraped_at: str
    search_page: int

    title: str | None = None
    price_mad: int | None = None

    year: str | None = None
    mileage_km: int | None = None       # parsed from fullValue, NOT value
    mileage_text: str | None = None     # raw fullValue, kept for auditing
    transmission: str | None = None
    fuel: str | None = None

    city: str | None = None
    city_id: str | None = None
    area_id: str | None = None

    seller_type: str | None = None      # STORE | PRIVATE
    is_shop: bool | None = None
    is_premium: bool | None = None
    is_urgent: bool | None = None
    is_highlighted: bool | None = None
    is_car_checked: bool | None = None

    n_photos: int | None = None
    date_text: str | None = None
    category_id: str | None = None

    parse_errors: list[str] = field(default_factory=list)


def parse_mileage(full_value: str | None) -> int | None:
    """Avito's numeric `value` is inconsistent (sometimes thousands).
    `fullValue` is unambiguous, so parse that instead."""
    if not full_value:
        return None
    m = MILEAGE_RE.search(full_value)
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m.group(1))
    return int(digits) if digits else None


def parse_search_page(html: str, page: int) -> list[SearchListing]:
    node = None
    try:
        from selectolax.parser import HTMLParser
        node = HTMLParser(html).css_first("script#__NEXT_DATA__")
    except Exception:
        return []
    if node is None:
        return []

    try:
        data = json.loads(node.text())
        items = data["props"]["pageProps"]["componentProps"]["ads"]["ads"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return []

    now = datetime.now(timezone.utc).isoformat()
    out: list[SearchListing] = []

    for it in items:
        if not isinstance(it, dict):
            continue

        listing = SearchListing(
            listing_id=str(it.get("listId") or it.get("id") or ""),
            url=it.get("href") or "",
            scraped_at=now,
            search_page=page,
            title=it.get("subject"),
            city=it.get("location"),
            city_id=it.get("cityId"),
            area_id=it.get("areaId"),
            date_text=it.get("date"),
            is_shop=it.get("isShop"),
            is_premium=it.get("isPremium"),
            is_urgent=it.get("isUrgent"),
            is_highlighted=it.get("isHighlighted"),
            is_car_checked=it.get("isCarChecked"),
            n_photos=len(it.get("images") or []),
        )

        # price: empty dict means "prix à débattre" — expected, not an error case
        price = it.get("price") or {}
        listing.price_mad = price.get("value")
        if listing.price_mad is None:
            listing.parse_errors.append("no_price")

        # seller: type only. Name and phone are deliberately never read.
        seller = it.get("seller") or {}
        listing.seller_type = seller.get("type")

        cat = it.get("category") or {}
        listing.category_id = cat.get("id")

        for p in (it.get("params") or {}).get("secondary") or []:
            key = p.get("key")
            if key == "regdate":
                listing.year = p.get("value")
            elif key == "mileage_exact":
                listing.mileage_text = p.get("fullValue")
                listing.mileage_km = parse_mileage(p.get("fullValue"))
                if listing.mileage_km is None:
                    listing.parse_errors.append("bad_mileage")
            elif key == "bv":
                listing.transmission = p.get("value")
            elif key == "fuel":
                listing.fuel = p.get("value")

        if listing.listing_id:
            out.append(listing)

    return out


def crawl(start: int = 1, end: int = 10, client: httpx.Client | None = None):
    """Yield SearchListing objects from search pages [start, end]."""
    own_client = client is None
    client = client or httpx.Client()
    try:
        for page in range(start, end + 1):
            url = SEARCH_URL.format(page=page)
            html = fetch(url, client)
            if html is None:
                print(f"page {page}: fetch failed")
                continue
            listings = parse_search_page(html, page)
            print(f"page {page}: {len(listings)} listings")
            if not listings:
                print(f"page {page}: empty — stopping")
                break
            yield from listings
    finally:
        if own_client:
            client.close()


if __name__ == "__main__":
    import random
    from src.scraper.store import connect

    conn = connect()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS search_listings (
        listing_id     TEXT PRIMARY KEY,
        url            TEXT,
        scraped_at     TEXT,
        search_page    INTEGER,
        title          TEXT,
        price_mad      INTEGER,
        year           TEXT,
        mileage_km     INTEGER,
        mileage_text   TEXT,
        transmission   TEXT,
        fuel           TEXT,
        city           TEXT,
        city_id        TEXT,
        area_id        TEXT,
        seller_type    TEXT,
        is_shop        INTEGER,
        is_premium     INTEGER,
        is_urgent      INTEGER,
        is_highlighted INTEGER,
        is_car_checked INTEGER,
        n_photos       INTEGER,
        date_text      TEXT,
        category_id    TEXT,
        parse_errors   TEXT
    );
    """)

    random.seed(42)
    pages = random.sample(range(1, 3000), 900)

    seen = 0
    with httpx.Client() as client:
        for i, page in enumerate(pages, 1):
            html = fetch(SEARCH_URL.format(page=page), client)
            if html is None:
                print(f"[{i}/{len(pages)}] page {page}: fetch failed")
                continue

            listings = parse_search_page(html, page)
            for listing in listings:
                d = asdict(listing)
                d["parse_errors"] = json.dumps(d["parse_errors"])
                cols = ", ".join(d)
                ph = ", ".join(f":{k}" for k in d)
                conn.execute(
                    f"INSERT OR IGNORE INTO search_listings ({cols}) VALUES ({ph})", d
                )
                seen += 1
            conn.commit()

            total = conn.execute("SELECT COUNT(*) FROM search_listings").fetchone()[0]
            print(f"[{i}/{len(pages)}] page {page}: +{len(listings)} seen={seen} unique={total}")

    total = conn.execute("SELECT COUNT(*) FROM search_listings").fetchone()[0]
    priced = conn.execute(
        "SELECT COUNT(*) FROM search_listings WHERE price_mad IS NOT NULL"
    ).fetchone()[0]
    print(f"\ndone. {total} unique listings, {priced} with price")