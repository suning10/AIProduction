# SCR Inventory Gap Agent — Design

Status: prototype (runs end-to-end against an in-process mock of the SCR API; not yet verified against the live
EcomToolBox server or a real LLM key).

## 1. Problem

The SCR (stock comparison report) compares on-hand inventory between two systems for every SKU × storage location
(sloc):

| System  | What it is                         | Source tables (per `SCRMapper.xml`)  |
|---------|------------------------------------|--------------------------------------|
| NERP    | ERP stock ledger (SAP MB51-style)  | material documents / movement types  |
| Synapse | 3PL WMS item activity              | item activity / order transactions   |

`netGap = NERP − Synapse`. On a given day 100+ SKUs across all slocs can carry a gap. For each one the agent must:

1. **Discover** the SKUs with a gap for a report date.
2. **Trace** the day-over-day gap history to find when the gap started and every day it changed.
3. **Reconcile** transactions on/after the origin date and find what one system is missing:
   - a transaction booked in one system but not the other,
   - an inventory adjustment on one side only,
   - the same reference with a different qty.
4. **Summarize** the findings and retrieve knowledge-base guidance on how to fix each kind of problem.

## 2. Key decision: deterministic investigation, per-SKU agents only for resolution

Steps 1–3 are deterministic: walking a time series back to its origin and diffing two transaction lists are exact
operations. Running them through an LLM per SKU would cost 100+ × several tool rounds of LLM calls, be slow,
non-reproducible, and risk invented quantities.

What steps 1–3 need is **I/O fan-out**, not reasoning fan-out: each SKU needs ~7 HTTP calls. So investigation is a
**deterministic map-reduce** (LangGraph `Send`) with bounded concurrency.

Resolution (step 4) is different: it needs judgement and SKU-specific knowledge-base lookups (movement type,
transaction type, system). So after step 3 a **per-SKU resolver agent** runs, each with its own small context — the
SKU's structured finding (a few hundred tokens), never raw transaction rows — and a single tool, knowledge-base search.
Simple SKUs skip the agent and get a deterministic template.

| LLM call                         | When                                                         | Count per run                 |
|----------------------------------|--------------------------------------------------------------|-------------------------------|
| Classify (structured)            | Only for SKUs the rules leave `unexplained`                  | 0 … #unexplained               |
| Resolver agent (tool loop + structured answer) | Every non-simple SKU (see triage)              | 2–4 per agent SKU (≤ 1 + `MAX_TOOL_ROUNDS`) |
| Summarize                        | Once                                                         | 1                             |

On the mock data 69 of 96 SKU/locations are simple (template, no LLM) and 27 go to the agent.

## 3. Architecture

```
POST /api/v1/inventory/investigations ──▶ row(status=pending) ──▶ background task
                                                                     │
                       ┌─────────────────────────────────────────────┘
                       ▼
                 discover_gaps ── Send per SKU/sloc ──▶ investigate_sku
                 (summary → slocs,                      dod → trace origin → reconcile window
                  gaps per sloc,                        → find discrepancies → classify
                  sort by |value|, cap)                 → (unexplained only) llm_classify
                       │ no gaps                               │ findings (operator.add)
                       │                                       ▼
                       │                                    triage
                       │              simple SKUs ─────────────┤──── Send per other SKU ────▶ resolve_sku
                       │              (template, no LLM)       │                              (agent: rag_search
                       │                                       │                               ≤ N rounds → ResolutionDraft)
                       ▼                                       ▼  resolutions (operator.add)       │
                   summarize ◀─────────────────────────────────┴───────────────────────────────────┘
                   (roll up per root cause → plans; LLM report, fallback)
                       │
                       ▼
                persist findings (+ resolution) + report + plans (Postgres) ──▶ status=completed
```

- Separate compiled graph (`InventoryGapAgent`), independent of the chat graph. No checkpointer: a run is a
  one-shot batch whose results are persisted explicitly.
- `findings` and `resolutions` use `operator.add` reducers so parallel branches merge; `run()` attaches each
  resolution to its finding before returning.
- `max_concurrency` (run config) plus an `asyncio.Semaphore` in the HTTP client (`INVENTORY_MAX_CONCURRENCY`, default
  8) bound load on the upstream server.
- LangGraph delivers `Send` payloads to nodes as plain dicts; nodes coerce them with `_as_state()`.

## 4. Upstream API (EcomToolBox `SCRController`)

All endpoints live under `{base_url}/admin/scr/` and return the `Result` envelope `{code, msg, data}` (`code == 1`
is success). No auth (the interceptor is disabled server-side).

