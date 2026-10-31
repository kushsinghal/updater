from fastapi import FastAPI, APIRouter, HTTPException, Request, BackgroundTasks, Response
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import asyncio
import hmac
import logging
import uuid
import httpx
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta

import engine
import pricehist
import tgconv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME']]
app = FastAPI()
api = APIRouter(prefix="/api")
logger = logging.getLogger("deals")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

NO_ID = {"_id": 0}
BULK_MAX = 5
DEFAULT_SETTINGS = {
    "id": "main", "auto_post": True, "supercoin_enabled": True, "giftcard_enabled": True, "giftcard_min": 5,
    "product_enabled": True, "product_min": 70, "loot_enabled": True, "keywords": [],
    "convert_enabled": True, "sankmo_api_url": "", "sankmo_token": "",
    "convert_mode": "sankmo_api", "sankmo_bot": "sankmo_bot", "tg_api_id": "", "tg_api_hash": "", "tg_phone": "",
    "tg_session": "", "tg_user": "", "check_interval_minutes": 15, "check_interval_seconds": 60, "post_style": "simple", "max_posts_per_update": 20,
    "website_max_age_hours": 24, "telegram_max_age_minutes": 60, "last_run_at": None, "amazon_tag": "",
}
SEED_SOURCES = ["dealsxpert", "TrickXpert", "lootdealsofficial", "desidime", "coolztricks", "omgdeals", "flipshope",
                "cooloffersofficial", "dealsheaven", "GiftCardLoot", "TricksByStg", "freekamaal", "dealzarena"]
SEED_RSS = ["https://www.coolztricks.com/feed"]


def now():
    return datetime.now(timezone.utc).isoformat()


def mask(t):
    return f"{t[:4]}••••{t[-4:]}" if t and len(t) > 10 else ("••••" if t else "")


class SourceIn(BaseModel):
    name: Optional[str] = None
    kind: str = "telegram"
    value: str
    enabled: bool = True


class DestinationIn(BaseModel):
    name: str = ""
    bot_token: Optional[str] = None
    chat_id: str
    categories: List[str] = []
    min_discount: float = 0
    stores: List[str] = []
    enabled: bool = True


class SettingsIn(BaseModel):
    auto_post: Optional[bool] = None
    supercoin_enabled: Optional[bool] = None
    giftcard_enabled: Optional[bool] = None
    giftcard_min: Optional[float] = None
    product_enabled: Optional[bool] = None
    product_min: Optional[float] = None
    loot_enabled: Optional[bool] = None
    keywords: Optional[List[str]] = None
    convert_enabled: Optional[bool] = None
    sankmo_api_url: Optional[str] = None
    sankmo_token: Optional[str] = None
    convert_mode: Optional[str] = None
    sankmo_bot: Optional[str] = None
    check_interval_minutes: Optional[int] = None
    check_interval_seconds: Optional[int] = None
    post_style: Optional[Literal["simple", "detailed"]] = None
    website_max_age_hours: Optional[float] = None
    telegram_max_age_minutes: Optional[float] = None
    max_posts_per_update: Optional[int] = None
    amazon_tag: Optional[str] = None


class BulkIn(BaseModel):
    text: str


class TgCodeIn(BaseModel):
    api_id: str = ""
    api_hash: str = ""
    phone: str


class TgVerifyIn(BaseModel):
    code: str
    password: Optional[str] = None


class FeatureIn(BaseModel):
    featured: bool


class DealIn(BaseModel):
    url: str
    title: Optional[str] = None
    price: Optional[float] = None
    mrp: Optional[float] = None
    discount: Optional[float] = None
    categories: Optional[List[str]] = None
    image: Optional[str] = None
    note: Optional[str] = None
    post_now: bool = True


class ConvertIn(BaseModel):
    url: str


async def get_settings():
    s = await db.settings.find_one({"id": "main"}, NO_ID)
    if not s:
        s = dict(DEFAULT_SETTINGS)
        await db.settings.insert_one(dict(s))
    return {**DEFAULT_SETTINGS, **s}


async def safe_convert(url, settings):
    try:
        return await engine.convert_link(url, settings)
    except Exception as e:
        logger.warning(f"Link conversion failed: {e}")
        if "login expired" in str(e):
            await db.settings.update_one({"id": "main"}, {"$set": {"tg_expired": True}})
        return url


def dest_matches(dest, deal):
    cats = set(deal.get("categories") or [])
    if not cats:
        return False
    if dest.get("categories") and not cats & set(dest["categories"]):
        return False
    if dest.get("stores") and deal.get("store") not in dest["stores"]:
        return False
    min_d = dest.get("min_discount") or 0
    if min_d and not cats & {"supercoin_100", "loot"} and (deal.get("discount") or 0) < min_d:
        return False
    return True


