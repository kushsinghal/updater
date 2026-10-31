import re
import html
import httpx
import feedparser
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')
AMOUNT_RE = re.compile(r'(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:₹|/-)', re.I)
MRP_RE = re.compile(r'(?:mrp|regular price|original price|worth|was|actual price)\s*[:@\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]+)', re.I)
PCT_RE = re.compile(r'(?:flat|upto|up to|get)?\s*(\d{1,2}(?:\.\d+)?)\s*%\s*(?:off|discount|cashback|instant|savings)', re.I)
FLAT_PCT_RE = re.compile(r'flat\s*(\d{1,2})\s*%', re.I)
SUPERCOIN_RE = re.compile(r'100\s*%\s*(?:off\s*)?(?:via|with|using|by|on|through)?\s*super\s*coins?|super\s*coins?.{0,40}100\s*%|full\s*super\s*coins?', re.I | re.S)
GIFT_RE = re.compile(r'gift\s*cards?|e-?gift|vouchers?|\bgv\b', re.I)
LOOT_RE = re.compile(r'\bloot\b|price\s*(?:error|bug|mistake|glitch)|\bbug\s*deal|glitch', re.I)

STORES = {
    "Flipkart": ["flipkart.com", "fkrt.it", "fkrt.cc", "fkrt.co", "fktr.in"],
    "Amazon": ["amazon.in", "amzn.to", "amzn.in", "amazon.com", "amzn.eu"],
    "Myntra": ["myntra.com", "myntr.it"],
    "Ajio": ["ajio.com", "ajiio.in"],
    "Meesho": ["meesho.com"],
    "Croma": ["croma.com"],
    "Tata CLiQ": ["tatacliq.com"],
    "JioMart": ["jiomart.com"],
    "Nykaa": ["nykaa.com"],
    "Xiaomi": ["mi.com"],
    "Snapdeal": ["snapdeal.com"],
    "Reliance Digital": ["reliancedigital.in"],
    "Paytm": ["paytm.com", "paytmmall.com"],
    "Swiggy": ["swiggy.com"],
    "Zomato": ["zomato.com"],
    "Woohoo": ["woohoo.in"],
    "Gyftr": ["gyftr.com"],
}
CATEGORIES = ["supercoin_100", "gift_card", "heavy_discount", "loot"]


def to_num(s):
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def detect_store(url, text=""):
    u = (url or "").lower()
    for name, domains in STORES.items():
        if any(d in u for d in domains):
            return name
    t = text.lower()
    for name in STORES:
        if name.lower() in t:
            return name
    return "Other"


def extract_prices(text):
    mrp_m = MRP_RE.search(text)
    mrp = to_num(mrp_m.group(1)) if mrp_m else None
    amounts = []
    for m in AMOUNT_RE.finditer(text):
        after = text[m.end():m.end() + 6].lower()
        if "off" in after:
            continue
        v = to_num(m.group(1) or m.group(2))
        if v and v >= 5:
            amounts.append(v)
    price = None
    for a in amounts:
        if a != mrp:
            price = a
            break
    if mrp is None and len(amounts) >= 2 and price is not None and max(amounts) > price:
        mrp = max(amounts)
    if price is None:
        m = re.search(r'(?:loot|@|\bat|price|only|just|deal)\s*:?\s*([\d,]{2,7})(?!\s*%)\b', text, re.I)
        price = to_num(m.group(1)) if m else None
    if price is not None and mrp is not None and mrp <= price:
        mrp = None
    return price, mrp


def extract_discount(text, price, mrp):
    vals = [float(m.group(1)) for m in PCT_RE.finditer(text)] + [float(m.group(1)) for m in FLAT_PCT_RE.finditer(text)]
    if price and mrp:
        vals.append(round((1 - price / mrp) * 100, 1))
    return max(vals) if vals else 0


