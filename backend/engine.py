import re
import html
import httpx
import feedparser
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')
AMOUNT_RE = re.compile(r'(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:₹|/-)', re.I)
MRP_RE = re.compile(r'(?:mrp|regular price|original price|worth|\bwas\b|actual price)\s*[:@\-]?\s*(?:₹|rs\.?|inr)?\s*([\d,]*\d)(\s*k\b)?', re.I)
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
    "Shopsy": ["shopsy.in"],
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
SANKMO_DEFAULT = ["Flipkart", "Myntra", "Ajio", "Shopsy", "Meesho", "Croma", "Tata CLiQ", "JioMart", "Nykaa", "Xiaomi",
                  "Snapdeal", "Reliance Digital"]
CATEGORIES = ["supercoin_100", "gift_card", "heavy_discount", "loot", "gold"]
GOLD_RE = re.compile(
    r'\b(?:gold|silver)\b[^\n]{0,40}?\b(?:coins?|bars?|pendants?|jewell?ery|chains?|rings?|earrings?|bangles?|gms?|grams?|24\s*k\w*|22\s*k\w*|999|916|hallmark\w*|bis)\b'
    r'|\b(?:coins?|bars?|pendants?|jewell?ery)\b[^\n]{0,25}?\b(?:gold|silver)\b'
    r'|\b(?:24|22|18)\s*(?:k|kt|karat|carat)\b|digital\s*gold'
    r'|\b(?:mmtc|augmont|tanishq|caratlane|kalyan\s*jewell\w*|malabar\s*gold|joyalukkas|senco|safegold)\b', re.I)
GOLD_NOT = re.compile(r'nescafe|coffee|\btea\b|\bdial\b|plated|rose\s*gold|gold\s*tone|golden|membership|prime|gold\s*card|contest|\bwin\b|gold\s*(?:pass|plan|member)', re.I)


def is_gold(text):
    for line in text.splitlines():
        if GOLD_RE.search(line) and not GOLD_NOT.search(line):
            return True
    return False


BANKS = ["HDFC", "SBI", "ICICI", "Axis", "Kotak", "IDFC", "OneCard", "BOB", "Bank of Baroda", "RBL", "HSBC", "Yes Bank", "AU",
         "Federal", "IndusInd", "Citi", "AMEX", "American Express", "Standard Chartered", "Flipkart Axis", "Amazon Pay ICICI",
         "Canara", "PNB", "Union Bank", "BOI", "DBS", "Paytm", "UPI", "Super.money", "Cred", "Mobikwik", "Amazon Pay", "PhonePe"]
CAP_RE = re.compile(r'(?:up\s*to|upto|max(?:imum)?)(?:\s*(?:discount|cashback|off|of|benefit|savings?))*\s*(?:₹|rs\.?|inr)\s*([\d,]*\d)', re.I)
BANK_NAMES = {b.lower(): b for b in BANKS}
WALLETS = {"UPI", "Paytm", "Cred", "Mobikwik", "Amazon Pay", "PhonePe", "Super.money"}
BANK_RE = re.compile(r'\b(' + "|".join(re.escape(b) for b in sorted(BANKS, key=len, reverse=True)) + r')\b', re.I)
CARD_RE = re.compile(r'\b(credit\s*card|debit\s*card|cc|dc|emi|card|upi|wallet)\b', re.I)
OFF_AMT_RE = re.compile(r'(?:₹|rs\.?|inr)\s*([\d,]*\d)|([\d,]*\d)\s*(?:₹|rs\b|/-)|(\d{1,2}(?:\.\d+)?)\s*%', re.I)
COINS_RE = re.compile(r'([\d,]*\d)\s*super\s*coins?|super\s*coins?[^\n\d]{0,20}([\d,]*\d)\b(?!\s*%)', re.I)
CODE_RE = re.compile(r'\b(?:code|coupon\s*code)\s*[:\-]?\s*([A-Z0-9]{4,20})\b')


def _amount_label(line, near=None):
    ms = list(OFF_AMT_RE.finditer(line))
    if not ms:
        return None, ""
    m = ms[0]
    if near:
        i = line.lower().find(near)
        before = [x for x in ms if x.start() < i] if i >= 0 else []
        m = before[-1] if before else min(ms, key=lambda x: abs(x.start() - i)) if i >= 0 else ms[0]
    if m.group(3):
        return float(m.group(3)), f"{m.group(3).rstrip('0').rstrip('.') if '.' in m.group(3) else m.group(3)}%"
    v = to_num(m.group(1) or m.group(2))
    return v, f"₹{v:,.0f}" if v else ""


