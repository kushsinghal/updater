# Iteration 4: time sort on every tab, original post url, dealsmagnet resolution, new sources, find chats, undated items
import os
import sys
import asyncio
import pytest
import requests
from pathlib import Path

BASE_URL = None
for line in Path("/app/frontend/.env").read_text().splitlines():
    if line.startswith("REACT_APP_BACKEND_URL="):
        BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"
NEW_SOURCES = ["dealsmagnet", "desidime_deals", "iamprasadtech", "Loot_DealsX", "indianlootdeals",
               "dealsindia_official", "brogity", "techamanTG"]


@pytest.fixture(scope="module")
def s():
    return requests.Session()


def is_desc(deals):
    ts = [d.get("posted_at") for d in deals]
    return all(ts[i] >= ts[i + 1] for i in range(len(ts) - 1))


# Sorting by posted_at desc on every category
class TestSorting:
    @pytest.mark.parametrize("cat", ["all", "best", "supercoin_100", "gift_card", "heavy_discount", "loot", "starred", "lowest", None])
    def test_category_sorted_desc(self, s, cat):
        params = {"category": cat} if cat else {}
        r = s.get(f"{API}/deals", params=params)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d, list)
        assert all(x.get("posted_at") for x in d), "deal without posted_at"
        assert is_desc(d), f"{cat} not sorted desc"

    def test_best_has_items(self, s):
        d = s.get(f"{API}/deals", params={"category": "best"}).json()
        assert len(d) <= 40
        for x in d:
            assert x.get("featured") or x.get("score", 0) >= 100


# Original post url
class TestOriginalPost:
    def test_all_scraped_deals_have_source_post_url(self, s):
        d = s.get(f"{API}/deals", params={"limit": 500}).json()
        scraped = [x for x in d if x.get("source_id") != "manual"]
        assert scraped
        for x in scraped:
            u = x.get("source_post_url")
            assert u and u.startswith("http"), x["id"]
            if "rss" not in (x.get("source") or "") and not (x.get("source") or "").startswith("http"):
                assert u.startswith("https://t.me/"), u
                tail = u.replace("https://t.me/", "")
                ch, pid = tail.split("/")
                assert pid.isdigit()


# dealsmagnet resolution
class TestDealsmagnet:
    def test_clean_url_resolved(self, s):
        d = s.get(f"{API}/deals", params={"limit": 500}).json()
        dm = [x for x in d if (x.get("source") or "").lower() == "@dealsmagnet"]
        if not dm:
            pytest.skip("no dealsmagnet deals currently")
        bad = [x["clean_url"] for x in dm if "dealsmagnet.com/deal" in x["clean_url"]]
        assert not bad, bad
        stores = [x for x in dm if x["store"] in ("Amazon", "Flipkart")]
        assert len(stores) >= len(dm) * 0.7

    def test_clean_url_has_no_dealsmagnet_path(self, s):
        d = s.get(f"{API}/deals", params={"limit": 500}).json()
        bad = [x["clean_url"] for x in d if "dealsmagnet.com" in x["clean_url"]]
        assert not bad, f"clean_url still contains dealsmagnet.com path: {bad}"

    def test_resolve_function_live(self):
        sys.path.insert(0, "/app/backend")
        import engine
        d = requests.get(f"{API}/deals", params={"limit": 500}).json()
        texts = [x["text"] for x in d if "dealsmagnet.com/deal/" in (x.get("text") or "")]
        if not texts:
            pytest.skip("no dealsmagnet deal link")
        import re
        m = re.search(r'(?:https?://)?(?:www\.)?dealsmagnet\.com/deal/[\w-]+', texts[0])
        url = m.group(0)
        if not url.startswith("http"):
            url = "https://" + url
        out, img = asyncio.run(engine.resolve_dealsmagnet(url))
        assert "dealsmagnet.com/deal" not in out
        assert engine.detect_store(out) in ("Amazon", "Flipkart", "Myntra", "Ajio", "Croma") or out.startswith("http")


# Sources
class TestSources:
    def test_22_sources_with_new(self, s):
        d = s.get(f"{API}/sources").json()
        assert len(d) == 22
        vals = {x["value"].lower() for x in d}
        for n in NEW_SOURCES:
            assert n.lower() in vals, n
        errs = [(x["value"], x["last_error"]) for x in d if x.get("last_error")]
        assert not errs, errs


# Find chat id
class TestFindChats:
    def test_fake_token_400(self, s):
        r = s.post(f"{API}/telegram/chats", json={"bot_token": "123456:FAKE_TOKEN_abcdef"})
        assert r.status_code == 400
        assert r.json().get("detail")

    def test_empty_token_400(self, s):
        r = s.post(f"{API}/telegram/chats", json={"bot_token": ""})
        assert r.status_code == 400

    def test_missing_token_422(self, s):
        r = s.post(f"{API}/telegram/chats", json={})
        assert r.status_code == 422


# Manual add + undated skip
class TestManualAndUndated:
    def test_manual_add_sets_posted_at(self, s):
        r = s.post(f"{API}/deals", json={"url": "https://www.amazon.in/dp/B0TESTI4X1", "title": "TEST_iter4 manual deal",
                                          "price": 999, "mrp": 4999, "post_now": False})
        assert r.status_code == 200
        deal = r.json()["deal"]
        try:
            assert deal["posted_at"]
            assert deal["source"] == "Manual"
            assert not deal.get("source_post_url")
            lst = s.get(f"{API}/deals", params={"q": "TEST_iter4"}).json()
            assert any(x["id"] == deal["id"] for x in lst)
        finally:
            s.delete(f"{API}/deals/{deal['id']}")
        assert s.delete(f"{API}/deals/{deal['id']}").status_code == 404

    def test_undated_item_skipped(self):
        sys.path.insert(0, "/app/backend")
        os.chdir("/app/backend")
        import server

        async def run():
            parsed = {"title": "TEST_undated", "text": "x", "url": "https://www.amazon.in/dp/B0UNDATED1", "store": "Amazon",
                      "price": None, "mrp": None, "discount": 80, "categories": ["heavy_discount"], "image": None,
                      "ext_id": "TEST_undated_ext", "posted_at": None}
            src = {"id": "TEST_src", "name": "TEST"}
            res = await server.ingest(parsed, src, dict(server.DEFAULT_SETTINGS), autopost=False)
            await server.db.seen.delete_many({"key": {"$regex": "^TEST_src:"}})
            return res
        assert asyncio.run(run()) is None
