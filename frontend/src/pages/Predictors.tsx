/**
 * Predictors (Epic ML, follow-up): the trained models a domain holds, which a
 * model reads with `predict name(inputs...)`. Train one from the domain's own
 * records, upload one trained elsewhere as `tree-ensemble/1` JSON (never a
 * pickle), see how well it predicted rows it was not trained on, delete one
 * nothing uses.
 */
import { useEffect, useMemo, useState } from "react";
import { BrainCircuit, Trash2 } from "lucide-react";
import { formatApiError } from "../api/errors";
import {
  useApplyPredictor,
  useDeletePredictor,
  useDeriveFields,
  useEntityTypes,
  usePredictors,
  usePredictorTraining,
  useTrainPredictor,
  useUploadPredictor,
  type ApplyPredictorBody,
  type EntityType,
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
/** What a yes-or-no model can learn: anything that may hold two values. */
const TWO_VALUED = new Set(["boolean", "text", "enum", "integer"]);

const METHODS: Record<string, string> = {
  random_forest: "Random forest",
  gradient_boosting: "Gradient boosting",
  random_forest_classifier: "Random forest (yes or no)",
};

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-50 px-2 py-1.5">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-mono text-sm text-slate-900">{value}</dd>
    </div>
  );
}

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
              ? `${METHODS[trained.kind ?? ""] ?? "Random forest"} on ${trained.entity_type}, predicting ${m.predicts ?? trained.target}`
                + (trained.lags ? `, from its ${trained.lags.field} ${trained.lags.steps.join(", ")} back by ${trained.lags.order_by}${trained.lags.group_by ? ` per ${trained.lags.group_by}` : ""}` : "")
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
          {m.positive !== undefined ? (
            <>
              <Tile label="Right" value={percent(m.accuracy)} />
              <Tile label="AUC" value={score(m.auc)} />
              <Tile label="Brier" value={score(m.brier)} />
            </>
          ) : (
            <>
              <Tile label="R²" value={score(m.r2)} />
              <Tile label="Mean error" value={score(m.mae)} />
              <Tile label="RMSE" value={score(m.rmse)} />
            </>
          )}
        </dl>
      ) : null}
      {m.positive !== undefined && m.holdout_rows ? (
        <p className="mt-2 text-xs text-slate-500">
          Right: held-out records called correctly at a 50% chance. AUC: 1 tells {m.positive} and {m.negative} apart perfectly, 0.5 is a coin toss.
          Brier: the average squared miss of the chance, lower is better.
        </p>
      ) : null}
      {m.interval_coverage !== undefined && m.interval_coverage !== null && (
        <p className="mt-2 text-xs text-slate-500">
          Its trees disagree too: {percent(m.interval_coverage)} of held-out values fell between their {m.interval ?? "10th and 90th percentile"}.
        </p>
      )}
      {m.evaluated_on && (
        <p className="mt-2 text-xs text-slate-500">
          Measured on {m.evaluated_on}{m.rows ? ` (${m.rows} rows${m.rows_skipped ? `, ${m.rows_skipped} skipped for missing numbers` : ""})` : ""}.
        </p>
      )}
      {canEdit && <KeepPredictions predictor={predictor} />}
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

/**
 * A model learns from numbers. A date, a text (weather, soil) or a number on a linked record
 * (an observation's road) is made into number fields here, once, on the records themselves
 * (benchmark, October 2026: four of five testers could not use what they had).
 */