def classify(text, discount, rules):
    cats = []
    is_gift = bool(GIFT_RE.search(text))
    if rules.get("supercoin_enabled", True) and SUPERCOIN_RE.search(text):
        cats.append("supercoin_100")
    if rules.get("giftcard_enabled", True) and is_gift and discount >= rules.get("giftcard_min", 5):
        cats.append("gift_card")
    if rules.get("product_enabled", True) and not is_gift and discount >= rules.get("product_min", 70):
        cats.append("heavy_discount")
    if rules.get("loot_enabled", True) and LOOT_RE.search(text):
        cats.append("loot")
    for kw in rules.get("keywords", []):
        if kw and kw.lower() in text.lower() and "loot" not in cats:
            cats.append("loot")
    return cats


def make_title(text):
    parts = []
    for line in text.splitlines():
        clean = re.sub(r'[^\w₹%&@.,:()\-+/ ]', '', URL_RE.sub('', line)).strip(" -:@")
        if len(clean) >= 3:
            parts.append(clean)
        if len(" ".join(parts)) >= 16:
            break
    return " · ".join(parts)[:140] or "Deal"


def parse_item(text, links, image, rules):
    def ok(l):
        return l.startswith("http") and "t.me/" not in l and not re.search(r'\.(jpe?g|png|gif|webp)(\?|$)', l, re.I)
    links = [l for l in links if ok(l)]
    links += [u for u in URL_RE.findall(text) if u not in links and ok(u)]
    if not links:
        return None
    url = next((l for l in links if detect_store(l) != "Other"), links[0])
    price, mrp = extract_prices(text)
    discount = extract_discount(text, price, mrp)
    return {
        "title": make_title(text),
        "text": text[:1500],
        "url": url,
        "store": detect_store(url, text),
        "price": price,
        "mrp": mrp,
        "discount": discount,
        "categories": classify(text, discount, rules),
        "image": image,
    }


async def fetch_telegram(username):
    username = username.strip().lstrip("@").replace("https://t.me/", "").replace("s/", "").strip("/")
    async with httpx.AsyncClient(timeout=20, headers=UA, follow_redirects=True) as c:
        r = await c.get(f"https://t.me/s/{username}")
        r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    if not soup.select("div.tgme_widget_message"):
        raise ValueError(f"@{username} is not a public channel or has no posts")
    items = []
    for m in soup.select("div.tgme_widget_message"):
        body = m.select_one(".tgme_widget_message_text")
        if not body:
            continue
        for br in body.find_all("br"):
            br.replace_with("\n")
        text = body.get_text()
        links = [a.get("href", "") for a in body.select("a")]
        img = None
        p = m.select_one(".tgme_widget_message_photo_wrap") or m.select_one(".link_preview_right_image") or m.select_one(".link_preview_image")
        if p and "url(" in (p.get("style") or ""):
            img = p["style"].split("url(")[1].split(")")[0].strip("'\"")
        t = m.select_one("time[datetime]")
        posted = None
        if t:
            from datetime import datetime, timezone
            posted = datetime.fromisoformat(t["datetime"]).astimezone(timezone.utc).isoformat()
        items.append({"ext_id": m.get("data-post"), "text": text, "links": links, "image": img, "posted_at": posted,
                      "post_url": f"https://t.me/{m.get('data-post')}" if m.get("data-post") else None})
    return items