async def post_deal(deal, dest_id=None):
    query = {"id": dest_id} if dest_id else {"enabled": True}
    dests = await db.destinations.find(query, NO_ID).to_list(100)
    text = engine.format_message(deal, (await get_settings()).get("post_style", "simple"))
    results = []
    for d in dests:
        if not dest_id and not dest_matches(d, deal):
            continue
        log = {"id": str(uuid.uuid4()), "deal_id": deal["id"], "deal_title": deal["title"],
               "destination_id": d["id"], "destination_name": d["name"], "url": deal.get("affiliate_url"),
               "created_at": now()}
        try:
            await engine.send_telegram(d["bot_token"], d["chat_id"], text, deal.get("image"), deal)
            log["status"] = "success"
            log["error"] = None
        except Exception as e:
            log["status"] = "failed"
            log["error"] = str(e)[:300]
        await db.logs.insert_one(dict(log))
        log.pop("_id", None)
        results.append(log)
    sent = [r["destination_name"] for r in results if r["status"] == "success"]
    if sent:
        await db.deals.update_one({"id": deal["id"]}, {"$addToSet": {"posted_to": {"$each": sent}}})
    return results


def age_minutes(iso):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60
    except (TypeError, ValueError):
        return 0


async def record_price(deal):
    """Store a price point and work out whether this is the lowest price seen for the product."""
    if not deal.get("price"):
        return
    prev = await db.price_history.find({"product_key": deal["product_key"]}, NO_ID).to_list(500)
    await db.price_history.insert_one({"product_key": deal["product_key"], "price": deal["price"], "mrp": deal.get("mrp"),
                                       "store": deal.get("store"), "source": deal.get("source"), "at": deal["posted_at"]})
    prices = [p["price"] for p in prev if p.get("price")]
    deal["history_count"] = len(prices) + 1
    deal["lowest_seen"] = min(prices + [deal["price"]])
    deal["highest_seen"] = max(prices + [deal["price"]])
    deal["lowest_ever"] = bool(prices) and deal["price"] < min(prices)
    if deal["lowest_ever"]:
        await db.deals.update_many({"product_key": deal["product_key"]}, {"$set": {"lowest_ever": False}})


_ph_sem = asyncio.Semaphore(3)


async def ph_data(url, max_age_hours=6):
    if not pricehist.supported(url):
        return None
    cached = await db.ph_cache.find_one({"url": url}, NO_ID)
    if cached and age_minutes(cached.get("fetched_at")) < max_age_hours * 60:
        return cached.get("data")
    async with _ph_sem:
        try:
            data = await pricehist.lookup(url)
        except Exception as e:
            logger.warning(f"pricehistory failed for {url}: {e}")
            return cached.get("data") if cached else None
    await db.ph_cache.update_one({"url": url}, {"$set": {"url": url, "data": data, "fetched_at": now()}}, upsert=True)
    return data


async def enrich(deal_id):
    """Add full store price history, missing price/image and the lowest-ever flag."""
    d = await db.deals.find_one({"id": deal_id}, NO_ID)
    if not d:
        return
    ph = await ph_data(d["clean_url"])
    upd = {"ph_checked": True}
    if d.get("store") == "Other" and engine.detect_store(d["clean_url"]) != "Other":
        upd["store"] = engine.detect_store(d["clean_url"])
    if ph:
        if ph.get("name") and len(re.sub(r"[^A-Za-z]", "", d.get("title", ""))) < 14:
            upd["title"] = ph["name"]
        upd.update({"ph_min": ph.get("min"), "ph_max": ph.get("max"), "ph_avg": ph.get("avg"), "ph_url": ph.get("page_url")})
        if not d.get("image") and ph.get("image"):
            upd["image"] = ph["image"]
        price = d.get("price") or ph.get("price")
        ref = ph.get("min") or ph.get("price")
        if d.get("price") and ref and d["price"] < ref * 0.3:
            price = None
            upd["price"] = ph.get("price")
            upd["lowest_ever"] = False
        elif not d.get("price") and ph.get("price"):
            upd["price"] = ph["price"]
            if ph.get("mrp") and ph["mrp"] > ph["price"]:
                upd["mrp"] = ph["mrp"]
                upd["discount"] = max(d.get("discount") or 0, round((1 - ph["price"] / ph["mrp"]) * 100, 1))
        if price and ph.get("min"):
            upd["lowest_ever"] = price <= ph["min"]
    await db.deals.update_one({"id": deal_id}, {"$set": upd})


async def backfill_enrich():
    async for d in db.deals.find({"ph_checked": {"$ne": True}}, {"_id": 0, "id": 1}).sort("posted_at", -1):
        await enrich(d["id"])