function MakeNumbers({ kind, kinds }: { kind: EntityType; kinds: EntityType[] }) {
  const derive = useDeriveFields();
  const [said, setSaid] = useState<{ error: boolean; text: string } | null>(null);
  const [linkOf, setLinkOf] = useState<Record<string, string>>({});
  const fields = kind.attributes ?? [];
  const dates = fields.filter((a) => (a.data_type as string) === "date");
  const texts = fields.filter((a) => a.data_type === "text" || a.data_type === "enum");
  const links = fields.filter((a) => a.data_type === "reference");
  if (!dates.length && !texts.length && !links.length) return null;
  const numbersOf = (a: (typeof fields)[number]) => {
    const target = kinds.find((k) => k.id === a.target_type_id);
    return (target?.attributes ?? []).filter((x) => NUMERIC.has(x.data_type)).map((x) => x.name);
  };
  const run = (body: { op: "date_parts" | "categories" | "from_link"; field: string; of?: string }) => {
    setSaid(null);
    derive.mutate({ entityTypeId: kind.id, body }, {
      onSuccess: (done) => setSaid({ error: false, text: `Made ${done.made.join(", ")} on ${done.records} records${done.left_empty ? `; ${done.left_empty} had nothing to read` : ""}${(done as { notes?: string[] }).notes?.length ? `; ${(done as { notes?: string[] }).notes!.join("; ")}` : ""}. Tick them above.` }),
      onError: (e) => setSaid({ error: true, text: formatApiError(e) }),
    });
  };
  const button = "rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-60";
  return (
    <div className="mt-2 rounded border border-slate-200 bg-slate-50 p-2 text-sm" aria-label="Make number fields">
      <p className="text-xs text-slate-600">Not a number yet? Make number fields from it:</p>
      <ul className="mt-1 space-y-1">
        {dates.map((a) => (
          <li key={a.name}><span className="font-mono text-xs">{a.name}</span>{" "}
            <button type="button" className={button} disabled={derive.isPending} onClick={() => run({ op: "date_parts", field: a.name })}>
              weekday, month and day of year</button></li>
        ))}
        {texts.map((a) => (
          <li key={a.name}><span className="font-mono text-xs">{a.name}</span>{" "}
            <button type="button" className={button} disabled={derive.isPending} onClick={() => run({ op: "categories", field: a.name })}>
              one yes/no field per value</button></li>
        ))}
        {links.map((a) => numbersOf(a).length > 0 && (
          <li key={a.name}><span className="font-mono text-xs">{a.name}</span>{" "}
            <select aria-label={`Number of the linked record for ${a.name}`} className="rounded border border-slate-300 px-1 text-xs"
              value={linkOf[a.name] ?? ""} onChange={(e) => setLinkOf({ ...linkOf, [a.name]: e.target.value })}>
              <option value="">its…</option>
              {numbersOf(a).map((n) => <option key={n} value={n}>{n}</option>)}
            </select>{" "}
            <button type="button" className={button} disabled={derive.isPending || !linkOf[a.name]}
              onClick={() => run({ op: "from_link", field: a.name, of: linkOf[a.name] })}>copy onto each record</button></li>
        ))}
      </ul>
      {/* Said at once: thousands of records take a moment (benchmark round 3: nothing seemed to happen). */}
      {derive.isPending && <p role="status" className="mt-1 text-xs text-slate-600">Making the fields…</p>}
      {said && !derive.isPending && <p role={said.error ? "alert" : "status"} className={`mt-1 text-xs ${said.error ? "text-red-700" : "text-green-800"}`}>{said.text}</p>}
    </div>
  );
}

/** A trained model's predictions kept as data: in a number field of each record, or -- one per record
 * and period -- in a data value `name[kind, period]`. The records may be another kind's, each input
 * read from a field, a linked record's field, or held at a number (benchmark re-test, October 2026). */