async def fetch_rss(url):
    async with httpx.AsyncClient(timeout=20, headers=UA, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
    feed = feedparser.parse(r.text)
    items = []
    for e in feed.entries[:40]:
        summary = BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ")
        img = None
        if e.get("media_content"):
            img = e.media_content[0].get("url")
        posted = None
        if e.get("published_parsed"):
            from datetime import datetime, timezone
            posted = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        items.append({"ext_id": e.get("id") or e.get("link"), "text": f"{e.get('title', '')}\n{summary}",
                      "links": [e.get("link", "")], "image": img, "posted_at": posted, "post_url": e.get("link")})
    return items


def _rel_time(txt):
    from datetime import datetime, timezone, timedelta
    t = (txt or "").lower()
    if re.search(r'just now|less than a minute|seconds?', t):
        return datetime.now(timezone.utc).isoformat()
    m = re.search(r'(\d+|an?|one)\s*(min|minute|hr|hour|day|d\b|h\b|m\b)', t)
    if not m:
        return None
    n = 1 if m.group(1) in ("a", "an", "one") else int(m.group(1))
    unit = m.group(2)
    delta = timedelta(days=n) if unit.startswith("d") else timedelta(hours=n) if unit.startswith("h") else timedelta(minutes=n)
    return (datetime.now(timezone.utc) - delta).isoformat()


async def _get_html(url):
    async with httpx.AsyncClient(timeout=20, headers={**UA, "Accept": "text/html", "Accept-Language": "en-IN,en"},
                                 follow_redirects=True) as c:
        r = await c.get(url)
    if r.status_code == 202 or "sgcaptcha" in r.text[:2000] or "challenge-platform" in r.text[:3000] and len(r.text) < 5000:
        raise ValueError("This website blocks automatic reading (captcha). Use its Telegram channel instead.")
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


async def fetch_desidime(url):
    s = await _get_html(url)
    items = []
    for a in s.select("article.deal-card")[:30]:
        did = a.get("data-gtm-deal-id")
        img = a.select_one("img")
        title = (img.get("alt") if img else "") or a.get_text(" ", strip=True)[:120]
        buy = a.select_one('a[href*="visit.desidime.com"]')
        perm = a.get("data-permalink")
        when = next((t for t in a.stripped_strings if re.search(r'\bago\b|just now', t)), "")
        body = a.get_text(" ", strip=True)
        items.append({"ext_id": f"desidime:{did}", "text": f"{title}\n{body}", "links": [buy["href"]] if buy else [],
                      "image": img.get("src") if img else None, "posted_at": _rel_time(when),
                      "post_url": f"https://www.desidime.com/{perm}" if perm else None, "title": title})
    return items


async def fetch_dealsmagnet(url):
    s = await _get_html(url)
    items, seen = [], set()
    for b in s.select(".hotdeal"):
        a = b.select_one('a[href*="/deal/"]')
        if not a or a["href"] in seen:
            continue
        seen.add(a["href"])
        img = b.select_one("img")
        title = (b.select_one(".title").get_text(" ", strip=True) if b.select_one(".title") else (img.get("alt") if img else ""))
        price = b.select_one(".DiscountedPrice")
        mrp = b.select_one(".OriginalPrice")
        disc = b.select_one(".Discount")
        when = b.select_one(".TimeDuration")
        rib = b.select_one(".ribbon")
        text = "\n".join(filter(None, [title, f"Deal Price {price.get_text(strip=True)}" if price else "",
                                       f"MRP {mrp.get_text(strip=True)}" if mrp else "",
                                       f"{disc.get_text(' ', strip=True).replace(' off', '')} off" if disc else "",
                                       rib.get_text(" ", strip=True) if rib else ""]))
        items.append({"ext_id": "dm:" + a["href"].rsplit("-", 1)[-1], "text": text, "links": [a["href"]],
                      "image": (img.get("data-src") or img.get("src")) if img else None,
                      "posted_at": _rel_time(when.get_text(" ", strip=True) if when else ""), "post_url": a["href"], "title": title})
        if len(items) >= 40:
            break
    return items


async def fetch_web(url):
    u = url.lower()
    if "desidime.com" in u:
        return await fetch_desidime(url)
    if "dealsmagnet.com" in u:
        return await fetch_dealsmagnet("https://www.dealsmagnet.com/" if u.rstrip("/").endswith("/deal") else url)
    if "crafin.in" in u:
        await _get_html(url)
    raise ValueError("Unsupported website. Supported: desidime.com, dealsmagnet.com (others: add their Telegram or RSS feed)")


SHORT_DOMAINS = ["visit.desidime.com", "fkrt.it", "fkrt.cc", "fkrt.co", "fktr.in", "dl.flipkart.com/s/", "amzn.to", "amzn.in", "amzn.eu",
                 "myntr.it", "ajiio.in", "bit.ly", "tinyurl.com", "ekaro.in", "linkredirect.in", "extp.in", "bitli.in",
                 "cutt.ly", "wishlink.com", "inr.deals", "clnk.in", "earnkaro.com", "t.co/", "rebrand.ly", "shrsl.com", "sankmo", "ddime.in",  "fas.st", "s.click", "tiny.cc", "goo.gl", "amzn-to.co", "amznn.cc", "fkrt.to", "cuelinks.com", "/s/", "bitly", "shorturl", "redirect"]
WRAP_KEYS = ["dl", "url", "u", "link", "redirect", "redirect_url", "target", "r", "ulp"]
AFF_KEYS = {"tag", "ascsubtag", "linkcode", "linkid", "creative", "creativeasin", "camp", "affid", "affextparam1",
            "affextparam2", "affextparam3", "cmpid", "ref", "ref_", "smid", "psc", "aff_id", "affiliate_id", "subid",
            "sub_id", "clickid", "gclid", "fbclid", "_appid", "pageuniqueid", "ocid", "_refid", "_ga", "utm_source",
            "utm_medium", "ascsub", "ck", "btn_ref", "btnref", "btn_type", "btntype", "pf_rd_r", "pd_rd_r", "utm_campaign", "utm_content", "utm_term", "utm_id", "source", "campaign", "src", "srsltid"}


def _unwrap(url):
    from urllib.parse import urlparse, parse_qs
    for _ in range(3):
        m = re.search(r'.(https?://.+)$', url[8:])
        if m and detect_store(m.group(1)) != "Other":
            url = m.group(1)
        q = parse_qs(urlparse(url).query)
        inner = next((q[k][0] for k in WRAP_KEYS if k in q and q[k][0].startswith("http")), None)
        if not inner:
            break
        url = inner
    return url


def strip_affiliate(url):
    from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
    p = urlparse(url)
    if "/dealsmagnet" in p.path:
        p = p._replace(path=re.sub(r'^/dealsmagnet\.com', '', p.path).replace("/dealsmagnet/p/dealsmagnet_deals", "/product/p/item"))
    host = p.netloc.lower()
    if "amazon." in host:
        m = re.search(r'/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})', p.path)
        if m:
            return f"https://www.amazon.in/dp/{m.group(1)}"
    params = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in AFF_KEYS]
    if "flipkart." in host:
        params = [(k, v) for k, v in params if k in ("pid", "lid", "marketplace", "q", "otracker")][:3]
        params = [(k, v) for k, v in params if k != "otracker"]
    return urlunparse((p.scheme, p.netloc, p.path, "", urlencode(params), ""))


