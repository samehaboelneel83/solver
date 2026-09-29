import LoadFailure from "../components/LoadFailure";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { NetworkError } from "../api/client";
import { useBackupStatus } from "../api/v1";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/**
 * Backups & recovery (OAAS OPS01 / R39): last dump from the LATEST manifest,
 * plus the documented RPO/RTO. Dumping and restore stay on the host scripts.
 */

export default function OpsBackups() {
  useDocumentTitle("Backups & recovery");
  const status = useBackupStatus();

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-semibold text-slate-900">Backups & recovery</h1>
      <p className="mt-1 text-sm text-slate-600">
        Nightly Postgres dumps and WAL under the host backup directory. ClickHouse
        analytics are rebuildable and are not dumped. See{" "}
        <code className="text-xs">docs/runbooks/backups.md</code>.
      </p>

      {status.isError ? (
        <div className="mt-6">
          {status.error instanceof NetworkError ? (
            <OfflineNotice subject="Backup status" reason="unreachable" />
          ) : (
            <LoadFailure subject="Backup status" error={status.error} retry={() => void status.refetch()} />
          )}
        </div>
      ) : status.isLoading || !status.data ? (
        <div className="mt-6"><Skeleton rows={3} cols={2} /></div>
      ) : (
        <dl className="mt-6 grid gap-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-slate-500">Targets</dt>
            <dd className="mt-1 text-slate-900">
              RPO {status.data.rpo_hours} h · RTO {status.data.rto_hours} h
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">Backup root</dt>
            <dd className="mt-1 font-mono text-xs text-slate-800">{status.data.root}</dd>
            <dd className="mt-0.5 text-xs text-slate-500">
              {status.data.reachable ? "Reachable from the API" : "Not mounted — run dumps on the host"}
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">Last dump</dt>
            <dd className="mt-1 text-slate-900">
              {status.data.latest?.night
                ? `${status.data.latest.night} (${status.data.latest.dump ?? "—"}${
                    status.data.latest.bytes ? `, ${status.data.latest.bytes} bytes` : ""
                  })`
                : "No LATEST manifest yet"}
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">WAL archive</dt>
            <dd className="mt-1 text-slate-900">{status.data.wal_present ? "Segments present" : "None seen"}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-slate-500">Recent dumps ({status.data.dump_count})</dt>
            <dd className="mt-1 font-mono text-xs text-slate-700">
              {status.data.dumps.length ? status.data.dumps.join(", ") : "—"}
            </dd>
          </div>
          <div className="sm:col-span-2 rounded border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
            <p className="font-medium text-slate-800">On the host</p>
            <p className="mt-1">
              <code>bash scripts/backup.sh dump</code> — take a dump now
            </p>
            <p>
              <code>bash scripts/backup.sh rehearse</code> — restore into{" "}
              <code>solver_restore</code> and run suites (never touches live{" "}
              <code>solver</code>)
            </p>
          </div>
        </dl>
      )}
    </div>
  );
}
