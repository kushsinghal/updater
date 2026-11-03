# DealLoot — PRD

## Original problem
Website that finds big deals (Flipkart 100% SuperCoin, gift card discounts, heavy product discounts, loot/price errors) from Flipkart and other stores, converts links to Sankmo earning links, shows them on the website and auto-posts them to multiple Telegram bots/channels. Phase 2: pull from other Telegram channels, websites, X and WhatsApp channels, plus price comparison and price history.

## User choices
- Sources: auto-fetch from public sources + manual add + user-added channel links
- Auto-post, with each channel getting its own rules (deal types, min %, stores)
- Rules: 100% SuperCoin, gift cards at ≥5% (editable), products at ≥70%, loot/price errors
- No login. Telegram and Sankmo tokens can be edited in the UI.

## Architecture
- FastAPI (`server.py` routes, `engine.py` for scraping/parsing/classifying/Sankmo/Telegram) + MongoDB (deals, sources, destinations, settings, logs, cron_runs)
- Sources: public Telegram channels scraped from t.me/s/<name>, and RSS feeds
- Platform cron `.emergent/crons.yml` runs every 15 min → POST /api/cron/fetch (bearer WEBHOOK_CRON_SECRET)
- React: `/` public deals feed and `/admin` control room (Sources, Telegram Channels, Rules, Add Deal, Sankmo Links, Post Log)

## Implemented (June 2026)
- Scraper, parser and classifier with deduping. The first scan of a new source saves deals without posting them.
- Multi-destination Telegram router (sendPhoto falling back to sendMessage), test message, masked tokens
- Generic Sankmo converter: GET template with {url}/{token}, or POST JSON. Falls back to the original link.
- Manual deal posting, post log, stats

## Iteration 2 (Oct 2026)
- Check interval (15 min–24 h) and max posts per update (1–200) are editable. Price-drop threshold is editable (default 70%).
- Best Deals section: scored automatically (SuperCoin > loot > gift card > discount) plus admin-starred picks. New admin Deals tab to star, repost and delete.
- Link cleaning: resolves short links and wrappers and removes other people's affiliate tags (tag, affid, utm, etc.) before converting
- Sankmo through @sankmo_bot using the user's Telegram account (Telethon: API ID/hash, phone code, optional 2-step password). Sankmo token saved.
- Added 10 more Telegram channels and the CoolzTricks RSS feed. Duplicates across channels removed (same link or title within 2 days).

## Iteration 3 (Oct 2026)
- Deals keep the original post time (Telegram <time> / RSS published) and cards show "posted X ago". Posts older than 24h are ignored and only posts under 60 min are sent to Telegram (both editable).
- Background poller in the app checks every 30s / 1m / 2m / 5m … 1h (editable). The 15-min cron stays as a backup. Sources are fetched 6 at a time.
- Star button on every card, a Starred filter and a "Starred first" sort
- Price tracking per product (Amazon ASIN / Flipkart pid). Each deal has a price chart dialog with compare links (Amazon, Flipkart, Myntra, Croma, Google Shopping, PriceHistory). New Lowest Price Ever section.

## Iteration 4 (Oct 2026)
- Every tab (including Best) is sorted by original post time. The share button is replaced with an "Original post" button (t.me/<channel>/<id>).
- Telegram posts use sendPhoto when there's an image, otherwise a large link preview shown above the text. og:image lookup for deals without an image.
- "Find my chat ID" helper (getUpdates) for sending to a personal chat or channel
- Added 8 more channels (23 sources total). dealsmagnet.com/deal pages are resolved to the real store link. Undated RSS items are skipped.

## Iteration 5 (Oct 2026)
- Full store price history from pricehistory.app (unofficial: search → page token → /api/price). Cached for 6h in ph_cache. Background enrichment fills in missing price/image/title and sets lowest_ever when price ≤ the all-time min. Prices below 30% of the all-time min are treated as implausible.
- Chart dialog with one coloured line per store plus a channel-seen line, 15D/1M/3M/6M/1Y/All ranges, per-store stats and a best-price store link
- Original post button labelled "Post", pointing to the t.me/s/ web view. Scan now button on the Deals page.