def extract_offers(text):
    """Bank/card, coupon, cashback and SuperCoin offers written in a deal post."""
    offers, seen = [], set()
    if SUPERCOIN_RE.search(text):
        offers.append({"kind": "supercoin", "label": "100% SuperCoins back — almost FREE"})
        seen.add("supercoin")
    for raw in INVISIBLE.sub("", text).splitlines():
        line = URL_RE.sub("", raw).strip(" •*-–>✅❌👉🔥💳🏦")
        if not line or len(line) > 160:
            continue
        if re.search(r"\bemi\b|no[\s-]*cost|instal+ment", line, re.I) and not re.search(r"incl|\+\s*emi|&\s*emi|and\s*emi|non[\s-]*emi|full\s*(?:swipe|payment)", line, re.I):
            continue
        bank = BANK_RE.search(line)
        low = line.lower()
        amt, amt_txt = _amount_label(line)
        if bank and not GIFT_RE.search(line) and (CARD_RE.search(line) or "off" in low or "discount" in low or "cashback" in low) and amt:
            name = BANK_NAMES.get(bank.group(1).lower(), bank.group(1))
            card = CARD_RE.search(line)
            ctype = {"cc": "Credit Card", "dc": "Debit Card"}.get(card.group(1).lower(), card.group(1).title()) if card else "Card"
            verb = "cashback" if "cashback" in low else "off"
            label = f"{amt_txt} {verb} via {name}" if name in WALLETS else f"{amt_txt} {verb} with {name} {ctype}".replace("Card Card", "Card")
            cap_m = CAP_RE.search(line)
            cap = to_num(cap_m.group(1)) if cap_m and amt_txt.endswith("%") else None
            if cap:
                label += f" (up to ₹{cap:,.0f})"
            key = f"bank:{name.lower()}:{amt}"
            if key not in seen:
                seen.add(key)
                offers.append({"kind": "bank", "label": label, "amount": amt, "wallet": name in WALLETS, **({"cap": cap} if cap else {})})
        elif "coupon" in low and amt:
            amt, amt_txt = _amount_label(line, "coupon")
            code = CODE_RE.search(raw)
            key = f"coupon:{amt}"
            if key not in seen:
                seen.add(key)
                offers.append({"kind": "coupon", "label": f"{amt_txt} coupon" + (f" (code {code.group(1)})" if code else ""), "amount": amt})
        elif "cashback" in low and amt:
            key = f"cashback:{amt}"
            if key not in seen:
                seen.add(key)
                offers.append({"kind": "cashback", "label": f"{amt_txt} cashback" + (f" via {bank.group(1)}" if bank else ""), "amount": amt})
        elif "supercoin" not in seen and re.search(r"super\s*coins?", line, re.I):
            m = COINS_RE.search(line)
            n = m and (m.group(1) or m.group(2))
            seen.add("supercoin")
            offers.append({"kind": "supercoin", "label": f"Use {n} SuperCoins" if n else "Extra savings with SuperCoins"})
    return offers[:6]


def mark_best_card(offers, price):
    """Flag the bank/card offer that saves the most on full payment."""
    def saving(o):
        a = o.get("amount") or 0
        if "%" in o["label"].split(" ")[0]:
            v = price * a / 100 if price else 0
            return min(v, o["cap"]) if o.get("cap") else v
        return a
    banks = [o for o in offers if o["kind"] == "bank"]
    for o in banks:
        o.pop("best", None)
    if banks:
        top = max(banks, key=saving)
        top["best"] = True
        s = saving(top)
        if s:
            top["saving"] = round(s)
    return offers


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


NUM = r'(?:₹|rs\.?|inr)?\s*([\d,]*\d(?:\.\d+)?)(\s*k\b)?'
STRONG_RE = re.compile(r'(?:offer\s*price|deal\s*price|effective(?:ly)?(?:\s*price)?(?:\s*will\s*be)?(?:\s*around)?|price\s*[:\-]|@)\s*[:\-]?\s*' + NUM, re.I)
WEAK_RE = re.compile(r'(?:\bat|\bonly|\bjust|\bstarts?(?:\s*from)?|\bfrom|\bloot|\bfor)\s*[:\-@]?\s*' + NUM, re.I)
BARE_RE = re.compile(r'(?:₹|rs\.?|inr)\s*([\d,]*\d(?:\.\d+)?)(\s*k\b)?|([\d,]*\d)\s*(?:₹|/-)()', re.I)
NOISE_LINE = re.compile(r'coupon|cashback|\bbank\b|hdfc|sbi|icici|axis|kotak|\bcc\b|credit|debit|\bemi\b|\bcode\b|exchange\s*(?:offer|bonus)|above|min\.?\s*order|up\s*to|upto|\bflat\b|\bsave\b|voucher|cred\b|perk', re.I)
AFTER_BAD = re.compile(r'^\s*(?:%|off\b|cashback|coupon|discount|back\b|instant|extra|super\s*coins?|gm\b|grams?\b|g\b|kg\b|ml\b|l\b|ltr|litre|hp\b|w\b|watt|cm\b|mm\b|gb\b|tb\b|mah|inch|°|pcs|pieces|days?\b|months?\b|years?\b|x\b)', re.I)
INVISIBLE = re.compile(r'[\u200b-\u200f\u202a-\u202e\u2060\ufeff]')


