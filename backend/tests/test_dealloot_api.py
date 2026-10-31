# DealLoot API regression tests: deals, sources, destinations, settings, sankmo convert, logs, cron
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
CRON_SECRET = _env("/app/backend/.env", "WEBHOOK_CRON_SECRET")
FAKE_TOKEN = "123456789:TEST_FAKE_TOKEN_ABCDEFGHIJ"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


@pytest.fixture(scope="module")
def created():
    data = {"sources": [], "dests": [], "deals": []}
    yield data
    for sid in data["sources"]:
        requests.delete(f"{API}/sources/{sid}")
    for did in data["dests"]:
        requests.delete(f"{API}/destinations/{did}")
    for did in data["deals"]:
        requests.delete(f"{API}/deals/{did}")


# Health + public deals
class TestDeals:
    def test_root(self, s):
        r = s.get(f"{API}/")
        assert r.status_code == 200 and r.json()["message"] == "DealLoot API"

    def test_list_deals_no_id(self, s):
        r = s.get(f"{API}/deals")
        assert r.status_code == 200
        for d in r.json():
            assert "_id" not in d and "dedupe_key" not in d

    @pytest.mark.parametrize("cat", ["supercoin_100", "gift_card", "heavy_discount", "loot"])
    def test_category_filter(self, s, cat):
        r = s.get(f"{API}/deals", params={"category": cat})
        assert r.status_code == 200
        assert all(cat in d["categories"] for d in r.json())

    def test_sort_discount(self, s):
        r = s.get(f"{API}/deals", params={"sort": "discount"})
        vals = [d.get("discount") or 0 for d in r.json()]
        assert vals == sorted(vals, reverse=True)

    def test_search_special_chars_no_500(self, s):
        r = s.get(f"{API}/deals", params={"q": "(abc"})
        assert r.status_code == 200, f"regex not escaped: {r.status_code}"

    def test_stats(self, s):
        r = s.get(f"{API}/stats")
        assert r.status_code == 200
        for k in ["total", "supercoin_100", "gift_card", "heavy_discount", "loot", "sources", "destinations", "posts_sent"]:
            assert isinstance(r.json()[k], int)


# Sources CRUD + fetch
class TestSources:
    def test_seeded_and_duplicate(self, s):
        vals = [x["value"] for x in s.get(f"{API}/sources").json()]
        assert "dealsxpert" in vals
        r = s.post(f"{API}/sources", json={"value": "dealsxpert"})
        assert r.status_code == 400 and "already" in r.json()["detail"]
        r = s.post(f"{API}/sources", json={"value": "https://t.me/s/dealsxpert"})
        assert r.status_code == 400

    def test_add_toggle_fetch_delete(self, s, created):
        r = s.post(f"{API}/sources", json={"value": "https://t.me/TEST_nonexistent_chan_xyz", "kind": "telegram"})
        assert r.status_code == 200
        src = r.json()
        created["sources"].append(src["id"])
        assert src["value"] == "TEST_nonexistent_chan_xyz" and src["name"] == "@TEST_nonexistent_chan_xyz"
        r = s.put(f"{API}/sources/{src['id']}", json={**src, "enabled": False})
        assert r.status_code == 200 and r.json()["enabled"] is False
        r = s.post(f"{API}/sources/{src['id']}/fetch")
        assert r.status_code == 200
        assert set(r.json()) >= {"fetched", "new_deals", "error"}
        r = s.delete(f"{API}/sources/{src['id']}")
        assert r.status_code == 200
        assert src["id"] not in [x["id"] for x in s.get(f"{API}/sources").json()]

    def test_fetch_seeded_source(self, s):
        src = next(x for x in s.get(f"{API}/sources").json() if x["value"] == "dealsxpert")
        r = s.post(f"{API}/sources/{src['id']}/fetch", timeout=90)
        assert r.status_code == 200
        d = r.json()
        print("dealsxpert fetch:", d)
        assert isinstance(d["fetched"], int) and isinstance(d["new_deals"], int)

    def test_fetch_missing_404(self, s):
        assert s.post(f"{API}/sources/nope/fetch").status_code == 404


