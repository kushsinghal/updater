# Iteration 8: backend responsiveness during telegram convert, poller, sources, destinations CRUD
import os
import time
import threading
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
NEW_SOURCES = ["CrafinGiftCard", "dealpao", "pakkapickdeals", "dealdetectors"]


# Convert in telegram mode must not freeze the event loop
def test_convert_does_not_block_other_endpoints():
    s = requests.get(f"{BASE_URL}/api/settings", timeout=10).json()
    assert s["convert_mode"] == "telegram"
    result = {}

    def do_convert():
        t0 = time.time()
        r = requests.post(f"{BASE_URL}/api/convert", json={"url": "https://www.flipkart.com/p/itm123?pid=ABC"}, timeout=90)
        result["elapsed"] = time.time() - t0
        result["status"] = r.status_code
        result["body"] = r.json()

    th = threading.Thread(target=do_convert)
    th.start()
    time.sleep(1.0)
    timings = []
    while th.is_alive() and len(timings) < 20:
        for ep in ("/api/sources", "/api/stats"):
            t0 = time.time()
            r = requests.get(f"{BASE_URL}{ep}", timeout=15)
            timings.append((ep, r.status_code, round(time.time() - t0, 2)))
        time.sleep(0.5)
    th.join(90)
    print("convert result:", result)
    print("concurrent timings:", timings)
    assert result["status"] == 200
    assert result["elapsed"] < 45
    assert all(code == 200 for _, code, _ in timings)
    assert max([t for *_, t in timings] or [0]) < 2.5


def test_sources_count_and_new_ones():
    d = requests.get(f"{BASE_URL}/api/sources", timeout=10).json()
    assert len(d) == 26
    vals = {x["value"].lower() for x in d}
    for v in NEW_SOURCES:
        assert v.lower() in vals


def test_three_destinations_persist_then_delete():
    before = {d["id"] for d in requests.get(f"{BASE_URL}/api/destinations", timeout=10).json()}
    ids = []
    try:
        for i in range(3):
            r = requests.post(f"{BASE_URL}/api/destinations", json={"name": f"TEST_api_{i}", "bot_token": f"111:FAKE{i}", "chat_id": f"@test_api_{i}"}, timeout=10)
            assert r.status_code == 200
            ids.append(r.json()["id"])
        after = requests.get(f"{BASE_URL}/api/destinations", timeout=10).json()
        names = {d["name"] for d in after}
        assert {"TEST_api_0", "TEST_api_1", "TEST_api_2"} <= names
        assert before <= {d["id"] for d in after}
    finally:
        for i in ids:
            requests.delete(f"{BASE_URL}/api/destinations/{i}", timeout=10)
    final = {d["id"] for d in requests.get(f"{BASE_URL}/api/destinations", timeout=10).json()}
    assert final == before