| Logical name          | Method / path                              | Params                                  | Used for                         |
|-----------------------|--------------------------------------------|-----------------------------------------|----------------------------------|
| `sloc_summary`        | GET `scrReportSummary`                     | `date={days_ago}`                       | slocs with gaps (if none given)  |
| `gaps`                | GET `scrReportGap`                         | `date={days_ago}`, `sloc`               | SKUs with a gap per sloc         |
| `day_over_day`        | GET `dodResearch`                          | `material={sku}`, `sloc`                | gap history                      |
| `qty_mismatch`        | POST `skuComparision`                      | body `{sku,start,end,sloc}`             | same reference, different qty    |
| `missing_in_synapse`  | POST `skuComparisionMissingNerp`           | body `{sku,start,end,sloc}`             | NERP doc with no Synapse match   |
| `missing_in_nerp`     | POST `skuComparisionMissingItemActivity`   | body `{sku,start,end,sloc}`             | Synapse activity with no NERP doc|
| `nerp_adjustments`    | POST `skuDetailNERPAdj`                    | body `{sku,start,end,sloc}`             | NERP-side adjustments            |
| `synapse_adjustments` | POST `skuDetailSynapseAdj`                 | body `{sku,start,end,sloc}`             | Synapse-side adjustments         |

Semantics derived from the controller and SQL:

- Report endpoints take `date` as a **days-ago offset** from today, and `scrReportGap` is per sloc.
- `dodResearch` returns the full history of the **absolute** gap (`TotGap`), dates as `MM/dd/yyyy`. It is used only
  for timing (origin and change dates); the signed net gap comes from `scrReportGap.netGap`.
- Reconciliation endpoints take a date **range** (`yyyy-MM-dd`), so one call per endpoint covers the whole window
  from origin to report date: 5 calls per SKU instead of 2 per change date.

### 4.1 Configurability

Every contract lives in `app/core/inventory_endpoints.json`, so adapting to a different API or a contract change is a
config edit:

```json
"gaps": {
  "method": "GET",
  "url": "{base_url}/admin/scr/scrReportGap",
  "params": {"date": "{days_ago}", "sloc": "{sloc}"},
  "records_path": "data",
  "field_map": {"sku": "material", "gap": "netGap", "abs_gap": "totalGap", ...},
  "qty_multiplier": 1
}
```

- Templates: `url`, `params`, `body`, `headers` accept `{base_url} {days_ago} {date} {sku} {sloc} {start} {end}` and
  `${ENV_VAR}` (for tokens). Values placed in the URL are percent-encoded (except `base_url`).
- `records_path`: dot path to the record list in the response.
- `field_map`: canonical field ← upstream dot path. Upstream strings like `"1,234"` or `"10/27/2026"` are coerced by
  Pydantic validators (`app/schemas/inventory.py`).
- `qty_multiplier`: flip to `-1` if one system reports quantities with the opposite sign.
- `envelope`: where to find the status code / message and which codes mean success.

Settings (`app/core/config.py`, documented in `.env.example`):

| Variable                           | Default                            | Purpose                                  |
|------------------------------------|------------------------------------|------------------------------------------|
| `INVENTORY_API_MODE`               | `mock`                             | `mock` (in-process fake) or `http`        |
| `INVENTORY_API_BASE_URL`           | `http://localhost:80`              | EcomToolBox server                        |
| `INVENTORY_ENDPOINTS_FILE`         | `app/core/inventory_endpoints.json`| contract file (swap per environment)      |
| `INVENTORY_API_TIMEOUT_SECONDS`    | 30                                 | per request                               |
| `INVENTORY_API_CACHE_TTL_SECONDS`  | 300                                | success-only response cache               |
| `INVENTORY_SLOCS`                  | (empty → discover via summary)     | default slocs                             |
| `INVENTORY_MAX_CONCURRENCY`        | 8                                  | concurrent upstream calls / graph branches|
| `INVENTORY_LOOKBACK_DAYS`          | 30                                 | how far back to search for the origin     |
| `INVENTORY_RECON_PADDING_DAYS`     | 2                                  | reconcile from origin − N days            |
| `INVENTORY_MAX_SKUS`               | 500                                | cap per run (largest value first)         |
| `INVENTORY_LLM_CLASSIFY_ENABLED`   | true                               | LLM fallback for unexplained SKUs         |
| `INVENTORY_MOCK_SKU_COUNT`         | 40                                 | size of the mock dataset                  |
| `INVENTORY_TEMPLATE_MAX_DISCREPANCIES` | 3                              | triage cutoff for templates (0 = agent for every SKU) |
| `INVENTORY_RESOLVE_MAX_TOOL_ROUNDS`| 3                                  | max KB-search rounds per resolver agent   |
| `INVENTORY_KB_CACHE_TTL_SECONDS`   | 3600                               | KB search cache (per user + query)        |

### 4.2 Client behaviour (`app/services/inventory_client.py`)