# Destinations: masking, edit-keeps-token, test with fake token
class TestDestinations:
    def test_requires_token(self, s):
        r = s.post(f"{API}/destinations", json={"name": "TEST_x", "chat_id": "@x"})
        assert r.status_code == 400

    def test_crud_masked(self, s, created):
        r = s.post(f"{API}/destinations", json={"name": "TEST_Dest", "bot_token": FAKE_TOKEN, "chat_id": "@test_chan",
                                                  "categories": [], "min_discount": 0, "stores": []})
        assert r.status_code == 200
        d = r.json()
        created["dests"].append(d["id"])
        assert "bot_token" not in d and d["bot_token_masked"] == "1234••••GHIJ"
        lst = s.get(f"{API}/destinations").json()
        for x in lst:
            assert "bot_token" not in x and "_id" not in x
        # edit with empty token keeps token
        r = s.put(f"{API}/destinations/{d['id']}", json={"name": "TEST_Dest2", "bot_token": "", "chat_id": "@test_chan",
                                                         "categories": ["loot"], "min_discount": 10, "stores": []})
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_Dest2" and r.json()["bot_token_masked"] == "1234••••GHIJ"
        assert r.json()["categories"] == ["loot"]
        # test send with fake token -> 400 telegram error
        r = s.post(f"{API}/destinations/{d['id']}/test")
        assert r.status_code == 400 and "Telegram error" in r.json()["detail"]

    def test_update_missing_404(self, s):
        r = s.put(f"{API}/destinations/nope", json={"name": "x", "chat_id": "x"})
        assert r.status_code == 404


# Settings + Sankmo
class TestSettings:
    def test_rules_persist(self, s):
        orig = s.get(f"{API}/settings").json()
        assert "sankmo_token" not in orig
        r = s.put(f"{API}/settings", json={"giftcard_min": 7, "product_min": 75})
        assert r.status_code == 200
        g = s.get(f"{API}/settings").json()
        assert g["giftcard_min"] == 7 and g["product_min"] == 75
        s.put(f"{API}/settings", json={"giftcard_min": orig["giftcard_min"], "product_min": orig["product_min"]})

    def test_sankmo_token_masked_and_convert(self, s):
        # NOTE: never overwrite the real saved sankmo_token (user data); only verify empty keeps it
        orig = s.get(f"{API}/settings").json()
        assert "sankmo_token" not in orig
        r = s.put(f"{API}/settings", json={"sankmo_token": ""})
        assert r.status_code == 200 and r.json()["sankmo_token_masked"] == orig["sankmo_token_masked"]
        url = "https://www.flipkart.com/item/p/abc"
        r = s.post(f"{API}/convert", json={"url": url})
        assert r.status_code == 200
        assert r.json()["converted"] == url and r.json()["changed"] is False
        s.put(f"{API}/settings", json={"sankmo_api_url": orig.get("sankmo_api_url", "")})


# Manual deal add + failed post log
class TestManualAdd:
    def test_manual_deal_and_log(self, s, created):
        r = s.post(f"{API}/destinations", json={"name": "TEST_ManualDest", "bot_token": FAKE_TOKEN, "chat_id": "@test_chan"})
        did = r.json()["id"]
        created["dests"].append(did)
        r = s.post(f"{API}/deals", json={"url": "https://www.flipkart.com/test-item/p/xyz", "title": "TEST_ Manual Deal",
                                           "price": 100, "mrp": 1000, "post_now": True}, timeout=60)
        assert r.status_code == 200
        body = r.json()
        deal = body["deal"]
        created["deals"].append(deal["id"])
        assert deal["discount"] == 90.0 and "heavy_discount" in deal["categories"] and deal["store"] == "Flipkart"
        assert "_id" not in deal
        mine = [x for x in body["post_results"] if x["destination_id"] == did]
        assert mine and mine[0]["status"] == "failed" and mine[0]["error"]
        lst = s.get(f"{API}/deals", params={"q": "TEST_ Manual"}).json()
        assert any(x["id"] == deal["id"] for x in lst)
        logs = s.get(f"{API}/logs").json()
        assert any(l["deal_id"] == deal["id"] and l["status"] == "failed" for l in logs)

    def test_repost_404(self, s):
        assert s.post(f"{API}/deals/nope/post").status_code == 404


# Cron auth
class TestCron:
    def test_no_auth(self, s):
        assert s.post(f"{API}/cron/fetch").status_code == 401

    def test_wrong(self, s):
        assert s.post(f"{API}/cron/fetch", headers={"Authorization": "Bearer wrong"}).status_code == 401

    def test_ok_and_dedupe(self, s):
        import uuid
        rid = f"TEST_{uuid.uuid4()}"
        h = {"Authorization": f"Bearer {CRON_SECRET}", "X-Webhook-Id": rid}
        r = s.post(f"{API}/cron/fetch", headers=h)
        assert r.status_code == 200 and r.json()["accepted"] is True
        r = s.post(f"{API}/cron/fetch", headers=h)
        assert r.status_code == 200 and r.json().get("duplicate") is True
