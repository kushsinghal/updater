# Unit check (run directly with python): ingest() age filters - website_max_age_hours drop & telegram_max_age_minutes autopost gate
import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta
sys.path.insert(0, "/app/backend")
import server  # noqa: E402

calls = []


async def fake_post(deal, dest_id=None):
    calls.append(deal["title"])
    return [{"status": "success", "destination_name": "x"}]


async def fake_clean(u):
    return u


async def main():
    server.post_deal = fake_post
    server.engine.clean_link = fake_clean
    server.safe_convert = lambda u, s: asyncio.sleep(0, result=u)
    settings = {**server.DEFAULT_SETTINGS, "auto_post": True}
    src = {"id": "TEST_src", "name": "TEST_src"}
    ago = lambda m: (datetime.now(timezone.utc) - timedelta(minutes=m)).isoformat()
    tag = uuid.uuid4().hex[:6]
    cases = [("fresh", 5), ("hour_old", 120), ("day_old", 60 * 30), ("noage", None)]
    out = {}
    for name, m in cases:
        p = {"title": f"TEST_{tag}_{name}", "url": f"https://example.com/{tag}/{name}", "price": 10, "categories": ["loot"],
             "ext_id": f"{tag}{name}", "posted_at": ago(m) if m is not None else None}
        out[name] = await server.ingest(p, src, settings, autopost=True, budget={"left": 5})
    print("saved:", {k: bool(v) for k, v in out.items()})
    print("posted:", [c.split("_", 2)[2] for c in calls])
    await server.db.deals.delete_many({"source_id": "TEST_src"})
    await server.db.seen.delete_many({"key": {"$regex": "^TEST_src:"}})
    await server.db.price_history.delete_many({"source": "TEST_src"})


asyncio.run(main())
