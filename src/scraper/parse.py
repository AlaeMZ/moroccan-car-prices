"""Parse cached Avito listing HTML into structured records.

Avito is a Next.js + Apollo app: the full listing sits in a JSON blob inside
<script id="__NEXT_DATA__">, so we read that rather than scraping the DOM.
Raw values are preserved; conversion and normalisation happen in src/data/clean.py.
"""

import json
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

from selectolax.parser import HTMLParser

# Moroccan mobile/landline formats sellers paste into descriptions
PHONE_RE = re.compile(r"(?:\+212|00212|0)\s*[5-7](?:[\s.\-]*\d){8}")


def scrub(text: str | None) -> str | None:
    """Redact phone numbers from free text. Personal data never enters the dataset."""
    if not text:
        return None
    return PHONE_RE.sub("[PHONE]", text)


@dataclass
class RawListing:
    listing_id: str
    url: str
    scraped_at: str

    title: str | None = None
    description: str | None = None
    price_mad: int | None = None
    price_text: str | None = None
    

    brand: str | None = None
    model: str | None = None
    year: str | None = None
    mileage_raw: float | None = None      # Avito's value, in THOUSANDS of km
    mileage_unit: str | None = None
    fuel: str | None = None
    transmission: str | None = None
    doors: str | None = None
    fiscal_power: str | None = None
    condition: str | None = None
    origin: str | None = None
    first_owner: str | None = None

    city: str | None = None
    area: str | None = None

    seller_type: str | None = None        # STORE | PRIVATE
    seller_active_ads: int | None = None
    # NOTE: seller name/phone/profile deliberately not collected.

    is_premium: bool | None = None
    is_urgent: bool | None = None
    list_time: str | None = None
    n_photos: int | None = None
    equipment: str | None = None          # JSON list of option ids

    parse_errors: list[str] = field(default_factory=list)


def _resolve(apollo: dict, node):
    """Apollo normalises nested objects into {'__ref': 'City:12'} pointers."""
    if isinstance(node, dict) and "__ref" in node:
        return apollo.get(node["__ref"], {})
    return node


def _params_by_id(ad: dict) -> dict:
    """Flatten params.primary + params.secondary into {id: value}."""
    out = {}
    for section in ("primary", "secondary"):
        for p in ad.get("params", {}).get(section) or []:
            if not isinstance(p, dict) or "id" not in p:
                continue
            value = p.get("textValue")
            if value is None:
                value = p.get("numericValue")
            out[p["id"]] = {"value": value, "unit": p.get("unit")}
    return out


def parse_listing(html: str, url: str) -> RawListing | None:
    """Return a RawListing, or None if the page has no usable ad payload."""
    node = HTMLParser(html).css_first("script#__NEXT_DATA__")
    if node is None:
        return None

    try:
        data = json.loads(node.text())
        apollo = data["props"]["pageProps"]["apolloState"]
        root = apollo["ROOT_QUERY"]
        ad_key = next(k for k in root if "getPublishedAd" in k)
        ad = _resolve(apollo, root[ad_key]["ad"])
    except (KeyError, StopIteration, json.JSONDecodeError):
        return None

    if not ad:
        return None

    listing = RawListing(
        listing_id=str(ad.get("listId") or ad.get("adId") or ""),
        url=url,
        scraped_at=datetime.now(timezone.utc).isoformat(),
        title=ad.get("title"),
        description=scrub(ad.get("description")),
        list_time=ad.get("listTime"),
        seller_type=ad.get("sellerType"),
        is_premium=ad.get("isPremium"),
        is_urgent=ad.get("isUrgent"),
    )

    # --- price: absent for "Prix à débattre" listings, which is expected ---
    price = ad.get("price") or {}
    listing.price_mad = price.get("withoutCurrency")
    listing.price_text = price.get("withCurrency")
    if listing.price_mad is None:
        listing.parse_errors.append("no_price")

    # --- attributes ---
    p = _params_by_id(ad)

    def val(key):
        return p.get(key, {}).get("value")

    listing.brand = val("brand")
    listing.model = val("model")
    listing.year = val("regdate")
    listing.fuel = val("fuel")
    listing.transmission = val("bv")
    listing.doors = val("doors")
    listing.fiscal_power = val("pfiscale")
    listing.condition = val("auto_condition")
    listing.origin = val("v_origin")
    listing.first_owner = val("first_owner")

    # ⚠ Avito stores mileage in THOUSANDS of km (120 == 120,000 km).
    # Kept raw here; the ×1000 conversion belongs in clean.py.
    listing.mileage_raw = p.get("mileage_exact", {}).get("value")
    listing.mileage_unit = p.get("mileage_exact", {}).get("unit")
    if listing.mileage_raw is None:
        listing.parse_errors.append("no_mileage")

    # --- location ---
    loc = ad.get("location") or {}
    city = _resolve(apollo, loc.get("city") or {})
    area = _resolve(apollo, loc.get("area") or {})
    listing.city = city.get("name")
    listing.area = area.get("name")

    # --- seller: type and volume only, never identity ---
    seller = ad.get("seller") or {}
    listing.seller_active_ads = seller.get("numberOfActiveAds")

    # --- equipment options (ABS, clim, caméra...) -> feature source for week 5 ---
    extras = [e.get("id") for e in (ad.get("params", {}).get("extra") or [])
              if isinstance(e, dict) and e.get("booleanValue")]
    listing.equipment = json.dumps(extras, ensure_ascii=False) if extras else None

    # --- photo count ---
    media = ad.get("media") or {}
    images = media.get("images") or []
    listing.n_photos = len(images) if images else (1 if media.get("defaultImage") else 0)

    return listing


if __name__ == "__main__":
    import glob

    ok = 0
    for path in sorted(glob.glob("data/raw/html/*.html")):
        html = open(path, encoding="utf-8").read()
        listing = parse_listing(html, url=path)
        if listing is None:
            print(f"{path}: NOT AN AD PAGE")
            continue
        ok += 1
        d = asdict(listing)
        print(f"\n--- {path} ---")
        for k in ("listing_id", "title", "price_mad", "brand", "model", "year",
                  "mileage_raw", "fuel", "transmission", "city", "seller_type",
                  "n_photos", "parse_errors"):
            print(f"  {k:<18} {d[k]!r}")

    print(f"\nparsed {ok} listings")