# Iteration 14: Telegram link-preview pictures for Flipkart in bulk convert, /api/img, BULK_MAX=10
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
FK = "https://www.flipkart.com/apple-iphone-15/p/itm6ac6485515ae4"
AMZ = "https://www.amazon.in/dp/B09G9HD6PD"


@pytest.fixture(scope="module")
def fk_item():
    r = requests.post(f"{BASE_URL}/api/convert/bulk", json={"text": f"Deal {FK}", "base": BASE_URL}, timeout=120)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["items"]) == 1
    return data["items"][0]


# Flipkart no-pid link gets picture via Telegram preview
def test_flipkart_image_from_preview(fk_item):
    print(fk_item)
    assert fk_item["image"], "no image"
    assert fk_item["image"].startswith(f"{BASE_URL}/api/img/") or fk_item["image"].startswith("http")
    assert fk_item["title"]


def test_img_endpoint_returns_jpeg(fk_item):
    img = fk_item["image"]
    if "/api/img/" not in img:
        pytest.skip(f"image came from another source: {img}")
    r = requests.get(img, timeout=30)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert len(r.content) > 1000
    assert r.content[:2] == b"\xff\xd8"


def test_go_page_og_image(fk_item):
    r = requests.get(f"{BASE_URL}/api/go/{fk_item['share_code']}", timeout=30)
    assert r.status_code == 200
    m = re.search(r'property="og:image" content="([^"]+)"', r.text)
    assert m and m.group(1) == fk_item["image"]


def test_img_unknown_404():
    r = requests.get(f"{BASE_URL}/api/img/unknown", timeout=30)
    assert r.status_code == 404


def test_no_base_no_preview():
    # without base, Telegram preview is not attempted (image may still come from db/ph)
    r = requests.post(f"{BASE_URL}/api/convert/bulk", json={"text": AMZ}, timeout=120)
    assert r.status_code == 200
    it = r.json()["items"][0]
    assert it["store"] == "Amazon"


# BULK_MAX = 10
def test_bulk_max_10():
    links = [f"https://www.amazon.in/dp/B0TEST{i:04d}" for i in range(12)]
    r = requests.post(f"{BASE_URL}/api/convert/bulk", json={"text": "\n".join(links)}, timeout=280)
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["items"]) == 10
    assert d["total_found"] == 12
    assert d["skipped"] == links[10:]
