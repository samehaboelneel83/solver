"""Dedicated ingestion process. Run separately from API and optimization workers."""
import multiprocessing as mp
import os
import time
from pathlib import Path
from uuid import UUID, uuid4
from sqlalchemy import text
from app import audit
from app.integrations.contracts import FAILURE_CODES, ExtractionError, ExtractionLimits, ExtractionRequest
from app.integrations.policy import source_for
from app.integrations.postgres import PostgresConnector
from app.integrations.secrets import decrypt
from app.integrations.snapshots import stage_snapshot


def _extract(row, output, cancelled, result):
    try:
        # Production worker runs in the Linux container. Windows pilots retain
        # the deadline but require an external Job Object/container memory cap.
        if os.name == "posix":
            import resource
            memory = 1024 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        source = source_for(row)
        try:
            password = decrypt(row["credential"], row["organization_id"], row["id"])
        except Exception:
            raise ExtractionError("The stored credential cannot be read with this server's keys", "credential_unreadable") from None
        adapter = PostgresConnector(source, lambda _: password)
        request = ExtractionRequest(row["organization_id"], row["id"], source.table, tuple(source.columns), ExtractionLimits())
        artifact = stage_snapshot(Path(output), adapter, request, cancelled)
        result.send(("extracted", artifact.name))
    except ExtractionError as error:
        result.send(("failed", error.code))  # A failure class only: never driver details or credentials.
    except Exception:
        result.send(("failed", "extraction_failed"))
    finally:
        result.close()


def process_one(session_factory, output: str) -> bool:
    with session_factory() as db:
        # A crashed supervisor cannot leave a job permanently active. There is
        # no automatic replay: the caller may explicitly submit a new job.
        db.execute(text("UPDATE ingestion_job SET state='failed',error_code='worker_lost',finished_at=now() WHERE state='running' AND started_at < now() - interval '10 minutes'"))
        job = db.execute(text("SELECT * FROM ingestion_job WHERE state='queued' ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1")).mappings().one_or_none()
        if job is None:
            db.commit()
            return False
        job = dict(job)
        connection = db.execute(text("SELECT * FROM integration_connection WHERE id=:id AND organization_id=:o"), {"id": job["connection_id"], "o": job["organization_id"]}).mappings().one()
        if job["cancel_requested"] or not connection["enabled"]:
            db.execute(text("UPDATE ingestion_job SET state='cancelled',finished_at=now() WHERE id=:id"), {"id": job["id"]})
            db.commit()
            return True
        row = dict(connection)
        attempt = uuid4()
        db.execute(text("UPDATE ingestion_job SET state='running',attempt=:a,started_at=now() WHERE id=:id"), {"a": attempt, "id": job["id"]})
        db.commit()
    context = mp.get_context("spawn")
    cancelled = context.Event()
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_extract, args=(row, output, cancelled, sender), daemon=True)
    state, artifact, error = "failed", None, "extraction_failed"
    started = time.monotonic()
    try:
        process.start()
        sender.close()
        while process.is_alive():
            process.join(timeout=0.25)
            with session_factory() as db:
                current = db.execute(text("SELECT j.state,j.attempt,j.cancel_requested,c.enabled FROM ingestion_job j JOIN integration_connection c ON c.id=j.connection_id WHERE j.id=:id"), {"id": job["id"]}).mappings().one()
            if current["state"] != "running" or current["attempt"] != attempt or current["cancel_requested"] or not current["enabled"]:
                cancelled.set()
                state, error = "cancelled", None
                break
            if time.monotonic() - started > 330:
                cancelled.set()
                error = "deadline_exceeded"
                break
        if not cancelled.is_set() and receiver.poll():
            try:
                state, artifact = receiver.recv()
                if state == "extracted":
                    artifact = UUID(artifact)
                    error = None
                else:
                    state, error = "failed", artifact if artifact in FAILURE_CODES else "extraction_failed"
                    artifact = None
            except (EOFError, ValueError):
                state, artifact = "failed", None
    finally:
        cancelled.set()
        if process.pid is not None:
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join()
        receiver.close()
        sender.close()
        with session_factory() as db:
            # Cancellation/disable races take precedence over a completed child.
            settled = db.execute(text("""UPDATE ingestion_job j SET
                state=CASE WHEN j.cancel_requested OR NOT c.enabled THEN 'cancelled' ELSE :state END,
                artifact_id=CASE WHEN j.cancel_requested OR NOT c.enabled THEN NULL ELSE CAST(:artifact AS uuid) END,
                error_code=:error,finished_at=now()
                FROM integration_connection c WHERE j.id=:id AND j.connection_id=c.id
                AND j.state='running' AND j.attempt=:attempt RETURNING j.state"""),
                {"state": state, "artifact": artifact, "error": error, "id": job["id"], "attempt": attempt}).scalar_one_or_none()
            if settled:
                audit.record(db, organization_id=job["organization_id"], action=f"integration.job.{settled}",
                             object_type="ingestion_job", object_id=job["id"])
            db.commit()
    return True


def main():
    from app.core.db import SessionLocal
    output = os.environ.get("OAAS_INTEGRATION_OUTPUT")
    if not output:
        raise SystemExit("OAAS_INTEGRATION_OUTPUT must name a private artifact directory")
    while True:
        if not process_one(SessionLocal, output):
            time.sleep(2)


if __name__ == "__main__":
    main()
