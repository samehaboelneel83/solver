// Phase 1 evaluation: one case through the platform in a real browser (headless Chrome).
//   PW_DIR=<folder with node_modules/playwright-core> node drive_case.mjs <case dir> <out dir> <workspace name>
// Sends the case's message (and attaches its files) to the Assistant in "Describe a problem", approves a plan it
// proposes, answers "continue" at most NUDGES times, then opens the run page, asks for alternative plans through
// "More run options", and saves: trace.log, panel.txt, run.json, export.csv, run-page.txt, alternatives.txt and
// screenshots. Scoring is done afterwards (score.py), from these files alone.
import { readFileSync, writeFileSync, appendFileSync, existsSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(process.env.PW_DIR + "/");
const { chromium } = require("playwright-core");

const [, , caseDir, outDir, workspace] = process.argv;
const BASE = process.env.WEB_URL || "http://localhost:3010";
const API = process.env.API_URL || "http://localhost:8010";
const LIMIT_MIN = Number(process.env.LIMIT_MIN || 20);
const NUDGES = 3;
mkdirSync(outDir, { recursive: true });
const t0 = Date.now();
const secs = () => Math.round((Date.now() - t0) / 1000);
const log = (line) => {
  const text = `[${String(secs()).padStart(5)}s] ${line}`;
  console.log(text);
  appendFileSync(`${outDir}/trace.log`, text + "\n");
};
const expected = JSON.parse(readFileSync(path.join(caseDir, "expected.json"), "utf8"));
const message = readFileSync(path.join(caseDir, "message.txt"), "utf8").replaceAll("{workspace}", workspace);

const login = await (await fetch(API + "/api/auth/login", {
  method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
  body: "username=admin&password=change-me-admin",
})).json();
const auth = { Authorization: `Bearer ${login.access_token}` };
const api = async (p) => { const r = await fetch(API + p, { headers: auth }); return [r.status, r.status < 300 ? await r.text() : await r.text()]; };

const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({ viewport: { width: 1500, height: 950 } });
await context.addInitScript((t) => { localStorage.setItem("solver_token", t); localStorage.setItem("solver_editor_level", "expert"); }, login.access_token);
const page = await context.newPage();
const problems = [];
page.on("pageerror", (e) => problems.push("pageerror: " + String(e).slice(0, 300)));
page.on("response", (r) => { if (r.status() >= 400 && r.url().includes("/api/")) problems.push(`HTTP ${r.status()} ${r.request().method()} ${r.url().replace(API, "").replace(BASE, "")}`); });
let shot = 0;
const snap = async (name) => { shot += 1; await page.screenshot({ path: `${outDir}/${String(shot).padStart(2, "0")}-${name}.png` }).catch(() => {}); };
const panel = page.locator('[aria-label="Assistant"]').first();
const panelText = async () => (await panel.innerText().catch(() => "")).trim();

const result = { case: caseDir, workspace, approved: 0, continues: 0, built: false, run: null, minutes: null };
// Runs made after this point are this case's (one case at a time): found through the API, not the panel's links.
const newestRun = async () => { const [, t] = await api("/api/v1/runs?limit=1"); const items = JSON.parse(t).items || []; return items.length ? items[0].id : 0; };
const startRun = await newestRun();
// The plan as asked is the newest run of a scenario that changes nothing (patch {}); what-if runs the Assistant
// solved after it ("Budget 400k") are not the answer (11 October 2026: p08 and p07 were scored on a what-if run).
const baseRun = async (ids) => {
  // From any run seen, walk to its problem's base scenario (patch {}) and take that scenario's newest answered
  // run: the base run is often not among the ids the page showed (12 October 2026: a what-if run scored again).
  for (const id of [...new Set(ids)].sort((a, b) => b - a)) {
    const [s, r] = await api(`/api/v1/runs/${id}`);
    if (s >= 300) continue;
    const [s2, sc] = await api(`/api/v1/scenarios/${JSON.parse(r).scenario_id}`);
    if (s2 >= 300) continue;
    const scen = JSON.parse(sc);
    if (Object.keys(scen.patch || {}).length === 0) return id;
    const [s3, list] = await api(`/api/v1/scenarios?problem_id=${scen.problem_id}&limit=100`);
    if (s3 >= 300) continue;
    const items = JSON.parse(list).items || JSON.parse(list);
    const base = (Array.isArray(items) ? items : []).find((x) => Object.keys(x.patch || {}).length === 0);
    if (!base) continue;
    const [s4, runs] = await api(`/api/v1/runs?scenario_id=${base.id}&limit=50`);
    if (s4 >= 300) continue;
    const answered = ((JSON.parse(runs).items || []).filter((x) => ["optimal", "feasible"].includes(x.status)).map((x) => x.id));
    if (answered.length) return Math.max(...answered);
  }
  return Math.max(...ids);
};
try {
  await page.goto(BASE + "/");
  await page.getByRole("button", { name: /Assistant \(Ctrl J\)/ }).click();
  await page.getByRole("tab", { name: "Describe a problem" }).click();
  const files = (expected.files || []).map((f) => path.join(caseDir, f));
  if (files.length) {
    await page.locator('input[type="file"]').first().setInputFiles(files);
    for (const f of expected.files) await page.getByText(f, { exact: false }).first().waitFor({ timeout: 60000 });
    log(`attached ${files.length} file(s)`);
  }
  await page.getByLabel("Message to the assistant").fill(message);
  await page.getByRole("button", { name: "Send" }).click();
  log("sent the problem");
  await snap("sent");

  const busy = async () => page.getByRole("button", { name: "Stop" }).isVisible().catch(() => false);
  let last = "", idleSince = null;
  while (Date.now() - t0 < LIMIT_MIN * 60000) {
    await page.waitForTimeout(5000);
    const text = await panelText();
    if (text !== last) {
      const fresh = text.startsWith(last.slice(0, 200)) ? text.slice(last.length) : text.slice(-500);
      const line = fresh.replace(/\s+/g, " ").trim().slice(0, 300);
      if (line.length > 20) log("panel: " + line);
      last = text;
    }
    const approve = page.getByRole("button", { name: /Approve and build/ });
    if (await approve.isVisible().catch(() => false) && await approve.isEnabled().catch(() => false)) {
      await snap("plan");
      writeFileSync(`${outDir}/plan-${result.approved + 1}.txt`, await panelText());
      // A person reads the plan card: a warning on the latest card ("CHECK THIS", or a trial with no answer) is
      // answered, not approved -- at most twice; then the plan is approved as it stands, and the run is scored.
      const card = (await page.locator('section[aria-label="Proposed model"]').last().innerText().catch(() => "")) || "";
      const warned = /CHECK THIS|NO answer exists/.test(card);
      result.warnings = (result.warnings || 0) + (warned ? 1 : 0);
      if (warned && (result.declined || 0) < 2) {
        result.declined = (result.declined || 0) + 1;
        const lines = card.split("\n").filter((l) => /CHECK THIS|NO answer exists/.test(l)).join(" ");
        await page.getByLabel("Message to the assistant").fill(
          `The plan card warns: ${lines.slice(0, 600)} That is not what I described. Please fix the model and propose it again.`);
        await page.getByRole("button", { name: "Send" }).click();
        idleSince = null;
        log(`declined a plan the card warns about (${result.declined})`);
        continue;
      }
      await approve.click();
      result.approved += 1;
      idleSince = null;
      log(`approved plan ${result.approved}`);
      continue;
    }
    if (await busy()) { idleSince = null; continue; }
    if (idleSince === null) { idleSince = Date.now(); continue; }
    if (Date.now() - idleSince < 12000) continue;
    const runs = [...text.matchAll(/\/runs\/(\d+)/g)].map((m) => Number(m[1]));
    const latest = await newestRun();
    if (latest > startRun) runs.push(latest);
    const links = await page.locator('[aria-label="Assistant"] a[href*="/runs/"]').evaluateAll((as) => as.map((a) => a.getAttribute("href")));
    for (const h of links) { const m = /\/runs\/(\d+)/.exec(h || ""); if (m) runs.push(Number(m[1])); }
    const mine = runs.filter((r) => r > startRun);  // only runs made during this case
    if (result.approved > 0 && (mine.length || /Built/.test(text))) { result.run = mine.length ? await baseRun(mine) : null; break; }
    if (result.continues >= NUDGES) { log("no more continues; stopping"); break; }
    result.continues += 1;
    await page.getByLabel("Message to the assistant").fill("continue");
    await page.getByRole("button", { name: "Send" }).click();
    idleSince = null;
    log(`typed "continue" (${result.continues})`);
  }
  result.minutes = +((Date.now() - t0) / 60000).toFixed(1);
  // A turn still running at the limit is stopped: left alone it holds the model, and the next case's first call
  // waited 20 minutes behind it (11 October 2026: p08 timed out, then p07 never got a reply).
  if (await busy()) {
    await page.getByRole("button", { name: "Stop" }).click().catch(() => {});
    result.stopped = true;
    for (let i = 0; i < 60 && (await busy()); i++) await page.waitForTimeout(2000);
    log(`stopped the running turn at the limit (busy after: ${await busy()})`);
  }
  for (const fold of await page.getByRole("button", { name: /\d+ steps?/ }).all()) {
    if ((await fold.getAttribute("aria-expanded")) === "false") await fold.click().catch(() => {});
  }
  writeFileSync(`${outDir}/panel.txt`, await panelText());
  await panel.screenshot({ path: `${outDir}/panel-end.png` }).catch(() => {});
  result.built = result.approved > 0 && /Built/.test(await panelText());
  log(`assistant done: built=${result.built} run=${result.run} minutes=${result.minutes}`);

  if (result.run) {
    const [, runJson] = await api(`/api/v1/runs/${result.run}`);
    writeFileSync(`${outDir}/run.json`, runJson);
    const run = JSON.parse(runJson);
    const [, csv] = await api(`/api/v1/runs/${result.run}/export?format=csv`);
    writeFileSync(`${outDir}/export.csv`, csv);
    const [, map] = await api(`/api/v1/runs/${result.run}/answer-map`);
    writeFileSync(`${outDir}/answer-map.json`, map);
    const [, problem] = await api(`/api/v1/scenarios/${run.scenario_id}`);
    const scen = JSON.parse(problem);
    // The workspace from the "Open the problem" link the Assistant shows once it has built.
    const hrefs = await page.locator('[aria-label="Assistant"] a[href*="/domains/"]').evaluateAll((as) => as.map((a) => a.getAttribute("href")));
    const owner = hrefs.map((h) => /\/domains\/(\d+)\/problems\/(\d+)/.exec(h || "")).filter((m) => m && Number(m[2]) === scen.problem_id)[0];
    const domainId = owner ? Number(owner[1]) : null;
    result.scenario = run.scenario_id; result.problem = scen.problem_id; result.domain = domainId;
    const runUrl = `${BASE}/domains/${domainId}/problems/${scen.problem_id}/runs/${result.run}`;
    await page.goto(runUrl);
    await page.waitForTimeout(6000);
    await page.screenshot({ path: `${outDir}/run-page.png`, fullPage: true }).catch(() => {});
    writeFileSync(`${outDir}/run-page.txt`, await page.locator("main").innerText().catch(() => ""));
    log("saved the run page");

    // Alternative plans: "More run options" -> Other plans 3, within 10% -> Solve.
    try {
      await page.getByText("More run options").click();
      await page.getByLabel(/Other plans/).fill("3");
      await page.getByLabel(/within \(% of the best\)/).fill("10");
      // Its own button, offered only when the model has yes/no or bounded whole-number decisions.
      const altButton = page.getByRole("button", { name: /alternative plans/ });
      if (!(await altButton.isVisible().catch(() => false))) {
        result.alternatives_offered = false;
        throw new Error("no 'Solve, with N alternative plans' button: the platform does not offer alternatives for this model");
      }
      result.alternatives_offered = true;
      await altButton.click();
      log("asked for 3 other plans within 10%");
      let alt = null;
      for (let i = 0; i < 120; i += 1) {
        await page.waitForTimeout(5000);
        const [, list] = await api(`/api/v1/runs?scenario_id=${run.scenario_id}`);
        const items = (JSON.parse(list).items || []).filter((r) => r.id > result.run);
        if (items.length && items.every((r) => !["queued", "running"].includes(r.status))) { alt = items; break; }
      }
      result.alternative_runs = (alt || []).map((r) => ({ id: r.id, status: r.status, objective: r.objective, purpose: r.purpose }));
      const newest = alt && alt.length ? Math.min(...alt.map((r) => r.id)) : null;
      if (newest) {
        await page.goto(`${BASE}/domains/${domainId}/problems/${scen.problem_id}/runs/${newest}`);
        await page.waitForTimeout(6000);
        const section = page.locator('section[aria-label="Alternative plans"]');
        writeFileSync(`${outDir}/alternatives.txt`, (await section.innerText().catch(() => "")) || (await page.locator("main").innerText().catch(() => "")));
        await page.screenshot({ path: `${outDir}/alternatives.png`, fullPage: true }).catch(() => {});
        const [, altJson] = await api(`/api/v1/runs/${newest}`);
        writeFileSync(`${outDir}/alternatives-run.json`, altJson);
      }
      log(`alternatives: ${JSON.stringify(result.alternative_runs)}`);
    } catch (e) {
      result.alternatives_error = String(e).slice(0, 300);
      log("alternatives failed: " + result.alternatives_error);
    }
  }
} catch (e) {
  result.error = String(e).slice(0, 500);
  log("ERROR " + result.error);
  await snap("error");
}
result.browser_problems = [...new Set(problems)];
writeFileSync(`${outDir}/result.json`, JSON.stringify(result, null, 2));
log("END " + JSON.stringify({ built: result.built, run: result.run, minutes: result.minutes, continues: result.continues }));
await browser.close();
