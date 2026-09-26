# Backups and disaster recovery (R39)

Starting targets: **RPO 24 h**, **RTO 4 h**.

## Where backups live

On this single-host deploy, backups are files on the host under
`SOLVER_BACKUP_DIR` (default: a sibling `solver-backups` folder beside the
repository — outside git). That directory is the object store:

| Path | Contents |
|---|---|
| `$SOLVER_BACKUP_DIR/dumps/solver-YYYY-MM-DD.dump` | Nightly `pg_dump -Fc` of the live `solver` database |
| `$SOLVER_BACKUP_DIR/wal/` | Archived WAL segments (`archive_mode=on` in Postgres) |
| `$SOLVER_BACKUP_DIR/LATEST` | Manifest of the last successful dump |

ClickHouse `run_fact` is **not** backed up: it is rebuildable from Postgres.

To keep an off-box copy, sync `SOLVER_BACKUP_DIR` to object storage (S3, R2,
B2, …) with whatever tool you already use. The platform does not bill or
provision that storage.

## Nightly dump

```bash
bash scripts/backup.sh dump
# or schedule it:
bash scripts/backup.sh --install   # Windows task at 02:30
```

`scripts/nightly.sh` also runs a dump after `check.sh`.

Retention: `SOLVER_BACKUP_KEEP` days of dumps (default 14). WAL files are
left in place until you prune them by hand (or by your sync tool's lifecycle
rules).

## Restore rehearsal

Proves a dump can come back without touching the live database:

```bash
bash scripts/backup.sh rehearse
# or a specific dump:
bash scripts/backup.sh rehearse /path/to/solver-backups/dumps/solver-2026-09-26.dump
```

This restores into `solver_restore` only, runs `python -m bench.suites` (R32)
against that database, then drops `solver_restore`. It refuses to use the
name `solver`.

## Real recovery (disaster)

1. Stop writers: `docker compose stop backend worker frontend`.
2. Restore into a new data directory or replace the live DB only after you
   have a second dump of the broken state.
3. `pg_restore` the chosen dump (and WAL replay from `$SOLVER_BACKUP_DIR/wal`
   if you need a point after the dump).
4. Start the stack; confirm `alembic current` and a plan run.
5. Budget: aim to be answering plans again within **4 h** of the decision to
   restore; accept up to **24 h** of data loss relative to the last good dump
   unless WAL replay covers the gap.

## Changing the backup root

```bash
# PowerShell / env for compose + scripts
$env:SOLVER_BACKUP_DIR = "D:/solver-backups"
mkdir -Force $env:SOLVER_BACKUP_DIR/dumps, $env:SOLVER_BACKUP_DIR/wal
docker compose up -d --force-recreate postgres
bash scripts/backup.sh dump
```
