/**
 * Camp layouts: the domain's camps, each drawn on the map and laid out by the
 * camp layout engine. Start one blank, from an example, or from a CAD drawing
 * or camp workbook; open one to draw, solve and see its layout.
 */
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileUp, MapPinned, Tent, Trash2 } from "lucide-react";
import { formatApiError } from "../api/errors";
import { importCampFile, useCamps, useCreateCamp, useDeleteCamp, type CampListItem } from "../api/camps";
import LoadFailure from "../components/LoadFailure";
import Skeleton from "../components/Skeleton";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useDomain } from "../hooks/useDomain";
import { relativeTime } from "../lib/relativeTime";

const STATUS: Record<string, string> = {
  queued: "Waiting to be laid out",
  running: "Being laid out",
  failed: "Last layout failed",
  cancelled: "Last layout stopped",
};

function CampRow({ camp, domainId, canEdit }: { camp: CampListItem; domainId: number; canEdit: boolean }) {
  const remove = useDeleteCamp();
  const [confirming, setConfirming] = useState(false);
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4" data-testid="camp">
      <div className="flex items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-emerald-50 text-emerald-700" aria-hidden>
          <Tent className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <Link to={`/domains/${domainId}/camps/${camp.id}`} className="font-semibold text-slate-900 hover:underline">
            {camp.name}
          </Link>
          <p className="mt-0.5 text-xs text-slate-500">
            {camp.doors} door{camp.doors === 1 ? "" : "s"} · edited {relativeTime(camp.updated_at)} ·{" "}
            {camp.origin_lonlat ? `${camp.origin_lonlat[1].toFixed(4)}, ${camp.origin_lonlat[0].toFixed(4)}` : ""}
          </p>
          <p className="mt-1 text-sm text-slate-700">
            {camp.status === "done"
              ? <>Latest layout: <strong>{camp.beds} beds</strong>{camp.valid ? ", every check passed" : ", some checks failed"}</>
              : camp.status ? STATUS[camp.status] : "Not laid out yet"}
          </p>
        </div>
        {canEdit && (
          <button type="button" aria-label={`Delete ${camp.name}`} onClick={() => setConfirming(true)}
            className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-red-700">
            <Trash2 className="h-4 w-4" />
          </button>
        )}
      </div>
      {confirming && (
        <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          Delete {camp.name} and every layout made of it?
          <div className="mt-2 flex gap-2">
            <button type="button" disabled={remove.isPending} className="rounded bg-red-600 px-3 py-1.5 text-white disabled:opacity-60"
              onClick={() => remove.mutate(camp.id)}>Delete</button>
            <button type="button" className="rounded px-3 py-1.5 underline" onClick={() => setConfirming(false)}>Keep it</button>
          </div>
        </div>
      )}
    </li>
  );
}

