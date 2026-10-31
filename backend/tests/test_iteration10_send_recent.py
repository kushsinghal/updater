# Iteration 10: send-recent, stats fresh window, tg send-code fallback
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FAKE_TOKEN = "123456:TEST_fake_token_abcdefghijklmnopqrstuv"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def test_dest(s):
    r = s.post(f"{BASE_URL}/api/destinations", json={"name": "TEST_iter10_dest", "bot_token": FAKE_TOKEN,
                                                      "chat_id": "-1000000000001", "categories": [], "enabled": False})
    assert r.status_code == 200, r.text
    d = r.json()
    yield d
    s.delete(f"{BASE_URL}/api/destinations/{d['id']}")


# Stats: fresh window equals settings telegram_max_age_minutes
def test_stats_fresh_window(s):
    st = s.get(f"{BASE_URL}/api/stats").json()
    cfg = s.get(f"{BASE_URL}/api/settings").json()
    assert st["fresh_window_minutes"] == int(cfg["telegram_max_age_minutes"])
    assert isinstance(st["fresh_3h"], int)
    assert "latest_deal_at" in st
    print("stats", st["fresh_window_minutes"], st["fresh_3h"], st["latest_deal_at"])


def test_send_recent_404(s):
    r = s.post(f"{BASE_URL}/api/destinations/does-not-exist/send-recent")
    assert r.status_code == 404


# Fake token: either 400 Telegram error (deals matched) or matched=0 with window
def test_send_recent_fake_token(s, test_dest):
    st = s.get(f"{BASE_URL}/api/stats").json()
    r = s.post(f"{BASE_URL}/api/destinations/{test_dest['id']}/send-recent", timeout=90)
    print(r.status_code, r.text[:300], "fresh", st["fresh_3h"])
    if r.status_code == 400:
        assert "Telegram error" in r.json()["detail"]
    else:
        assert r.status_code == 200
        j = r.json()
        assert set(j) >= {"matched", "sent", "failed", "window_minutes"}
        assert j["sent"] == 0
        assert j["window_minutes"] == st["fresh_window_minutes"]


def test_send_recent_no_match_returns_shape(s):
    # destination filtered to a store that will never match -> matched 0
    r = s.post(f"{BASE_URL}/api/destinations", json={"name": "TEST_iter10_nomatch", "bot_token": FAKE_TOKEN,
                                                      "chat_id": "-1000000000002", "stores": ["TEST_nostore"], "enabled": False})
    did = r.json()["id"]
    try:
        r = s.post(f"{BASE_URL}/api/destinations/{did}/send-recent")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["matched"] == 0 and j["sent"] == 0 and j["failed"] == 0
        assert isinstance(j["window_minutes"], (int, float))
    finally:
        s.delete(f"{BASE_URL}/api/destinations/{did}")


# send-code accepts empty api_id/api_hash (falls back to saved)
def test_send_code_empty_fallback(s):
    cfg = s.get(f"{BASE_URL}/api/settings").json()
    r = s.post(f"{BASE_URL}/api/sankmo/telegram/send-code", json={"api_id": "", "api_hash": "", "phone": "+10000000000"}, timeout=60)
    print(r.status_code, r.text[:300], "saved hash masked:", cfg.get("tg_api_hash_masked"))
    assert r.status_code == 400
    if cfg.get("tg_api_hash_masked"):
        assert "Could not send code" in r.json()["detail"]
    else:
        assert "required" in r.json()["detail"]


def test_send_code_missing_fields_not_422(s):
    r = s.post(f"{BASE_URL}/api/sankmo/telegram/send-code", json={"phone": "+10000000000"}, timeout=60)
    assert r.status_code != 422