def _amounts(regex, text, check_noise):
    out = []
    for line in text.splitlines():
        if check_noise and NOISE_LINE.search(line):
            continue
        for m in regex.finditer(line):
            if AFTER_BAD.match(line[m.end():]):
                continue
            raw = m.group(1) or (m.group(3) if m.lastindex and m.lastindex >= 3 else None)
            v = to_num(raw)
            if v and m.group(2):
                v *= 1000
            if v and 5 <= v <= 5_000_000:
                out.append(v)
    return out


def extract_prices(text):
    text = INVISIBLE.sub("", text)
    mrp_m = MRP_RE.search(text)
    mrp = to_num(mrp_m.group(1)) if mrp_m else None
    if mrp and mrp_m.group(2):
        mrp *= 1000
    text = MRP_RE.sub(" ", text)
    price = None
    for regex, noisy in ((STRONG_RE, False), (WEAK_RE, True), (BARE_RE, True)):
        found = [a for a in _amounts(regex, text, noisy) if a != mrp]
        if found:
            price = found[0]
            break
    if price is not None and mrp is not None and mrp <= price * 1.02:
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
    if rules.get("gold_enabled", True) and is_gold(text):
        cats.append("gold")
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
        return l.startswith("http") and "t.me/" not in l and not re.search(r'\.(jpe?g|png|gif|webp|js|css|svg)(\?|/|$)|/raw/upload/|dash-front-assets', l, re.I)
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
                    visit = re.findall(r'https://visit\.desidime\.com/visit/[^"\'\s<>]+', r.text)
                    if not found and visit and "desidime.com" in url:
                        url = next((v for v in visit if "buy-now" in v), None) or next((v for v in visit if "/deals-" in v), visit[0])
                        continue
                    if found:
                        url = _unwrap(found[0])
                    break
        except Exception:
            pass
    return strip_affiliate(url)


DEAL_SITES = ["desidime.com", "ddime.in", "dealsmagnet.com", "dealsheaven.in", "coolztricks.com", "freekaamaal.com",
              "t.me/", "telegram.me", "lootdeals", "dealzarena", "indiafreestuff"]


def is_deal_site(url):
    return any(d in (url or "").lower() for d in DEAL_SITES)


def score(deal):
    cats = deal.get("categories") or []
    s = min(deal.get("discount") or 0, 100)
    s += 120 if "supercoin_100" in cats else 0
    s += 60 if "loot" in cats else 0
    s += 30 if "gift_card" in cats else 0
    s += 15 if deal.get("store") in ("Flipkart", "Amazon") else 0
    s += 5 if deal.get("image") else 0
    return round(s, 1)


def clean_title(t):
    t = re.sub(r"[\s\-–,|]+(?:for|with|and|by|of|in|-)?\s*$", "", (t or "").strip(), flags=re.I)
    return t or None


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
    if not settings.get("convert_enabled", True) or is_deal_site(url):
        return url
    if is_amazon(url):
        return amazon_affiliate(url, settings.get("amazon_tag"))
    allowed = settings.get("sankmo_stores") or SANKMO_DEFAULT
    if detect_store(url) not in allowed:
        return url
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
             "loot": "🚨 LOOT / PRICE ERROR", "heavy_discount": "🔥 HEAVY DISCOUNT", "gold": "🪙 GOLD & SILVER DEAL"}


def inr(v):
    return f"₹{v:,.0f}" if v else None


OFFER_ICONS = {"bank": "💳", "coupon": "🎟️", "supercoin": "🪙", "cashback": "💰"}


def offer_lines(deal):
    out = []
    sp, p = deal.get("store_price"), deal.get("price")
    if sp and p and sp > p:
        out.append(f"🏷️ Store {inr(sp)} → you pay {inr(p)}")
    for o in deal.get("offers") or []:
        if o["kind"] == "supercoin" and "supercoin" in deal["title"].lower() and "100%" in o["label"]:
            continue
        out.append(f"{OFFER_ICONS.get(o['kind'], '•')} {html.escape(o['label'])}")
    return out


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
        elif "gold" in cats and not re.search(r"gold|silver", deal["title"], re.I):
            prefix = "Gold Deal: "
        lines = [f"<b>{prefix}{title}</b>"]
        if deal.get("price"):
            lines.append(f"Price: {inr(deal['price'])}" + (f" (MRP {inr(deal['mrp'])})" if deal.get("mrp") else ""))
        lines += offer_lines(deal)
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
    lines += offer_lines(deal)
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