async def ingest(parsed, source, settings, autopost, budget=None):
    key = f"{source['id']}:{parsed.pop('ext_id', None) or parsed['url']}"
    if await db.seen.find_one({"key": key}, {"_id": 1}):
        return None
    await db.seen.insert_one({"key": key, "at": now()})
    raw_posted = parsed.pop("posted_at", None)
    if not raw_posted and source["id"] != "manual":
        return None
    posted_at = raw_posted or now()
    if source["id"] != "manual" and age_minutes(posted_at) > settings.get("website_max_age_hours", 24) * 60:
        return None
    deal = {**parsed, "id": str(uuid.uuid4()), "dedupe_key": key, "source": source.get("name"),
            "source_id": source["id"], "posted_to": [], "created_at": now(), "posted_at": posted_at}
    if "dealsmagnet.com/deal" in deal["url"]:
        try:
            deal["url"], dm_img = await engine.resolve_dealsmagnet(deal["url"])
            deal["image"] = deal.get("image") or dm_img
            deal["store"] = engine.detect_store(deal["url"], deal.get("text", ""))
        except Exception as e:
            logger.warning(f"dealsmagnet resolve failed: {e}")
    deal["clean_url"] = await engine.clean_link(deal["url"])
    if deal.get("store") == "Other":
        deal["store"] = engine.detect_store(deal["clean_url"], deal.get("text", ""))
    since = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    deal["title_key"] = re.sub(r"[^a-z0-9]", "", deal["title"].lower())[:60]
    deal["product_key"] = engine.product_key(deal["clean_url"])
    dup = [{"clean_url": deal["clean_url"]}, {"title_key": deal["title_key"]}]
    if deal["product_key"]:
        dup.append({"product_key": deal["product_key"], "price": deal.get("price")})
    if source["id"] != "manual" and await db.deals.find_one({"$or": dup, "created_at": {"$gte": since}}, {"_id": 1}):
        return None
    if not deal.get("image") and "flipkart" not in deal["clean_url"]:
        deal["image"] = await engine.fetch_og_image(deal["clean_url"])
    await record_price(deal)
    deal["affiliate_url"] = await safe_convert(deal["clean_url"], settings)
    deal["converted"] = deal["affiliate_url"] != deal["clean_url"]
    deal["featured"] = False
    deal["score"] = engine.score(deal)
    await db.deals.insert_one(dict(deal))
    deal.pop("_id", None)
    asyncio.create_task(enrich(deal["id"]))
    fresh = (raw_posted or source["id"] == "manual") and age_minutes(posted_at) <= settings.get("telegram_max_age_minutes", 60)
    if autopost and fresh and settings.get("auto_post") and (budget is None or budget["left"] > 0):
        results = await post_deal(deal)
        if budget is not None and results:
            budget["left"] -= 1
    return deal


async def fetch_source(src, budget=None):
    settings = await get_settings()
    try:
        items = await (engine.fetch_telegram(src["value"]) if src["kind"] == "telegram"
                       else engine.fetch_web(src["value"]) if src["kind"] == "web" else engine.fetch_rss(src["value"]))
    except Exception as e:
        await db.sources.update_one({"id": src["id"]}, {"$set": {"last_error": str(e)[:200], "last_fetched_at": now()}})
        return {"fetched": 0, "new_deals": 0, "error": str(e)[:200]}
    new = 0
    for it in items:
        parsed = engine.parse_item(it["text"], it["links"], it["image"], settings)
        if not parsed or not parsed["categories"]:
            continue
        parsed["ext_id"] = it["ext_id"]
        parsed["posted_at"] = it.get("posted_at")
        parsed["source_post_url"] = it.get("post_url")
        if it.get("title"):
            parsed["title"] = it["title"][:140]
        if await ingest(parsed, src, settings, autopost=True, budget=budget):
            new += 1
    await db.sources.update_one({"id": src["id"]}, {"$set": {"last_fetched_at": now(), "last_error": None},
                                                    "$inc": {"total_deals": new}})
    return {"fetched": len(items), "new_deals": new, "error": None}


_fetch_lock = asyncio.Lock()


async def fetch_all(force=False):
    if _fetch_lock.locked():
        return
    async with _fetch_lock:
        settings = await get_settings()
        await db.settings.update_one({"id": "main"}, {"$set": {"last_run_at": now()}})
        budget = {"left": int(settings.get("max_posts_per_update") or 20)}
        srcs = await db.sources.find({"enabled": True}, NO_ID).to_list(200)
        sem = asyncio.Semaphore(6)

        async def one(s):
            async with sem:
                await fetch_source(s, budget)
        await asyncio.gather(*(one(s) for s in srcs))


