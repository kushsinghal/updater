# Iteration 23: dangling title words cleanup (engine.clean_title + DB cleanup + settings regression)
import os, re, sys
import pytest, requests

sys.path.insert(0, "/app/backend")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
DANGLING = re.compile(r"[\s\-–,|](for|with|and|by|of|in)\s*$", re.I)


@pytest.mark.parametrize("raw,expected", [
    ("Unltd by TIMEX Group Analog Watch  For", "Unltd by TIMEX Group Analog Watch"),
    ("Titan Watch - For Men", "Titan Watch - For Men"),
    ("Boat Earbuds with", "Boat Earbuds"),
    ("Pack of", "Pack"),
    ("Shoes -", "Shoes"),
    ("Shirt, ", "Shirt"),
    ("Platform", "Platform"),
    ("Cotton Kurta for", "Cotton Kurta"),
])
def test_clean_title(raw, expected):
    import engine
    assert engine.clean_title(raw) == expected


def test_clean_title_empty():
    import engine
    assert engine.clean_title("") is None
    assert engine.clean_title(None) is None


def test_no_dangling_titles_in_deals():
    r = requests.get(f"{BASE_URL}/api/deals", params={"limit": 500}, timeout=60)
    assert r.status_code == 200
    data = r.json()
    deals = data if isinstance(data, list) else data.get("deals", data.get("items", []))
    assert len(deals) > 0
    bad = [d["title"] for d in deals if DANGLING.search(d.get("title") or "")]
    assert not bad, bad


def test_settings_copy_link_style_direct():
    r = requests.get(f"{BASE_URL}/api/settings", timeout=30)
    assert r.status_code == 200
    assert r.json().get("copy_link_style") == "direct"
