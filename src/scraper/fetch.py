import hashlib, time, random
from pathlib import Path
import httpx

RAW = Path("data/raw/html")
RAW.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "student-research-project/0.1 (portfolio project)"}

def _cache_path(url: str) -> Path:
    return RAW / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}.html"

def fetch(url: str, client: httpx.Client) -> str | None:
    cache = _cache_path(url)
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    try:
        r = client.get(url, timeout=20, headers=HEADERS, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        print(f"failed {url}: {e}")
        return None
    cache.write_text(r.text, encoding="utf-8")
    time.sleep(random.uniform(2.0, 3.5))
    return r.text

if __name__ == "__main__":
    with httpx.Client() as client:
        html = fetch("https://www.avito.ma/fr/a%C3%AFn_borja/voitures_d_occasion/BMW_S%C3%A9rie_3_Sport_2017_58479126.htm", client)
        print(f"got {len(html) if html else 0} chars")