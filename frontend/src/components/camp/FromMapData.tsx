/**
 * Start a camp from map data: choose an imported drawing, and say which of its
 * layers is the camp boundary and which hold doors, closed areas, no-bed
 * areas and bed zones. Layer names are matched to roles as a first guess
 * (`BOUNDARY`, `SITE`, `DOOR`, `GATE`, `OBSTACLE`, `NO_BEDS`, `ZONE_`...).
 */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Layers } from "lucide-react";
import { formatApiError } from "../../api/errors";
import { createCampFromMap, type FromMapRoles } from "../../api/camps";
import { useDataset, useDatasets, type GisLayer } from "../../api/gis";

type Role = "boundary" | "doors" | "obstacles" | "prohibited" | "zones";
const ROLES: [Role, string, RegExp][] = [
  ["boundary", "Camp boundary", /bound|site|camp|plot|outline|fence|perimeter/i],
  ["doors", "Doors and gates", /door|gate|entr|exit/i],
  ["obstacles", "Closed areas", /obstacle|closed|build|struct|fixed|tank|tree|wall/i],
  ["prohibited", "No-beds areas", /no.?bed|prohib|fire|keep.?clear|clear/i],
  ["zones", "Bed zones", /^zone|zone_/i],
];

function guess(layers: GisLayer[]): Record<Role, number[]> {
  const out: Record<Role, number[]> = { boundary: [], doors: [], obstacles: [], prohibited: [], zones: [] };
  for (const l of layers) {
    const role = ROLES.find(([, , re]) => re.test(l.name));
    if (role) out[role[0]].push(l.id);
  }
  out.boundary = out.boundary.slice(0, 1);
  return out;
}

export default function FromMapData({ domainId }: { domainId: number }) {
  const datasets = useDatasets(domainId);
  const [datasetId, setDatasetId] = useState<number | null>(null);
  const dataset = useDataset(datasetId);
  const [roles, setRoles] = useState<Record<Role, number[]>>({ boundary: [], doors: [], obstacles: [], prohibited: [], zones: [] });
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (dataset.data) {
      setRoles(guess(dataset.data.layers));
      setName(dataset.data.name);
    }
  }, [dataset.data]);

  const items = datasets.data?.items ?? [];
  if (!items.length) {
    return (
      <p className="text-xs text-slate-500">
        Import a CAD drawing under <Link className="text-blue-700 underline" to={`/domains/${domainId}/map-data/import`}>Map data</Link> to
        start a camp from its layers.
      </p>
    );
  }
  const layers = dataset.data?.layers ?? [];
  const make = async () => {
    if (!datasetId || !roles.boundary[0]) return;
    setBusy(true);
    setError(null);
    try {
      const body: FromMapRoles = { boundary: roles.boundary[0], doors: roles.doors, obstacles: roles.obstacles,
        prohibited: roles.prohibited, zones: roles.zones };
      const made = await createCampFromMap({ domain_id: domainId, name: name.trim() || "Camp", dataset_id: datasetId, ...body });
      navigate(`/domains/${domainId}/camps/${made.id}`);
    } catch (e) {
      setError(formatApiError(e));
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2" aria-label="From map data">
      <label className="block text-sm text-slate-700">
        Map data
        <select value={datasetId ?? ""} aria-label="Map data to start from" onChange={(e) => setDatasetId(e.target.value ? Number(e.target.value) : null)}
          className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm">
          <option value="">choose an imported drawing…</option>
          {items.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.layers} layers)</option>)}
        </select>
      </label>
      {dataset.data && (
        <>
          <div className="grid gap-2 md:grid-cols-2">
            {ROLES.map(([role, label]) => (
              <fieldset key={role} className="rounded border border-slate-200 p-2">
                <legend className="px-1 text-xs font-semibold text-slate-700">{label}{role === "boundary" ? " (one layer)" : ""}</legend>
                <div className="max-h-28 overflow-y-auto text-xs">
                  {layers.map((l) => (
                    <label key={l.id} className="flex items-center gap-1.5 py-0.5">
                      <input type={role === "boundary" ? "radio" : "checkbox"} name={`role-${role}`}
                        checked={roles[role].includes(l.id)}
                        onChange={(e) => setRoles({ ...roles, [role]: role === "boundary" ? [l.id]
                          : e.target.checked ? [...roles[role], l.id] : roles[role].filter((x) => x !== l.id) })} />
                      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: l.color }} />
                      {l.name} <span className="text-slate-400">{l.feature_count}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
          </div>
          <label className="block text-sm text-slate-700">
            Camp name
            <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200}
              className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
          </label>
          <button type="button" disabled={busy || !roles.boundary.length} onClick={() => void make()}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60">
            <Layers className="h-4 w-4" aria-hidden /> {busy ? "Building the camp…" : "Create the camp from these layers"}
          </button>
        </>
      )}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </div>
  );
}