export default function CampList() {
  useDocumentTitle("Camp layouts");
  const { domainId } = useDomain();
  const camps = useCamps(domainId);
  const create = useCreateCamp();
  const navigate = useNavigate();
  const { can } = useCapabilities();
  const canEdit = can("domain.edit");
  const [name, setName] = useState("");
  const [start, setStart] = useState<"blank" | "small" | "complex">("blank");
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [units, setUnits] = useState("");
  const [crs, setCrs] = useState("");
  const file = useRef<HTMLInputElement>(null);

  if (domainId === null) return <p className="text-sm text-slate-600">Choose a domain first.</p>;

  const make = async (body: Parameters<typeof create.mutateAsync>[0]) => {
    setError(null);
    try {
      const made = await create.mutateAsync(body);
      navigate(`/domains/${domainId}/camps/${made.id}`);
    } catch (e) {
      setError(formatApiError(e));
    }
  };

  const fromFile = async (picked: File | undefined) => {
    if (!picked) return;
    setImporting(true);
    setError(null);
    try {
      const got = await importCampFile(picked, units, crs);
      await make({ domain_id: domainId, name: name.trim() || got.problem.name, problem: got.problem });
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setImporting(false);
      if (file.current) file.current.value = "";
    }
  };

  return (
    <div className="max-w-5xl space-y-6">
      <header>
        <h1 className="mb-1 text-lg font-semibold text-slate-900">Camp layouts</h1>
        <p className="text-sm text-slate-500">
          Draw a camp on the map — its outline, doors, closed areas, no-bed areas and bed zones — then lay it out:
          the most beds that fit, each reachable from a door along corridors at least as wide as you set, shown on the map.
        </p>
      </header>

      {canEdit && (
        <section className="rounded-lg border border-slate-200 bg-white p-4" aria-labelledby="new-camp">
          <h2 id="new-camp" className="text-sm font-semibold text-slate-900">New camp</h2>
          <div className="mt-3 grid gap-3 md:grid-cols-[1fr_auto]">
            <label className="text-sm text-slate-700">
              Name
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. North camp, block B"
                className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" maxLength={200} />
            </label>
            <fieldset className="text-sm text-slate-700">
              <legend>Start from</legend>
              <div className="mt-1 flex flex-wrap gap-3">
                {([["blank", "A blank 30 × 20 m camp"], ["small", "Small example"], ["complex", "Complex example"]] as const).map(([v, label]) => (
                  <label key={v} className="flex items-center gap-1.5">
                    <input type="radio" name="start" checked={start === v} onChange={() => setStart(v)} /> {label}
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button type="button" disabled={create.isPending}
              onClick={() => void make({ domain_id: domainId, name: name.trim() || (start === "blank" ? "New camp" : start === "small" ? "Small camp" : "Irregular camp"), start })}
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60">
              <MapPinned className="h-4 w-4" aria-hidden /> Create and draw
            </button>
            <span className="text-sm text-slate-500">or</span>
            <button type="button" disabled={importing} onClick={() => file.current?.click()}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60">
              <FileUp className="h-4 w-4" aria-hidden /> {importing ? "Reading…" : "From a CAD drawing (.dxf) or workbook (.xlsx)"}
            </button>
            <input ref={file} type="file" accept=".dxf,.xlsx" className="hidden" aria-label="CAD drawing or camp workbook"
              onChange={(e) => void fromFile(e.target.files?.[0])} />
            <label className="text-xs text-slate-600">
              Drawing units
              <select value={units} onChange={(e) => setUnits(e.target.value)} className="ml-1 rounded border border-slate-300 bg-white px-1 py-0.5">
                <option value="">from the drawing</option>
                <option value="mm">millimetres</option>
                <option value="cm">centimetres</option>
                <option value="m">metres</option>
                <option value="ft">feet</option>
              </select>
            </label>
            <label className="text-xs text-slate-600">
              Coordinate system
              <input value={crs} onChange={(e) => setCrs(e.target.value)} placeholder="e.g. EPSG:32636 (optional)"
                className="ml-1 w-44 rounded border border-slate-300 px-1 py-0.5" />
            </label>
          </div>
          <p className="mt-2 text-xs text-slate-500">
            A drawing is read by layer: CAMP_BOUNDARY, DOORS, OBSTACLES, NO_BEDS and ZONE_&lt;name&gt;. With a coordinate
            system, the camp lands where the drawing is on the map.
          </p>
          {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
        </section>
      )}

      <section aria-label="Camps">
        {camps.isLoading ? <Skeleton /> : camps.isError ? <LoadFailure subject="The camps" error={camps.error} retry={() => void camps.refetch()} /> : (
          camps.data!.items.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">
              No camps in this domain yet.
            </p>
          ) : (
            <ul className="space-y-3">
              {camps.data!.items.map((c) => <CampRow key={c.id} camp={c} domainId={domainId} canEdit={canEdit} />)}
            </ul>
          )
        )}
      </section>
    </div>
  );
}
