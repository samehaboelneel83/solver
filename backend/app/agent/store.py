"""The Assistant's conversations, kept on the server (migration 0109).

The browser sends only the new message and the conversation's id; the history the model is sent, the
attached files and the turn count are read from here and written back when the turn ends. A layout
problem's history passed 1 MB and the web server refused the request (October 2026): the browser no
longer carries it.

Every read and write names the owner: a conversation is the person's own, whoever else is in the
organization. Rows not touched for `KEEP_DAYS` are swept.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

KEEP_DAYS = 30


def load(db: Session, conversation_id: str, owner_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text("SELECT mode, messages, files, turns FROM agent_conversation WHERE id = :i AND owner_id = CAST(:o AS uuid)"),
        {"i": conversation_id, "o": owner_id}).mappings().one_or_none()
    return dict(row) if row else None


def taken(db: Session, conversation_id: str, owner_id: str) -> bool:
    """Whether someone else already has a conversation with this id (ids come from the browser)."""
    return bool(db.execute(
        text("SELECT 1 FROM agent_conversation WHERE id = :i AND owner_id <> CAST(:o AS uuid)"),
        {"i": conversation_id, "o": owner_id}).first())


def save(db: Session, conversation_id: str, owner_id: str, organization_id: str, mode: str,
         messages: list[dict[str, Any]], files: list[dict[str, Any]] | None, turned: bool = True) -> None:
    """Insert or replace the conversation's history (and its files, when given)."""
    params = {"i": conversation_id, "o": owner_id, "org": organization_id, "m": mode,
              "msgs": json.dumps(messages, ensure_ascii=False, default=str),
              "f": json.dumps(files if files is not None else [], ensure_ascii=False, default=str),
              "keep_files": files is None, "t": 1 if turned else 0}
    db.execute(text(
        "INSERT INTO agent_conversation (id, organization_id, owner_id, mode, messages, files, turns)"
        " VALUES (:i, CAST(:org AS uuid), CAST(:o AS uuid), :m, CAST(:msgs AS jsonb), CAST(:f AS jsonb), :t)"
        " ON CONFLICT (id) DO UPDATE SET messages = EXCLUDED.messages, mode = EXCLUDED.mode,"
        "   files = CASE WHEN :keep_files THEN agent_conversation.files ELSE EXCLUDED.files END,"
        "   turns = agent_conversation.turns + EXCLUDED.turns"
        " WHERE agent_conversation.owner_id = CAST(:o AS uuid)"), params)
    db.commit()


def delete(db: Session, conversation_id: str, owner_id: str) -> None:
    db.execute(text("DELETE FROM agent_conversation WHERE id = :i AND owner_id = CAST(:o AS uuid)"),
               {"i": conversation_id, "o": owner_id})
    db.commit()


def sweep(db: Session) -> int:
    n = db.execute(text(f"DELETE FROM agent_conversation WHERE updated_at < now() - interval '{KEEP_DAYS} days'")).rowcount
    db.commit()
    return n
