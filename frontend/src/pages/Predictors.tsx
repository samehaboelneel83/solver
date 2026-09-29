/**
 * Predictors (Epic ML, follow-up): the trained models a domain holds, which a
 * model reads with `predict name(inputs...)`. Train one from the domain's own
 * records, upload one trained elsewhere as `tree-ensemble/1` JSON (never a
 * pickle), see how well it predicted rows it was not trained on, delete one
 * nothing uses.
 */
import { useMemo, useState } from "react";
import { BrainCircuit, Trash2 } from "lucide-react";
import { formatApiError } from "../api/errors";
import {
  useDeletePredictor,
  useEntityTypes,
  usePredictors,
  useTrainPredictor,
  useUploadPredictor,
  type Predictor,
} from "../api/v1";
import LoadFailure from "../components/LoadFailure";
import OfflineNotice from "../components/OfflineNotice";
import Skeleton from "../components/Skeleton";
import { INPUT_CLASS } from "../components/attrTypes";
import { useCapabilities } from "../hooks/useCapability";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useDomain } from "../hooks/useDomain";
import { relativeTime } from "../lib/relativeTime";

const NAME = /^[a-z][a-z0-9_]*$/;
const NUMERIC = new Set(["integer", "number"]);

function score(value: number | null | undefined, digits = 3): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("en", { maximumFractionDigits: digits });
}

function PredictorCard({ predictor, canEdit }: { predictor: Predictor; canEdit: boolean }) {
  const remove = useDeletePredictor();
  const [confirming, setConfirming] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const m = predictor.metrics ?? {};
  const trained = predictor.training;
  const updated = relativeTime(predictor.updated_at);
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4" data-testid="predictor">
      <div className="flex items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-700" aria-hidden="true">
          <BrainCircuit size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-sans text-sm font-semibold tracking-normal text-slate-900">{predictor.name}</h3>
          <code className="mt-0.5 block truncate font-mono text-xs text-slate-700">
            predict {predictor.name}({predictor.inputs.join(", ")})
          </code>
          {predictor.note && <p className="mt-1 text-sm text-slate-600">{predictor.note}</p>}
          <p className="mt-1 text-xs text-slate-500">
            {trained?.entity_type
              ? `${trained.kind === "gradient_boosting" ? "Gradient boosting" : "Random forest"} on ${trained.entity_type}, predicting ${trained.target}`
              : "Uploaded"}
            {predictor.summary?.trees ? ` · ${predictor.summary.trees} trees, ${predictor.summary.leaves ?? "?"} leaves` : ""}
            {updated ? ` · updated ${updated}` : ""}
          </p>
        </div>
        {canEdit && !confirming && (
          <button type="button" aria-label={`Delete ${predictor.name}`} title="Delete" onClick={() => setConfirming(true)}
            className="rounded p-1.5 text-slate-500 hover:bg-slate-100 hover:text-red-700">
            <Trash2 size={15} aria-hidden="true" />
          </button>
        )}
      </div>
      {m.holdout_rows ? (
        <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-xs" aria-label={`How well ${predictor.name} predicts`}>
          <div className="rounded bg-slate-50 px-2 py-1.5"><dt className="text-slate-500">R²</dt><dd className="font-mono text-sm text-slate-900">{score(m.r2)}</dd></div>
          <div className="rounded bg-slate-50 px-2 py-1.5"><dt className="text-slate-500">Mean error</dt><dd className="font-mono text-sm text-slate-900">{score(m.mae)}</dd></div>
          <div className="rounded bg-slate-50 px-2 py-1.5"><dt className="text-slate-500">RMSE</dt><dd className="font-mono text-sm text-slate-900">{score(m.rmse)}</dd></div>
        </dl>
      ) : null}
      {m.evaluated_on && (
        <p className="mt-2 text-xs text-slate-500">
          Measured on {m.evaluated_on}{m.rows ? ` (${m.rows} rows${m.rows_skipped ? `, ${m.rows_skipped} skipped for missing numbers` : ""})` : ""}.
        </p>
      )}
      {confirming && (
        <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          <p>Delete {predictor.name}? A model version that reads it keeps it from being deleted.</p>
          <div className="mt-2 flex gap-2">
            <button type="button" disabled={remove.isPending} className="rounded bg-red-600 px-3 py-1.5 text-white disabled:opacity-60"
              onClick={() => remove.mutate(predictor.id, { onError: (e) => { setProblem(formatApiError(e)); setConfirming(false); } })}>
              Delete it
            </button>
            <button type="button" className="rounded px-3 py-1.5 underline" onClick={() => setConfirming(false)}>Keep it</button>
          </div>
        </div>
      )}
      {problem && <p role="alert" className="mt-2 text-sm text-red-700">{problem}</p>}
    </li>
  );
}

