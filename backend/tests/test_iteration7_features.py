import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
API = f"{BASE_URL}/api"
FAKE = "123456:TEST_fake_token_abcdefghijklmnop"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def created(s):
    ids = []
    yield ids
    for i in ids:
        s.delete(f"{API}/destinations/{i}")


# Destinations: create with empty name, strip, required token
def test_create_empty_name_defaults_to_chat(s, created):
    r = s.post(f"{API}/destinations", json={"name": "", "bot_token": f"  {FAKE}  ", "chat_id": "  -100TEST123  "})
    assert r.status_code == 200, r.text
    d = r.json()
    created.append(d["id"])
    assert d["chat_id"] == "-100TEST123"
    assert d["name"] == "-100TEST123"
    assert "bot_token" not in d and d["bot_token_masked"]


def test_create_without_token_400(s):
    r = s.post(f"{API}/destinations", json={"name": "TEST_x", "chat_id": "123"})
    assert r.status_code == 400
    assert "token" in r.json()["detail"].lower()


def test_create_without_chat_id_422(s):
    r = s.post(f"{API}/destinations", json={"name": "TEST_x", "bot_token": FAKE})
    assert r.status_code == 422


def test_create_blank_chat_id(s, created):
    r = s.post(f"{API}/destinations", json={"name": "TEST_blank", "bot_token": FAKE, "chat_id": "   "})
    if r.status_code == 200:
        created.append(r.json()["id"])
    # Report-only: blank chat_id ideally rejected
    print("blank chat_id status:", r.status_code)


# Test message path: fake token -> Unauthorized, NOT field url error
def test_destination_test_fake_token(s, created):
    did = created[0]
    r = s.post(f"{API}/destinations/{did}/test")
    assert r.status_code == 400
    det = r.json()["detail"]
    print(det)
    assert "field url" not in det.lower()
    assert det.startswith("Telegram error:")
    assert "Unauthorized" in det and "bot token is wrong" in det


def test_destination_test_404(s):
    r = s.post(f"{API}/destinations/nonexistent-TEST/test")
    assert r.status_code == 404


# PUT edits, keeps token when empty
def test_update_keeps_token(s, created):
    did = created[0]
    before = [d for d in s.get(f"{API}/destinations").json() if d["id"] == did][0]
    r = s.put(f"{API}/destinations/{did}", json={"name": " TEST_edited ", "bot_token": "", "chat_id": " 999TEST ",
                                                  "categories": ["loot"], "min_discount": 50, "enabled": False})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "TEST_edited" and d["chat_id"] == "999TEST"
    assert d["categories"] == ["loot"] and d["min_discount"] == 50 and d["enabled"] is False
    assert d["bot_token_masked"] == before["bot_token_masked"]
    got = [x for x in s.get(f"{API}/destinations").json() if x["id"] == did][0]
    assert got["name"] == "TEST_edited"
    # token still works for chats lookup (Unauthorized from telegram, not "paste")
    r2 = s.post(f"{API}/telegram/chats", json={"destination_id": did})
    assert r2.status_code == 400
    assert "Telegram error" in r2.json()["detail"]


def test_update_new_token(s, created):
    did = created[0]
    r = s.put(f"{API}/destinations/{did}", json={"name": "TEST_edited", "bot_token": "999:TEST_other_token_zzzzzz", "chat_id": "999TEST"})
    assert r.status_code == 200
    assert r.json()["bot_token_masked"] != ""


def test_update_404(s):
    r = s.put(f"{API}/destinations/nonexistent-TEST", json={"chat_id": "1", "bot_token": ""})
    assert r.status_code == 404


# telegram/chats
def test_chats_empty_400(s):
    r = s.post(f"{API}/telegram/chats", json={})
    assert r.status_code == 400
    assert "token" in r.json()["detail"].lower()


def test_chats_bad_dest_400(s):
    r = s.post(f"{API}/telegram/chats", json={"destination_id": "nonexistent-TEST"})
    assert r.status_code == 400


def test_chats_fake_token(s):
    r = s.post(f"{API}/telegram/chats", json={"bot_token": FAKE})
    assert r.status_code == 400
    assert "Telegram error" in r.json()["detail"]


# Stats
def test_stats_fields(s):
    d = s.get(f"{API}/stats").json()
    for k in ["last_scan_at", "check_interval_seconds", "fresh_3h", "latest_deal_at", "total"]:
        assert k in d, k
    assert isinstance(d["fresh_3h"], int)
    assert isinstance(d["check_interval_seconds"], int)
    print(d)


# Convert with sankmo_api mode
def test_convert_sankmo(s):
    st = s.get(f"{API}/settings").json()
    assert st["convert_mode"] == "sankmo_api"
    r = s.post(f"{API}/convert", json={"url": "https://www.amazon.in/dp/B0CHX1W1XY?tag=abc-21&ref=xyz"})
    assert r.status_code == 200
    d = r.json()
    print(d)
    assert d["error"] and "Sankmo" in d["error"]
    assert d["converted"] == d["cleaned"]
    assert "tag=abc-21" not in d["cleaned"]
