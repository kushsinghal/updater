"""Iteration 11: Amazon tag conversion, link cleaning, bulk convert, image proxy, retag."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
AMZ = "https://www.amazon.in/dp/B09G9HD6PD?tag=other-21&linkCode=ll1"
FK = "https://www.flipkart.com/boat-airdopes/p/itm123abc?pid=ACCG8XYZ12345&affid=someone&affExtParam1=xyz&otracker=abc"
IMG = "https://m.media-amazon.com/images/I/61SUj2aKoEL._SL1500_.jpg"


@pytest.fixture(scope="module")
def s():
    ses = requests.Session()
    yield ses
    ses.put(f"{API}/settings", json={"amazon_tag": ""}, timeout=30)


def set_tag(s, tag):
    r = s.put(f"{API}/settings", json={"amazon_tag": tag}, timeout=60)
    assert r.status_code == 200, r.text
    assert r.json().get("amazon_tag") == tag
    return r.json()


# Amazon convert with no tag -> cleaned link only
def test_amazon_no_tag_clean(s):
    set_tag(s, "")
    d = s.post(f"{API}/convert", json={"url": AMZ}, timeout=60).json()
    assert d["cleaned"] == "https://www.amazon.in/dp/B09G9HD6PD"
    assert d["converted"] == "https://www.amazon.in/dp/B09G9HD6PD"
    assert d["changed"] is False
    assert d["store"] == "Amazon"


# Amazon convert with tag -> own tag added, no sankmo
def test_amazon_with_tag(s):
    set_tag(s, "testtag-21")
    d = s.post(f"{API}/convert", json={"url": AMZ}, timeout=60).json()
    assert d["converted"] == "https://www.amazon.in/dp/B09G9HD6PD?tag=testtag-21"
    assert d["changed"] is True
    assert "sankmo" not in d["converted"].lower()
    assert "other-21" not in d["converted"]


# Amazon tag whitespace trimmed
def test_amazon_tag_trimmed(s):
    r = s.put(f"{API}/settings", json={"amazon_tag": "  spaced-21  "}, timeout=60)
    assert r.json()["amazon_tag"] == "spaced-21"
    set_tag(s, "testtag-21")


# Flipkart cleaned
def test_flipkart_cleaned(s):
    d = s.post(f"{API}/convert", json={"url": FK}, timeout=60).json()
    print(d)
    assert "affid" not in d["cleaned"].lower()
    assert "affextparam1" not in d["cleaned"].lower()
    assert "otracker" not in d["cleaned"]
    assert "pid=ACCG8XYZ12345" in d["cleaned"]
    assert d["store"] == "Flipkart"
    assert d["converted"] == d["cleaned"]


# Amazon wrapped in a redirect url (dl=) unwrapped
def test_wrapped_amazon(s):
    from urllib.parse import quote
    wrapped = "https://linkredirect.in/visitretailer/2001?id=1&dl=" + quote(AMZ, safe="")
    d = s.post(f"{API}/convert", json={"url": wrapped}, timeout=60).json()
    print(d)
    assert d["cleaned"] == "https://www.amazon.in/dp/B09G9HD6PD"
    assert d["converted"].endswith("?tag=testtag-21")


# Bulk convert: 7 links, max 5
def test_bulk_seven(s):
    links = [AMZ, FK,
             "https://www.amazon.in/dp/B0CHX1W1XY?tag=x-21",
             "https://www.amazon.in/dp/B0BDJ6N5Q1?ref=abc&tag=y-21",
             "https://www.amazon.in/dp/B07WHQTP3L?tag=z-21",
             "https://www.amazon.in/dp/B08L5WHFT9?tag=q-21",
             "https://www.amazon.in/dp/B09XYZABCD?tag=w-21"]
    text = "Hot deals!\n" + "\n".join(f"Deal {i}: {u}" for i, u in enumerate(links))
    r = s.post(f"{API}/convert/bulk", json={"text": text}, timeout=180)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total_found"] == 7
    assert len(d["items"]) == 5
    assert d["skipped"] == links[5:]
    amz = d["items"][0]
    assert amz["converted"] == "https://www.amazon.in/dp/B09G9HD6PD?tag=testtag-21"
    assert amz["changed"] is True
    for k in ("title", "image", "price", "mrp", "store", "error", "cleaned"):
        assert k in amz
    print("amz info:", amz["title"], amz["image"], amz["price"])
    fk = d["items"][1]
    assert fk["changed"] is False and fk["error"]
    assert AMZ not in d["message"]
    assert "https://www.amazon.in/dp/B09G9HD6PD?tag=testtag-21" in d["message"]
    assert links[5] in d["message"]  # skipped links untouched
    assert "Hot deals!" in d["message"]


# Bulk: no links -> 400
def test_bulk_no_links(s):
    r = s.post(f"{API}/convert/bulk", json={"text": "no links here"}, timeout=30)
    assert r.status_code == 400


# Bulk dedupe
def test_bulk_dedupe(s):
    r = s.post(f"{API}/convert/bulk", json={"text": f"{AMZ}\n{AMZ}."}, timeout=120)
    d = r.json()
    assert d["total_found"] == 1


# Image proxy
def test_image_proxy_ok(s):
    r = s.get(f"{API}/image-proxy", params={"url": IMG}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    assert r.headers["content-type"].startswith("image/")
    assert len(r.content) > 1000


def test_image_proxy_non_image(s):
    r = s.get(f"{API}/image-proxy", params={"url": "https://example.com/"}, timeout=30)
    assert r.status_code == 400


def test_image_proxy_bad_scheme(s):
    r = s.get(f"{API}/image-proxy", params={"url": "ftp://x"}, timeout=30)
    assert r.status_code == 400


def test_image_proxy_unreachable_host(s):
    r = s.get(f"{API}/image-proxy", params={"url": "https://nonexistent-host-xyz-12345.invalid/a.jpg"}, timeout=30)
    print("unreachable status", r.status_code)
    assert r.status_code == 400


# Retag existing Amazon deals
def test_retag_existing_amazon_deal(s):
    set_tag(s, "testtag-21")
    r = s.post(f"{API}/deals", json={"url": "https://www.amazon.in/dp/B0TESTRETG?tag=foreign-21",
                                     "title": "TEST_retag deal", "price": 100, "mrp": 1000}, timeout=60)
    assert r.status_code == 200, r.text
    deal = r.json()["deal"]
    did = deal["id"]
    try:
        print("created:", deal.get("affiliate_url"), deal.get("clean_url"))
        assert "foreign-21" not in deal["affiliate_url"]
        assert deal["affiliate_url"].endswith("tag=testtag-21")
        set_tag(s, "newtag-21")
        lst = s.get(f"{API}/deals", params={"q": "TEST_retag"}, timeout=30).json()
        deals = lst["deals"] if isinstance(lst, dict) else lst
        found = [d for d in deals if d["id"] == did]
        assert found, "deal not in list"
        assert found[0]["affiliate_url"].endswith("tag=newtag-21")
        set_tag(s, "")
        lst = s.get(f"{API}/deals", params={"q": "TEST_retag"}, timeout=30).json()
        deals = lst["deals"] if isinstance(lst, dict) else lst
        found = [d for d in deals if d["id"] == did]
        assert found[0]["affiliate_url"] == "https://www.amazon.in/dp/B0TESTRETG"
    finally:
        s.delete(f"{API}/deals/{did}", timeout=30)
