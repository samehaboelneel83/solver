/**
 * A ready example in words, before its JSON (improvement plan 4.7): what it
 * decides, what must be true, what it makes best, what data it needs -- and
 * where to use it. The raw `default_ir` editor stays below for whoever
 * maintains templates.
 */
import { Link } from "react-router-dom";
import { useDomain } from "../hooks/useDomain";

type Ir = {
  sets?: string[];
  parameters?: Record<string, { index?: string[] }>;
  variables?: Record<string, { index?: string[]; domain?: string }>;
  constraints?: { id?: string; note?: string; severity?: string }[];
  objective?: { sense?: string; mode?: string; terms?: { id?: string; note?: string }[] };
};

const plain = (name: string) => name.replace(/^[a-z]_(?=[a-z])/, "").replace(/_/g, " ");
const DOMAINS: Record<string, string> = { binary: "yes or no", integer: "a whole number", continuous: "an amount", interval: "a task in time" };

export default function TemplateInWords({ record }: { record: Record<string, unknown> }) {
  const { domainId } = useDomain();
  const ir = (record.default_ir ?? {}) as Ir;
  const decisions = Object.entries(ir.variables ?? {});
  const rules = ir.constraints ?? [];
  const terms = ir.objective?.terms ?? [];
  const data = Object.entries(ir.parameters ?? {});
  return (
    <section aria-label="This example in words" className="mb-4 space-y-2 rounded-md border border-blue-200 bg-blue-50/40 p-3 text-sm text-slate-800">
      <h2 className="text-base font-semibold text-slate-900">{String(record.name ?? "Example")} in words</h2>
      {typeof record.description === "string" && record.description && <p>{record.description}</p>}
      {(ir.sets?.length ?? 0) > 0 && <p><span className="font-medium">About:</span> {ir.sets?.join(", ")}.</p>}
      {decisions.length > 0 && (
        <div><span className="font-medium">It decides:</span>
          <ul className="ml-5 list-disc">
            {decisions.map(([name, spec]) => (
              <li key={name}><span className="font-mono">{name}</span> — {DOMAINS[spec.domain ?? "binary"] ?? spec.domain}
                {spec.index?.length ? ` for each ${spec.index.join(" and ")}` : ""}</li>
            ))}
          </ul>
        </div>
      )}
      {rules.length > 0 && (
        <div><span className="font-medium">What must be true:</span>
          <ul className="ml-5 list-disc">
            {rules.map((rule, i) => (
              <li key={rule.id ?? i}>{rule.note || plain(rule.id ?? "a rule")}{rule.severity === "soft" ? " (a preference)" : ""}</li>
            ))}
          </ul>
        </div>
      )}
      {terms.length > 0 && (
        <p><span className="font-medium">It makes {ir.objective?.sense?.startsWith("max") ? "as large" : "as small"} as it can:</span>{" "}
          {terms.map((t) => t.note || plain(t.id ?? "the goal")).join(ir.objective?.mode === "lex" ? ", then " : " + ")}.</p>
      )}
      {data.length > 0 && (
        <p><span className="font-medium">Data it reads:</span> {data.map(([name, spec]) => `${name}${spec.index?.length ? `[${spec.index.join(", ")}]` : ""}`).join(", ")}.</p>
      )}
      <p>
        {domainId != null
          ? <Link className="font-medium text-blue-700 underline" to={`/domains/${domainId}/start`}>Use it: start a problem from a ready example</Link>
          : "Open a workspace, then Problems › New problem › From a ready example."}
      </p>
    </section>
  );
}
