import time
from app.core.db import SessionLocal
from app.api.answer_map import _map_of
db = SessionLocal()
t = time.time()
m = _map_of(db, 51)
print("MAP", round(time.time()-t, 1), len(m["features"]), [l["title"] for l in m["layers"]], m["features"][0]["geometry"]["coordinates"][0][:2] if m["features"] else None)
