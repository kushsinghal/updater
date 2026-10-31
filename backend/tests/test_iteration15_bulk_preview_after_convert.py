# Iteration 15: Flipkart no-pid bulk convert -> converted (fkrt.site) AND Telegram-preview image; base validation
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
LINKS = [
    "https://www.flipkart.com/apple-iphone-15/p/itm6ac6485515ae4",
    "https://www.flipkart.com/tommy-hilfiger-automatic-analog-watch-men/p/itm2f049aec7e6b6",
    "https://www.flipkart.com/apple-iphone-15/p/itm6ac6485515ae4",
]


def bulk(text, base=BASE_URL):
    body = {"text": text}
    if base is not None:
        body["base"] = base
    r = requests.post(f"{BASE_URL}/api/convert/bulk", json=body, timeout=180)
    assert r.status_code == 200, r.text
    return r.json()


# Converted AND picture, 3 runs
@pytest.mark.parametrize("url", LINKS)
def test_flipkart_converted_and_image(url):
    it = bulk(f"Deal {url}")["items"][0]
    print(it.get("converted"), it.get("image"), it.get("error"), it.get("title"))
    assert it["changed"] is True, it
    assert it["error"] is None
    assert "fkrt" in it["converted"] or it["converted"] != it["cleaned"]
    assert it["image"] and it["image"].startswith(f"{BASE_URL}/api/img/"), it["image"]
    r = requests.get(it["image"], timeout=30)
    assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"
    g = requests.get(f"{BASE_URL}/api/go/{it['share_code']}", timeout=30)
    m = re.search(r'property="og:image" content="([^"]+)"', g.text)
    assert m and m.group(1) == it["image"]


# Invalid base -> no lookup, no crash, still converts
@pytest.mark.parametrize("base", ["http://evil.com", "javascript:alert(1)", "https://a.com/x", ""])
def test_invalid_base(base):
    it = bulk(f"x {LINKS[1]}", base=base)["items"][0]
    print(base, it.get("converted"), it.get("image"), it.get("error"))
    assert it["changed"] is True, it
    assert not (it["image"] or "").find("/api/img/") >= 0 or it["image"] is None
    assert it["image"] is None or "/api/img/" not in it["image"]
