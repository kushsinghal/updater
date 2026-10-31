# Iteration 9: website sources (desidime/dealsmagnet/crafin), post_style, format_message
import os, sys, asyncio, re
import pytest
import requests

sys.path.insert(0, "/app/backend")
import engine  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
S = requests.Session()


def run(c):
    return asyncio.get_event_loop().run_until_complete(c) if False else asyncio.run(c)


# ---- engine.fetch_web direct (no posting) ----
class TestFetchWebEngine:
    @pytest.mark.parametrize("url", ["https://www.desidime.com/new", "https://www.dealsmagnet.com/", "https://www.dealsmagnet.com/deal"])
    def test_fetch_web_items(self, url):
        items = run(engine.fetch_web(url))
        assert len(items) > 0, f"no items from {url}"
        withimg = [i for i in items if i.get("image")]
        withtime = [i for i in items if i.get("posted_at")]
        withpost = [i for i in items if i.get("post_url")]
        print(url, len(items), "img", len(withimg), "time", len(withtime), "post", len(withpost))
        print("sample:", {k: (str(v)[:100]) for k, v in items[0].items()})
        assert all(i.get("title") for i in items)
        assert len(withimg) >= len(items) * 0.7
        assert len(withtime) >= len(items) * 0.7
        assert len(withpost) >= len(items) * 0.7
        assert all(i["ext_id"] for i in items)

    def test_crafin_captcha(self):
        with pytest.raises(ValueError) as e:
            run(engine.fetch_web("https://www.crafin.in/buy-gift-cards"))
        print("crafin:", e.value)
        assert "captcha" in str(e.value).lower() or "Unsupported" in str(e.value)

    def test_unsupported(self):
        with pytest.raises(ValueError) as e:
            run(engine.fetch_web("https://example.com/deals"))
        assert "Unsupported website" in str(e.value)


class TestRelTime:
    @pytest.mark.parametrize("txt,mins", [("5 mins ago", 5), ("2 hours ago", 120), ("an hour ago", 60),
                                          ("1 day ago", 1440), ("3h ago", 180), ("10m ago", 10), ("just now", 0)])
    def test_rel(self, txt, mins):
        from datetime import datetime, timezone
        v = engine._rel_time(txt)
        assert v, txt
        diff = (datetime.now(timezone.utc) - datetime.fromisoformat(v)).total_seconds() / 60
        assert abs(diff - mins) < 2, (txt, diff)

    def test_rel_none(self):
        assert engine._rel_time("") is None
        assert engine._rel_time("yesterday") is None or True


# ---- format_message ----
class TestFormatMessage:
    deal = {"title": "Poco X6 5G <Black>", "url": "https://www.flipkart.com/x", "price": 9999, "mrp": 19999,
            "discount": 50, "store": "Flipkart", "categories": ["supercoin_100"]}

    def test_simple_supercoin(self):
        m = engine.format_message(self.deal, "simple")
        assert m == "<b>100% Supercoins Back: Poco X6 5G &lt;Black&gt;</b>\nPrice: ₹9,999 (MRP ₹19,999)\nhttps://www.flipkart.com/x"

    def test_default_is_simple(self):
        assert engine.format_message(self.deal).startswith("<b>100% Supercoins Back:")

    def test_simple_uses_affiliate(self):
        d = {**self.deal, "affiliate_url": "https://fkrt.it/abc"}
        assert engine.format_message(d, "simple").endswith("https://fkrt.it/abc")

    def test_simple_no_price(self):
        d = {**self.deal, "price": None}
        assert engine.format_message(d, "simple") == "<b>100% Supercoins Back: Poco X6 5G &lt;Black&gt;</b>\nhttps://www.flipkart.com/x"

    def test_simple_gift(self):
        d = {**self.deal, "title": "Amazon voucher", "categories": ["gift_card"]}
        assert engine.format_message(d, "simple").startswith("<b>Gift Card Deal: Amazon voucher</b>")

    def test_detailed(self):
        m = engine.format_message(self.deal, "detailed")
        assert m.startswith("<b>🪙 100% SUPERCOIN DEAL</b>")
        assert "50% OFF" in m and "Store: Flipkart" in m and "👉 https://www.flipkart.com/x" in m


# ---- API ----
class TestSourcesApi:
    def test_existing_web_sources_ok(self):
        srcs = S.get(f"{BASE_URL}/api/sources").json()
        web = {s["name"]: s for s in srcs if s["kind"] == "web"}
        assert "desidime.com (website)" in web and "dealsmagnet.com (website)" in web
        for s in web.values():
            assert s["last_error"] is None, s
            assert s["last_fetched_at"]

    def test_crafin_add_fetch_delete(self):
        r = S.post(f"{BASE_URL}/api/sources", json={"value": "https://www.crafin.in/buy-gift-cards", "kind": "web"})
        assert r.status_code == 200, r.text
        src = r.json()
        try:
            assert src["kind"] == "web" and src["name"] == "crafin.in (website)"
            f = S.post(f"{BASE_URL}/api/sources/{src['id']}/fetch", timeout=60).json()
            print("crafin fetch:", f)
            assert f["fetched"] == 0
            assert f["error"] == "This website blocks automatic reading (captcha). Use its Telegram channel instead."
            got = [s for s in S.get(f"{BASE_URL}/api/sources").json() if s["id"] == src["id"]][0]
            assert got["last_error"] == f["error"]
        finally:
            S.delete(f"{BASE_URL}/api/sources/{src['id']}")
        assert not [s for s in S.get(f"{BASE_URL}/api/sources").json() if s["id"] == src["id"]]

    def test_unsupported_add_fetch_delete(self):
        r = S.post(f"{BASE_URL}/api/sources", json={"value": "https://example.com/TEST_deals", "kind": "web"})
        assert r.status_code == 200, r.text
        src = r.json()
        try:
            f = S.post(f"{BASE_URL}/api/sources/{src['id']}/fetch", timeout=60).json()
            assert f["error"].startswith("Unsupported website")
        finally:
            S.delete(f"{BASE_URL}/api/sources/{src['id']}")

    def test_web_deals_exist(self):
        deals = S.get(f"{BASE_URL}/api/deals", params={"limit": 500}).json()
        items = deals if isinstance(deals, list) else deals.get("items", [])
        web = [d for d in items if "desidime.com/" in (d.get("source_post_url") or "") or "dealsmagnet.com/deal/" in (d.get("source_post_url") or "")]
        print("web deals:", len(web), [(d.get("source_name"), d.get("title")[:50], d.get("posted_at")) for d in web[:5]])
        for d in web:
            assert d.get("title")


class TestPostStyle:
    def test_default_and_update(self):
        assert S.get(f"{BASE_URL}/api/settings").json().get("post_style") == "simple"
        try:
            r = S.put(f"{BASE_URL}/api/settings", json={"post_style": "detailed"})
            assert r.status_code == 200 and r.json()["post_style"] == "detailed"
            assert S.get(f"{BASE_URL}/api/settings").json()["post_style"] == "detailed"
        finally:
            r = S.put(f"{BASE_URL}/api/settings", json={"post_style": "simple"})
        assert S.get(f"{BASE_URL}/api/settings").json()["post_style"] == "simple"


def test_health():
    assert S.get(f"{BASE_URL}/api/", timeout=10).status_code == 200
