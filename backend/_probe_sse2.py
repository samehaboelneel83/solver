import threading
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.core.db import SessionLocal
from app.core.config import get_settings
from app.core.security import create_access_token
from app.main import app

db = SessionLocal()
run_id = db.execute(text("SELECT run_id FROM run_event GROUP BY run_id ORDER BY run_id DESC LIMIT 1")).scalar_one()
headers = {"Authorization": "Bearer " + create_access_token(subject=get_settings().admin_username)}

def go(label, fn):
    t = threading.Thread(target=fn, daemon=True); t.start(); t.join(timeout=15)
    print(label, "hung" if t.is_alive() else "ok")

def plain():
    r = TestClient(app).get(f"/api/v1/runs/{run_id}", headers=headers); print("  plain status", r.status_code)

def streamed():
    with TestClient(app).stream("GET", f"/api/v1/runs/{run_id}/events", headers=headers) as r:
        print("  stream status", r.status_code)
        n = 0
        for line in r.iter_lines():
            n += 1
            if n > 40: break
        print("  lines", n)

go("plain", plain)
go("stream", streamed)
