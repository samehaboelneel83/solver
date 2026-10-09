# Everything without the Assistant

The owner's rule (9 October 2026): this is a general-purpose solver platform, and everything the Assistant can do
must be doable in the platform itself. This page maps each Assistant tool to where a person does the same.

| The Assistant's tool | In the platform | API |
| --- | --- | --- |
| `make_layout` (placement or candidate form) | Start a problem → **From a drawing**: layers, items, aisle, access, grid; preview; trial; make | `POST /api/v1/layouts/drawings`, `/layouts/preview`, `/layouts/build` |
| `check_spec` (read-back, trial) | Model editor → Review → **Read it back and try it** | `POST /api/v1/problems/{id}/draft-check` |
| `propose_plan` from files | Start a problem → From a spreadsheet; Sources → kept files → **Load into…** | `/spreadsheet/*`, `/domains/{d}/source-bindings` |
| Anything a form does not draw (generated sets, placement rules, any contract key) | Model editor → **Exact IR** (editable, checked as typed) | — |
| Generated sets (`generate`: range, product, positions) | Model editor → declarations → **Generated sets** | — |
| `connected` with `sources` | Rule editor → **Reached from (sources)** | — |
| A `predict` term | Term picker → **Prediction** (once a trained model exists) | — |
| `read_result` | Run page → **The answer explained** | `GET /api/v1/runs/{id}/explanation` |
| `what_if`, `set_limit` on a data value | Scenarios → a rule's limit, or **its limit is the data value …** | scenario patch `set_param` |
| Run options (seed, reuse, futures, trade-off points, other plans) | Runs → **More run options** | `POST /scenarios/{id}/runs` |
| `use_source`, `refresh_sources`, `schedule_refresh` | Sources → import → **Keep them refreshed**; **Check for changes**; schedule; **Stop keeping refreshed** | `/ingestion-jobs/{id}/load` (`keep_refreshed`), `/domains/{d}/sources/refresh` |
| `query_file` (exact counts and sums) | Records → **Totals of …** (group by a field, add up numbers) | `GET /api/v1/entity-types/{id}/totals` |
| A failed sign-in to a source | Sources → **Replace the password / token / client secret** | `PUT /connections/{id}/credential` |
| Keeping an answer to hold later versions to | Run page → **Keep this answer as an acceptance case**; version checks → **Remove case** | `/problems/{id}/suite-cases/from-run/{run}` |
| Map data in a second workspace | Map data → **Copy into…** | `POST /api/v1/gis/datasets/{id}/copy` |
| (operator) a new tenant, its quota, export, delete | Administration → **Organizations and sign-in** | `GET/POST /api/v1/organizations`, `/organizations/{id}/quota`, `/export`, `/delete` |
| Single sign-on, directory sync | Administration → Organizations and sign-in | `/api/v1/sso/provider`, `POST /api/v1/scim/token` |

Still only through the Assistant: describing a problem in words and getting a first model from them (the model
editor's "Describe the problem in words" helps, but writes less), and running Python in its sandbox.