function KeepPredictions({ predictor }: { predictor: Predictor }) {
  const apply = useApplyPredictor();
  const { domainId } = useDomain();
  const kinds = useEntityTypes(domainId, { limit: 500, offset: 0 });
  const trainedOn = predictor.training?.entity_type ?? "";
  const features = predictor.training?.features ?? [];
  const target = predictor.training?.target ?? "value";
  const [field, setField] = useState(`${target}_forecast`);
  const [onlyMissing, setOnlyMissing] = useState(true);
  const [forKind, setForKind] = useState(trainedOn);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [numbers, setNumbers] = useState<Record<string, string>>({});
  const [overKind, setOverKind] = useState("");
  const [overFeature, setOverFeature] = useState("");
  const [said, setSaid] = useState<{ error: boolean; text: string } | null>(null);
  if (!predictor.training?.entity_type || predictor.training.positive !== undefined) return null;
  const all = kinds.data?.items ?? [];
  const kind = all.find((k) => k.name === forKind);
  const fields = (kind?.attributes ?? []).filter((a) => a.data_type === "number" || a.data_type === "integer").map((a) => a.name);
  // A linked record's number fields: "road.lanes".
  const through = (kind?.attributes ?? []).filter((a) => a.data_type === "reference").flatMap((a) =>
    (all.find((k) => k.id === a.target_type_id)?.attributes ?? []).filter((b) => b.data_type === "number" || b.data_type === "integer")
      .map((b) => `${a.name}.${b.name}`));
  const sourceOf = (f: string) => inputs[f] ?? (fields.includes(f) ? f : "");
  const body = (): ApplyPredictorBody => {
    const mapped: Record<string, string | number> = {};
    for (const f of features) {
      if (overKind && f === overFeature) continue;
      const from = sourceOf(f);
      if (from === "#") { const n = Number(numbers[f]); if (Number.isFinite(n)) mapped[f] = n; }
      else if (from && from !== f) mapped[f] = from;
    }
    return { field, only_missing: onlyMissing && !overKind && forKind === trainedOn,
      ...(forKind !== trainedOn ? { entity_type: forKind } : {}), ...(Object.keys(mapped).length ? { inputs: mapped } : {}),
      ...(overKind && overFeature ? { over: { kind: overKind, feature: overFeature } } : {}) };
  };
  const select = "rounded border border-slate-300 px-1 py-0.5 font-mono text-xs";
  return (
    <form className="mt-3 space-y-2 text-sm" aria-label={`Keep ${predictor.name}'s predictions`}
      onSubmit={(e) => {
        e.preventDefault();
        apply.mutate({ id: predictor.id, body: body() }, {
          onSuccess: (done) => setSaid({ error: false, text: (done.parameter
            ? `${done.written} predictions kept as the data value ${done.parameter}[${forKind}, ${overKind}]`
            : `${done.written} ${forKind} records now have ${done.field}`)
            + `${done.skipped_count ? `; ${done.skipped_count} lack an input (${done.skipped.slice(0, 5).join(", ")})` : ""}. A model reads it as data.` }),
          onError: (err) => setSaid({ error: true, text: formatApiError(err) }),
        });
      }}>
      <div className="flex flex-wrap items-center gap-2">
        <span>Keep its predictions for the</span>
        <select aria-label="Records to predict for" className={select} value={forKind} onChange={(e) => { setForKind(e.target.value); setInputs({}); }}>
          {all.filter((k) => !k.is_abstract).map((k) => <option key={k.id} value={k.name}>{k.name}</option>)}
        </select>
        <span>records in</span>
        <input aria-label="Field for the predictions" className="w-40 rounded border border-slate-300 px-2 py-0.5 font-mono text-xs"
          value={field} onChange={(e) => setField(e.target.value)} />
        {forKind === trainedOn && !overKind && (
          <label className="inline-flex items-center gap-1 text-xs">
            <input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} />
            only those with no {target} yet</label>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-700">
        <span>One per</span>
        <select aria-label="One prediction per" className={select} value={overKind} onChange={(e) => setOverKind(e.target.value)}>
          <option value="">record only</option>
          {all.filter((k) => !k.is_abstract && k.name !== forKind).map((k) => <option key={k.id} value={k.name}>{k.name}</option>)}
        </select>
        {overKind && (
          <label>its key feeds
            <select aria-label="Input each period feeds" className={`${select} ml-1`} value={overFeature} onChange={(e) => setOverFeature(e.target.value)}>
              <option value="">choose…</option>
              {features.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </label>
        )}
      </div>
      <ul className="flex flex-wrap gap-3 text-xs text-slate-700" aria-label="Where each input comes from">
        {features.filter((f) => !(overKind && f === overFeature)).map((f) => (
          <li key={f}>
            <label>{f} from
              <select aria-label={`${f} comes from`} className={`${select} ml-1`} value={sourceOf(f)} onChange={(e) => setInputs({ ...inputs, [f]: e.target.value })}>
                <option value="">choose…</option>
                {fields.map((n) => <option key={n} value={n}>{n}</option>)}
                {through.map((n) => <option key={n} value={n}>{n}</option>)}
                <option value="#">a number…</option>
              </select>
            </label>
            {sourceOf(f) === "#" && (
              <input aria-label={`${f} held at`} inputMode="decimal" className="ml-1 w-16 rounded border border-slate-300 px-1 py-0.5 text-xs"
                value={numbers[f] ?? ""} onChange={(e) => setNumbers({ ...numbers, [f]: e.target.value })} />
            )}
          </li>
        ))}
      </ul>
      <button type="submit" disabled={apply.isPending || (!!overKind && !overFeature)} className="rounded bg-blue-600 px-2 py-1 text-xs text-white disabled:opacity-60">
        {apply.isPending ? "Predicting…" : "Predict and keep"}</button>
      {said && <p role={said.error ? "alert" : "status"} className={`text-xs ${said.error ? "text-red-700" : "text-green-800"}`}>{said.text}</p>}
    </form>
  );
}

function TrainForm({ domainId }: { domainId: number }) {
  const types = useEntityTypes(domainId, { limit: 500, offset: 0 });
  const train = useTrainPredictor();
  const [name, setName] = useState("");
  const [entityType, setEntityType] = useState("");
  const [target, setTarget] = useState("");
  const [features, setFeatures] = useState<string[]>([]);
  const [kind, setKind] = useState<"random_forest" | "gradient_boosting" | "random_forest_classifier">("random_forest");
  const [positive, setPositive] = useState("");
  const yesOrNo = kind === "random_forest_classifier";
  const [trees, setTrees] = useState("50");
  const [depth, setDepth] = useState("6");
  // Earlier values as inputs (benchmark re-test, October 2026): yesterday's, last week's.
  const [lagOrder, setLagOrder] = useState("");
  const [lagGroup, setLagGroup] = useState("");
  const [lagSteps, setLagSteps] = useState("1, 7");
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);
  // Training goes on after the request (operator trial F31): this is the one being waited for.
  const [trainingId, setTrainingId] = useState<number | null>(null);
  const training = usePredictorTraining(trainingId);
  const running = train.isPending || (trainingId !== null && training.data?.state !== "done" && training.data?.state !== "failed");
  useEffect(() => {
    const t = training.data;
    if (!t || t.state === "running") return;
    setMessage(t.state === "done" ? { error: false, text: `Trained ${t.request.name}.` } : { error: true, text: t.error ?? "The training failed." });
    setTrainingId(null);
  }, [training.data]);

  const typeItems = types.data?.items ?? [];
  const chosen = typeItems.find((t) => t.name === entityType);
  const numeric = useMemo(() => (chosen?.attributes ?? []).filter((a) => NUMERIC.has(a.data_type)).map((a) => a.name), [chosen]);
  const targets = useMemo(
    () => (yesOrNo ? (chosen?.attributes ?? []).filter((a) => TWO_VALUED.has(a.data_type)).map((a) => a.name) : numeric),
    [chosen, numeric, yesOrNo],
  );
  const targetType = chosen?.attributes?.find((a) => a.name === target)?.data_type;
  // A linked record's numbers, read through the link at training and when predicting (benchmark re-test, October 2026).
  const throughLinks = useMemo(() => (chosen?.attributes ?? []).filter((a) => a.data_type === "reference").flatMap((a) =>
    ((types.data?.items ?? []).find((k) => k.id === a.target_type_id)?.attributes ?? []).filter((x) => NUMERIC.has(x.data_type)).map((x) => `${a.name}.${x.name}`)),
  [chosen, types.data]);
  const steps = [...new Set(lagSteps.split(/[\s,]+/).filter(Boolean).map(Number))].sort((a, b) => a - b);
  const stepsOk = steps.length > 0 && steps.length <= 5 && steps.every((n) => Number.isInteger(n) && n >= 1 && n <= 366);
  const lagged = !yesOrNo && lagOrder !== "";
  const lagNames = lagged && stepsOk ? steps.map((n) => `${target}_lag${n}`) : [];
  const problem = !NAME.test(name)
    ? "Name it with lower-case letters, digits and underscores, starting with a letter."
    : !chosen ? "Choose the records to learn from."
      : !target ? "Choose what to predict."
        : lagged && !stepsOk ? "Earlier values: whole numbers of records back, 1 to 366, at most five (1, 7)."
          : features.length === 0 && lagNames.length === 0 ? "Choose at least one input."
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
          {
            domain_id: domainId, name, entity_type: entityType, target, kind,
            features: [...features, ...lagNames.filter((n) => !features.includes(n))],
            ...(lagNames.length ? { lags: { order_by: lagOrder, ...(lagGroup ? { group_by: lagGroup } : {}), steps } } : {}),
            ...(yesOrNo && positive.trim() ? { positive: positive.trim() } : {}),
            trees: Number(trees) || 50, max_depth: Number(depth) || 6,
          },
          {
            onSuccess: (queued) => setTrainingId(queued.training_id),
            onError: (e) => setMessage({ error: true, text: formatApiError(e) }),
          },
        );
      }}
    >
      <h2 id="train-heading" className="font-sans text-base font-semibold tracking-normal text-slate-900">Train a model</h2>
      <p className="text-sm text-slate-600">
        Learns one attribute of a record type from its numeric ones, with a held-out fifth of the records to say how well it predicts.
        A yes-or-no model learns an attribute with two values and predicts the chance of one of them.
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
            <option value="">{chosen && targets.length === 0 ? (yesOrNo ? "No attributes to learn" : "No numeric attributes") : "Choose an attribute"}</option>
            {targets.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
        <label className="block text-sm">Method
          <select className={INPUT_CLASS} value={kind} onChange={(e) => {
            const next = e.target.value as typeof kind;
            setKind(next);
            // What can be predicted changes with the method.
            if ((next === "random_forest_classifier") !== yesOrNo) setTarget("");
          }}>
            {Object.entries(METHODS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        {yesOrNo && target && targetType !== "boolean" && (
          <label className="block text-sm">Counts as yes
            <input className={INPUT_CLASS} value={positive} onChange={(e) => setPositive(e.target.value)}
              placeholder="one of its two values; the later one if empty" />
          </label>
        )}
      </div>
      {chosen && (
        <fieldset>
          <legend className="text-sm">From these inputs</legend>
          <div className="mt-1 flex flex-wrap gap-3">
            {[...numeric.filter((a) => a !== target), ...throughLinks].map((a) => (
              <label key={a} className="inline-flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={features.includes(a)}
                  onChange={(e) => setFeatures((f) => (e.target.checked ? [...f, a] : f.filter((x) => x !== a)))} />
                {a.includes(".") ? `${a.split(".")[1]} of its ${a.split(".")[0]}` : a}
              </label>
            ))}
          </div>
          <MakeNumbers kind={chosen} kinds={typeItems} />
          {!yesOrNo && target && (
            <div className="mt-2 flex flex-wrap items-end gap-3 text-sm" role="group" aria-label="Earlier values as inputs">
              <label className="block">Earlier {target}, in the order of
                <select aria-label="In the order of" className={INPUT_CLASS} value={lagOrder} onChange={(e) => setLagOrder(e.target.value)}>
                  <option value="">no earlier values</option>
                  {(chosen.attributes ?? []).filter((a) => ["date", "datetime", "text", "integer", "number"].includes(a.data_type) && a.name !== target)
                    .map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
                </select>
              </label>
              {lagOrder && (
                <>
                  <label className="block">each its own series by
                    <select aria-label="Each its own series by" className={INPUT_CLASS} value={lagGroup} onChange={(e) => setLagGroup(e.target.value)}>
                      <option value="">one series</option>
                      {(chosen.attributes ?? []).filter((a) => ["text", "enum", "reference", "integer"].includes(a.data_type) && a.name !== target && a.name !== lagOrder)
                        .map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
                    </select>
                  </label>
                  <label className="block">records back
                    <input aria-label="Records back" className={INPUT_CLASS} value={lagSteps} onChange={(e) => setLagSteps(e.target.value)} placeholder="1, 7" />
                  </label>
                  <p className="w-full text-xs text-slate-500">
                    Adds {lagNames.join(", ") || "…"} as inputs. When predicting, a record with no {target} yet passes its
                    forecast on to the next: tomorrow reads today&apos;s forecast.
                  </p>
                </>
              )}
            </div>
          )}
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
      <button type="submit" disabled={problem !== null || running}
        className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
        {running ? "Training…" : "Train"}
      </button>
      {running && trainingId !== null && (
        <p role="status" className="text-sm text-slate-600">
          Training{training.data ? ` for ${Math.round(training.data.seconds)} s` : ""}. It goes on on the server if you leave
          this page; the model appears in the list when it is done.
        </p>
      )}
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
  useDocumentTitle("Forecasts");
  const { domainId } = useDomain();
  const { can } = useCapabilities();
  const list = usePredictors(domainId);
  const canEdit = can("domain.edit");
  if (domainId === null) return <p className="text-sm text-slate-600">Choose a domain first.</p>;
  const items = list.data?.items ?? [];
  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h1 className="mb-1 text-lg font-semibold text-slate-900">Forecasts <span className="text-sm font-normal text-slate-500">(predictors)</span></h1>
        <p className="text-sm text-slate-500">
          Trained models this workspace holds. A rule or goal reads one as <code className="font-mono">predict name(inputs…)</code>;
          a run freezes the model it used, so retraining changes later runs, never earlier ones.
          {/* Benchmark re-test, October 2026: a tester believed decisions could not be inputs. */}
          {" "}An input may be a decision with an upper bound — <code className="font-mono">predict yield_model(water[p], rain[p])</code> —
          and the solver then chooses it for the best prediction: water put where it raises the yield most.
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
