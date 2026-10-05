# The Assistant

A language model built into the platform. It opens from the **Assistant** button
in the header (or Ctrl J) on every page, and has two tabs:

| Tab | What it does |
|---|---|
| **Ask** | Does anything in the platform you ask, through the platform's own API, as you, with exactly your permissions: find, create, change, solve, explain. It asks before any delete. |
| **Describe a problem** | You describe a decision problem in your own words and attach your data files. It interviews you until it understands, shows you the model it would build (sets, parameters, variables, rules, goals), builds it only when you approve, then solves it and explains the results. |

It runs on your own model server (vLLM). Nothing leaves your network.

## Describing a problem: what happens

1. **Understand.** The assistant restates what it understood and asks the open
   questions, at most four at a time: what is decided, what to minimise or
   maximise, every rule (and whether it may ever bend, at what cost), and the
   data with units. Vague words ("cheap", "fair", "as many as possible") get a
   question or a concrete proposal to confirm. It points out contradictions and
   missing data. When you say "you decide", it picks a specific default and
   lists it as an assumption.
   When data is missing it asks for it: type it, or **attach a file** (the
   paperclip: CSV, TSV, Excel, JSON) with the columns it names. It reads and
   checks attached files, and asks about anything odd.
2. **Propose.** When nothing important is open, it shows a **Proposed model**
   in the Model Editor's terms: **Sets** (with their data and where it comes
   from), **Parameters**, **Variables**, **Rules** (each in words *and* as a
   formula, hard or soft), **Goals**, and **Assumptions**. *Technical details*
   shows the exact spec. Rows of an attached file are loaded by the spec
   (`entities_from_file`, `parameter_values_from_file`), not copied through the
   chat, so a file of thousands of rows costs nothing in the conversation.
3. **Approve or change.** **Approve and build**, or **Request changes** and say
   what should change. It revises and proposes again.
4. **Build, solve, report.** On approval it builds exactly the plan you
   approved: the domain's record types, fields, records (typed and from your
   files), links and parameters, the problem, its first model version and a
   **Base** scenario. Then it solves the Base scenario, waits for the run, and
   explains what it built and the results: status, the goal's value, the
   decisions as a table in your names, and for an infeasible run which rules
   conflict and what to relax. Links take you to the problem, model and run.

#### Map files: CAD drawings and GIS

Attach (or drop on the Assistant) the same files the Map Import page takes: a
CAD drawing (.dxf), GeoJSON, KML/KMZ, GPX, a Shapefile as a .zip of its .shp,
.shx, .dbf and .prj, a GeoPackage (.gpkg), or a CSV with a WKT column or
lon/lat (x/y) columns. They are read by the platform's own Map Import readers
and kept as its uploads are (a day).

- Each layer becomes a table of features: its position (lon/lat), area and
  length in metres, its shape, and its attributes.
- A GeoJSON, KML or GPX file, or a file whose coordinate system the platform is
  sure of (a .prj, a GeoPackage's SRS, a drawing's GEODATA), is placed on the
  map at once. Otherwise, a drawing in metres for example, the chip says
  *coordinate system to confirm*: the Assistant asks which system it is in,
  offering the likely ones, places it (`place_file`), and checks with you that
  it lands in the right place.
- In a plan, a layer's features become records with real shapes
  (`entities_from_file` with a `geometry` field), ready for distances, maps
  and the answer map. In the Ask tab the file can also be imported as map data
  (`POST /api/v1/gis/datasets`) and turned into records from its layers.

## What the server enforces (not just the prompt)

- **No plan before a conversation.** A plan proposed before you have answered
  anything is refused and sent back to the model.
- **No plan you cannot build.** Every plan is dry-run
  (`POST /api/v1/problems/from-spec` with `dry_run: true`) before you see it.
  Errors go back to the model to fix.
- **No writes in this mode** except the approved build and solving its
  scenario.
- **All or nothing.** The build is one transaction; a refusal keeps nothing.
- **As you.** Every call carries your own token: your capabilities, your
  organization, your audit trail (`problem.from_spec` in the audit log).


## It runs what it decides (the audit's "General assistant" plan)

`general_assistant_kit` is wired into `backend/app/agent/`:

