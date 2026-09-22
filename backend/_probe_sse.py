import asyncio, threading, time
from sqlalchemy import text
from app.core.db import SessionLocal, engine
from app.api.run_events import _stream

db = SessionLocal()
run_id = db.execute(text("SELECT run_id FROM run_event GROUP BY run_id ORDER BY run_id DESC LIMIT 1")).scalar_one()
print("run", run_id, "status", db.execute(text("SELECT status FROM run WHERE id=:r"), {"r": run_id}).scalar_one())

async def main():
    out = []
    async for chunk in _stream(run_id, 0):
        out.append(chunk)
        if len(out) > 50: break
    print("frames", len(out), out[-1][:60].replace("\n", "|"))

t = threading.Thread(target=lambda: asyncio.run(main()), daemon=True)
t.start(); t.join(timeout=20)
print("alive after 20s:", t.is_alive())
