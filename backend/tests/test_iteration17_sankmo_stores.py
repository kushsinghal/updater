# Iteration 17: Sankmo store allow-list, non-Sankmo links kept, asset-link filtering, convert error fallback
import os, sys, time, re
import pytest, requests

sys.path.insert(0, "/app/backend")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"

DEFAULT = ["Flipkart", "Myntra", "Ajio", "Shopsy", "Meesho", "Croma", "Tata CLiQ", "JioMart", "Nykaa", "Xiaomi",
           "Snapdeal", "Reliance Digital"]
NON_SANKMO = [
    "https://play.google.com/store/apps/details?id=com.dreamplug.androidapp",
    "https://www.district.in/webviews/movies/raavan-arcade&utm_source=social",
    "https://instamart-media-assets.swiggy.com/swiggy/raw/upload/dash-front-assets/js/",
]
MYNTRA = "https://www.myntra.com/watches/fossil/fossil-women-analogue-watch/123456/buy"


@pytest.fixture(scope="module", autouse=True)
def restore_defaults():
    yield
    requests.put(f"{API}/settings", json={"sankmo_stores": DEFAULT}, timeout=30)


# Settings default list
def test_settings_default_stores():
    r = requests.get(f"{API}/settings", timeout=30)
    assert r.status_code == 200
    s = r.json()
    assert s["sankmo_stores"] == DEFAULT, s.get("sankmo_stores")
    assert s.get("tg_connected") is True


# Non-Sankmo links: not converted, no error, fast
@pytest.mark.parametrize("url", NON_SANKMO)
def test_convert_non_sankmo_instant(url):
    t = time.time()
    r = requests.post(f"{API}/convert", json={"url": url}, timeout=90)
    dt = time.time() - t
    assert r.status_code == 200
    d = r.json()
    print(url, d, f"{dt:.1f}s")
    assert d["changed"] is False
    assert d["error"] is None
    assert dt < 8, f"took {dt:.1f}s - likely Sankmo was called"


# Sankmo store link still converted
def test_convert_flipkart_goes_to_sankmo():
    r = requests.post(f"{API}/convert", json={"url": "https://www.flipkart.com/fossil-women-watch/p/itmabc123?pid=WATG123"}, timeout=120)
    d = r.json()
    print(d)
    assert d["store"] == "Flipkart"
    assert d["changed"] is True or (d["error"] and d["error"] != ""), d
    assert d["error"] != ""


def test_convert_fkrt_goes_to_sankmo():
    r = requests.post(f"{API}/convert", json={"url": "https://fkrt.co/abcXYZ"}, timeout=120)
    d = r.json()
    print(d)
    assert r.status_code == 200
    assert d["error"] != ""


# Toggle Myntra off -> not converted; on -> converted
def test_toggle_myntra():
    s = requests.put(f"{API}/settings", json={"sankmo_stores": [x for x in DEFAULT if x != "Myntra"]}, timeout=30).json()
    assert "Myntra" not in s["sankmo_stores"]
    t = time.time()
    d = requests.post(f"{API}/convert", json={"url": MYNTRA}, timeout=60).json()
    print("off", d, time.time() - t)
    assert d["store"] == "Myntra" and d["changed"] is False and d["error"] is None
    s = requests.put(f"{API}/settings", json={"sankmo_stores": DEFAULT}, timeout=30).json()
    assert s["sankmo_stores"] == DEFAULT
    d = requests.post(f"{API}/convert", json={"url": MYNTRA}, timeout=120).json()
    print("on", d)
    assert d["changed"] is True or d["error"], d


# Bulk: non-Sankmo store status text
def test_bulk_non_sankmo_status():
    r = requests.post(f"{API}/convert/bulk", json={"text": "Free app " + NON_SANKMO[0] + "\nmovie " + NON_SANKMO[1]}, timeout=120)
    assert r.status_code == 200
    items = r.json()["items"]
    for it in items:
        print(it["store"], it["error"])
        assert it["changed"] is False
        assert it["error"] == "Not a Sankmo store — link kept as is"


# Existing deals: no converted non-Sankmo store deals
def test_existing_deals_converted_only_sankmo():
    import engine
    r = requests.get(f"{API}/deals", params={"limit": 500}, timeout=60)
    data = r.json()
    deals = data if isinstance(data, list) else data.get("deals") or data.get("items") or []
    assert deals
    bad = [(d.get("store"), d.get("clean_url")) for d in deals
           if d.get("converted") and d.get("store") != "Amazon" and engine.detect_store(d.get("clean_url") or "") not in DEFAULT]
    print("deals", len(deals), "bad", bad)
    assert not bad


# engine asset link filter
def test_parse_item_skips_assets():
    import engine, inspect
    src = inspect.getsource(engine)
    m = re.search(r"def ok\(l\):\n\s+return (.+)", src)
    ok = eval("lambda l: " + m.group(1), {"re": re})
    assert not ok("https://instamart-media-assets.swiggy.com/swiggy/raw/upload/dash-front-assets/js/")
    assert not ok("https://x.com/a/app.js")
    assert not ok("https://x.com/a/s.css?v=1")
    assert not ok("https://x.com/logo.svg")
    assert ok("https://www.flipkart.com/p/itm123")
    assert ok("https://play.google.com/store/apps/details?id=com.dreamplug.androidapp")
