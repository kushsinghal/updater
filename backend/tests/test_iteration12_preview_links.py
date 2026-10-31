# Iteration 12: share_code preview links (/api/go), deal preview (/api/go/d), copy settings
import html
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
FK = "https://www.flipkart.com/flipkart/p/item?pid=WATHG4Y5XJHUFWJ"
AMZ = "https://www.amazon.in/dp/B0GQV895L5"
DEFAULT_HEADER = "🪙 100% SuperCoin Deals 🪙"


@pytest.fixture(scope="module")
def s():
    x = requests.Session()
    yield x
    # restore defaults
    x.put(f"{API}/settings", json={"copy_header": DEFAULT_HEADER, "copy_link_style": "preview"}, timeout=30)


def meta(page, prop):
    m = re.search(rf'<meta property="{prop}" content="([^"]*)"', page)
    return html.unescape(m.group(1)) if m else None


# --- Settings: copy_header / copy_link_style
def test_settings_defaults(s):
    d = s.get(f"{API}/settings", timeout=30).json()
    assert d["copy_header"] == DEFAULT_HEADER
    assert d["copy_link_style"] == "preview"


def test_settings_update_and_persist(s):
    r = s.put(f"{API}/settings", json={"copy_header": "TEST HEADER", "copy_link_style": "direct"}, timeout=30)
    assert r.status_code == 200
    assert r.json()["copy_header"] == "TEST HEADER" and r.json()["copy_link_style"] == "direct"
    g = s.get(f"{API}/settings", timeout=30).json()
    assert g["copy_header"] == "TEST HEADER" and g["copy_link_style"] == "direct"


def test_settings_empty_header_persists(s):
    r = s.put(f"{API}/settings", json={"copy_header": ""}, timeout=30)
    assert r.status_code == 200
    assert s.get(f"{API}/settings", timeout=30).json()["copy_header"] == ""


def test_settings_invalid_style_rejected(s):
    r = s.put(f"{API}/settings", json={"copy_link_style": "bogus"}, timeout=30)
    assert r.status_code == 422
    assert s.get(f"{API}/settings", timeout=30).json()["copy_link_style"] in ("preview", "direct")


def test_settings_restore(s):
    r = s.put(f"{API}/settings", json={"copy_header": DEFAULT_HEADER, "copy_link_style": "preview"}, timeout=30)
    assert r.json()["copy_header"] == DEFAULT_HEADER and r.json()["copy_link_style"] == "preview"


# --- Bulk convert returns share_code; /api/go/{code} serves OG preview
@pytest.fixture(scope="module")
def bulk(s):
    r = s.post(f"{API}/convert/bulk", json={"text": f"Deal one {FK}\nDeal two {AMZ}"}, timeout=120)
    assert r.status_code == 200, r.text
    return r.json()


def test_bulk_share_codes(bulk):
    assert len(bulk["items"]) == 2
    for it in bulk["items"]:
        assert isinstance(it["share_code"], str) and len(it["share_code"]) == 8
        print(it["store"], it["converted"], it["changed"], it["error"], it.get("price"), bool(it.get("image")))


def test_go_link_preview(s, bulk):
    for it in bulk["items"]:
        r = s.get(f"{API}/go/{it['share_code']}", timeout=30, allow_redirects=False)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        page = r.text
        assert meta(page, "og:title")
        desc = meta(page, "og:description")
        assert it["store"] in desc
        if it.get("price"):
            assert "Deal Price ₹" in desc
        if it.get("image"):
            assert meta(page, "og:image") == it["image"]
        assert f"location.replace(\"{it['converted']}\")" in page or it["converted"].replace("/", "\\/") in page or it["converted"] in page


def test_flipkart_converted_to_fkrt(bulk):
    fk = [i for i in bulk["items"] if i["store"] == "Flipkart"][0]
    print("FK converted:", fk["converted"], fk["error"])
    assert fk["changed"] is True
    assert "fkrt" in fk["converted"]


def test_go_link_unknown_404(s):
    assert s.get(f"{API}/go/doesnotexist123", timeout=30).status_code == 404


# --- /api/go/d/{deal_id}
def test_go_deal_preview(s):
    deals = s.get(f"{API}/deals", timeout=30).json()
    deals = deals if isinstance(deals, list) else deals.get("deals") or deals.get("items")
    d = next(x for x in deals if x.get("image") and x.get("price"))
    r = s.get(f"{API}/go/d/{d['id']}", timeout=30)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert meta(r.text, "og:image") == d["image"]
    assert "Deal Price ₹" in meta(r.text, "og:description")
    target = d.get("affiliate_url") or d["url"]
    assert target in r.text or target.replace("/", "\\/") in r.text


def test_go_deal_unknown_404(s):
    assert s.get(f"{API}/go/d/nonexistent-deal-id", timeout=30).status_code == 404
