import { useId } from "react";
import type { ModelTarget, ModelTargetRequest } from "../hooks/useModelTarget";

/**
 * Which problem, and which of its model versions, the optimization view
 * draws.
 *
 * The version defaults to the latest -- what a person means by "the model"
 * -- and says so, because an older version is a legitimate thing to look at
 * (it is what an old run solved) but must never be mistaken for the current
 * one.
 */
export default function ModelPicker({
  target,
  onChange,
}: {
  target: ModelTarget;
  onChange: (request: ModelTargetRequest) => void;
}) {
  const problemId = useId();
  const versionId = useId();
  const latest = target.versions[0]?.id ?? null;

  return (
    <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="model-picker">
      <label htmlFor={problemId} className="text-slate-600">
        Problem
      </label>
      <select
        id={problemId}
        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
        value={target.problemId === null ? "" : String(target.problemId)}
        disabled={target.problems.length === 0}
        onChange={(event) => onChange({ problemId: Number(event.target.value), versionId: null })}
      >
        {target.problems.length === 0 && <option value="">No problems</option>}
        {target.problems.map((problem) => (
          <option key={problem.id} value={String(problem.id)}>
            {problem.name}
          </option>
        ))}
      </select>
      <label htmlFor={versionId} className="text-slate-600">
        Version
      </label>
      <select
        id={versionId}
        className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
        value={target.versionId === null ? "" : String(target.versionId)}
        disabled={target.versions.length === 0}
        onChange={(event) =>
          onChange({ problemId: target.problemId, versionId: Number(event.target.value) })
        }
      >
        {target.versions.length === 0 && <option value="">No versions</option>}
        {target.versions.map((version) => (
          <option key={version.id} value={String(version.id)}>
            v{version.version}
            {version.id === latest ? " (latest)" : ""}
            {version.note ? ` — ${version.note}` : ""}
          </option>
        ))}
      </select>
    </div>
  );
}