- `httpx.AsyncClient`; in mock mode an `httpx.MockTransport` serving Java-identical JSON
  (`app/services/inventory_mock.py`), so the same request/mapping path is exercised.
- Retries with tenacity (3 attempts, exponential backoff) on transport errors, 5xx and 429 only.
- Only successful, validated responses are cached (`cache_service`); envelope failures and mapping errors raise
  `InventoryApiError` and are never cached.

## 5. Analysis rules (`app/services/inventory_analysis.py`)

Pure functions, no I/O, unit-tested.

### 5.1 Origin tracing — `trace_gap_history`

1. Keep points within `[as_of − lookback, as_of]`; sum duplicate rows for the same date.
2. If the latest day has no gap → no origin.
3. Walk back through the contiguous run of non-zero days; the earliest day is the **origin**.
4. If the run reaches the oldest visible day, mark `origin_truncated` (the gap may be older than the lookback).
5. Record every day-over-day change (`date, abs_gap, delta`) within the run.

The reconciliation window is `[origin − RECON_PADDING_DAYS, as_of]`; the padding covers report snapshots that lag
postings.

### 5.2 Discrepancies — `find_discrepancies`

Sign convention: impact is the contribution to `NERP − Synapse`.

| Kind                  | Source                                  | Impact               |
|-----------------------|-----------------------------------------|----------------------|
| `qty_mismatch`        | same reference, `nerpQty ≠ synapseQty`  | `nerp − synapse`     |
| `missing_in_synapse`  | NERP doc with no Synapse counterpart    | `+qty`               |
| `missing_in_nerp`     | Synapse activity with no NERP doc       | `−qty`               |
| `nerp_adjustment`     | unmatched NERP adjustment               | `+qty`               |
| `synapse_adjustment`  | unmatched Synapse adjustment            | `−qty`               |

Adjustments carry no shared reference, so `cancel_matched_adjustments` first removes pairs with equal qty booked in
both systems within 1 day — those are a correction done correctly on both sides.

### 5.3 Classification — `classify`

- `explained_qty = Σ impact`; the SKU is **explained** iff `explained_qty == netGap`.
- `root_cause` = the kind with the largest total `|impact|`; `unexplained` when nothing was found.
- Additional root causes: `timing_difference`, `unexplained`, `error` (upstream failure for that SKU).
- If unexplained and LLM classification is enabled, the LLM gets the gap history and raw discrepancies and returns a
  structured `LlmClassification` (root cause, hypothesis, confidence). Its output is labelled as a hypothesis, never
  used to alter quantities.

## 6. Resolution and report

### 6.1 Triage

