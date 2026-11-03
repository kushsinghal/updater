# Iteration 19: gold category, offers extraction, 24h website window, store filter, lookup, manual add, 3h title dedupe
import os, sys, asyncio, uuid
from datetime import datetime, timezone, timedelta
import pytest, requests

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
import engine  # noqa: E402
import server  # noqa: E402

API = f"{BASE_URL}/api"


# ---- engine: gold ----
@pytest.mark.parametrize("t", ["MMTC-PAMP 1g 24k gold coin", "PNG Jewellers 2 gm Gold Ring 24 kt"])
def test_is_gold_true(t):
    assert engine.is_gold(t)
    assert "gold" in engine.classify(t, 0, {"gold_enabled": True})


@pytest.mark.parametrize("t", ["Nescafe Gold Coffee 95 Grams", "Titan Rose Gold Dial Watch", "Win Gold Coin contest"])
def test_is_gold_false(t):
    assert not engine.is_gold(t)


def test_gold_disabled_rule():
    assert "gold" not in engine.classify("MMTC-PAMP 1g 24k gold coin", 0, {"gold_enabled": False})


# ---- engine: offers ----
def test_extract_offers_kinds():
    text = ("Some product @ 9999\n• Apply ₹3000 Coupon\n• ₹10,750 Off With HDFC CC\n"
            "5% cashback with Amazon Pay ICICI\nUse 500 SuperCoins")
    offers = engine.extract_offers(text)
    print(offers)
    kinds = [o["kind"] for o in offers]
    assert "coupon" in kinds and "bank" in kinds and "supercoin" in kinds
    labels = " | ".join(o["label"] for o in offers)
    assert "₹3,000 coupon" in labels
    assert "₹10,750 off with HDFC Credit Card" in labels
    assert "Use 500 SuperCoins" in labels
    # 5% cashback with Amazon Pay ICICI -> bank-or-cashback with readable label
    assert any("5%" in o["label"] and "Amazon Pay ICICI" in o["label"] for o in offers)


def test_extract_offers_cashback_plain():
    offers = engine.extract_offers("Get ₹200 cashback on this order")
    assert offers and offers[0]["kind"] == "cashback" and offers[0]["label"] == "₹200 cashback"


def test_extract_offers_supercoin_100():
    offers = engine.extract_offers("Watch at 999\n100% supercoins back")
    assert offers[0]["kind"] == "supercoin" and "almost FREE" in offers[0]["label"]


def test_gift_card_not_bank():
    offers = engine.extract_offers("Flipkart Gift Card ₹1000 at 920\nBuy Amazon Pay gift card get 8% off")
    print(offers)
    assert not any(o["kind"] == "bank" for o in offers), offers


# ---- engine: format_message ----
def test_format_message_offer_lines_and_gold_prefix():
    deal = {"title": "MMTC-PAMP 1g 24k coin", "url": "https://x.y/a", "price": 7000, "mrp": 8000, "store_price": 8000,
            "categories": ["gold"], "offers": [{"kind": "bank", "label": "₹500 off with HDFC Credit Card"},
                                               {"kind": "coupon", "label": "₹100 coupon"},
                                               {"kind": "supercoin", "label": "Use 50 SuperCoins"},
                                               {"kind": "cashback", "label": "₹20 cashback"}]}
    m = engine.format_message(deal)
    print(m)
    assert m.startswith("<b>Gold Deal: ")
    for icon in ["💳", "🎟️", "🪙", "💰", "🏷️ Store ₹8,000 → you pay ₹7,000"]:
        assert icon in m
    m2 = engine.format_message(deal, style="rich")
    assert "💳" in m2 and "🎟️" in m2


# ---- API: window ----
def _within(iso, hours):
    return datetime.fromisoformat(iso) >= datetime.now(timezone.utc) - timedelta(hours=hours, minutes=5)


def test_deals_window_all_categories():
    hours = requests.get(f"{API}/settings").json().get("website_max_age_hours", 24)
    for cat in [None, "all", "supercoin_100", "gift_card", "heavy_discount", "loot", "gold", "lowest", "best"]:
        params = {"category": cat} if cat else {}
        r = requests.get(f"{API}/deals", params=params)
        assert r.status_code == 200, cat
        bad = [d for d in r.json() if not d.get("featured") and not _within(d["posted_at"], hours)]
        assert not bad, f"{cat}: {len(bad)} old deals e.g. {bad[0]['posted_at']}"
        if cat == "gold":
            assert all("gold" in d["categories"] for d in r.json())


