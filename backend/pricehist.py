import re
import httpx
from datetime import datetime, timezone

PH = "https://pricehistory.app"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
SUPPORTED = ["amazon.in", "flipkart.com", "myntra.com", "ajio.com", "croma.com", "tatacliq.com", "nykaa.com",
             "jiomart.com", "reliancedigital.in", "meesho.com", "shopsy.in", "vijaysales.com"]


def supported(url):
    u = (url or "").lower()
    if re.search(r'amazon\.in/s\b|/search\?|/s\?k=', u):
        return False
    return any(d in u for d in SUPPORTED)


def _downsample(points, n=400):
    if len(points) <= n:
        return points
    step = len(points) / n
    out = [points[int(i * step)] for i in range(n)]
    out[-1] = points[-1]
    return out


async def lookup(url):
    """Fetch full price history for a store product link from pricehistory.app."""
    async with httpx.AsyncClient(timeout=15, headers=UA, follow_redirects=True) as c:
        r = await c.post(f"{PH}/api/search", json={"url": url})
        j = r.json()
        if not j.get("status") or not j.get("code"):
            return None
        code = j["code"]
        page = await c.get(f"{PH}/p/{code}")
        tok = re.search(r'append\("token","([a-f0-9]+)"', page.text)
        pid = re.search(r'append\("page","([A-Za-z0-9]+)"', page.text)
        if not tok or not pid:
            return None
        img = re.search(r'og:image" content="([^"]+)"', page.text)
        p = await c.post(f"{PH}/api/price/{pid.group(1)}", headers={**UA, "Content-Type": "application/json",
                         "page": pid.group(1), "token": tok.group(1), "Referer": f"{PH}/p/{code}"})
        d = p.json()
    price = d.get("Price") or {}
    hist = [{"x": h["x"].replace(" ", "T") + "+05:30", "y": h["y"]} for h in (d.get("History") or {}).get("Price", []) if h.get("y")]
    return {
        "code": code, "name": j.get("name"), "page_url": f"{PH}/p/{code}",
        "image": img.group(1) if img else None,
        "price": price.get("Price"), "mrp": price.get("MRP"),
        "min": price.get("MinPrice"), "min_on": price.get("MinPriceOn"),
        "max": price.get("MaxPrice"), "max_on": price.get("MaxPriceOn"),
        "avg": round(price["TotalPrice"] / price["Count"]) if price.get("Count") else None,
        "history": _downsample(hist),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
