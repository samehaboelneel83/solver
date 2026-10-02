import { useState } from "react";
import { Link } from "react-router-dom";
import { scopedPath } from "../nav/registry";

/** One step of the path from data to a shared answer: what it is, and the page it lives on. */
type Step = { what: string; how: string; page: string; where: string };

/**
 * The sixteen steps from a question to a shared answer, in order, each with the page it lives on
 * (benchmark, October 2026: "what does this app do?" was a guess for every tester, and features
 * were found by wandering). Grouped as a planner meets them: data, the model, solving, the answer.
 */
export const STAGES: { title: string; steps: Step[] }[] = [
  { title: "Bring the data in", steps: [
    { what: "See what the app does", how: "This list, and the getting-started guide.", page: "help-start", where: "Help → Getting started" },
    { what: "Import data", how: "Upload a CSV or Excel file of records; columns are matched for you.", page: "records", where: "Records → Many records at once" },
    { what: "Combine tables and maps", how: "Turn map layers into records, or give spreadsheet rows a place from lat/lon.", page: "map-data", where: "Map data → Use in models" },
    { what: "Explore the data", how: "Browse kinds, records and their links side by side.", page: "workbench", where: "Data workbench" },
    { what: "Link and join records", how: "Link records by a code they hold (a join), totals of linked records, values looked up through a link.", page: "records", where: "Records → Compute and join" },
    { what: "Measure from the map", how: "Distances, travel times, within reach, which area, along your own roads.", page: "parameters", where: "Data values → From the map" },
  ] },
  { title: "Write the model", steps: [
    { what: "Describe it in words", how: "Get a first draft of decisions, rules and goals from a description: places within reach, projects within a budget, a supply network, projects over years, land among crops.", page: "model", where: "Model → Describe the problem in words" },
    { what: "Decisions", how: "What the answer chooses: open a site, ship an amount, assign a person.", page: "model", where: "Model → Decisions" },
    { what: "Goals", how: "What makes one answer better: least cost, most covered, in order.", page: "model", where: "Model → Goals" },
    { what: "Rules", how: "What must hold, in sentences, boxes or equations; recipes write common ones.", page: "model", where: "Model → Rules" },
    { what: "Forecasts", how: "Train a model on past records and use its predictions as data.", page: "predictors", where: "Forecasts" },
  ] },
  { title: "Solve and compare", steps: [
    { what: "Solve", how: "Choose how long to look for an answer, and solve.", page: "problem-overview", where: "Problem overview → Solve" },
    { what: "What-ifs", how: "Change data in a scenario (+30 % demand, a site closed) and compare answers.", page: "scenarios", where: "What-ifs" },
  ] },
  { title: "Read and share the answer", steps: [
    { what: "See it on the map", how: "Chosen places, flows along roads, any map data under it.", page: "runs", where: "Results → On the map" },
    { what: "Understand it", how: "In plain words, what the goal is made of, and why a rule binds.", page: "runs", where: "Results → What the goal is made of" },
    { what: "Export and share", how: "Excel, CSV, GeoJSON, a PDF report, or keep it as data.", page: "runs", where: "Results → Take the answer out" },
  ] },
];

const PROBLEM_PAGES = new Set(["model", "problem-overview", "scenarios", "runs"]);
const KEY = "solver_home_path_open";

export default function WhatThisAppDoes({ domainId, problemId = null }: { domainId: number | null; problemId?: number | null }) {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(KEY) !== "0";
    } catch {
      return true;
    }
  });
  const href = (page: string) => {
    if (domainId == null) return page === "help-start" ? scopedPath(page) : "/domains";
    // A problem's page without a problem open: the problems, to pick one.
    if (PROBLEM_PAGES.has(page) && problemId == null) return `/domains/${domainId}/problems`;
    return scopedPath(page, { domainId, problemId });
  };
  let n = 0;
  return (
    <details className="mb-8 rounded-lg border border-slate-200 bg-white p-4" open={open}
      onToggle={(e) => {
        const now = e.currentTarget.open;
        setOpen(now);
        try {
          localStorage.setItem(KEY, now ? "1" : "0");
        } catch {
          /* remembered for this page only */
        }
      }}>
      <summary className="cursor-pointer text-sm font-semibold text-slate-900">What can this app do? From data to a shared answer, in 16 steps</summary>
      {domainId == null && <p className="mt-2 text-xs text-slate-600">Choose or start a workspace and each step below links to its page there.</p>}
      <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {STAGES.map((stage) => (
          <section key={stage.title} aria-label={stage.title}>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{stage.title}</h3>
            <ol className="space-y-1.5">
              {stage.steps.map((step) => {
                n += 1;
                return (
                  <li key={step.what} className="text-sm">
                    <span className="mr-1 inline-block w-5 text-right text-xs text-slate-400">{n}.</span>
                    <Link to={href(step.page)} className="font-medium text-blue-700 hover:underline">{step.what}</Link>
                    <span className="block pl-6 text-xs text-slate-600">{step.how} <span className="text-slate-400">— {step.where}</span></span>
                  </li>
                );
              })}
            </ol>
          </section>
        ))}
      </div>
    </details>
  );
}