def needs_resolve(url):
    return any(d in url.lower() for d in SHORT_DOMAINS) or detect_store(url) == "Other"


async def resolve_dealsmagnet(url):
    """Dealsmagnet pages hide the store link behind a buy button; follow it."""
    async with httpx.AsyncClient(timeout=10, headers=UA, follow_redirects=True) as c:
        r = await c.get(url)
        page = str(r.url)
        m = re.search(r'data-code="([^"]+)"', r.text)
        img = re.search(r'og:image" content="([^"]+)"', r.text)
        if not m:
            return url, img.group(1) if img else None
        b = await c.get(f"https://www.dealsmagnet.com/buy?{html.unescape(m.group(1))}",
                        headers={**UA, "Referer": page}, follow_redirects=False)
        loc = b.headers.get("location") or url
    return _unwrap(loc), img.group(1) if img else None


async def fetch_og_image(url):
    try:
        async with httpx.AsyncClient(timeout=8, headers=UA, follow_redirects=True) as c:
            r = await c.get(url)
        m = re.search(r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)', r.text) or \
            re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image', r.text)
        return m.group(1) if m and m.group(1).startswith("http") else None
    except Exception:
        return None


async def clean_link(url):
    """Resolve short/affiliate links and remove other people's tracking tags."""
    url = _unwrap(url).replace("://dl.flipkart.com/dl/", "://www.flipkart.com/")
    if needs_resolve(url):
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False) as c:
                for _ in range(8):
                    r = await c.get(url)
                    loc = r.headers.get("location")
                    if r.is_redirect and loc:
                        url = _unwrap(str(httpx.URL(url).join(loc)))
                        if not needs_resolve(url):
                            break
                        continue
                    found = [u for u in URL_RE.findall(r.text) if detect_store(u) != "Other"]
                    if found:
                        url = _unwrap(found[0])
                    break
        except Exception:
            pass
    return strip_affiliate(url)