async def poller():
    while True:
        settings = await get_settings()
        secs = int(settings.get("check_interval_seconds") or 60)
        try:
            await fetch_all()
        except Exception as e:
            logger.error(f"Poller error: {e}")
        await asyncio.sleep(max(secs, 30))


# ---------- Deals ----------
@api.get("/deals")
async def list_deals(category: Optional[str] = None, q: Optional[str] = None, store: Optional[str] = None,
                     sort: str = "latest", limit: int = 120):
    query = {}
    proj = {**NO_ID, "dedupe_key": 0}
    if category == "best":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        query["$or"] = [{"featured": True}, {"posted_at": {"$gte": cutoff}, "score": {"$gte": 100}}]
        if q:
            query["$and"] = [{"$or": [{"title": {"$regex": re.escape(q), "$options": "i"}},
                                      {"store": {"$regex": re.escape(q), "$options": "i"}}]}]
        return await db.deals.find(query, proj).sort([("posted_at", -1)]).to_list(40)
    if category == "starred":
        query["featured"] = True
    elif category == "lowest":
        query["lowest_ever"] = True
    elif category and category != "all":
        query["categories"] = category
    if store:
        query["store"] = store
    if q:
        rq = re.escape(q)
        query["$or"] = [{"title": {"$regex": rq, "$options": "i"}}, {"store": {"$regex": rq, "$options": "i"}}]
    if sort == "price":
        query["price"] = {"$ne": None}
    sort_map = {"latest": [("posted_at", -1)], "discount": [("discount", -1)], "price": [("price", 1)],
                "starred": [("featured", -1), ("posted_at", -1)]}
    return await db.deals.find(query, proj).sort(sort_map.get(sort, sort_map["latest"])).to_list(min(limit, 500))


@api.get("/deals/{deal_id}/original")
async def original_post(deal_id: str):
    d = await db.deals.find_one({"id": deal_id}, NO_ID)
    if not d:
        raise HTTPException(404, "Deal not found")
    web = d.get("source_post_url")
    app_url = None
    m = re.match(r"https://t\.me/(?:s/)?([\w]+)/(\d+)", web or "")
    if m:
        app_url = f"tg://resolve?domain={m.group(1)}&post={m.group(2)}"
    return {"source": d.get("source"), "posted_at": d.get("posted_at"), "text": d.get("text") or d.get("note") or "",
            "image": d.get("image"), "web_url": web, "app_url": app_url}


@api.get("/price-history/{deal_id}")
async def price_history(deal_id: str):
    deal = await db.deals.find_one({"id": deal_id}, NO_ID)
    if not deal:
        raise HTTPException(404, "Deal not found")
    pts = await db.price_history.find({"product_key": deal.get("product_key")}, NO_ID).sort("at", 1).to_list(500)
    stores = []
    candidates = [deal]
    tk = (deal.get("title_key") or "")[:18]
    if len(tk) >= 10:
        others = await db.deals.find({"title_key": {"$regex": f"^{re.escape(tk)}"}, "store": {"$ne": deal.get("store")},
                                      "id": {"$ne": deal_id}}, NO_ID).to_list(5)
        seen_stores = {deal.get("store")}
        for o in others:
            if o.get("store") not in seen_stores:
                seen_stores.add(o["store"])
                candidates.append(o)
    phs = await asyncio.gather(*(ph_data(c["clean_url"]) for c in candidates))
    for c, ph in zip(candidates, phs):
        if ph and ph.get("history"):
            stores.append({"store": c.get("store"), "url": c.get("affiliate_url") or c.get("clean_url"),
                           "current": ph.get("price"), "lowest": ph.get("min"), "lowest_on": ph.get("min_on"),
                           "highest": ph.get("max"), "average": ph.get("avg"), "points": ph["history"],
                           "source_page": ph.get("page_url")})
    seen = [{"x": p["at"], "y": p["price"]} for p in pts if p.get("price")]
    if seen:
        stores.append({"store": "Seen in deal channels", "url": deal.get("affiliate_url"), "current": deal.get("price"),
                       "lowest": min(p["y"] for p in seen), "highest": max(p["y"] for p in seen), "points": seen})
    priced = [s for s in stores if s.get("current") and s["store"] != "Seen in deal channels"]
    best = min(priced, key=lambda s: s["current"]) if priced else None
    best = {"store": best["store"], "current": best["current"], "url": best["url"]} if best else None
    if deal.get("price") and (not best or deal["price"] < best["current"]):
        best = {"store": deal.get("store"), "current": deal["price"], "url": deal.get("affiliate_url") or deal.get("clean_url")}
    all_prices = [p["y"] for s in stores for p in s["points"]]
    return {"stores": stores, "best": best, "lowest": min(all_prices) if all_prices else None,
            "highest": max(all_prices) if all_prices else None, "compare": engine.compare_links(deal["title"])}


