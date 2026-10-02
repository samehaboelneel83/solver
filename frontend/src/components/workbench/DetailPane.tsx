import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import { formatApiError } from "../../api/errors";
import EntityRelationships from "../EntityRelationships";
import RecordHistory from "../RecordHistory";
import RecordTrees from "../RecordTrees";
import { useToast } from "../ToastProvider";
import { useCapabilities } from "../../hooks/useCapability";
import { RecordPanel } from "../../pages/EntityRecord";
import LocationEditor from "./LocationEditor";
import { useChildren, usePlace, useRecordValues, type RecordValues } from "../../api/workbench";
import { useEntityRecord, useEntityType, type Entity, type EntityType, type Id } from "../../api/v1";
import { asGeometry } from "../../lib/geoShape";
import type { GeoGeometry } from "../map/GeoMap";

type Tab = "fields" | "location" | "linked" | "values" | "problems" | "history";

const WORDS: Record<string, string> = {
  loop: "It is in a chain that comes back on itself. Change one link in the chain.",
  too_deep: "It sits deeper below the top of its tree than the domain's limit.",
  outside_tree: "It has no parent and nothing under it, while the rest of its kind is placed in a tree.",
  inactive_target: "One of its reference fields names a switched-off record; a solve leaves that record out.",
};

function OwnValue({ entityId, p }: { entityId: Id; p: RecordValues }) {
  const { can } = useCapabilities();
  const toast = useToast();
  const queryClient = useQueryClient();
  const stored = p.cells[0]?.value ?? null;
  const [draft, setDraft] = useState(stored === null ? "" : String(stored));
  const [busy, setBusy] = useState(false);
  const changed = draft !== (stored === null ? "" : String(stored));

  async function save() {
    const value = draft.trim() === "" ? p.default_value : Number(draft);
    if (value !== null && !Number.isFinite(value)) {
      toast.error(`${p.name}: must be a number`);
      return;
    }
    setBusy(true);
    try {
      await apiFetch(`/api/v1/parameters/${p.parameter_id}/values`, {
        method: "PUT",
        body: JSON.stringify({ cells: [{ entity_ids: [entityId], value }] }),
      });
      toast.success(`${p.name} saved`);
      await queryClient.invalidateQueries({ queryKey: ["v1"] });
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <input
        aria-label={p.name}
        className="w-28 rounded-md border border-slate-300 px-2 py-1 text-right text-sm"
        inputMode="decimal"
        placeholder={p.default_value === null ? "" : String(p.default_value)}
        value={draft}
        disabled={!can("domain.edit")}
        onChange={(e) => setDraft(e.target.value)}
      />
      {p.unit && <span className="text-xs text-slate-500">{p.unit}</span>}
      {changed && (
        <button type="button" disabled={busy} onClick={save} className="rounded-md bg-slate-900 px-2 py-1 text-xs text-white">
          Save
        </button>
      )}
      {stored === null && !changed && <span className="text-xs text-slate-400">the default, {p.default_value}</span>}
    </div>
  );
}

function Values({ entityId, domainId }: { entityId: Id; domainId: Id }) {
  const values = useRecordValues(entityId);
  const params = values.data?.parameters ?? [];
  if (values.isLoading) return <p className="text-sm text-slate-500">Loading…</p>;
  if (params.length === 0) return <p className="text-sm text-slate-500">No parameter is indexed by this kind of record.</p>;
  return (
    <ul className="space-y-3">
      {params.map((p) => (
        <li key={p.parameter_id} className="rounded-md border border-slate-200 p-3">
          <p className="text-sm font-medium text-slate-900">
            {p.name}
            <span className="ml-1 text-xs font-normal text-slate-500">[{p.index_kinds.join(", ")}]</span>
          </p>
          {p.single && !p.entity_valued ? (
            <div className="mt-2">
              <OwnValue entityId={entityId} p={p} />
            </div>
          ) : (
            <>
              <ul className="mt-1 text-sm text-slate-700">
                {p.cells.slice(0, 8).map((c) => (
                  <li key={c.entity_ids.join("-")}>
                    <span className="font-mono text-xs">{c.keys.join(" · ")}</span> → {c.value_key ?? c.value}
                  </li>
                ))}
                {p.cells.length === 0 && <li className="text-slate-500">No cells set; every one is the default.</li>}
                {p.cells.length > 8 && <li className="text-slate-500">and {p.cells.length - 8} more</li>}
              </ul>
              <Link to={`/domains/${domainId}/data/parameters`} className="mt-1 inline-block text-xs text-blue-700 underline">
                Edit all cells on the Parameters page
              </Link>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Every shape a record holds, in any of its kind's shape fields. */
function shapesOf(e: Entity | undefined | null, type: EntityType | undefined | null): GeoGeometry[] {
  if (!e || !type) return [];
  return type.attributes
    .filter((a) => a.data_type === "geometry")
    .map((a) => asGeometry(e.attrs?.[a.name]))
    .filter((g): g is GeoGeometry => g !== null);
}

/** The location editor, with what is around the record drawn faintly: its parent's shape and its siblings'. */
function Surroundings({ domainId, entity, type }: { domainId: Id; entity: Entity; type: EntityType }) {
  const place = usePlace(domainId, entity.id);
  const parent = useEntityRecord(place.data?.parent?.id ?? null);
  const parentType = useEntityType(parent.data?.entity_type_id ?? null);
  const siblings = useChildren(domainId, place.data?.group ?? null, place.data?.parent?.id ?? null, { limit: 200 });
  const context = [
    ...shapesOf(parent.data, parentType.data),
    ...(siblings.data?.items ?? []).filter((s) => s.id !== entity.id).flatMap((s) => shapesOf(s, type)),
  ];
  return <LocationEditor key={`${entity.id}-${entity.updated_at}`} entity={entity} type={type} context={context} />;
}

/**
 * The right of the workbench: the record chosen, its fields as the record form, what links to it,
 * its parameter values (its own value editable in place), what the quality checks say of it, and
 * who changed what.
 */
export default function DetailPane({
  entityId,
  domainId,
  problems,
  onClosed,
}: {
  entityId: Id;
  domainId: Id;
  problems: string[];
  onClosed: () => void;
}) {
  const [tab, setTab] = useState<Tab>("fields");
  const record = useEntityRecord(entityId);
  const type = useEntityType(record.data?.entity_type_id ?? null);
  const placed = (type.data?.attributes ?? []).some((a) => a.data_type === "geometry");
  const tabs: [Tab, string][] = [
    ["fields", "Fields"],
    ...(placed ? ([["location", "Location"]] as [Tab, string][]) : []),
    ["linked", "Linked"],
    ["values", "Values"],
    ["problems", problems.length ? `Problems (${problems.length})` : "Problems"],
    ["history", "History"],
  ];
  return (
    <section aria-label="Selected record" className="space-y-3">
      <header>
        <p className="text-xs uppercase tracking-wide text-slate-500">{type.data?.name}</p>
        <h2 className="text-lg font-semibold text-slate-900">
          {record.data?.label || record.data?.key}
          {record.data?.label && <span className="ml-2 font-mono text-sm text-slate-500">{record.data.key}</span>}
        </h2>
        <Link to={`/entities/${entityId}`} className="text-xs text-blue-700 underline">
          Open on its own page
        </Link>
      </header>
      <div role="tablist" aria-label="About this record" className="flex gap-1 border-b border-slate-200">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            type="button"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`rounded-t-md border-b-2 px-3 py-1.5 text-sm ${
              tab === key ? "border-blue-600 font-medium text-blue-800" : "border-transparent text-slate-600"
            } ${key === "problems" && problems.length ? "text-amber-700" : ""}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "fields" && <RecordPanel entityId={entityId} onDeleted={onClosed} />}
        {tab === "linked" && record.data && type.data && (
          <div className="space-y-4">
            <RecordTrees entity={record.data} />
            <EntityRelationships entity={record.data} entityType={type.data} />
          </div>
        )}
        {tab === "location" && record.data && type.data && (
          <Surroundings domainId={domainId} entity={record.data} type={type.data} />
        )}
        {tab === "values" && <Values entityId={entityId} domainId={domainId} />}
        {tab === "history" && <RecordHistory entityId={entityId} />}
        {tab === "problems" &&
          (problems.length === 0 ? (
            <p className="text-sm text-emerald-800">The quality checks find nothing wrong with this record.</p>
          ) : (
            <ul className="space-y-2">
              {problems.map((code) => (
                <li key={code} className="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
                  {WORDS[code] ?? code}
                </li>
              ))}
              <li>
                <Link to={`/domains/${domainId}/data/quality`} className="text-xs text-blue-700 underline">
                  See all of the domain's quality checks
                </Link>
              </li>
            </ul>
          ))}
      </div>
    </section>
  );
}
