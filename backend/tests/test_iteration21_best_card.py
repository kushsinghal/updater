# Iteration 21: EMI skip, cap capture, mark_best_card, deals API offers, regression
import os, sys, requests, pytest
sys.path.insert(0, "/app/backend")
import engine

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for l in open("/app/frontend/.env"):
        if l.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = l.split("=", 1)[1].strip().rstrip("/")

TEXT = """iPhone deal @ 24999
₹1,500 off HDFC CC
10% off SBI Credit Card (up to ₹2,000)
₹3000 off ICICI Credit Card EMI
No Cost EMI with Axis Bank card ₹2500 off
5% instalment discount Kotak credit card"""


# engine: EMI lines skipped
def test_emi_skipped():
    offs = engine.extract_offers(TEXT)
    labels = " | ".join(o["label"] for o in offs)
    assert "ICICI" not in labels and "Axis" not in labels and "Kotak" not in labels, labels
    assert any("HDFC" in o["label"] for o in offs)
    assert any("SBI" in o["label"] for o in offs)


# engine: cap captured on % offers
def test_cap_captured():
    sbi = [o for o in engine.extract_offers(TEXT) if "SBI" in o["label"]][0]
    assert sbi.get("cap") == 2000
    assert "(up to ₹2,000)" in sbi["label"]
    assert sbi["amount"] == 10


def test_no_cap_on_flat():
    o = engine.extract_offers("₹1,500 off HDFC Credit Card up to ₹5000")[0]
    assert "cap" not in o


# engine: best card
def test_mark_best_sbi():
    offs = engine.mark_best_card(engine.extract_offers(TEXT), 24999)
    best = [o for o in offs if o.get("best")]
    assert len(best) == 1 and "SBI" in best[0]["label"], offs
    assert best[0]["saving"] == 2000


def test_mark_best_flat_wins_low_price():
    offs = engine.mark_best_card(engine.extract_offers(TEXT), 9999)  # 10% = 999.9 < 1500
    best = [o for o in offs if o.get("best")]
    assert "HDFC" in best[0]["label"] and best[0]["saving"] == 1500


def test_mark_best_no_price():
    offs = engine.mark_best_card(engine.extract_offers(TEXT), None)
    best = [o for o in offs if o.get("best")]
    assert "HDFC" in best[0]["label"]


def test_mark_best_idempotent_and_empty():
    assert engine.mark_best_card([], 100) == []
    offs = engine.mark_best_card(engine.extract_offers(TEXT), 24999)
    offs = engine.mark_best_card(offs, 9999)
    assert sum(1 for o in offs if o.get("best")) == 1


def test_coupon_not_best():
    offs = engine.mark_best_card(engine.extract_offers("₹500 coupon on page"), 1000)
    assert not any(o.get("best") for o in offs)


# API: deals list includes offers with best flags consistent
def test_api_deals_best_flags():
    r = requests.get(f"{BASE_URL}/api/deals", params={"limit": 500}, timeout=30)
    assert r.status_code == 200
    deals = r.json()
    assert isinstance(deals, list) and deals
    for d in deals:
        assert "_id" not in d
        bests = [o for o in (d.get("offers") or []) if o.get("best")]
        assert len(bests) <= 1, d["id"]
        for o in bests:
            assert o["kind"] == "bank"


def test_api_store_distribution():
    deals = requests.get(f"{BASE_URL}/api/deals", params={"limit": 500}, timeout=30).json()
    stores = {}
    for d in deals:
        stores[d.get("store")] = stores.get(d.get("store"), 0) + 1
    print("STORES", stores, "TOTAL", len(deals))
    assert all(s for s in stores)
