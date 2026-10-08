"""Test driver (Claude, temporary): one Assistant turn as the admin user, inside the backend container.

python driver.py /tmp/at/turn.json  -> prints each event as one line, then STATE <json> and FILES <json>.
turn.json: {"mode", "text", "confirm", "messages", "files" (already-read files), "upload": [paths], "conversation_id"}
"""
import json, sys, time
import httpx
from app.core.security import create_access_token
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.iam import UserAccount

turn = json.load(open(sys.argv[1], encoding="utf-8"))
db = SessionLocal()
name = get_settings().admin_username
u = db.query(UserAccount).filter(UserAccount.username == name).first()
token = create_access_token(u.username, 120, token_version=u.token_version or 0)
db.close()
H = {"Authorization": f"Bearer {token}"}
base = "http://localhost:8000/api/v1/agent"

files = list(turn.get("files") or [])
for path in turn.get("upload") or []:
    with open(path, "rb") as f:
        r = httpx.post(base + "/files", headers=H, files={"file": (path.rsplit("/", 1)[-1], f)}, timeout=120)
    print("UPLOAD", path, r.status_code, json.dumps(r.json())[:400], flush=True)
    if r.status_code == 200:
        files.append(r.json())

body = {k: turn[k] for k in ("mode", "text", "confirm", "messages", "conversation_id") if turn.get(k) is not None}
body["files"] = files
t0 = time.time()
state = None
with httpx.stream("POST", base + "/chat", headers=H, json=body, timeout=httpx.Timeout(1800, connect=30)) as r:
    print("HTTP", r.status_code, flush=True)
    for line in r.iter_lines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if ev.get("type") == "ping":
            continue
        if ev.get("type") == "state":
            state = ev
            continue
        print(f"[{time.time()-t0:6.1f}s] EVENT", json.dumps(ev, ensure_ascii=False), flush=True)
print("STATE", json.dumps(state, ensure_ascii=False))
print("FILES", json.dumps(files, ensure_ascii=False))
print("ELAPSED", round(time.time() - t0, 1))
