# Iteration 18: multi-link split posts, dedupe fix, client-base, poller
import os, sys, asyncio, time, uuid
from datetime import datetime, timezone
import pytest, requests

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
import server  # noqa: E402

POST_TITLE = "Flipkart: Get 100% Supercoins back on women watches"


# ---- split_post unit tests ----
def _parsed():
    return {"title": "TEST multi", "ext_id": "chan/1", "url": "https://fkrt.co/a1", "categories": ["supercoin_100"]}


def test_split_post_caps_at_10():
    links = [f"https://fkrt.co/x{i}" for i in range(14)]
    parts = server.split_post(_parsed(), "\n".join(f"Watch {i} @ {999+i}\n{l}" for i, l in enumerate(links)), links, {"split_multi": True})
    assert len(parts) == 10
    assert [p["split_index"] for p in parts] == list(range(1, 11))
    assert all(p["split_total"] == 10 and p["split"] and p["post_title"] == "TEST multi" for p in parts)
    assert parts[0]["ext_id"] == "chan/1#0" and parts[9]["ext_id"] == "chan/1#9"


def test_split_post_single_link_not_split():
    p = _parsed()
    parts = server.split_post(p, "Deal https://fkrt.co/a1 and https://t.me/chan https://example.com/x", ["https://fkrt.co/a1"], {"split_multi": True})
    assert len(parts) == 1 and not parts[0].get("split")


def test_split_post_disabled():
    links = ["https://fkrt.co/a1", "https://fkrt.co/a2", "https://fkrt.co/a3"]
    parts = server.split_post(_parsed(), " ".join(links), links, {"split_multi": False})
    assert len(parts) == 1 and not parts[0].get("split")


def test_split_post_default_true_when_missing():
    links = ["https://fkrt.co/a1", "https://fkrt.co/a2"]
    assert len(server.split_post(_parsed(), " ".join(links), links, {})) == 2


def test_split_post_prices_per_link():
    text = "Titan A @ 1299\nhttps://fkrt.co/a1\nTitan B @ 2499\nhttps://fkrt.co/a2"
    parts = server.split_post(_parsed(), text, ["https://fkrt.co/a1", "https://fkrt.co/a2"], {"split_multi": True})
    print([(p["url"], p["price"]) for p in parts])
    assert parts[0]["price"] == 1299 and parts[1]["price"] == 2499


# ---- dedupe (ingest) ----
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.new_event_loop().run_until_complete(coro)


async def _ingest_cases():
    from motor.motor_asyncio import AsyncIOMotorClient
    server.db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    db = server.db
    tag = uuid.uuid4().hex[:8]
    title = f"TEST_dedupe {tag} same title"
    src_a = {"id": f"TEST_src_a_{tag}", "name": "TEST A"}
    src_b = {"id": f"TEST_src_b_{tag}", "name": "TEST B"}
    settings = {"split_multi": True, "website_max_age_hours": 24}
    nowiso = datetime.now(timezone.utc).isoformat()

    def item(i):
        return {"title": title, "url": f"https://example.org/{tag}/p{i}", "ext_id": f"{tag}/{i}", "posted_at": nowiso,
                "categories": ["loot"], "store": "Other", "text": title, "image": "https://example.org/i.jpg"}
    out = {}
    try:
        out["first"] = bool(await server.ingest(item(1), src_a, settings, autopost=False))
        out["same_src_new_link"] = bool(await server.ingest(item(2), src_a, settings, autopost=False))
        out["other_src_same_title"] = bool(await server.ingest(item(3), src_b, settings, autopost=False))
        dup = item(1); dup["ext_id"] = f"{tag}/dupurl"
        out["other_src_same_url"] = bool(await server.ingest(dup, src_b, settings, autopost=False))
    finally:
        await db.deals.delete_many({"source_id": {"$in": [src_a["id"], src_b["id"]]}})
        await db.seen.delete_many({"key": {"$regex": f"^TEST_src_.*{tag}"}})
    return out


def test_ingest_dedupe_rules():
    out = _run(_ingest_cases())
    print(out)
    assert out["first"] is True
    assert out["same_src_new_link"] is True, "same channel, same title, new link should be accepted"
    assert out["other_src_same_title"] is False, "different source, same title within 6h must be deduped"
    assert out["other_src_same_url"] is False, "same clean_url must be deduped"


# ---- API ----
def test_brogity_split_deals_api():
    r = requests.get(f"{BASE_URL}/api/deals", params={"q": "Titan", "limit": 200}, timeout=30)
    assert r.status_code == 200
    r2 = requests.get(f"{BASE_URL}/api/deals", params={"q": "FOSSIL Laney", "limit": 50}, timeout=30)
    deals = [d for d in r.json() + r2.json() if d.get("source") == "@brogity" and d.get("split")
             and d.get("posted_at", "").startswith("2026-10-31T04:55")]
    by_idx = {d["split_index"]: d for d in deals}
    print({k: (v["title"], v.get("price"), v.get("affiliate_url")) for k, v in by_idx.items()})
    assert set(by_idx) == {1, 2, 3, 4, 5}
    titles = {d["title"] for d in by_idx.values()}
    assert len(titles) == 5 and POST_TITLE not in titles
    for d in by_idx.values():
        assert d["image"] and d["image"].startswith("http")
        assert d.get("price")
        assert d["affiliate_url"].startswith("https://fkrt.site/")
        assert "supercoin_100" in d["categories"]
        assert d["post_title"] == POST_TITLE and d["split_total"] == 5


def test_client_base():
    r = requests.post(f"{BASE_URL}/api/client-base", json={"text": "", "base": "not-a-url"}, timeout=15)
    assert r.status_code == 200 and r.json()["ok"] is False
    r = requests.post(f"{BASE_URL}/api/client-base", json={"text": "", "base": "http://insecure.com"}, timeout=15)
    assert r.json()["ok"] is False
    r = requests.post(f"{BASE_URL}/api/client-base", json={"text": "", "base": BASE_URL + "/"}, timeout=15)
    assert r.json()["ok"] is True
    from pymongo import MongoClient
    s = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]].settings.find_one({"id": "main"})
    assert s["public_base"] == BASE_URL


def test_split_multi_setting_roundtrip():
    r = requests.put(f"{BASE_URL}/api/settings", json={"split_multi": False}, timeout=15)
    assert r.status_code == 200
    try:
        assert requests.get(f"{BASE_URL}/api/settings", timeout=15).json()["split_multi"] is False
    finally:
        requests.put(f"{BASE_URL}/api/settings", json={"split_multi": True}, timeout=15)
    assert requests.get(f"{BASE_URL}/api/settings", timeout=15).json()["split_multi"] is True


def test_poller_last_scan_updates():
    a = requests.get(f"{BASE_URL}/api/stats", timeout=30).json()["last_scan_at"]
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(a)).total_seconds()
    print("last_scan_at", a, "age", age)
    assert age < 600
    deadline = time.time() + 100
    while time.time() < deadline:
        time.sleep(10)
        b = requests.get(f"{BASE_URL}/api/stats", timeout=30).json()["last_scan_at"]
        if b != a:
            return
    pytest.fail("last_scan_at did not change in 100s")