function TrainForm({ domainId }: { domainId: number }) {
  const types = useEntityTypes(domainId, { limit: 500, offset: 0 });
  const train = useTrainPredictor();
  const [name, setName] = useState("");
  const [entityType, setEntityType] = useState("");
  const [target, setTarget] = useState("");
  const [features, setFeatures] = useState<string[]>([]);
  const [kind, setKind] = useState<"random_forest" | "gradient_boosting">("random_forest");
  const [trees, setTrees] = useState("50");
  const [depth, setDepth] = useState("6");
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);

  const typeItems = types.data?.items ?? [];
  const chosen = typeItems.find((t) => t.name === entityType);
  const numeric = useMemo(() => (chosen?.attributes ?? []).filter((a) => NUMERIC.has(a.data_type)).map((a) => a.name), [chosen]);
  const problem = !NAME.test(name)
    ? "Name it with lower-case letters, digits and underscores, starting with a letter."
    : !chosen ? "Choose the records to learn from."
      : !target ? "Choose what to predict."
        : features.length === 0 ? "Choose at least one input."
          : null;

  return (
    <form
      className="space-y-3 rounded-lg border border-slate-200 bg-white p-4"
      aria-labelledby="train-heading"
      onSubmit={(event) => {
        event.preventDefault();
        if (problem) return;
        setMessage(null);
        train.mutate(
          { domain_id: domainId, name, entity_type: entityType, target, features, kind, trees: Number(trees) || 50, max_depth: Number(depth) || 6 },
          {
            onSuccess: (made) => setMessage({ error: false, text: `Trained ${made.name}.` }),
            onError: (e) => setMessage({ error: true, text: formatApiError(e) }),
          },
        );
      }}
    >
      <h2 id="train-heading" className="font-sans text-base font-semibold tracking-normal text-slate-900">Train a model</h2>
      <p className="text-sm text-slate-600">
        Learns one numeric attribute of a record type from others, with a held-out fifth of the records to say how well it predicts.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">Name of the model
          <input className={INPUT_CLASS} value={name} onChange={(e) => setName(e.target.value)} placeholder="demand_model" />
        </label>
        <label className="block text-sm">Learn from records of
          <select className={INPUT_CLASS} value={entityType} onChange={(e) => { setEntityType(e.target.value); setTarget(""); setFeatures([]); }}>
            <option value="">Choose a record type</option>
            {typeItems.map((t) => <option key={String(t.id)} value={t.name}>{t.name}</option>)}
          </select>
        </label>
        <label className="block text-sm">Predict
          <select className={INPUT_CLASS} value={target} disabled={!chosen}
            onChange={(e) => { setTarget(e.target.value); setFeatures((f) => f.filter((x) => x !== e.target.value)); }}>
            <option value="">{chosen && numeric.length === 0 ? "No numeric attributes" : "Choose an attribute"}</option>
            {numeric.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label className="block text-sm">Method
          <select className={INPUT_CLASS} value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
            <option value="random_forest">Random forest</option>
            <option value="gradient_boosting">Gradient boosting</option>
          </select>
        </label>
      </div>
      {chosen && (
        <fieldset>
          <legend className="text-sm">From these inputs</legend>
          <div className="mt-1 flex flex-wrap gap-3">
            {numeric.filter((a) => a !== target).map((a) => (
              <label key={a} className="inline-flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={features.includes(a)}
                  onChange={(e) => setFeatures((f) => (e.target.checked ? [...f, a] : f.filter((x) => x !== a)))} />
                {a}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <details>
        <summary className="cursor-pointer py-1 text-sm text-slate-600">Size of the model</summary>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">Trees<input inputMode="numeric" className={INPUT_CLASS} value={trees} onChange={(e) => setTrees(e.target.value.replace(/\D/g, ""))} /></label>
          <label className="block text-sm">Depth of each tree<input inputMode="numeric" className={INPUT_CLASS} value={depth} onChange={(e) => setDepth(e.target.value.replace(/\D/g, ""))} /></label>
        </div>
      </details>
      {problem && name !== "" && <p className="text-sm text-slate-600">{problem}</p>}
      <button type="submit" disabled={problem !== null || train.isPending}
        className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
        {train.isPending ? "Training…" : "Train"}
      </button>
      {message && <p role={message.error ? "alert" : "status"} className={`text-sm ${message.error ? "text-red-700" : "text-green-800"}`}>{message.text}</p>}
    </form>
  );
}

function UploadForm({ domainId }: { domainId: number }) {
  const upload = useUploadPredictor();
  const [name, setName] = useState("");
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);
  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="font-sans text-base font-semibold tracking-normal text-slate-900">Upload a model</h2>
      <p className="text-sm text-slate-600">
        A tree ensemble trained elsewhere, as a <code className="font-mono">tree-ensemble/1</code> JSON file. Code is never loaded.
      </p>
      <label className="block text-sm">Name of the uploaded model
        <input className={INPUT_CLASS} value={name} onChange={(e) => setName(e.target.value)} placeholder="yield_model" />
      </label>
      <label className="block text-sm">Model file
        <input type="file" accept=".json,application/json" disabled={!NAME.test(name) || upload.isPending} className="mt-1 block text-sm"
          onChange={async (event) => {
            const file = event.currentTarget.files?.[0];
            event.currentTarget.value = "";
            if (!file) return;
            setMessage(null);
            let model: unknown;
            try {
              model = JSON.parse(await file.text());
            } catch {
              setMessage({ error: true, text: "That file is not JSON." });
              return;
            }
            upload.mutate({ domain_id: domainId, name, model }, {
              onSuccess: (made) => setMessage({ error: false, text: `Uploaded ${made.name}.` }),
              onError: (e) => setMessage({ error: true, text: formatApiError(e) }),
            });
          }} />
      </label>
      {!NAME.test(name) && <p className="text-xs text-slate-500">Name it first.</p>}
      {message && <p role={message.error ? "alert" : "status"} className={`text-sm ${message.error ? "text-red-700" : "text-green-800"}`}>{message.text}</p>}
    </div>
  );
}

export default function Predictors() {
  useDocumentTitle("Predictors");
  const { domainId } = useDomain();
  const { can } = useCapabilities();
  const list = usePredictors(domainId);
  const canEdit = can("domain.edit");
  if (domainId === null) return <p className="text-sm text-slate-600">Choose a domain first.</p>;
  const items = list.data?.items ?? [];
  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h1 className="mb-1 text-lg font-semibold text-slate-900">Predictors</h1>
        <p className="text-sm text-slate-500">
          Trained models this domain holds. A rule or goal reads one as <code className="font-mono">predict name(inputs…)</code>;
          a run freezes the model it used, so retraining changes later runs, never earlier ones.
        </p>
      </div>
      {list.fetchStatus === "paused" && !list.data ? <OfflineNotice subject="The predictors" />
        : list.isError ? <LoadFailure subject="The predictors" error={list.error} retry={() => { void list.refetch(); }} />
          : list.isLoading ? <Skeleton rows={2} cols={2} />
            : items.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500">
                No predictors yet.{canEdit ? " Train one from this domain's records, or upload one." : ""}
              </p>
            ) : (
              <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {items.map((p) => <PredictorCard key={String(p.id)} predictor={p} canEdit={canEdit} />)}
              </ul>
            )}
      {canEdit && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <TrainForm domainId={domainId} />
          <UploadForm domainId={domainId} />
        </div>
      )}
    </div>
  );
}