A finding is **simple** when it is fully explained, has 1…`INVENTORY_TEMPLATE_MAX_DISCREPANCIES` discrepancies, and
they are all of one kind. Simple findings get a **template resolution** (no LLM): one concrete action per discrepancy,
quoting only reconciled facts (e.g. *"Reference 45038819260 (RECEIPT 2026-10-28): NERP qty 34 vs Synapse qty 10 —
confirm the correct quantity and correct the other system by 24."*), the generic procedure for that kind, and a
verification step. Error findings get no resolution. Everything else — mixed causes, partially explained, unexplained —
goes to the resolver agent, highest gap value first.

### 6.2 Resolver agent (`resolve_sku`)

- **Input:** the compact finding (`_resolver_input`): net gap, value, origin, day-over-day changes, up to 25
  discrepancies with their impacts, root cause, LLM hypothesis if any.
- **Tool:** only `rag_search` (the existing tool's schema). The node executes the calls itself through `_search_kb`:
  - scoped to the requesting user via `rag_service.search(user_id, …)` — the model cannot choose whose access applies;
  - cached per (user, lower-cased query) for `INVENTORY_KB_CACHE_TTL_SECONDS`, non-empty hits only, so many agents
    asking the same question hit the vector store once.
- **Loop:** up to `INVENTORY_RESOLVE_MAX_TOOL_ROUNDS` tool-calling turns, then one structured call returning
  `ResolutionDraft` {rationale, actions (SKU-specific), procedure (general SOP), kb_sources, confidence,
  needs_human_review}.
- **Guards:** `kb_sources` is filtered to titles actually retrieved (no invented citations); `needs_human_review` is
  forced on when nothing was cited or the gap is not fully explained. The prompt forbids inventing references,
  quantities or codes and tells the agent not to recompute the reconciled facts.
- **Failure:** any exception → the template resolution with `method="fallback"`, `needs_human_review=true`.

### 6.3 Roll-up and report

`summarize` builds one `RemediationPlan` per root cause from the resolutions: SKU list and totals, `steps` = the
general procedure of the highest-impact (preferably agent/KB-grounded) SKU in the group, union of `kb_sources`, and
`review_count`. The LLM report gets aggregate stats, the plans and the top 10 SKU actions; on LLM failure a templated
fallback report (including a "Highest-impact SKUs" section) is produced, so a run always completes.

Prompts: `app/core/prompts/inventory_classify.md`, `inventory_resolve.md`, `inventory_summary.md`.
All LLM calls go through `llm_service` with the Langfuse callback in the run config.

## 7. Persistence and API

Tables (migration `a7c41e9d2b30`):

- `inventory_investigation`: id, user_id, as_of_date, locations (JSONB), status
  (`pending|running|completed|failed`), total_gaps, truncated, report, remediations (JSONB), error, created_at,
  completed_at.
- `inventory_sku_finding`: investigation_id (FK, cascade), sku, sloc, gap, root_cause, explained, payload (JSONB —
  full `SkuFinding` incl. history, discrepancies and its `resolution`).

Endpoints (`app/api/v1/inventory.py`, JWT auth, rate limited, owner-only visibility):

| Route                                                  | Purpose                                               |
|--------------------------------------------------------|-------------------------------------------------------|
| `POST /api/v1/inventory/investigations` `{date, locations?}` | start a run, returns 202 + id (future dates → 422) |
| `GET /api/v1/inventory/investigations?limit=`          | recent investigations                                 |
| `GET /api/v1/inventory/investigations/{id}?root_cause=`| status, report, remediation plans, findings           |
| `GET /api/v1/inventory/investigations/{id}/skus/{sku}` | one SKU's findings (with resolution) across slocs     |

Runs execute as background asyncio tasks inside the API process (strong references kept so they aren't GC'd).

## 8. Failure handling

| Failure                                   | Behaviour                                                        |
|-------------------------------------------|------------------------------------------------------------------|
| One sloc's gap list fails                 | recorded as an `error` finding; other slocs continue             |
| One SKU's DoD / reconciliation fails      | that SKU → `root_cause=error` with message; batch continues      |
| Upstream 5xx / 429 / network              | retried 3× with backoff, then treated as above                   |
| Envelope `code ≠ 1` or contract mismatch  | `InventoryApiError`, not retried, not cached                     |
| LLM classify fails                        | SKU stays `unexplained`                                          |
| KB search fails                           | agent told search failed; continues, resolution flagged for review |
| Resolver agent fails                      | template resolution, `method=fallback`, flagged for review       |
| Summary LLM fails                         | templated fallback report                                        |
| Whole graph raises                        | investigation `status=failed` with error                         |

## 9. Observability

- structlog events (`inventory_api_fetched`, `inventory_investigation_completed`, …).
- Prometheus: `inventory_skus_investigated_total{root_cause,explained}`,
  `inventory_sku_investigation_seconds`, `inventory_sku_resolutions_total{method,needs_review}`.
- Langfuse trace per run (session id = investigation id); LLM spans are classify, resolver turns and summary.

## 10. Testing

- `tests/test_inventory_analysis.py`: origin detection, no gap, truncation, duplicate/future points, string parsing,
  sign of each discrepancy kind, adjustment cancellation, classify outcomes.
- `tests/test_inventory_agent.py` (stub LLM, RAG and cache):
  - full run: triage split, one agent per non-simple SKU (2 turns each), citations filtered to retrieved titles,
    duplicate KB queries served from cache, one plan per root cause, fallback report;
  - resolver failure → fallback resolutions flagged for review;
  - `INVENTORY_TEMPLATE_MAX_DISCREPANCIES=0` → every SKU goes to the agent;
  - location filter with an unknown sloc.
- Mock run: 96 SKU/sloc findings; every gap with transaction differences reconciles exactly to `netGap`;
  69 template / 27 agent.

## 11. Assumptions to validate on real data

1. Both systems use signed quantities with the same convention (supported by `a.qty - b.qty` in the SQL); otherwise
   set `qty_multiplier: -1` on the affected endpoints.
2. `netGap` from `scrReportGap` is `NERP − Synapse`.
3. Report snapshots may lag postings by up to `INVENTORY_RECON_PADDING_DAYS`.
4. Matching adjustments on both sides within 1 day are intentional corrections.

## 12. Not yet done / next steps

- Verify against the live EcomToolBox server (`INVENTORY_API_MODE=http`) and a real LLM key.
- Run `make migrate`; exercise the HTTP routes via `make dev`.
- Ingest SCR remediation SOPs into the RAG knowledge base so plans are grounded.
- Eval metric `evals/metrics/prompts/remediation_grounding.md` (do resolutions cite the KB and only use input facts?).
- Optional extra resolver tools (re-fetch transactions, order/ASN status) if KB-only resolutions prove insufficient.
- Chat tool so users can ask follow-ups about a finished investigation.
- If runs outgrow the API process, move execution to a worker queue.
