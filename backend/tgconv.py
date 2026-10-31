import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

URL_RE = __import__("engine").URL_RE
_pending = {}
_lock = asyncio.Lock()


async def send_code(api_id, api_hash, phone):
    client = TelegramClient(StringSession(), int(api_id), api_hash)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
    except Exception:
        await client.disconnect()
        raise
    old = _pending.pop("login", None)
    if old:
        await old["client"].disconnect()
    _pending["login"] = {"client": client, "phone": phone, "hash": sent.phone_code_hash}


async def verify(code, password=None):
    p = _pending.get("login")
    if not p:
        raise ValueError("Send the code first")
    client = p["client"]
    try:
        await client.sign_in(phone=p["phone"], code=code, phone_code_hash=p["hash"])
    except SessionPasswordNeededError:
        if not password:
            raise ValueError("This account has a 2-step password. Enter it and verify again.")
        await client.sign_in(password=password)
    me = await client.get_me()
    session = client.session.save()
    await client.disconnect()
    _pending.pop("login", None)
    return session, (me.username or me.first_name or "connected")


async def _convert(url, settings, timeout):
    session = settings.get("tg_session")
    bot = (settings.get("sankmo_bot") or "sankmo_bot").lstrip("@")
    client = TelegramClient(StringSession(session), int(settings["tg_api_id"]), settings["tg_api_hash"])
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise ValueError("Telegram login expired — reconnect in Sankmo Links")
        async with client.conversation(bot, timeout=timeout, exclusive=False) as conv:
            await conv.send_message(url, link_preview=False)
            for _ in range(3):
                resp = await conv.get_response()
                links = [u for u in URL_RE.findall(resp.raw_text or "") if u.rstrip("/") != url.rstrip("/")]
                if resp.entities:
                    for e in resp.entities:
                        if getattr(e, "url", None) and e.url != url:
                            links.insert(0, e.url)
                if links:
                    return links[0]
    finally:
        await client.disconnect()
    raise ValueError("Sankmo bot did not return a link")


async def convert_via_bot(url, settings, timeout=18):
    if not settings.get("tg_session"):
        raise ValueError("Telegram account not connected")
    async with _lock:
        return await asyncio.wait_for(_convert(url, settings, timeout), timeout + 15)


async def _preview(client, url):
    from telethon import functions
    for _ in range(6):
        r = await client(functions.messages.GetWebPagePreviewRequest(message=url))
        wp = getattr(getattr(r, "media", r), "webpage", None)
        if type(wp).__name__ != "WebPagePending":
            break
        await asyncio.sleep(2)
    if type(wp).__name__ != "WebPage":
        return None
    photo = await client.download_media(wp.photo, file=bytes) if getattr(wp, "photo", None) else None
    return {"title": wp.title, "photo": photo}


async def web_previews(urls, settings, timeout=25):
    """Ask Telegram (which stores don't block) for link previews: title + product photo."""
    if not settings.get("tg_session") or not urls:
        return {}
    client = TelegramClient(StringSession(settings["tg_session"]), int(settings["tg_api_id"]), settings["tg_api_hash"])
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return {}
        res = await asyncio.wait_for(asyncio.gather(*[_preview(client, u) for u in urls], return_exceptions=True), timeout)
        return {u: r for u, r in zip(urls, res) if isinstance(r, dict)}
    except asyncio.TimeoutError:
        return {}
    finally:
        await client.disconnect()
