# DealLoot iteration 3: posted_at, age filters, poller interval, star/starred filter, price history, lowest filter
import os
import time
import uuid
import pytest
import requests
from pathlib import Path
from datetime import datetime, timezone


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


@pytest.fixture(scope="module", autouse=True)
def restore(s):
    yield
    s.put(f"{API}/settings", json={"check_interval_seconds": 60, "website_max_age_hours": 24, "telegram_max_age_minutes": 60})


def _ts(iso):
    return datetime.fromisoformat(iso)


# --- posted_at ---
class TestPostedAt:
    def test_all_deals_have_posted_at(self, s):
        deals = s.get(f"{API}/deals", params={"category": "all"}).json()
        assert len(deals) > 0
        for d in deals:
            assert d.get("posted_at"), d["id"]
            _ts(d["posted_at"])

    def test_latest_sorted_by_posted_at_desc(self, s):
        deals = s.get(f"{API}/deals", params={"category": "all", "sort": "latest"}).json()
        ts = [_ts(d["posted_at"]) for d in deals]
        assert ts == sorted(ts, reverse=True)

    def test_no_deals_older_than_website_max_age(self, s):
        hrs = s.get(f"{API}/settings").json().get("website_max_age_hours", 24)
        deals = s.get(f"{API}/deals", params={"category": "all", "limit": 500}).json()
        now = datetime.now(timezone.utc)
        auto = [d for d in deals if d.get("source_id") != "manual"]
        old = [d["title"] for d in auto if (now - _ts(d["posted_at"])).total_seconds() > hrs * 3600 + 3600]
        assert not old, f"{len(old)} deals older than {hrs}h: {old[:3]}"

    def test_posted_before_created(self, s):
        deals = s.get(f"{API}/deals", params={"category": "all"}).json()
        for d in deals:
            if d.get("source_id") != "manual":
                assert _ts(d["posted_at"]) <= _ts(d["created_at"])


# --- settings / poller ---
class TestSettings:
    def test_defaults(self, s):
        st = s.get(f"{API}/settings").json()
        assert st["check_interval_seconds"] == 60
        assert st["website_max_age_hours"] == 24
        assert st["telegram_max_age_minutes"] == 60

    def test_clamp_interval_low(self, s):
        r = s.put(f"{API}/settings", json={"check_interval_seconds": 5})
        assert r.status_code == 200 and r.json()["check_interval_seconds"] == 30

    def test_clamp_interval_high(self, s):
        r = s.put(f"{API}/settings", json={"check_interval_seconds": 999999})
        assert r.json()["check_interval_seconds"] == 86400

    def test_age_fields_persist(self, s):
        s.put(f"{API}/settings", json={"website_max_age_hours": 12, "telegram_max_age_minutes": 30, "check_interval_seconds": 60})
        st = s.get(f"{API}/settings").json()
        assert st["website_max_age_hours"] == 12 and st["telegram_max_age_minutes"] == 30
        s.put(f"{API}/settings", json={"website_max_age_hours": 24, "telegram_max_age_minutes": 60})

    def test_poller_last_run_updates(self, s):
        s.put(f"{API}/settings", json={"check_interval_seconds": 60})
        first = s.get(f"{API}/settings").json()["last_run_at"]
        changed = None
        for _ in range(20):  # up to ~100s
            time.sleep(5)
            cur = s.get(f"{API}/settings").json()["last_run_at"]
            if cur != first:
                changed = cur
                break
        assert changed, "last_run_at did not update within 100s"
        assert abs((datetime.now(timezone.utc) - _ts(changed)).total_seconds()) < 30


# --- star ---
class TestStar:
    def test_star_and_filter(self, s):
        d = s.get(f"{API}/deals", params={"category": "all"}).json()[-1]
        r = s.put(f"{API}/deals/{d['id']}/feature", json={"featured": True})
        assert r.status_code == 200
        starred = s.get(f"{API}/deals", params={"category": "starred"}).json()
        assert d["id"] in [x["id"] for x in starred] and all(x["featured"] for x in starred)
        srt = s.get(f"{API}/deals", params={"category": "all", "sort": "starred"}).json()
        assert srt[0]["id"] == d["id"]
        s.put(f"{API}/deals/{d['id']}/feature", json={"featured": False})
        assert d["id"] not in [x["id"] for x in s.get(f"{API}/deals", params={"category": "starred"}).json()]

    def test_feature_unknown_404(self, s):
        assert s.put(f"{API}/deals/nope-{uuid.uuid4()}/feature", json={"featured": True}).status_code == 404


# --- price history & lowest ---
class TestPriceHistory:
    def test_price_history_shape(self, s):
        deals = s.get(f"{API}/deals", params={"category": "all"}).json()
        d = next((x for x in deals if x.get("history_count")), deals[0])
        r = s.get(f"{API}/price-history/{d['id']}")
        assert r.status_code == 200
        j = r.json()
        assert isinstance(j["stores"], list)
        names = [c["name"] for c in j["compare"]]
        assert "Amazon" in names and "Flipkart" in names
        if d.get("price"):
            seen = [x for x in j["stores"] if x["store"] == "Seen in deal channels"]
            assert seen and len(seen[0]["points"]) >= 1
            assert j["lowest"] <= d["price"] <= j["highest"]

    def test_price_history_404(self, s):
        assert s.get(f"{API}/price-history/nope").status_code == 404

    def test_lowest_filter(self, s):
        r = s.get(f"{API}/deals", params={"category": "lowest"})
        assert r.status_code == 200
        assert all(x.get("lowest_ever") for x in r.json())

    def test_manual_repeat_builds_history_and_lowest(self, s):
        url = f"https://www.amazon.in/dp/B0TEST{uuid.uuid4().hex[:4].upper()}"
        ids = []
        try:
            a = s.post(f"{API}/deals", json={"url": url, "title": "TEST_ PH one", "price": 500, "mrp": 1000, "post_now": False}).json()["deal"]
            b = s.post(f"{API}/deals", json={"url": url, "title": "TEST_ PH two", "price": 400, "mrp": 1000, "post_now": False}).json()["deal"]
            ids = [a["id"], b["id"]]
            assert a["lowest_ever"] is False
            assert b["lowest_ever"] is True
            j = s.get(f"{API}/price-history/{b['id']}").json()
            seen = [x for x in j["stores"] if x["store"] == "Seen in deal channels"][0]
            assert len(seen["points"]) == 2 and j["lowest"] == 400 and j["highest"] == 500
            assert b["id"] in [x["id"] for x in s.get(f"{API}/deals", params={"category": "lowest"}).json()]
        finally:
            for i in ids:
                s.delete(f"{API}/deals/{i}")


# --- regression ---
class TestRegression:
    def test_best(self, s):
        r = s.get(f"{API}/deals", params={"category": "best"})
        assert r.status_code == 200 and len(r.json()) <= 40

    def test_search_special_chars(self, s):
        assert s.get(f"{API}/deals", params={"q": "(test"}).status_code == 200

    def test_sources_and_fetch_all(self, s):
        assert len(s.get(f"{API}/sources").json()) >= 10
        assert s.post(f"{API}/fetch-all").json()["queued"] is True