@api.post("/deals")
async def add_deal(body: DealIn):
    settings = await get_settings()
    text = " ".join(filter(None, [body.title, body.note]))
    price, mrp = body.price, body.mrp
    discount = body.discount if body.discount is not None else engine.extract_discount(text, price, mrp)
    cats = body.categories if body.categories else engine.classify(text, discount, settings)
    deal = {"title": body.title or engine.make_title(body.url), "text": body.note or "", "note": body.note,
            "url": body.url.strip(), "store": engine.detect_store(body.url, text), "price": price, "mrp": mrp,
            "discount": discount or 0, "categories": cats or ["heavy_discount"], "image": body.image}
    src = {"id": "manual", "name": "Manual"}
    deal["ext_id"] = str(uuid.uuid4())
    created = await ingest(deal, src, settings, autopost=False)
    results = await post_deal(created) if body.post_now else []
    created["posted_to"] = [r["destination_name"] for r in results if r["status"] == "success"]
    created.pop("dedupe_key", None)
    return {"deal": created, "post_results": results}


@api.post("/deals/{deal_id}/post")
async def repost(deal_id: str, destination_id: Optional[str] = None):
    deal = await db.deals.find_one({"id": deal_id}, NO_ID)
    if not deal:
        raise HTTPException(404, "Deal not found")
    return {"post_results": await post_deal(deal, destination_id)}


@api.put("/deals/{deal_id}/feature")
async def feature_deal(deal_id: str, body: FeatureIn):
    r = await db.deals.update_one({"id": deal_id}, {"$set": {"featured": body.featured}})
    if not r.matched_count:
        raise HTTPException(404, "Deal not found")
    return {"ok": True, "featured": body.featured}


@api.delete("/deals/{deal_id}")
async def delete_deal(deal_id: str):
    r = await db.deals.delete_one({"id": deal_id})
    if not r.deleted_count:
        raise HTTPException(404, "Deal not found")
    return {"ok": True}


@api.get("/stats")
async def stats():
    out = {"total": await db.deals.count_documents({})}
    for c in engine.CATEGORIES:
        out[c] = await db.deals.count_documents({"categories": c})
    out["sources"] = await db.sources.count_documents({"enabled": True})
    out["destinations"] = await db.destinations.count_documents({"enabled": True})
    out["posts_sent"] = await db.logs.count_documents({"status": "success"})
    s = await get_settings()
    out["last_scan_at"] = s.get("last_run_at")
    out["check_interval_seconds"] = s.get("check_interval_seconds", 60)
    win = int(s.get("telegram_max_age_minutes", 60))
    since = (datetime.now(timezone.utc) - timedelta(minutes=win)).isoformat()
    out["fresh_window_minutes"] = win
    out["fresh_3h"] = await db.deals.count_documents({"posted_at": {"$gte": since}})
    latest = await db.deals.find_one({}, {"_id": 0, "posted_at": 1}, sort=[("posted_at", -1)])
    out["latest_deal_at"] = latest.get("posted_at") if latest else None
    return out


# ---------- Sources ----------
@api.get("/sources")
async def list_sources():
    return await db.sources.find({}, NO_ID).sort("created_at", -1).to_list(200)


@api.post("/sources")
async def add_source(body: SourceIn):
    value = body.value.strip()
    if body.kind == "telegram":
        value = value.replace("https://", "").replace("t.me/s/", "").replace("t.me/", "").lstrip("@").strip("/")
    if await db.sources.find_one({"value": {"$regex": f"^{re.escape(value)}$", "$options": "i"}}):
        raise HTTPException(400, "Source already added")
    src = {"id": str(uuid.uuid4()), "name": body.name or (f"@{value}" if body.kind == "telegram" else
                                                       re.sub(r'^https?://(www\.)?', '', value).split("/")[0] + (" (website)" if body.kind == "web" else "")),
           "kind": body.kind, "value": value, "enabled": body.enabled, "last_fetched_at": None,
           "last_error": None, "total_deals": 0, "created_at": now()}
    await db.sources.insert_one(dict(src))
    return src


@api.put("/sources/{sid}")
async def update_source(sid: str, body: SourceIn):
    await db.sources.update_one({"id": sid}, {"$set": {"enabled": body.enabled, "name": body.name or body.value}})
    return await db.sources.find_one({"id": sid}, NO_ID)


@api.delete("/sources/{sid}")
async def delete_source(sid: str):
    await db.sources.delete_one({"id": sid})
    return {"ok": True}


@api.post("/sources/{sid}/fetch")
async def fetch_one(sid: str):
    src = await db.sources.find_one({"id": sid}, NO_ID)
    if not src:
        raise HTTPException(404, "Source not found")
    return await fetch_source(src)


