import sys, json
sys.path.insert(0, "/app/backend")
from pymongo import MongoClient
import engine
for d in MongoClient("mongodb://localhost:27017").test_database.deals.find({}, {"_id": 0, "text": 1, "price": 1, "mrp": 1}):
    p, m = engine.extract_prices(d["text"])
    print(json.dumps({"t": d["text"][:90].replace("\n", " | "), "old": [d.get("price"), d.get("mrp")], "new": [p, m]}, ensure_ascii=False))