- **Calls written as text run.** Qwen sometimes writes a tool call into its reply instead of sending it:
  a `<tool_call>` block after some prose, a Qwen3-Coder `<function=…>` block, or fenced JSON.
  `app/agent/toolcall.py` (the kit's) finds and runs them. The old parser silently skipped any
  call whose JSON did not load, so the person saw the call as text and nothing ran.
- **A broken call is never half-run.** Bad JSON, a key given twice (which silently dropped data
  before) or an unknown tool goes back to the model with the reason, and it sends the call again.
- **A reply cut off at the length limit never runs its call.** The model is told to send a smaller
  call (rows from files, several calls) rather than having half a spec repaired and built.
- **No unrun calls and no empty claims in a final reply.** A reply still holding tool-call text, or
  saying something was built, imported, placed or solved when no tool did it in that turn, goes
  back to the model once (at most 3 nudges a turn). These platform messages start `[Platform]` and
  do not count as the person's turns.
- **New tools.** `query_file` (exact counts, filters, sums and groups over an attached sheet), `describe_workspace` (a domain's kinds of record, fields, counts, relationships,
  data values, map data and problems, in one call: `GET /api/v1/agent/workspace`), `check_spec`
  (the full plan through the platform's validators, without building or showing anything), and
  `relationships_from_file` (one link per row of a two-column sheet) for loading records into any
  workspace.
- **Method.** Look first, keep an "Agreed so far" list, size the problem, check then propose, and
  the kit's modelling patterns (`via` sums, ranked `lex` goals, cover, capacity, linking).

### What the first field test changed (October 2026)

A warehouse problem described to the Assistant with three CSV files (5 candidate warehouses, 12 customers,
60 lanes; at most 3 open; no lane over 450 road km; one warehouse per customer), solved separately as a
reference (Cairo-6Oct, Tanta, Assiut open; 1,338,765 EGP a month). The platform solves the same model to the
same answer (`tests/test_agent_field_test.py`). What went wrong on the way, and what changed:

| Seen | Changed |
|---|---|
| Added and counted in its head, wrongly (capacity 2,450 for 2,850; 11 lanes over the limit for 13). | Each attached sheet comes with exact **totals** (sum, min, max per number column; distinct values per text column). New tool **`query_file`**: count, filter, add up and group a sheet exactly. The prompt forbids mental arithmetic. |
| Could not see how to write "only lanes up to 450 km" and thought aloud in circles until the length limit, twice (28,000 characters each time, shown as the answer). | A reply that runs to the length limit without a tool call is **never shown**: the same step is asked again with thinking off, then the model is told; at the end the person gets one honest line. New **pattern**: a value per pair limits which pairs may be used: `lane_km[w,c] * assign[w,c] <= 450`. |
| Sent the spec with `entity_types` twice, three times in a row, then an empty answer. | A list split over two same-named keys is **joined** (two objects with no key in common merged) and the model is told; two different values are still refused, now naming both. A broken JSON call says where it broke. An **empty answer** is sent back. |
| (Seen before) a spec written into the reply instead of a tool call. | In *Describe a problem*, a spec in the reply is run through `check_spec` for the model. |

### The camp-bed evaluation (October 2026): data first, local metres, no endless loop

A drawing-based layout brief (sofabeds in camps, a DXF with no projection) showed the Assistant understood
the goal but could not turn the drawing into records: it used EPSG:4326 on a metre drawing (an 88 m camp
became "86 km"), built kinds with no records, solved nothing, and looped 24 times until the context
overflowed. Changes:

| Fix | What it does |
|---|---|
| **Data first** | A plan is refused when any set it uses would have no records: each needs a source -- typed records, `entities_from_file` (an attached file, a map layer, or a file `run_python` generated), or records already in the domain. |
| **Data tools** | In *Describe a problem* the Assistant may now prepare data: a new domain, map data imported (`/gis/datasets`, `/records/propose`, `/records`, map-to-records), and the platform's calculations (`/distances`, `/within`, `/derive-value`, `/entity-types/{id}/derive`). |
| **run_python on** | `AGENT_RUN_PYTHON` defaults to 1 (still only for people who may publish models). The sandbox no longer fails where Docker refuses network namespaces (the Python socket guard applies). Files it writes are loaded whole from its folder (up to 200,000 rows), and are never overwritten by their 5,000-row attachment copy. |
| **Local metres for CAD** | A drawing with no coordinate system is placed at once in local metres: `x_m`, `y_m`, `width_m`, `height_m`, `area_m2`, `shape_m` (WKT in metres for run_python). No coordinate-system question; `place_file` refuses degrees for a non-degree drawing; a drawing more than 5 km across gets a scale check. |
| **Solve blocked on empty sets** | A set the model's decisions range over that has no records is a readiness *blocker* (Solve disabled) and a run is refused with 422 naming the set. |
| **Stop the loop** | The same refusal 3 times ends the turn with the exact error and the part of the plan it is about. Only the latest spec attempt stays in the history. Each reply gets min(planned, context − prompt − 512) tokens. The context size is read from the model server (`max_model_len`), so raising vLLM to 64k needs no platform change. The person's first message (the problem) is never trimmed away. |
| **Layout pattern** | Candidates, cells and an `occupies` link generated with run_python; no overlap is one rule per cell (`via occupies`), never pairs of candidates. Plans may hold 50,000 records and 200,000 values; records and links are written in one flush (20,000 records: 38 s → 14 s). |

### run_python (on by default since the camp-bed evaluation)

The model's workbench: Python in a working folder per conversation, where every attached sheet is a
CSV. Files it writes come back as attachments for a plan to load. It runs code a language model
wrote. It is **on** by default (`AGENT_RUN_PYTHON=1`; set `0` to turn it off), and only for people who may publish models.
The code runs as `nobody` (it cannot read the backend's secrets), with no environment, CPU, memory
and time limits, and no network: its own network namespace where the kernel allows it, otherwise
Python's sockets are disabled. That last one is a guard, not a wall. Code that goes around Python
could still reach ClickHouse (no password) or your LAN, so run the backend under a network policy
before you turn this on for people you do not trust. `GET /api/v1/agent/status` shows the setting,
and each result says which isolation applied.

## Configuration

Set these in `.env`; `docker-compose.yml` passes them to the backend.

| Variable | Default | |
|---|---|---|
| `AGENT_ENABLED` | `1` | `0` turns the assistant off |
| `LLM_BASE_URL` | `http://10.125.18.189:8000/v1` | your vLLM server (OpenAI-compatible) |
| `LLM_MODEL` | `qwen3.5` | the served model id |
| `LLM_API_KEY` | `EMPTY` | if the server wants one |
| `LLM_CONTEXT` | `262144` | the model's `max_model_len`, used only when vLLM does not report its own |
| `LLM_COMPACT_AT` | `0.6` | summarize the older conversation once it passes this share of the context |
| `LLM_MAX_TOKENS` | `16384` | per reply, Ask tab; never more than a quarter of the context |
| `LLM_PLAN_MAX_TOKENS` | `32768` | per reply, Describe tab (a plan carries data); never more than a quarter of the context |
| `LLM_TEMPERATURE` | `0.2` | |
| `LLM_THINKING` | *(server default)* | `on` / `off` for Qwen's thinking |
| `LLM_TOOL_MODE` | `auto` | `native` / `text`; `auto` detects |
| `AGENT_CONFIRM` | `delete` | `write` asks before every change, `none` never |
| `AGENT_MAX_STEPS` | `60` | tool calls per turn |
| `AGENT_RUN_PYTHON` | `1` | `0` turns run_python off (see above); `unsafe` also when the server is not root |
| `AGENT_SANDBOX_ROOT` | `/tmp/assistant_sandbox` | run_python's working folders (kept a day) |

**Tool calling.** Best with vLLM started with
`--enable-auto-tool-choice --tool-call-parser qwen3_coder` (or `hermes`). Without
those flags the assistant detects it and uses `<tool_call>` text blocks instead.

**Reaching the model.** The backend container calls `LLM_BASE_URL`. Check with
the Assistant panel (it warns when the model cannot be reached), or:

```bash
docker compose exec backend python -c "import urllib.request;print(urllib.request.urlopen('http://10.125.18.189:8000/v1/models').read()[:200])"
```

## Long conversations: summarized, not cut

Every turn sends the whole conversation to the model again: the brief, the files that were read, and every
tool call and result. A layout problem fills 32k tokens quickly.

**Automatic summary.** When the conversation passes `LLM_COMPACT_AT` of the context (60% by default), the
older part is summarized by the model itself, and the recent part is kept word for word
(`app/agent/compact.py`).

- **What the summary holds.** It uses fixed headings: Problem, Agreed, Data, Platform (every id), Done, and
  Open. It keeps ids, file names and numbers exactly.
- **What is kept word for word.** The person's first message is always kept as written. Their latest
  request is kept too, when it falls in the summarized part.
- **What code carries, not the model.** The numbers the person gave and the tools computed are carried on
  record by code, so the data-values check still accepts them. Whether the plan was built is carried the
  same way, so solving stays allowed. The model's own summary text vouches for nothing.
- **Long and repeated summaries.** A conversation longer than the context is summarized in pieces. A
  later summary folds the earlier one in.
- **The short version is what gets sent next.** The browser keeps the summarized history, so the next
  turn sends the short version. The chat on screen is unchanged, and a note says what was summarized.
- **If summarizing fails,** the old trimming (`fit()`) still keeps the request under the limit.

**Sizes follow the context.** A tool result may take an eighth of the context (32,768 characters at 262k,
8,000 at 32k), and a reply at most a quarter. The footer under the message box shows roughly how many
tokens the conversation uses, out of the model's limit.

**Chat commands** (typed as the whole message): `/reset` (also `/new`, `/clear`) starts a new conversation;
`/compact` (also `/summarize`) summarizes now; `/help` lists them.

**On request:** the **Summarize chat** link under the message box (or a message that is just `/compact`)
summarizes now and shows the summary.

**A bigger context.** The platform reads vLLM's real `max_model_len` from `/v1/models`, so raising it on
the server needs no change here. For the hybrid Qwen3.5 MoE (`Qwen3_5MoeForConditionalGeneration`: 48
layers, only every 4th uses full attention, 2 KV heads of 256), the KV cache is small. It costs about
12 × 2 × 2 × 256 × 2 bytes ≈ 24 KB per token in bf16:

| Context length | KV cache for one conversation |
|---|---|
| 64k | about 1.6 GB |
| 128k | about 3.2 GB |
| 256k (`max_position_embeddings`) | about 6.4 GB |

To raise it, start vLLM with `--max-model-len 131072` (or `262144`). vLLM's start-up log says whether the
cache fits ("Maximum concurrency for … tokens per request").

## API

- `GET /api/v1/agent/status`: on/off, model, whether the model answers.
- `POST /api/v1/agent/chat`: one turn, streamed as NDJSON. The conversation is
  the client's: send the `messages` from the last `state` event back each turn.
  Events: `thinking`, `note`, `tool`, `result`, `confirm`, `plan`, `built`,
  `answer`, `error`, `ping`, and always `state` last. `confirm: {"allow": bool}`
  answers a `confirm` or `plan`; a new `text` instead is feedback on it.
- `POST /api/v1/agent/files`: read an attached file into tables: CSV/TSV/Excel/JSON
  (up to 10 MB, 5,000 rows a sheet; not stored), or a map file (up to 50 MB; kept
  as a Map Import upload, `spatial.upload_id`). The client sends the tables back
  as `files` with each chat turn.
- `POST /api/v1/agent/files/place`: a map file read again in the coordinate
  system named, `{"upload_id", "placement": {"kind": "epsg", "code": n}}`.
- `POST /api/v1/problems/from-spec`: build a domain's data, a problem, its model
  and a Base scenario from one spec (`domain_seed` + IR), all or nothing;
  `dry_run: true` only checks. Needs `model.publish`. Usable without the
  assistant.

Code: `backend/app/agent/core.py` (loop, tools, prompts), `backend/app/agent/files.py`,
`backend/app/api/agent.py`, `backend/app/api/model_spec.py`,
`frontend/src/components/assistant/`.

## Also in this change

`NulByteGuard` (`app/core/nul_guard.py`) answered `http.disconnect` once it had
replayed a request body, so any streamed response to a POST stopped before its
first line. It now hands over to the real connection.