## Iteration 6 (Oct 2026)
- Light warm theme (#F5F2EA background, white cards), replacing the dark theme
- The Post button opens an in-app dialog with the original text, image and time, plus tg://resolve "Open in Telegram app" and web links. t.me is blocked by some Indian ISPs. New route GET /api/deals/{id}/original.
- Added backend/requirements-render.txt (no emergent-only packages) for deploying on Render

## Iteration 7 (Oct 2026)
- Sankmo real API found in their dashboard bundle: POST https://sankmo.in/api/convertMunafaLinks (form text=<url>, Authorization: Bearer <token>) → convertedText. New default convert_mode "sankmo_api". The saved token returns "Invalid Token!", so the user must click Generate Token on sankmo.in/influencers/publicApi.
- Fixed test message error (link_preview_options url=None). Destination name is optional; chat_id is required and stripped. Friendly errors for chat not found / unauthorized. Edit scrolls to the form and shows a toast. Find chat ID works in edit mode via destination_id.
- Deals page redesign: "Fresh loot" hero, last scan time, fresh-in-3h count, big Scan now button, black-outline cards with lime accent. /stats returns last_scan_at, fresh_3h and check_interval_seconds.
- Removed the forced dark class; Switch colours fixed for the light theme

## Iteration 8 (Oct 2026)
- CRITICAL FIX: an unauthorized Telethon session caused start() to call input() and freeze the whole backend. tgconv now uses connect(), checks is_user_authorized and wraps the call in wait_for. An expired session sets tg_expired and the UI shows a reconnect state.
- Editing banner and highlighted row in Telegram Channels (the user overwrote a bot while in edit mode)
- Deals page redesign: dark hero card with orange (#FF5A1F) accent, soft white cards, sticky header fixed
- Added sources @CrafinGiftCard, @dealpao, @pakkapickdeals, @dealdetectors (26 total). PointsPerksPicks not found.
- Sankmo public token rejected ("Invalid Token!") by the convertMunafaLinks endpoint; the real public-API format is unknown

## Iteration 9 (Oct 2026)
- New source kind "web": desidime.com/new (article.deal-card) and dealsmagnet.com (.hotdeal) scrapers with relative-time parsing. crafin.in is captcha-protected (SiteGround + Cloudflare), so an error tells the user to use @CrafinGiftCard.
- Telegram post_style "simple" (default): photo + bold "100% Supercoins Back: title" + price + link; "detailed" is optional
- Search works on the Best tab. Dedupe also by product_key + same price.
- /app/render.yaml blueprint (free API web service + static site) and backend/requirements-render.txt

## Iteration 10 (Oct 2026)
- Telegram delivery verified working (test plus 1 SuperCoin deal sent to the user's chat). Auto-post only covers deals found after a channel exists, so a "Send recent" button and POST /destinations/{id}/send-recent now backfill matching deals within telegram_max_age_minutes.
- The fresh counter window follows telegram_max_age_minutes; the hero shows when the newest deal was posted
- send-code falls back to the saved api_id/api_hash
- Sankmo via @sankmo_bot is now WORKING (returns fkrt.site links). POST /deals/reconvert converts the last 24h of deals in the background.

## Backlog
- P0: user connects Telegram account (my.telegram.org API ID/hash) → verify Sankmo bot conversion
- P1: Price history / lowest-ever section, live price comparison across stores
- P1: admin password; X/WhatsApp (skipped: paid/no public access)
- P2: better price/title parsing, custom message templates, deal expiry

## Iteration 11 (Jun 2026)
- Amazon links skip Sankmo (Sankmo doesn't support Amazon): cleaned to amazon.in/dp/ASIN, then user's Amazon Associates tag added (settings.amazon_tag, PLACEHOLDER empty until user sets it in Affiliate Setup). Saving tag retags all Amazon deals; startup also retags.
- Bulk convert: POST /api/convert/bulk (max 5 links per run, rest returned in skipped), cleans others' tracking first, then converts; returns title/image/price via pricehistory + rewritten full message. Admin tab "Convert Links" (default) with copy link / copy with image / share per link and "load next 5".
- Share with image: GET /api/image-proxy; deal cards have Copy (image + text + link) and Share (native share sheet with image file, fallback copy).
## Backlog
- P1: Amazon images often missing (Amazon blocks scraping) — consider Amazon PA-API
- P2: publish bulk-converted deals to website/Telegram in one tap

## Iteration 12 (Jun 2026)
- Copy now copies text only (title, deal price, MRP, % off, store, your link) so it pastes everywhere; Share sends text to any app; "Share with image" is optional in bulk results. Bulk: "Copy all deals with details" button.

## Iteration 13 (Jun 2026)
- Picture preview links: /api/go/{code} (bulk) and /api/go/d/{deal_id} (deal cards) serve og:title/description/image then redirect to the affiliate link, so Telegram/WhatsApp show the product photo. Copy setting: preview (default) or direct link.
- Editable copy header (settings.copy_header, default "🪙 100% SuperCoin Deals 🪙") added to "Copy all deals" for any count.
- Missing pictures: reuse from known deals, else user pastes a picture link (PUT /api/go/{code}).

## Iteration 14 (Jun 2026)
- Auto Flipkart pictures in bulk convert: Telegram link preview (GetWebPagePreview via the connected Telegram account, after conversions, under tgconv lock) → photo stored in db.images, served at /api/img/{id}; titles cleaned.
- Bulk convert up to 10 links (frontend sends batches of 3 with progress), "Load next" for more.
- Alternatives to Sankmo researched: Cuelinks API, INRDeals, EarnKaro, ExtraPe, Affiliaters, Amazon PA-API.

## Iteration 15 (Jun 2026)
- New price parser (deal price keywords > weak keywords > ₹ amounts; skips coupon/bank/cashback lines, units, MRP phrases; K suffix). Enrich keeps post price (text_price), store price only as fallback; MRP dropped if ≤ price+3%; discount/categories recomputed. One-time reprice_all (prices_v2).
- Bulk convert uses the price written next to each link in the post (store_price shown as "before offers").
- Desidime deal pages resolved to store via visit.desidime.com; deal-site links never sent to Sankmo.
- Sankmo store allow-list (settings.sankmo_stores, chips in Affiliate Setup); other links posted clean. Asset links (.js/.css/raw/upload) ignored.
- Original post dialog: "Convert all links to mine" → Convert Links prefilled; "Load next" keeps the full message with earlier converted links.
- WEBHOOK_CRON_SECRET added to backend .env.

## Iteration 16 (Jun 2026)
- Dedupe fix: same-title block only across different sources within 6h (was any source within 2 days → hid reposts with new links).
- Split multi-link posts (settings.split_multi, Rules switch): one deal per store link (max 10), own title/picture (pricehistory → Telegram preview stored in db.images using settings.public_base from POST /api/client-base) and price from text near the link.

## Iteration 17 (Jun 2026)
- Title dedupe window 3h. Website lists + stats only show deals within website_max_age_hours (starred always).
- Gold & Silver category (engine.is_gold, gold_enabled rule, website tab, Telegram prefix/headline, destination routing).
- Store tabs (Flipkart/Amazon/Myntra/Ajio/Other). Offer breakdown (engine.extract_offers: bank/card, coupon, cashback, SuperCoins; store_price → you pay) on cards, copy text, Telegram posts, bulk convert.
- Manual add: /api/lookup auto-fills title/price/MRP/image; note chips (100% SuperCoins = completely FREE, bank, coupon, cashback).

## Iteration 18 (Jun 2026)
- Store split moved to Control Room → Deals tab (All/Flipkart/Amazon/Myntra/Ajio/Other with counts); public page store chips removed.
- Offers: EMI/No-cost-EMI lines skipped (unless full payment also mentioned); % card offers keep "up to/max ₹X" cap; mark_best_card flags best full-payment card/wallet offer with saving; shown on cards + admin rows.

## Iteration 19 (Jun 2026)
- Copy link default = direct Sankmo/affiliate link (preview website link optional). engine.clean_title trims dangling words in all title paths.
