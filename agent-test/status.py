import json, httpx
from app.core.security import create_access_token
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.iam import UserAccount
db = SessionLocal(); u = db.query(UserAccount).filter(UserAccount.username == get_settings().admin_username).first()
t = create_access_token(u.username, 30, token_version=u.token_version or 0); db.close()
r = httpx.get("http://localhost:8000/api/v1/agent/status", headers={"Authorization": f"Bearer {t}"}, timeout=30)
print("STATUS", r.text[:600])
