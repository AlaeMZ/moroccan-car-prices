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


def load_urls(path: str = "data/raw/seed_urls.txt") -> list[str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [l.split("#")[0].strip() for l in lines
            if l.strip() and not l.strip().startswith("#")]


if __name__ == "__main__":
    urls = load_urls()
    print(f"loaded {len(urls)} urls")
    with httpx.Client() as client:
        for url in urls:
            html = fetch(url, client)
            print(f"{len(html) if html else 0:>8} chars  {url[:60]}")