@api.post("/fetch-all")
async def fetch_all_now(bg: BackgroundTasks):
    bg.add_task(fetch_all, True)
    return {"queued": True}


# ---------- Destinations ----------
def public_dest(d):
    d = dict(d)
    d["bot_token_masked"] = mask(d.pop("bot_token", ""))
    return d


@api.get("/destinations")
async def list_destinations():
    return [public_dest(d) for d in await db.destinations.find({}, NO_ID).sort("created_at", 1).to_list(100)]


@api.post("/destinations")
async def add_destination(body: DestinationIn):
    if not body.bot_token:
        raise HTTPException(400, "Bot token is required")
    d = {**body.model_dump(), "id": str(uuid.uuid4()), "created_at": now()}
    d["bot_token"] = d["bot_token"].strip()
    d["chat_id"] = d["chat_id"].strip()
    if not d["chat_id"]:
        raise HTTPException(400, "Chat ID is required")
    d["name"] = d["name"].strip() or d["chat_id"]
    await db.destinations.insert_one(dict(d))
    return public_dest(d)


@api.put("/destinations/{did}")
async def update_destination(did: str, body: DestinationIn):
    upd = body.model_dump()
    upd["chat_id"] = upd["chat_id"].strip()
    if not upd["chat_id"]:
        raise HTTPException(400, "Chat ID is required")
    upd["name"] = upd["name"].strip() or upd["chat_id"]
    if not upd.get("bot_token"):
        upd.pop("bot_token")
    else:
        upd["bot_token"] = upd["bot_token"].strip()
    await db.destinations.update_one({"id": did}, {"$set": upd})
    d = await db.destinations.find_one({"id": did}, NO_ID)
    if not d:
        raise HTTPException(404, "Destination not found")
    return public_dest(d)


@api.delete("/destinations/{did}")
async def delete_destination(did: str):
    await db.destinations.delete_one({"id": did})
    return {"ok": True}


@api.post("/destinations/{did}/test")
async def test_destination(did: str):
    d = await db.destinations.find_one({"id": did}, NO_ID)
    if not d:
        raise HTTPException(404, "Destination not found")
    try:
        await engine.send_telegram(d["bot_token"], d["chat_id"], f"✅ <b>DealLoot connected</b>\nThis channel ({d['name']}) will receive deals.")
        return {"ok": True}
    except Exception as e:
        msg = str(e)
        if "chat not found" in msg.lower():
            msg += " — for a private channel use its number ID (like -100…) from 'Find my chat ID', and make the bot an admin. For your personal chat, send /start to the bot first."
        elif "unauthorized" in msg.lower():
            msg += " — the bot token is wrong. Copy it again from @BotFather."
        raise HTTPException(400, f"Telegram error: {msg}")
def public_settings(s):
    s = dict(s)
    s["sankmo_token_masked"] = mask(s.pop("sankmo_token", ""))
    s["tg_connected"] = bool(s.pop("tg_session", "")) and not s.get("tg_expired")
    s["tg_api_hash_masked"] = mask(s.pop("tg_api_hash", ""))
    return s


@api.get("/settings")
async def read_settings():
    return public_settings(await get_settings())


@api.put("/settings")
async def write_settings(body: SettingsIn):
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if upd.get("sankmo_token") == "":
        upd.pop("sankmo_token")
    if "check_interval_minutes" in upd:
        upd["check_interval_minutes"] = min(max(upd["check_interval_minutes"], 15), 1440)
    if "check_interval_seconds" in upd:
        upd["check_interval_seconds"] = min(max(upd["check_interval_seconds"], 30), 86400)
    if "website_max_age_hours" in upd:
        upd["website_max_age_hours"] = min(max(upd["website_max_age_hours"], 1), 720)
    if "telegram_max_age_minutes" in upd:
        upd["telegram_max_age_minutes"] = min(max(upd["telegram_max_age_minutes"], 1), 10080)
    if "max_posts_per_update" in upd:
        upd["max_posts_per_update"] = min(max(upd["max_posts_per_update"], 1), 200)
    if "amazon_tag" in upd:
        upd["amazon_tag"] = upd["amazon_tag"].strip()
    await get_settings()
    await db.settings.update_one({"id": "main"}, {"$set": upd})
    if "amazon_tag" in upd:
        await retag_amazon(upd["amazon_tag"])
    return public_settings(await get_settings())


async def retag_amazon(tag):
    async for d in db.deals.find({"store": "Amazon"}, {"_id": 0, "id": 1, "clean_url": 1}):
        aff = engine.amazon_affiliate(d["clean_url"], tag)
        await db.deals.update_one({"id": d["id"]}, {"$set": {"affiliate_url": aff, "converted": aff != d["clean_url"]}})


