# Iteration 13: deal_info db reuse + unescape, PUT /api/go/{code} image, settings persistence, regression
import html
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
DEFAULT_HEADER = "🪙 100% SuperCoin Deals 🪙"
KNOWN_FK = "https://www.flipkart.com/x/p/itma5c981881bf9d?pid=WATH2H2KJVNFHJY4"
NOPID_FK = "https://www.flipkart.com/tommy-hilfiger-analog-watch/p/itm2f049aec7e6b6"
AMZ = "https://www.amazon.in/dp/B0GQV895L5"
IMG = "https://images.price.tools/images/nautica-analog-watch-men-l-Mxtz2yqs.jpg"


@pytest.fixture(scope="module")
def s():
    x = requests.Session()
    yield x
    x.put(f"{API}/settings", json={"copy_header": DEFAULT_HEADER, "copy_link_style": "preview"}, timeout=30)


def meta(page, prop):
    m = re.search(rf'<meta property="{prop}" content="([^"]*)"', page)
    return html.unescape(m.group(1)) if m else None


@pytest.fixture(scope="module")
def bulk(s):
    r = s.post(f"{API}/convert/bulk", json={"text": f"A {KNOWN_FK}\nB {NOPID_FK}\nC {AMZ}"}, timeout=180)
    assert r.status_code == 200, r.text
    return r.json()["items"]


# settings persistence
def test_settings_custom_persist(s):
    r = s.put(f"{API}/settings", json={"copy_header": "X CUSTOM", "copy_link_style": "direct"}, timeout=30)
    assert r.status_code == 200
    g = s.get(f"{API}/settings", timeout=30).json()
    assert g["copy_header"] == "X CUSTOM" and g["copy_link_style"] == "direct"
    s.put(f"{API}/settings", json={"copy_header": DEFAULT_HEADER, "copy_link_style": "preview"}, timeout=30)


# deal_info reuse from db.deals
def test_known_deal_reused(bulk):
    it = bulk[0]
    for x in bulk:
        print(x["store"], x["share_code"], x.get("title"), x.get("image"), x.get("price"), x["changed"], x["error"])
    assert it["image"] == IMG
    assert "NAUTICA" in (it["title"] or "")


def test_titles_unescaped(bulk):
    for it in bulk:
        if it.get("title"):
            assert "&amp" not in it["title"] and "&#" not in it["title"], it["title"]


# PUT /api/go/{code}
def test_set_image_and_og(s, bulk):
    code = bulk[1]["share_code"]
    r = s.put(f"{API}/go/{code}", json={"image": IMG}, timeout=30)
    assert r.status_code == 200 and r.json()["ok"] is True
    page = s.get(f"{API}/go/{code}", timeout=30).text
    assert meta(page, "og:image") == IMG


def test_set_image_unknown_code(s):
    r = s.put(f"{API}/go/zzzzzzzz", json={"image": IMG}, timeout=30)
    assert r.status_code == 404


def test_set_image_non_http(s, bulk):
    r = s.put(f"{API}/go/{bulk[1]['share_code']}", json={"image": "ftp://x/y.jpg"}, timeout=30)
    assert r.status_code == 400
    r2 = s.put(f"{API}/go/{bulk[1]['share_code']}", json={"image": "javascript:alert(1)"}, timeout=30)
    assert r2.status_code == 400


def test_set_image_missing_body(s, bulk):
    r = s.put(f"{API}/go/{bulk[1]['share_code']}", json={}, timeout=30)
    assert r.status_code == 422


# regression
def test_go_link_redirect(s, bulk):
    for it in bulk:
        page = s.get(f"{API}/go/{it['share_code']}", timeout=30).text
        assert "location.replace" in page and meta(page, "og:title")


def test_go_unknown(s):
    assert s.get(f"{API}/go/nope1234", timeout=30).status_code == 404
    assert s.get(f"{API}/go/d/nope", timeout=30).status_code == 404


def test_go_deal(s):
    deals = s.get(f"{API}/deals", timeout=30).json()
    items = deals if isinstance(deals, list) else deals.get("items") or deals.get("deals")
    d = items[0]
    page = s.get(f"{API}/go/d/{d['id']}", timeout=30).text
    assert "location.replace" in page
    if d.get("image"):
        assert meta(page, "og:image") == d["image"]
