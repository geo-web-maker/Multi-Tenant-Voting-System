import os, time
from urllib.parse import urlparse
from pymongo import MongoClient
for name in ("MONGO_URL", "SECOND_MONGO_URL"):
    u = os.getenv(name); t = time.time()
    try:
        MongoClient(u, serverSelectionTimeoutMS=8000).admin.command("ping")
        print(name, urlparse(u).hostname, "OK", round((time.time()-t)*1000), "ms")
    except Exception as e:
        print(name, urlparse(u).hostname, "FAIL", str(e)[:100])