@api.post("/convert")
async def convert(body: ConvertIn):
    settings = await get_settings()
    cleaned = await engine.clean_link(body.url.strip())
    try:
        out = await engine.convert_link(cleaned, settings)
        return {"original": body.url, "cleaned": cleaned, "converted": out, "changed": out != cleaned, "error": None,
                "store": engine.detect_store(cleaned)}
    except Exception as e:
        if "login expired" in str(e):
            await db.settings.update_one({"id": "main"}, {"$set": {"tg_expired": True}})
        return {"original": body.url, "cleaned": cleaned, "converted": cleaned, "changed": False, "error": str(e)[:300],
                "store": engine.detect_store(cleaned)}


async def deal_info(url):
    ph = await ph_data(url)
    info = {"title": None, "image": None, "price": None, "mrp": None}
    if ph:
        info.update({"title": ph.get("name"), "image": ph.get("image"), "price": ph.get("price"), "mrp": ph.get("mrp")})
    if not info["image"]:
        info["image"] = await engine.fetch_og_image(url)
    return info


@api.post("/convert/bulk")
async def convert_bulk(body: BulkIn):
    found = list(dict.fromkeys(u.rstrip(".,;!") for u in engine.URL_RE.findall(body.text) if "t.me/" not in u))
    if not found:
        raise HTTPException(400, "No links found. Paste one or more deal links.")
    links = found[:BULK_MAX]
    settings = await get_settings()
    cleaned = await asyncio.gather(*[engine.clean_link(u) for u in links])
    infos = await asyncio.gather(*[deal_info(c) for c in cleaned])
    items, message = [], body.text
    for orig, clean, info in zip(links, cleaned, infos):
        err = None
        try:
            out = await engine.convert_link(clean, settings)
        except Exception as e:
            out, err = clean, str(e)[:300]
            if "login expired" in err:
                await db.settings.update_one({"id": "main"}, {"$set": {"tg_expired": True}})
        store = engine.detect_store(clean)
        if not err and out == clean:
            err = "Add your Amazon tag first" if store == "Amazon" else "Sankmo not set up or returned no link"
        message = message.replace(orig, out)
        items.append({"original": orig, "cleaned": clean, "converted": out, "changed": out != clean, "error": err,
                      "store": store, **info})
    return {"items": items, "message": message.strip(), "total_found": len(found), "skipped": found[BULK_MAX:]}


@api.get("/image-proxy")
async def image_proxy(url: str):
    if not url.startswith("http"):
        raise HTTPException(400, "Bad image link")
    async with httpx.AsyncClient(timeout=15, headers=engine.UA, follow_redirects=True) as c:
        r = await c.get(url)
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or not ctype.startswith("image/") or len(r.content) > 8_000_000:
        raise HTTPException(400, "Could not load image")
    return Response(content=r.content, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})


@api.post("/sankmo/telegram/send-code")
async def tg_send_code(body: TgCodeIn):
    saved = await get_settings()
    api_id = body.api_id.strip() or saved.get("tg_api_id", "")
    api_hash = body.api_hash.strip() or saved.get("tg_api_hash", "")
    if not api_id or not api_hash:
        raise HTTPException(400, "API ID and API hash are required")
    try:
        await tgconv.send_code(api_id, api_hash, body.phone.strip())
    except Exception as e:
        raise HTTPException(400, f"Could not send code: {e}")
    await db.settings.update_one({"id": "main"}, {"$set": {"tg_api_id": api_id,
                                                           "tg_api_hash": api_hash, "tg_phone": body.phone.strip()}})
    return {"ok": True}


async def _reconvert():
    s = await get_settings()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    q = {"$or": [{"converted": {"$ne": True}}, {"store": "Amazon"}], "posted_at": {"$gte": since}}
    async for d in db.deals.find(q, NO_ID).sort("posted_at", -1):
        aff = await safe_convert(d["clean_url"], s)
        if aff != d["clean_url"]:
            await db.deals.update_one({"id": d["id"]}, {"$set": {"affiliate_url": aff, "converted": True}})


@api.post("/deals/reconvert")
async def reconvert(bg: BackgroundTasks):
    bg.add_task(_reconvert)
    return {"ok": True}


@api.post("/destinations/{did}/send-recent")
async def send_recent(did: str):
    d = await db.destinations.find_one({"id": did}, NO_ID)
    if not d:
        raise HTTPException(404, "Destination not found")
    s = await get_settings()
    since = (datetime.now(timezone.utc) - timedelta(minutes=s.get("telegram_max_age_minutes", 60))).isoformat()
    deals = await db.deals.find({"posted_at": {"$gte": since}, "posted_to": {"$ne": d["name"]}}, NO_ID).sort("posted_at", -1).to_list(500)
    match = [x for x in deals if dest_matches(d, x)][: int(s.get("max_posts_per_update", 20))]
    sent = failed = 0
    for x in match:
        r = await post_deal(x, d["id"])
        ok = any(i["status"] == "success" for i in r)
        sent += ok
        failed += not ok
        if failed and not sent:
            raise HTTPException(400, f"Telegram error: {r[0]['error']}")
        await asyncio.sleep(1.2)
    return {"matched": len(match), "sent": sent, "failed": failed, "window_minutes": s.get("telegram_max_age_minutes", 60)}


