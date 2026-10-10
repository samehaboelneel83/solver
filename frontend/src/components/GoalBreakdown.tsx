/** What the goal is made of (benchmark, October 2026, G5a), as the run recorded it (`app/solve/breakdown.py`). */
export type Breakdown = {
  sense: string;
  mode: string;
  terms: {
    id: string; weight: number; value: number; contribution: number;
    /** None for goals solved in order: they make no one sum. */
    share: number | null;
    records: { kind: string; key: string; value: number }[];
    rest?: { records: number; value: number };
    /** The term by decision, over every cell (one term is often several costs). */
    decisions?: { var: string; value: number }[];
  }[];
  soft_rules?: number;
};

const words = (id: string) => id.replace(/_/g, " ");
const show = (n: number) => n.toLocaleString(undefined, { maximumSignificantDigits: 6 });

/**
 * Each goal term's value and share of the whole, and the records it comes from -- "transport 61 %,
 * opening 30 %; most of the transport from Giza" -- so an answer can be explained, not only read.
 */
export default function GoalBreakdown({ breakdown, labels = {} }: { breakdown: Breakdown | undefined; labels?: Record<string, string> }) {
  const terms = (breakdown?.terms ?? []).filter((t) => t.id !== "stay_close" && t.id !== "preferences");
  if (!breakdown || (terms.length < 2 && !(terms[0]?.records.length > 1))) return null;
  // Goals in order are not added up: each is shown with its place, not a weight or a share of a sum
  // (benchmark round 4: a count of people and a cost in pounds were shown as 23.9 % and 76.1 %).
  const ordered = breakdown.mode === "lex";
  return (
    <details className="mb-4 rounded-md border border-slate-200 bg-white p-3" open>
      <summary className="cursor-pointer text-sm font-semibold text-slate-900">What the goal is made of</summary>
      {breakdown.mode === "lex" && <p className="mt-1 text-xs text-slate-600">Goals in order: each was made as good as it could be before the next.</p>}
      <table className="mt-2 w-full text-left text-sm" aria-label="Goal by term">
        <thead><tr className="text-xs text-slate-600"><th className="py-1">Goal term</th><th>Its value</th>
          {ordered ? <th>In order</th> : <><th>In the goal</th><th>Share</th></>}<th>Most of it from</th></tr></thead>
        <tbody>
          {terms.map((t, i) => (
            <tr key={t.id} className="border-t border-slate-100 align-top">
              <td className="py-1 pr-2 font-medium">{words(t.id)}{!ordered && t.weight !== 1 && <span className="text-xs text-slate-500"> × {show(t.weight)}</span>}
                {(t.decisions?.length ?? 0) > 1 && (
                  <div className="text-xs font-normal text-slate-600" aria-label={`${words(t.id)} by decision`}>
                    {t.decisions!.map((d) => `${words(d.var)} ${show(d.value * t.weight)}`).join(" · ")}
                  </div>
                )}
              </td>
              <td className="pr-2 font-mono">{show(t.value)}</td>
              {ordered ? <td className="pr-2">{`${i + 1}${["st", "nd", "rd"][i] ?? "th"}`}</td> : (
                <>
                  {/* Weighted, as it counts in the goal (benchmark round 3: "water use × -0.5" showed only its own total). */}
                  <td className="pr-2 font-mono">{show(t.contribution)}</td>
                  <td className="pr-2">
                    <span className="inline-block h-2 rounded bg-blue-500 align-middle" style={{ width: `${Math.max(2, Math.round((t.share ?? 0) * 80))}px` }} />{" "}
                    {Math.round((t.share ?? 0) * 1000) / 10}%
                  </td>
                </>
              )}
              <td className="text-xs text-slate-700">
                {t.records.slice(0, 5).map((r) => `${labels[`${r.kind}:${r.key}`] ?? r.key} ${show(r.value)}`).join(", ") || "—"}
                {t.records.length > 5 && (
                  <details className="inline"><summary className="inline cursor-pointer text-blue-700"> and {t.records.length - 5} more</summary>
                    {t.records.slice(5).map((r) => `${labels[`${r.kind}:${r.key}`] ?? r.key} ${show(r.value)}`).join(", ")}
                  </details>
                )}
                {t.rest && <span> · {t.rest.records} others {show(t.rest.value)}</span>}
              </td>
            </tr>
          ))}
          {breakdown.soft_rules ? (
            <tr className="border-t border-slate-100"><td className="py-1 font-medium">soft rules broken</td><td /><td className="font-mono">{show(breakdown.soft_rules)}</td><td colSpan={ordered ? 1 : 2} /></tr>
          ) : null}
        </tbody>
      </table>
    </details>
  );
}
