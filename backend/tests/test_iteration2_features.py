# DealLoot iteration 2: best deals, feature toggle, interval/max-posts clamps, link cleaning, Telegram sankmo login, secrets masking
import os
import pytest
import requests
from pathlib import Path


def _env(path, key):
    for line in Path(path).read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _env("/app/frontend/.env", "REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def orig(s):
    o = s.get(f"{API}/settings").json()
    yield o
    s.put(f"{API}/settings", json={"check_interval_minutes": 15, "max_posts_per_update": 20, "product_min": 70,
                                   "convert_mode": "telegram"})


# Best deals
class TestBest:
    def test_best_order(self, s):
        r = s.get(f"{API}/deals", params={"category": "best"})
        assert r.status_code == 200
        rows = r.json()
        # iteration 4: best is sorted by posted_at desc
        ts = [d.get("posted_at") for d in rows]
        assert ts == sorted(ts, reverse=True), ts
        for d in rows:
            assert "_id" not in d and "dedupe_key" not in d
            assert d.get("featured") or (d.get("score") or 0) >= 60

    def test_feature_toggle(self, s):
        allrows = s.get(f"{API}/deals", params={"limit": 500}).json()
        best_ids = {d["id"] for d in s.get(f"{API}/deals", params={"category": "best"}).json()}
        cand = next((d for d in sorted(allrows, key=lambda x: x.get("score") or 0) if d["id"] not in best_ids), None)
        if not cand:
            pytest.skip("no deal outside best")
        try:
            r = s.put(f"{API}/deals/{cand['id']}/feature", json={"featured": True})
            assert r.status_code == 200 and r.json()["featured"] is True
            best = s.get(f"{API}/deals", params={"category": "best"}).json()
            assert any(d["id"] == cand["id"] and d["featured"] for d in best)
        finally:
            s.put(f"{API}/deals/{cand['id']}/feature", json={"featured": False})
        best = s.get(f"{API}/deals", params={"category": "best"}).json()
        assert cand["id"] not in {d["id"] for d in best}

    def test_feature_missing_deal(self, s):
        r = s.put(f"{API}/deals/nope-nonexistent/feature", json={"featured": True})
        print("feature nonexistent:", r.status_code, r.text)
        assert r.status_code == 404, "feature endpoint should 404 for missing deal"


# Rules: interval + max posts clamp
class TestRulesClamp:
    def test_persist(self, s, orig):
        r = s.put(f"{API}/settings", json={"check_interval_minutes": 60, "max_posts_per_update": 150})
        assert r.status_code == 200
        g = s.get(f"{API}/settings").json()
        assert g["check_interval_minutes"] == 60 and g["max_posts_per_update"] == 150

    @pytest.mark.parametrize("val,exp", [(500, 200), (0, 1), (-5, 1), (200, 200)])
    def test_max_posts_clamp(self, s, orig, val, exp):
        r = s.put(f"{API}/settings", json={"max_posts_per_update": val})
        assert r.json()["max_posts_per_update"] == exp

    @pytest.mark.parametrize("val,exp", [(5, 15), (99999, 1440), (30, 30)])
    def test_interval_clamp(self, s, orig, val, exp):
        r = s.put(f"{API}/settings", json={"check_interval_minutes": val})
        assert r.json()["check_interval_minutes"] == exp

    def test_product_min_persist(self, s, orig):
        s.put(f"{API}/settings", json={"product_min": 65})
        assert s.get(f"{API}/settings").json()["product_min"] == 65


# Link cleaning / affiliate stripping
class TestConvert:
    def test_amzn_short(self, s):
        r = s.post(f"{API}/convert", json={"url": "https://amzn.to/4wVBBhV"}, timeout=60)
        assert r.status_code == 200
        print(r.json())
        assert r.json()["cleaned"] == "https://www.amazon.in/dp/B0H1X7JHZP"

    def test_amazon_tag_removed(self, s):
        r = s.post(f"{API}/convert", json={"url": "https://www.amazon.in/Some-Product/dp/B0H1X7JHZP?tag=xyz-21&linkCode=ll1&ref_=abc"}, timeout=60)
        c = r.json()["cleaned"]
        assert "tag=" not in c and c == "https://www.amazon.in/dp/B0H1X7JHZP"

    def test_amazon_non_dp_tag_removed(self, s):
        r = s.post(f"{API}/convert", json={"url": "https://www.amazon.in/s?k=phone&tag=xyz-21"}, timeout=60)
        c = r.json()["cleaned"]
        assert "tag=" not in c and "k=phone" in c

    def test_flipkart_affid_removed(self, s):
        r = s.post(f"{API}/convert", json={"url": "https://www.flipkart.com/x/p/itm123?pid=ABC&affid=someone&affExtParam1=zz"}, timeout=60)
        c = r.json()["cleaned"]
        assert "affid" not in c.lower() and "pid=ABC" in c

    def test_wrapped_url(self, s):
        r = s.post(f"{API}/convert", json={"url": "https://linkredirect.in/visitretailer/1?dl=https%3A%2F%2Fwww.amazon.in%2Fdp%2FB0H1X7JHZP%3Ftag%3Dabc-21"}, timeout=60)
        assert r.json()["cleaned"] == "https://www.amazon.in/dp/B0H1X7JHZP"


# Sankmo Telegram login + secrets
class TestSankmoTelegram:
    def test_mode_switch(self, s, orig):
        r = s.put(f"{API}/settings", json={"convert_mode": "api"})
        assert r.json()["convert_mode"] == "api"
        r = s.put(f"{API}/settings", json={"convert_mode": "telegram"})
        assert r.json()["convert_mode"] == "telegram"

    def test_send_code_fake(self, s):
        r = s.post(f"{API}/sankmo/telegram/send-code", json={"api_id": "abc", "api_hash": "x", "phone": "+910000000000"}, timeout=60)
        assert r.status_code == 400 and "Could not send code" in r.json()["detail"]

    def test_send_code_fake_numeric(self, s):
        r = s.post(f"{API}/sankmo/telegram/send-code", json={"api_id": "12345", "api_hash": "0123456789abcdef0123456789abcdef", "phone": "+910000000000"}, timeout=90)
        print("numeric fake:", r.status_code, r.text[:300])
        assert r.status_code == 400

    def test_verify_without_code(self, s):
        r = s.post(f"{API}/sankmo/telegram/verify", json={"code": "12345"}, timeout=30)
        assert r.status_code == 400

    def test_secrets_not_exposed(self, s):
        g = s.get(f"{API}/settings").json()
        for k in ["tg_session", "tg_api_hash", "sankmo_token"]:
            assert k not in g
        assert "tg_connected" in g and "sankmo_token_masked" in g and "tg_api_hash_masked" in g


# Fetch-all + cron
class TestFetchAll:
    def test_fetch_all_queued(self, s):
        r = s.post(f"{API}/fetch-all")
        assert r.status_code == 200 and r.json()["queued"] is True

    def test_cron_requires_bearer(self, s):
        assert s.post(f"{API}/cron/fetch").status_code == 401

    def test_sources_count(self, s):
        rows = s.get(f"{API}/sources").json()
        assert len(rows) >= 14
        assert any(x["kind"] == "rss" for x in rows)