@api.post("/sankmo/telegram/verify")
async def tg_verify(body: TgVerifyIn):
    try:
        session, user = await tgconv.verify(body.code.strip(), body.password)
    except Exception as e:
        raise HTTPException(400, str(e))
    await db.settings.update_one({"id": "main"}, {"$set": {"tg_session": session, "tg_user": user, "convert_mode": "telegram", "tg_expired": False}})
    return {"ok": True, "user": user}


@api.post("/sankmo/telegram/logout")
async def tg_logout():
    await db.settings.update_one({"id": "main"}, {"$set": {"tg_session": "", "tg_user": "", "tg_expired": False}})
    return {"ok": True}


class BotTokenIn(BaseModel):
    bot_token: Optional[str] = None
    destination_id: Optional[str] = None


@api.post("/telegram/chats")
async def find_chats(body: BotTokenIn):
    token = (body.bot_token or "").strip()
    if not token and body.destination_id:
        d = await db.destinations.find_one({"id": body.destination_id}, NO_ID)
        token = d["bot_token"] if d else ""
    if not token:
        raise HTTPException(400, "Paste the bot token first")
    body.bot_token = token
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://api.telegram.org/bot{body.bot_token.strip()}/getUpdates")
        data = r.json()
    except Exception as e:
        raise HTTPException(400, f"Telegram error: {e}")
    if not data.get("ok"):
        raise HTTPException(400, f"Telegram error: {data.get('description', 'Invalid bot token')} — check the bot token from @BotFather.")
    chats = {}
    for u in data.get("result", []):
        msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        ch = msg.get("chat")
        if ch:
            chats[ch["id"]] = {"id": str(ch["id"]), "type": ch.get("type"),
                               "name": ch.get("title") or " ".join(filter(None, [ch.get("first_name"), ch.get("last_name")])) or ch.get("username")}
    return list(chats.values())


@api.get("/logs")
async def logs(limit: int = 200):
    return await db.logs.find({}, NO_ID).sort("created_at", -1).to_list(min(limit, 500))


# ---------- Cron ----------
@api.post("/cron/fetch")
async def cron_fetch(request: Request, bg: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    auth = request.headers.get("Authorization", "")
    secret = os.environ["WEBHOOK_CRON_SECRET"]
    if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], secret):
        raise HTTPException(401, "Unauthorized")
    run_id = request.headers.get("X-Webhook-Id") or str(uuid.uuid4())
    if await db.cron_runs.find_one({"run_id": run_id}):
        return {"accepted": True, "duplicate": True}
    await db.cron_runs.insert_one({"run_id": run_id, "created_at": now()})
    bg.add_task(fetch_all)
    return {"accepted": True}


@api.get("/")
async def root():
    return {"message": "DealLoot API"}


@app.on_event("startup")
async def seed():
    await get_settings()
    await db.deals.create_index("dedupe_key", unique=True)
    await db.seen.create_index("key", unique=True)
    await db.price_history.create_index("product_key")
    async for d in db.deals.find({"source_post_url": {"$exists": False}}, {"_id": 0, "id": 1, "dedupe_key": 1}):
        ext = (d.get("dedupe_key") or "").split(":", 1)[-1]
        url = ext if ext.startswith("http") else (f"https://t.me/{ext}" if "/" in ext else None)
        await db.deals.update_one({"id": d["id"]}, {"$set": {"source_post_url": url}})
    asyncio.create_task(poller())
    asyncio.create_task(backfill_enrich())
    settings = await get_settings()
    for v in ([] if settings.get("seeded_v2") else SEED_SOURCES):
        if not await db.sources.find_one({"value": {"$regex": f"^{v}$", "$options": "i"}}):
            await add_source(SourceIn(value=v))
    for v in ([] if settings.get("seeded_v2") else SEED_RSS):
        if not await db.sources.find_one({"value": v}):
            await add_source(SourceIn(value=v, kind="rss"))
    await db.settings.update_one({"id": "main"}, {"$set": {"seeded_v2": True}})
    async for d in db.deals.find({"score": {"$exists": False}}, NO_ID):
        await db.deals.update_one({"id": d["id"]}, {"$set": {"score": engine.score(d), "featured": False}})
    await retag_amazon(settings.get("amazon_tag", ""))


app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True,
                   allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
