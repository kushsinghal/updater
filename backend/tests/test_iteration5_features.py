# Iteration 5: pricehistory.app integration, price-history endpoint, lowest filter, enrichment, fetch-all
import os
import re
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
S = requests.Session()


@pytest.fixture(scope="module")
def deals():
    r = S.get(f"{BASE_URL}/api/deals", params={"category": "all", "limit": 500}, timeout=30)
    assert r.status_code == 200
    return r.json()


def _ph_deals(deals):
    return [d for d in deals if d["store"] in ("Amazon", "Flipkart") and d.get("ph_min")]


# --- price-history endpoint shape
def test_price_history_404():
    r = S.get(f"{BASE_URL}/api/price-history/nonexistent-id", timeout=30)
    assert r.status_code == 404


def test_price_history_shape_with_stores(deals):
    cands = _ph_deals(deals)
    assert cands, "No Amazon/Flipkart deal with ph_min"
    ok = 0
    for d in cands[:4]:
        r = S.get(f"{BASE_URL}/api/price-history/{d['id']}", timeout=60)
        assert r.status_code == 200
        j = r.json()
        for k in ("stores", "best", "lowest", "highest", "compare"):
            assert k in j
        assert isinstance(j["compare"], list) and len(j["compare"]) >= 1
        real = [s for s in j["stores"] if s["store"] != "Seen in deal channels"]
        if real:
            ok += 1
            s = real[0]
            for k in ("store", "url", "current", "lowest", "highest", "points"):
                assert k in s
            assert len(s["points"]) > 1
            assert all("x" in p and "y" in p for p in s["points"][:5])
            assert j["lowest"] <= j["highest"]
            assert j["best"] and j["best"]["url"] and j["best"]["current"]
            # best is cheapest of store currents (or deal price)
            mins = [x["current"] for x in real if x.get("current")]
            if d.get("price"):
                mins.append(d["price"])
            assert j["best"]["current"] == min(mins)
    assert ok >= 1, "No deal returned real pricehistory store data"


def test_price_history_points_within_400(deals):
    d = _ph_deals(deals)[0]
    j = S.get(f"{BASE_URL}/api/price-history/{d['id']}", timeout=60).json()
    for s in j["stores"]:
        assert len(s["points"]) <= 500


# --- lowest filter
def test_lowest_filter_has_deals():
    r = S.get(f"{BASE_URL}/api/deals", params={"category": "lowest"}, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert len(d) > 0
    assert all(x.get("lowest_ever") is True for x in d)
    ts = [x["posted_at"] for x in d]
    assert ts == sorted(ts, reverse=True)


def test_lowest_ever_consistent_with_ph_min(deals):
    bad = [d for d in deals if d.get("ph_min") and d.get("price") and d.get("lowest_ever") and d["price"] > d["ph_min"]]
    assert not bad, [(d["id"], d["price"], d["ph_min"]) for d in bad]


def test_lowest_ever_price_plausibility(deals):
    """Deal price < 20% of all-time min suggests mis-parsed price flagged as lowest."""
    sus = [(d["id"], d["title"][:40], d["price"], d["ph_min"]) for d in deals
           if d.get("ph_min") and d.get("price") and d.get("lowest_ever") and d["price"] < 0.2 * d["ph_min"]]
    assert not sus, f"Implausible lowest_ever deals: {sus}"


# --- enrichment
def test_all_deals_ph_checked(deals):
    assert all(d.get("ph_checked") for d in deals)


def test_enrichment_fields(deals):
    e = [d for d in deals if d.get("ph_url")]
    assert e
    assert all(d["ph_url"].startswith("https://pricehistory.app/p/") for d in e)


# --- original post url format
def test_source_post_url_telegram(deals):
    tg = [d for d in deals if (d.get("source_post_url") or "").startswith("https://t.me/")]
    assert tg
    assert all(re.match(r"^https://t\.me/(s/)?[A-Za-z0-9_]+/\d+$", d["source_post_url"]) for d in tg)


# --- fetch-all
def test_fetch_all():
    r = S.post(f"{BASE_URL}/api/fetch-all", timeout=30)
    assert r.status_code == 200
    time.sleep(3)
    r2 = S.get(f"{BASE_URL}/api/deals", params={"category": "all"}, timeout=30)
    assert r2.status_code == 200 and len(r2.json()) > 0


# --- regression: sort
@pytest.mark.parametrize("cat", ["best", "all", "lowest", "loot", "heavy_discount"])
def test_sorted_posted_at_desc(cat):
    d = S.get(f"{BASE_URL}/api/deals", params={"category": cat}, timeout=30).json()
    ts = [x["posted_at"] for x in d]
    assert ts == sorted(ts, reverse=True)
