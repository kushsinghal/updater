# Iteration 22: copy_link_style default 'direct' + dangling 'For' title trim
import os
import re
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
SRV = open(os.path.join(os.path.dirname(__file__), "..", "server.py")).read()


# Settings default
def test_settings_copy_link_style_direct():
    r = requests.get(f"{BASE_URL}/api/settings", timeout=30)
    assert r.status_code == 200
    assert r.json()["copy_link_style"] == "direct"
    assert '"copy_link_style": "direct"' in SRV


# Bulk convert Flipkart -> fkrt.site link
def test_bulk_convert_flipkart_returns_sankmo():
    r = requests.post(f"{BASE_URL}/api/convert/bulk", json={
        "text": "https://www.flipkart.com/apple-iphone-15/p/itm6ac6485515ae4", "base": BASE_URL}, timeout=90)
    assert r.status_code == 200
    it = r.json()["items"][0]
    assert it["changed"] is True
    assert "fkrt.site" in it["converted"]
    assert "/api/go/" not in it["converted"]
    assert not re.search(r"\s(for|with|and|by|of|in)$", it["title"] or "", re.I)


# Title trim regex (copied from server.deal_info)
TRIM = re.compile(r"[\s\-–,|]+(?:for|with|and|by|of|in|-)?\s*$", re.I)


@pytest.mark.parametrize("raw,expected", [
    ("Unltd by TIMEX Group Analog Watch  For", "Unltd by TIMEX Group Analog Watch"),
    ("Analog Watch - For Men", "Analog Watch - For Men"),
    ("Boat Earbuds with", "Boat Earbuds"),
    ("Apple iPhone 15 (Black, 128 GB)", "Apple iPhone 15 (Black, 128 GB)"),
    ("Shoes -", "Shoes"),
    ("Formal Shirt", "Formal Shirt"),
])
def test_title_trim(raw, expected):
    assert "(?:for|with|and|by|of|in|-)?" in SRV
    assert (TRIM.sub("", raw.strip()) or raw) == expected