def score(deal):
    cats = deal.get("categories") or []
    s = min(deal.get("discount") or 0, 100)
    s += 120 if "supercoin_100" in cats else 0
    s += 60 if "loot" in cats else 0
    s += 30 if "gift_card" in cats else 0
    s += 15 if deal.get("store") in ("Flipkart", "Amazon") else 0
    s += 5 if deal.get("image") else 0
    return round(s, 1)


def is_amazon(url):
    return detect_store(url) == "Amazon"


def amazon_affiliate(url, tag):
    from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
    tag = (tag or "").strip()
    if not tag:
        return url
    p = urlparse(url)
    params = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() != "tag"] + [("tag", tag)]
    return urlunparse((p.scheme, p.netloc, p.path, "", urlencode(params), ""))


async def convert_link(url, settings):
    if not settings.get("convert_enabled", True):
        return url
    if is_amazon(url):
        return amazon_affiliate(url, settings.get("amazon_tag"))
    if settings.get("convert_mode", "telegram") == "telegram":
        if not settings.get("tg_session"):
            return url
        import tgconv
        return await tgconv.convert_via_bot(url, settings)
    if settings.get("convert_mode") == "sankmo_api":
        token = (settings.get("sankmo_token") or "").strip()
        if not token:
            return url
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post("https://sankmo.in/api/convertMunafaLinks", data={"text": url},
                             headers={"Authorization": f"Bearer {token}"})
        data = r.json()
        txt = (data.get("convertedText") or "") if isinstance(data, dict) else ""
        found = URL_RE.findall(txt)
        if found:
            return found[0]
        raise ValueError(f"Sankmo: {data.get('msg') or 'no converted link returned'}")
    api = (settings.get("sankmo_api_url") or "").strip()
    token = (settings.get("sankmo_token") or "").strip()
    if not api or not token:
        return url
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        if "{url}" in api:
            from urllib.parse import quote
            r = await c.get(api.replace("{url}", quote(url, safe="")).replace("{token}", token))
        else:
            r = await c.post(api, json={"url": url, "link": url, "token": token},
                             headers={"Authorization": f"Bearer {token}", "X-API-Key": token})
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError:
        found = URL_RE.findall(r.text)
        return found[0] if found else url
    for key in ["converted_url", "short_url", "shortUrl", "affiliate_url", "earn_link", "link", "url", "data", "result"]:
        v = data.get(key) if isinstance(data, dict) else None
        if isinstance(v, dict):
            v = next((x for x in v.values() if isinstance(x, str) and x.startswith("http")), None)
        if isinstance(v, str) and v.startswith("http") and v != url:
            return v
    found = URL_RE.findall(r.text)
    return next((f for f in found if f != url), url)


HEADLINES = {"supercoin_100": "🪙 100% SUPERCOIN DEAL", "gift_card": "🎁 GIFT CARD OFFER",
             "loot": "🚨 LOOT / PRICE ERROR", "heavy_discount": "🔥 HEAVY DISCOUNT"}


def inr(v):
    return f"₹{v:,.0f}" if v else None


