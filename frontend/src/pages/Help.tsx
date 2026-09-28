import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

/**
 * In-app Help (OAAS HELP01 / proposal §3.2). Content ships with the UI so an
 * air-gapped install still has a first path, coverage honesty, and API entry
 * without fetching the public internet.
 */

type Topic = {
  title: string;
  purpose: string;
  body: ReactNode;
};

const TOPICS: Record<string, Topic> = {
  "getting-started": {
    title: "Getting started",
    purpose: "From sign-in to a first optimal answer.",
    body: (
      <ol className="list-decimal space-y-3 ps-5 text-sm text-slate-700">
        <li>
          Open the{" "}
          <Link className="text-blue-700 underline" to="/public/template">
            Template library
          </Link>{" "}
          and apply a showcase template (for example weekly rota, feed blend, or
          Cairo University lectures). Applying builds a domain and a first model.
        </li>
        <li>
          Open{" "}
          <Link className="text-blue-700 underline" to="/runs">
            Runs & results
          </Link>{" "}
          and submit a run. A worker claims the queue; status moves to optimal or
          explains why not.
        </li>
        <li>
          Use the Guided view on a run for a planner-facing reading of the answer.
          Cell locks and what-if live on the planner panel when you need a
          re-plan that stays close to the last roster.
        </li>
        <li>
          Prefer bookmarking domain-scoped URLs (
          <code className="text-xs">/domains/…/problems/…</code>) so a shared link
          cannot silently switch to another problem.
        </li>
      </ol>
    ),
  },
  modeling: {
    title: "Modeling guide",
    purpose: "How a business question becomes a model on this platform.",
    body: (
      <div className="space-y-3 text-sm text-slate-700">
        <p>
          You do not write LP/MILP/CP as the product language. You shape{" "}
          <strong className="font-medium text-slate-900">domain data</strong>{" "}
          (records, relationships, parameters) and a{" "}
          <strong className="font-medium text-slate-900">problem IR</strong>{" "}
          (sets, variables, constraints, objective). The platform classifies the
          model and chooses an admissible solver.
        </p>
        <ul className="list-disc space-y-2 ps-5">
          <li>
            <Link className="text-blue-700 underline" to="/model">
              Model
            </Link>{" "}
            — forms or blocks that publish immutable versions.
          </li>
          <li>
            <Link className="text-blue-700 underline" to="/scenarios">
              Scenarios
            </Link>{" "}
            — assumptions and soften/lock patches on top of a version.
          </li>
          <li>
            Relationships can be walked in rules with{" "}
            <code className="text-xs">via</code>; scheduling uses intervals and
            no-overlap where declared.
          </li>
        </ul>
        <p className="text-xs text-slate-500">
          Full contract: <code>docs/contracts/problem-ir.md</code> in the install
          bundle (not fetched from the network).
        </p>
      </div>
    ),
  },
  coverage: {
    title: "Problem coverage & limitations",
    purpose: "What this install claims to run, and what it does not.",
    body: (
      <div className="space-y-3 text-sm text-slate-700">
        <p>
          Built-in backends cover LP, MILP/IP, quadratic and selected nonlinear
          classes, plus CP-SAT for scheduling and routing. Adapter solvers
          (Gurobi, Xpress, CPLEX, …) are never chosen automatically until their
          conformance kit passes for this version.
        </p>
        <ul className="list-disc space-y-2 ps-5">
          <li>
            Proof labels are honest: <em>global</em>, <em>local</em>, or{" "}
            <em>approximate</em> — shown on each run.
          </li>
          <li>
            Learned solver selection stays in shadow mode until evidence on
            stored runs supports promotion.
          </li>
          <li>
            Portfolio racing and some heuristics stay off by default; family
            policies and equal-budget benches gate changes.
          </li>
        </ul>
        <p className="text-xs text-slate-500">
          Matrix: <code>docs/coverage-acceptance-matrix.md</code>. Solvers page:{" "}
          <Link className="text-blue-700 underline" to="/solvers">
            Solver health & licenses
          </Link>
          .
        </p>
      </div>
    ),
  },
  api: {
    title: "API reference",
    purpose: "Machine access to the same capabilities as the UI.",
    body: (
      <div className="space-y-3 text-sm text-slate-700">
        <p>
          Interactive OpenAPI docs are served by this install&apos;s API (same
          host as planning — no public internet required):
        </p>
        <p>
          <a className="text-blue-700 underline" href="/docs" target="_blank" rel="noreferrer">
            Open API docs (/docs)
          </a>
        </p>
        <ul className="list-disc space-y-2 ps-5">
          <li>
            Create a key under{" "}
            <Link className="text-blue-700 underline" to="/api-keys">
              API keys
            </Link>
            ; the token is shown once.
          </li>
          <li>
            Typical path: authenticate → apply or publish a model →{" "}
            <code className="text-xs">POST /api/v1/scenarios/&#123;id&#125;/runs</code> →
            poll the run.
          </li>
        </ul>
      </div>
    ),
  },
  "release-notes": {
    title: "Release notes",
    purpose: "What this line of the product recently delivered.",
    body: (
      <div className="space-y-3 text-sm text-slate-700">
        <ul className="list-disc space-y-2 ps-5">
          <li>
            <strong className="font-medium text-slate-900">OAAS Phase 0–5</strong> —
            planner navigation, offline install path, chunked large results,
            approvals, scale reservations, coverage/bench gates.
          </li>
          <li>
            <strong className="font-medium text-slate-900">U01</strong> — Cairo
            University lecture timetable template.
          </li>
          <li>
            <strong className="font-medium text-slate-900">OPS01 / ADM01</strong> —
            Operations (queue, audit, backups) and a quieter IAM sidebar.
          </li>
        </ul>
        <p className="text-xs text-slate-500">
          Operator detail lives in <code>handover.md</code> beside the repository
          on the install host.
        </p>
      </div>
    ),
  },
  install: {
    title: "Installation & updates",
    purpose: "Offline bundle, digests, and recovery pointers.",
    body: (
      <div className="space-y-3 text-sm text-slate-700">
        <p>
          A single-host reference install is transferred as a versioned bundle
          and started with Compose. Public egress can stay blocked after the
          transfer.
        </p>
        <ul className="list-disc space-y-2 ps-5">
          <li>
            Contract: <code>docs/runbooks/offline-install.md</code>
          </li>
          <li>
            Digests: <code>scripts/render-digest-compose.sh</code> into the
            offline bundle
          </li>
          <li>
            Backups:{" "}
            <Link className="text-blue-700 underline" to="/ops/backups">
              Backups & recovery
            </Link>{" "}
            (RPO 24 h / RTO 4 h)
          </li>
        </ul>
      </div>
    ),
  },
};

export type HelpTopicId = keyof typeof TOPICS;

export default function Help({ topic }: { topic: HelpTopicId }) {
  const page = TOPICS[topic];
  useDocumentTitle(page.title);

  return (
    <div className="max-w-3xl">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Help</p>
      <h1 className="mt-1 text-2xl font-semibold text-slate-900">{page.title}</h1>
      <p className="mt-1 text-sm text-slate-600">{page.purpose}</p>
      <div className="mt-6">{page.body}</div>
      <nav className="mt-10 border-t border-slate-200 pt-4 text-sm" aria-label="Help topics">
        <ul className="flex flex-wrap gap-x-4 gap-y-2">
          {(Object.keys(TOPICS) as HelpTopicId[]).map((id) => (
            <li key={id}>
              <Link
                to={id === "install" ? "/help/install" : `/help/${id}`}
                className={
                  id === topic ? "font-semibold text-slate-900" : "text-blue-700 underline"
                }
                aria-current={id === topic ? "page" : undefined}
              >
                {TOPICS[id].title}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