def test_stats_windowed():
    s = requests.get(f"{API}/stats").json()
    print({k: s.get(k) for k in ["total", "all_time", "website_max_age_hours", "gold", "supercoin_100"]})
    assert "website_max_age_hours" in s and "all_time" in s and "gold" in s
    assert s["total"] <= s["all_time"]
    for c in engine.CATEGORIES:
        assert s[c] <= s["total"]


# ---- API: store filter ----
@pytest.mark.parametrize("store", ["Flipkart", "Amazon", "Myntra", "Ajio"])
def test_store_filter(store):
    r = requests.get(f"{API}/deals", params={"store": store})
    assert r.status_code == 200
    assert all(d["store"] == store for d in r.json())


def test_store_other():
    r = requests.get(f"{API}/deals", params={"store": "Other"})
    assert r.status_code == 200
    assert all(d["store"] not in ["Flipkart", "Amazon", "Myntra", "Ajio"] for d in r.json())


# ---- API: lookup ----
def test_lookup_flipkart():
    r = requests.get(f"{API}/lookup", params={"url": "https://www.flipkart.com/apple-iphone-15/p/itm6ac6485515ae4"}, timeout=60)
    assert r.status_code == 200
    d = r.json()
    print(d)
    assert d["store"] == "Flipkart"
    assert d["cleaned"].startswith("https://www.flipkart.com/")
    assert d.get("title"), "title missing"
    assert d.get("image"), "image missing"


def test_lookup_bad():
    r = requests.get(f"{API}/lookup", params={"url": "ftp://x"})
    assert r.status_code == 400


# ---- API: manual add with offers from note ----
def test_manual_add_offers_from_note():
    tag = uuid.uuid4().hex[:6]
    body = {"url": f"https://www.flipkart.com/test-item/p/itm{tag}test", "title": f"TEST_manual {tag} speaker",
            "price": 1999, "mrp": 4999, "note": "Extra ₹1,200 off with HDFC Credit Card", "post_now": False}
    r = requests.post(f"{API}/deals", json=body, timeout=60)
    assert r.status_code == 200
    deal = r.json()["deal"]
    try:
        assert any(o["kind"] == "bank" and "HDFC" in o["label"] for o in deal["offers"]), deal["offers"]
        assert deal["store"] == "Flipkart"
        assert r.json()["post_results"] == []
        lst = requests.get(f"{API}/deals", params={"q": f"TEST_manual {tag}"}).json()
        assert lst and lst[0]["id"] == deal["id"] and lst[0]["offers"]
    finally:
        assert requests.delete(f"{API}/deals/{deal['id']}").status_code == 200
    assert requests.delete(f"{API}/deals/{deal['id']}").status_code == 404


# ---- ingest: 3h title dedupe ----
def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _dedupe_cases():
    from motor.motor_asyncio import AsyncIOMotorClient
    server.db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    db = server.db
    tag = uuid.uuid4().hex[:8]
    src_a = {"id": f"TEST_src_a_{tag}", "name": "TEST A"}
    src_b = {"id": f"TEST_src_b_{tag}", "name": "TEST B"}
    settings = {"split_multi": True, "website_max_age_hours": 24}
    nowiso = datetime.now(timezone.utc).isoformat()
    out = {}

    def item(title, i):
        return {"title": title, "url": f"https://example.org/{tag}/p{i}", "ext_id": f"{tag}/{i}", "posted_at": nowiso,
                "categories": ["loot"], "store": "Other", "text": title, "image": "https://example.org/i.jpg"}
    try:
        for label, hrs in (("old4h", 4), ("recent2h", 2)):
            title = f"TEST_dedupe3h {tag} {label}"
            tk = "".join(ch for ch in title.lower() if ch.isalnum())[:60]
            await db.deals.insert_one({"id": f"TEST_{tag}_{label}", "title": title, "title_key": tk, "source_id": src_a["id"],
                                       "clean_url": f"https://example.org/{tag}/{label}/orig", "posted_at": nowiso,
                                       "created_at": (datetime.now(timezone.utc) - timedelta(hours=hrs)).isoformat(),
                                       "categories": ["loot"], "dedupe_key": f"TEST_src_a_{tag}:{label}"})
            out[label] = bool(await server.ingest(item(title, label), src_b, settings, autopost=False))
    finally:
        await db.deals.delete_many({"source_id": {"$in": [src_a["id"], src_b["id"]]}})
        await db.seen.delete_many({"key": {"$regex": f"^TEST_src_.*{tag}"}})
    return out


def test_title_dedupe_3h_window():
    out = _run(_dedupe_cases())
    print(out)
    assert out["recent2h"] is False, "same title other source within 3h must be blocked"
    assert out["old4h"] is True, "same title other source older than 3h must be accepted"