def format_message(deal, style="simple"):
    link = deal.get("affiliate_url") or deal["url"]
    title = html.escape(deal["title"])
    if style == "simple":
        cats = deal.get("categories") or []
        prefix = ""
        if "supercoin_100" in cats and "supercoin" not in deal["title"].lower():
            prefix = "100% Supercoins Back: "
        elif "gift_card" in cats and "gift" not in deal["title"].lower():
            prefix = "Gift Card Deal: "
        lines = [f"<b>{prefix}{title}</b>"]
        if deal.get("price"):
            lines.append(f"Price: {inr(deal['price'])}" + (f" (MRP {inr(deal['mrp'])})" if deal.get("mrp") else ""))
        lines.append(link)
        return "\n".join(lines)
    head = HEADLINES.get((deal.get("categories") or ["heavy_discount"])[0], "🔥 DEAL")
    lines = [f"<b>{head}</b>", "", f"<b>{html.escape(deal['title'])}</b>"]
    price_line = []
    if deal.get("price"):
        price_line.append(f"Price: <b>{inr(deal['price'])}</b>")
    if deal.get("mrp"):
        price_line.append(f"MRP: <s>{inr(deal['mrp'])}</s>")
    if deal.get("discount"):
        price_line.append(f"<b>{deal['discount']:.0f}% OFF</b>")
    if price_line:
        lines.append(" | ".join(price_line))
    lines.append(f"Store: {html.escape(deal.get('store', ''))}")
    if deal.get("note"):
        lines += ["", html.escape(deal["note"])]
    lines += ["", f"👉 {deal.get('affiliate_url') or deal['url']}"]
    return "\n".join(lines)


async def send_telegram(token, chat_id, text, image=None, deal=None):
    deal = deal or {}
    lp = {"url": deal.get("affiliate_url") or deal.get("url"), "prefer_large_media": True, "show_above_text": True}
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if isinstance(lp["url"], str) and lp["url"].startswith("http"):
        payload["link_preview_options"] = lp
    async with httpx.AsyncClient(timeout=20) as c:
        if image:
            r = await c.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                             json={"chat_id": chat_id, "photo": image, "caption": text[:1024], "parse_mode": "HTML"})
            if r.status_code == 200:
                return r.json()
        r = await c.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram error"))
    return data


def product_key(url):
    from urllib.parse import urlparse, parse_qs
    p = urlparse(url)
    m = re.search(r'/dp/([A-Z0-9]{10})', p.path)
    if m:
        return f"amazon:{m.group(1)}"
    q = parse_qs(p.query)
    if "flipkart." in p.netloc and q.get("pid"):
        return f"flipkart:{q['pid'][0]}"
    m = re.search(r'/(itm[a-z0-9]+)', p.path)
    if m:
        return f"flipkart:{m.group(1)}"
    return f"{p.netloc}{p.path}?{p.query}".lower().rstrip("/?")


def compare_links(title):
    from urllib.parse import quote_plus
    words = re.sub(r'(?i)\b(loot|deal|deals|offer|price error|bug|off|flat|upto|up to|back|supercoins?|on|at)\b|\d+\s*%|₹\s*[\d,]+|[^\w\s]', ' ', title)
    words = " ".join(words.split())[:80]
    q = quote_plus(words)
    slug = "-".join(words.lower().split())
    return [
        {"name": "Amazon", "url": f"https://www.amazon.in/s?k={q}"},
        {"name": "Flipkart", "url": f"https://www.flipkart.com/search?q={q}"},
        {"name": "Myntra", "url": f"https://www.myntra.com/{slug}"},
        {"name": "Croma", "url": f"https://www.croma.com/searchB?q={q}"},
        {"name": "Google Shopping", "url": f"https://www.google.com/search?tbm=shop&q={q}"},
        {"name": "PriceHistory", "url": f"https://pricehistory.app/search?q={q}"},
    ]
