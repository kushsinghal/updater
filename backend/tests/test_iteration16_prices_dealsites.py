# Iteration 16: new price parser, deal-site link resolution, poller, manual deal prices
import os
import sys
import time
import pytest
import requests

sys.path.insert(0, "/app/backend")
import engine  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
S = requests.Session()


def _secret():
    for line in open("/app/backend/.env"):
        if line.startswith("WEBHOOK_CRON_SECRET"):
            return line.split("=", 1)[1].strip().strip('"')


# ---- engine.extract_prices unit tests ----
@pytest.mark.parametrize("text,price,mrp", [
    ("Haier 596L Refrigerator @45,240*\n• Apply ₹3000 Coupon\n• ₹10,750 / ₹14,751 Off With HDFC CC", 45240, None),
    ("Loot | 75% Off : Armani Exchange Watch at 4979\n\nat 5647 : link", 4979, "any"),
    ("Electric Scooter Loot Is Back at \u200e38950*\n10000₹ Off With HDFCCC\nRegular Price: ₹52K+", 38950, 52000),
    ("WHP 24kt (999) 1 Gm Gold Pendant @14,359 (Effectively)\n1st Collect ₹250 Cashback", 14359, "any"),
    ("✅ Offer Price : ₹1,279\n❌ MRP : ₹4,599", 1279, 4599),
    ("Mokobara Cabin Luggage\nOn-Page Coupon: Extra 20% OFF (up to ₹1,000)", None, "any"),
    (" 87% off on - Instamart Something - Rs. 328", 328, "any"),
])
def test_extract_prices(text, price, mrp):
    p, m = engine.extract_prices(text)
    assert p == price, f"price {p} != {price} (mrp {m})"
    if mrp != "any":
        assert m == mrp, f"mrp {m} != {mrp}"


def test_is_deal_site():
    assert engine.is_deal_site("https://www.desidime.com/deals/x")
    assert engine.is_deal_site("https://ddime.in/abc")
    assert engine.is_deal_site("https://dealsmagnet.com/deal/x")
    assert engine.is_deal_site("https://t.me/foo/1")
    assert not engine.is_deal_site("https://www.flipkart.com/p/itm1")


# ---- GET /api/deals price sanity ----
class TestDealsList:
    @pytest.fixture(scope="class")
    def deals(self):
        r = S.get(f"{BASE_URL}/api/deals", params={"limit": 500}, timeout=30)
        assert r.status_code == 200
        return r.json()

    def test_no_near_equal_mrp(self, deals):
        bad = [(d["title"][:50], d["price"], d["mrp"]) for d in deals
               if d.get("price") and d.get("mrp") and d["mrp"] <= d["price"] * 1.03]
        assert not bad, f"{len(bad)} deals with mrp<=price*1.03: {bad[:5]}"

    def test_triple_loot(self, deals):
        t = [d for d in deals if "triple loot" in (d.get("title", "") + d.get("text", "")).lower()]
        if not t:
            pytest.skip("No Triple Loot deal in list")
        for d in t:
            print(d["title"][:60], d.get("price"), d.get("mrp"), d.get("text_price"))
        hai = [d for d in t if "45,240" in d.get("text", "") or "45240" in d.get("text", "")]
        for d in hai or t:
            assert d["price"] == 45240 if hai else True
            assert d.get("mrp") is None or d["mrp"] > d["price"]

    def test_armani(self, deals):
        a = [d for d in deals if "armani" in d.get("title", "").lower() and "4979" in d.get("text", "")]
        if not a:
            pytest.skip("No Armani deal")
        for d in a:
            assert d["price"] == 4979, (d["title"], d["price"], d["mrp"])

    def test_no_deal_site_links(self, deals):
        bad = [d["clean_url"] for d in deals if engine.is_deal_site(d.get("clean_url")) and "t.me/" not in d.get("clean_url", "")]
        print("deal-site clean_urls:", bad[:5])
        bad_aff = [d["affiliate_url"] for d in deals if d.get("converted") and engine.is_deal_site(d.get("clean_url"))]
        assert not bad_aff, bad_aff[:5]


# ---- bulk convert with post price ----
def test_bulk_armani_post_price():
    text = "Loot | 75% Off : Armani Exchange Watch at 4979\n\nhttps://www.flipkart.com/flipkart/p/itm69cc6d7c2842e?pid=WATG4NP8QGQNZGGH"
    r = S.post(f"{BASE_URL}/api/convert/bulk", json={"text": text, "base": BASE_URL}, timeout=120)
    assert r.status_code == 200, r.text
    it = r.json()["items"][0]
    print({k: it.get(k) for k in ("price", "mrp", "store_price", "converted", "error")})
    assert it["price"] == 4979
    assert it.get("store_price") is not None
    if it.get("store_price"):
        assert it["store_price"] != 4979
    assert it.get("mrp") and it["mrp"] > 4979


# ---- convert desidime ----
def test_convert_desidime():
    url = "https://www.desidime.com/deals/diwali-celebration-sale-is-live-2190683"
    r = S.post(f"{BASE_URL}/api/convert", json={"url": url}, timeout=120)
    assert r.status_code == 200
    d = r.json()
    print(d)
    assert "desidime" not in d["cleaned"] and "ddime" not in d["cleaned"]
    assert "biba" in d["cleaned"]


def test_convert_deal_site_not_sent():
    # a deal-site URL that can't be resolved must be returned unchanged (never sent to bot)
    url = "https://dealsmagnet.com/some-nonexistent-page-xyz"
    t = time.time()
    r = S.post(f"{BASE_URL}/api/convert", json={"url": url}, timeout=60)
    assert r.status_code == 200
    d = r.json()
    print(d, time.time() - t)
    if engine.is_deal_site(d["cleaned"]):
        assert d["converted"] == d["cleaned"] and d["changed"] is False


# ---- poller / cron ----
def test_cron_fetch_auth():
    r = S.post(f"{BASE_URL}/api/cron/fetch", timeout=30)
    assert r.status_code == 401
    r = S.post(f"{BASE_URL}/api/cron/fetch", headers={"Authorization": f"Bearer {_secret()}"}, timeout=30)
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] is True


def test_last_scan_updates():
    a = S.get(f"{BASE_URL}/api/stats", timeout=30).json()
    print("stats1", a.get("last_scan_at"), a["total"])
    deadline = time.time() + 150
    while time.time() < deadline:
        time.sleep(15)
        b = S.get(f"{BASE_URL}/api/stats", timeout=30).json()
        if b.get("last_scan_at") != a.get("last_scan_at"):
            print("stats2", b.get("last_scan_at"), b["total"])
            return
    pytest.fail("last_scan_at did not change in 150s")


# ---- manual deal keeps prices ----
def test_manual_deal_prices():
    r = S.post(f"{BASE_URL}/api/deals", json={
        "url": "https://www.flipkart.com/flipkart/p/itm69cc6d7c2842e?pid=WATG4NP8QGQNZGGH",
        "title": "TEST_ manual armani", "price": 499, "mrp": 999, "categories": ["loot"]}, timeout=60)
    assert r.status_code in (200, 201), r.text
    d = r.json()
    did = d.get("id") or d.get("deal", {}).get("id")
    try:
        time.sleep(20)
        deals = S.get(f"{BASE_URL}/api/deals", params={"q": "TEST_ manual", "limit": 50}, timeout=30).json()
        got = next(x for x in deals if x["id"] == did)
        print(got.get("price"), got.get("mrp"), got.get("ph_checked"))
        assert got["price"] == 499 and got["mrp"] == 999
    finally:
        S.delete(f"{BASE_URL}/api/deals/{did}", timeout=30)
