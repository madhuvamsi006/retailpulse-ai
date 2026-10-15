# Groundswell — 5-Day Solo Build Plan

**Constraints:** solo dev · 3–5 days · full GCP project + billing · React + FastAPI frontend

---

## 0. The one idea judges must leave with

> **Agents propose. Deterministic code disposes.**
>
> Groundswell runs a closed loop — understand intent → recommend only *viable* products → detect inventory risk → propose corrective action → enforce cryptographic authorization before any money or stock moves. The LLM never touches the database and never approves a payment.

Every build decision below is scored against whether it makes that sentence demonstrable on screen in four minutes.

---

## 1. Write the demo first, build backward

The demo script **is** the spec. Nothing gets built that doesn't appear here.

### The 4-minute run of show

**Act 1 — Constraint-aware discovery (60s)**

> Customer: *"I need running shoes for a marathon in 3 weeks, under $150, size 10, and I have wide feet."*

- Orchestrator decomposes → delegates in parallel
- Discovery Agent: BigQuery `VECTOR_SEARCH` over product embeddings (semantic: "marathon" → long-distance cushioned road shoes, not trail)
- Inventory Agent: called **over A2A** across a service boundary → live stock for size 10 / 2E width
- UI returns **3 options**, each with a *why*: matched attributes, price headroom, stock status
- One option is visibly flagged: **"Only 2 left at Store 04 — 68% chance of stockout before your race"**

🎯 *Judge takeaway:* the budget and size filters are hard constraints applied in code, not politely suggested to a model.

**Act 2 — AP2 authorization, including a live rejection (90s) ← the money shot**

- Customer picks a shoe. Commerce Agent builds a cart with **prices re-verified at cart time** (not model-recalled)
- Customer signs an **Intent Mandate**: *"up to $160, running shoes, expires in 15 minutes"* — Ed25519, in the browser
- Merchant signs a **Cart Mandate** over the exact line items
- Press **Authorize** → deterministic validator runs → sandbox payment → receipt
- **Then press the red `Tamper` button.** It mutates cart quantity 1 → 10 *after* signing.
- Press Authorize again → **`REJECTED: CART_HASH_MISMATCH`** in red, with the mandate diff shown side by side.

🎯 *Judge takeaway:* this is a real authorization protocol with real failure modes, not a "Buy now" dialog with an LLM behind it.

**Act 3 — A trend breaks and the loop closes on its own (90s) ← the differentiator**

See [SOCIAL_SIGNALS.md](./SOCIAL_SIGNALS.md) for the full design.

- Overnight, the signal ingester pulls the last 24h of social posts. **Nobody asks it anything.**
- Signal Agent (Gemini) reads **raw post text** → structured signal: entity, momentum, geo, confidence
- SKU Mapper (code, reusing the Day 0 embeddings) resolves *"those grey cushioned runners"* → Pegasus 41
- Deterministic fusion applies a **capped** surge multiplier to the ARIMA_PLUS baseline
- **Switch to the Manager dashboard — it has already lit up:**
  > ⚠️ *Nike Pegasus 41, size 10 / 2E, Store 04 — demand surge detected. Baseline forecast 31 units; fused forecast **142**. Projected stockout in 4 days. Confidence 0.81, surge 2.4x (capped at 4x), corroborated across 2 sources.*

**Then the money shot — split the panel:**

| | Baseline (what every retailer runs today) | Groundswell |
|---|---|---|
| 7-day forecast | 31 units | **142 units** |
| Reorder | 40 | **160** |
| Outcome | Stockout day 4 | Demand captured |
| **Revenue impact** | **−$25,200** | **$0** |

> *"One SKU. One week. $25,200. There are 1,200 variants in this catalog."*

🎯 *Judge takeaway:* nobody asked a question, and the gap between the industry-standard forecast
and ours is shown **in dollars**, not asserted on a slide.

**Act 4 — Agentic replenishment under human authority (45s)**

- Merchandising Agent drafts a PO: **40 units** — reasoning shown: forecast demand 31, supplier lead time 7d, MOQ 24, unit cost $62, within $3k category budget
- Manager clicks **Approve** → AP2-governed approval → PO submitted → **audit row lands in BigQuery live on screen**
- Open the audit trail: every agent, every tool call, every authorization decision, every confidence score, timestamped

🎯 *Judge takeaway:* closed loop, with a human holding the pen on spend.

### Three "we're not faking it" proofs — keep these loaded for Q&A

1. **Tamper → reject**, live (Act 2)
2. **`SELECT` the service account's IAM** — the agent runtime has *zero* direct BigQuery/Firestore write grants. All writes route through MCP tools.
3. **Audit table filling in real time** during the demo — not pre-seeded

---

## 2. Scope: what's in, what's cut, and why

Ruthless cuts are the difference between a demo and an apology.

### ✅ IN

| Component | Why it survives |
|---|---|
| ADK orchestrator + 4 sub-agents | The core story |
| MCP server, 9 tools | Only path to data — this *is* the governance claim |
| A2A for **Inventory Agent only** | One honest cross-service hop beats four fake ones |
| AP2 mandates, Ed25519, real validator | The money shot. Highest value per hour on the board |
| BigQuery `VECTOR_SEARCH` | One SQL statement, carries the semantic-search claim |
| BigQuery ML `ARIMA_PLUS` | One SQL statement, carries the whole forecasting claim |
| Pub/Sub → Cloud Run, **one event type** | Makes "event-driven" true instead of aspirational |
| Firestore transactions for stock reservation | Atomic reservations without a fourth datastore |
| React agent-trace panel (SSE) | Makes invisible multi-agent work *visible*. Do not cut this. |
| **Social demand signals → fused forecast** | The $300B claim. Baseline ARIMA is what everyone already runs; the fused contrast is the pitch. See SOCIAL_SIGNALS.md |

### ❌ CUT — and defend the cut if asked

| Cut | Reason |
|---|---|
| **Cloud SQL** | Firestore transactions give you atomic reserve-stock. A fourth datastore is a day you don't have. *If asked:* "Firestore transactions are ACID within a document set; Cloud SQL is the right call at real order volume and it's a swap behind the `create_cart` tool." |
| **UCP** | Too new, and AP2 already carries the commerce-authorization narrative. A second protocol logo adds zero demo seconds. |
| **Cross-store transfer optimization (idea C)** | Looks great in a doc, costs a day in routing/cost modeling. Ship a *read-only* "also available at Store 07, 2.3km" badge — 30 minutes, 80% of the perceived value. |
| **Multiple event types** | One event type (signal ingest → risk recompute) proves the architecture. Five prove nothing extra. |
| **Live TikTok / Reddit / X APIs** | Keys, approval queues, quotas, and corporate TLS interception. The *corpus* is seeded; the *extraction and fusion* are real. Say so out loud — see SOCIAL_SIGNALS.md §3. |
| **Real payment provider** | Sandbox only, and **say so out loud in the demo.** Judges respect the disclosure and penalize the discovery. |
| **Auth / multi-tenancy / user accounts** | Hardcode two personas: `customer_demo` and `manager_demo`. |

---

## 3. Repository layout

```
groundswell/
├── infra/
│   ├── setup.sh                 # one-shot: enable APIs, create dataset, SA, topics
│   ├── bigquery/
│   │   ├── 01_schema.sql
│   │   ├── 02_embeddings.sql    # ML.GENERATE_EMBEDDING over products
│   │   ├── 03_forecast.sql      # ARIMA_PLUS model + forecast table
│   │   └── 04_views.sql         # sales_velocity, sales_at_risk
│   └── seed/
│       ├── generate.py          # synthetic catalog + 18mo sales history
│       └── load.py
├── mcp_server/
│   ├── server.py                # FastMCP, 9 tools, all SQL parameterized
│   ├── tools/
│   │   ├── discovery.py         # search_products, find_alternatives
│   │   ├── inventory.py         # check_inventory, get_sales_velocity, forecast_stockout
│   │   ├── commerce.py          # create_cart, authorize_checkout
│   │   ├── replenish.py         # request_replenishment
│   │   └── audit.py             # get_agent_audit
│   └── guards.py                # input validation, rate limits, audit emit
├── agents/
│   ├── orchestrator.py          # ADK root agent, plans + delegates + verifies
│   ├── discovery_agent.py
│   ├── commerce_agent.py
│   ├── merchandising_agent.py
│   └── inventory_a2a/           # ← separate Cloud Run service
│       ├── main.py              # A2A JSON-RPC server
│       └── agent_card.json      # /.well-known/agent.json
├── ap2/
│   ├── mandates.py              # IntentMandate, CartMandate dataclasses
│   ├── signing.py               # Ed25519 keygen / sign / verify
│   └── validator.py             # ← pure deterministic. ZERO LLM calls. Heavily tested.
├── events/
│   └── consumer/main.py         # Cloud Run, Pub/Sub push → risk recompute
├── api/
│   ├── main.py                  # FastAPI: /chat (SSE), /cart, /authorize, /manager/*
│   └── schemas.py               # ← write these FIRST, day 1, before any UI or agent code
├── web/
│   ├── src/
│   │   ├── CustomerView.tsx
│   │   ├── ManagerView.tsx
│   │   ├── AgentTrace.tsx       # the SSE trace panel — highest-value component
│   │   └── mocks/responses.json # ← unblocks UI on day 1
│   └── vite.config.ts
└── demo/
    ├── script.md                # the 4 minutes, rehearsed
    └── reset.py                 # one command back to clean demo state
```

**The single most important file is `api/schemas.py`.** Freeze the request/response contracts on Day 1 morning. Everything else — React, agents, MCP — develops independently against those shapes. Solo devs lose days to interface churn; this is the fix.

---

## 4. Data model

### BigQuery — dataset `groundswell` (analytical)

| Table | Key columns |
|---|---|
| `products` | `product_id, name, brand, category, description, attributes JSON, price, image_url, embedding ARRAY<FLOAT64>` |
| `variants` | `variant_id, product_id, size, width, color` |
| `stores` | `store_id, name, lat, lng, region` |
| `sales` | `sale_id, variant_id, store_id, ts, qty, unit_price` — **18 months of history** |
| `suppliers` | `supplier_id, name, lead_time_days, moq, unit_cost, product_ids ARRAY<STRING>` |
| `agent_audit` | `event_id, ts, session_id, agent, tool, input_hash, output_summary, decision, confidence, latency_ms` |
| `stockout_forecast` | materialized from ARIMA_PLUS: `variant_id, store_id, forecast_date, predicted_qty, ci_low, ci_high` |

**Seed realism matters more than seed volume.** Bake in: a weekend sales spike, one genuinely slow mover, one product about to stock out in exactly 4 days, and a size-curve (sizes 9–10 sell 3× faster than 7 or 13). Judges notice flat random data instantly.

### Firestore (operational)

| Collection | Shape |
|---|---|
| `inventory/{store_id}_{variant_id}` | `on_hand, reserved, updated_at` |
| `sessions/{session_id}` | `preferences, history` |
| `carts/{cart_id}` | line items with **locked** prices, `expires_at`, `state` |
| `mandates/{mandate_id}` | AP2 mandate + signature |
| `purchase_orders/{po_id}` | draft POs awaiting approval |

Stock reservation runs inside a Firestore transaction: read `on_hand - reserved`, verify, increment `reserved`. Atomic, no Cloud SQL needed.

---

## 5. The MCP toolbox

Nine tools. Four are demo-critical (marked ⭐). Every one: parameterized SQL, input validation, audit emit, least-privilege service account.

| Tool | Signature | Access |
|---|---|---|
| ⭐ `search_products` | `(query, budget_max, size, width, category) → ranked[]` | read |
| ⭐ `check_inventory` | `(variant_ids[], store_id, radius_km) → availability[]` | read |
| `get_sales_velocity` | `(variant_id, store_id, window_days) → units_per_day` | read |
| ⭐ `forecast_stockout` | `(variant_id, store_id) → {date, confidence, units_at_risk, revenue_at_risk}` | read |
| `find_alternatives` | `(variant_id, constraints) → substitutes[]` | read |
| ⭐ `create_cart` | `(session_id, items[]) → cart with verified prices` | **write, validated** |
| `request_replenishment` | `(variant_id, qty, supplier_id) → draft PO` | **write, approval required** |
| `authorize_checkout` | `(cart_id, intent_mandate, cart_mandate) → receipt \| rejection` | **restricted** |
| `get_agent_audit` | `(session_id, limit) → audit[]` | read, restricted |

**Hard rule:** the LLM never emits SQL. Ranking in `search_products` is hybrid — BigQuery `VECTOR_SEARCH` for semantic relevance, then a **deterministic Python scorer** applies budget, size, stock, and delivery constraints. Budget and availability are filters, not suggestions the model can talk itself out of.

---

## 6. AP2 implementation

Structurally faithful, scoped to a sandbox. Two mandates, Ed25519-signed:

```python
IntentMandate  = {user_id, constraints: {max_amount, currency, categories, expires_at}, nonce, signature}
CartMandate    = {cart_id, items: [{sku, qty, unit_price}], total, merchant_id, cart_hash, expires_at, signature}
```

`ap2/validator.py` is **pure deterministic code with zero LLM involvement.** It checks, in order, returning a specific reason code on first failure:

1. `SIG_INVALID` — Ed25519 verification on both mandates
2. `MANDATE_EXPIRED` — either mandate past `expires_at`
3. `CART_HASH_MISMATCH` — recompute hash over line items; must match the signed value ← **the tamper demo**
4. `PRICE_DRIFT` — every `unit_price` re-checked against live catalog
5. `BUDGET_EXCEEDED` — `cart.total > intent.max_amount`
6. `CATEGORY_NOT_PERMITTED` — items outside the intent's allowed categories
7. `NONCE_REPLAY` — nonce already consumed

Write this module **test-first**. It is the highest-stakes 150 lines in the project and the one thing that must not fail live. Seven tests, one per reason code, plus a happy path.

> **Say this out loud during the demo:** *"Payment execution is simulated — AP2 is an authorization protocol, not a payment processor. What's real here is the mandate signing, the validation, and the rejection."*

---

## 7. Day-by-day

Estimates assume ~10 focused hours/day. Each day ends at a **hard checkpoint** — if you miss it, take the triage branch.

### Day 0 — Evening prep (2h)
- [ ] `gcloud` project set, billing confirmed, APIs enabled: Vertex AI, BigQuery, Firestore, Cloud Run, Pub/Sub, Cloud Build
- [ ] Service accounts created with **least privilege** — the agent runtime SA gets **no** direct BQ/Firestore write roles *(this is Proof #2; set it up correctly now so the claim is true)*
- [ ] `pip install google-adk google-cloud-bigquery google-cloud-firestore mcp cryptography fastapi`
- [ ] `npm create vite@latest web -- --template react-ts`, add Tailwind
- [ ] Hello-world deploy to Cloud Run — **prove the deploy pipeline today**, not at 2am on Day 4

### Day 1 — Foundation and contracts (10h)

| Hours | Work |
|---|---|
| 1h | ⚠️ **`api/schemas.py` first.** Freeze every request/response shape. Generate `mocks/responses.json` from it. |
| 3h | `infra/seed/generate.py` — synthetic catalog (~200 products, ~1200 variants, 6 stores) + 18mo sales with the planted patterns. Load to BigQuery. |
| 2h | `02_embeddings.sql` — `ML.GENERATE_EMBEDDING` over product descriptions; verify `VECTOR_SEARCH` returns sane results for "marathon shoes" |
| 2h | MCP server skeleton + the 4 read tools (`search_products`, `check_inventory`, `get_sales_velocity`, `find_alternatives`) |
| 2h | React shell against **mocks only** — three routes, layout, Tailwind theme. No backend calls yet. |

> **✅ Checkpoint 1:** `search_products("marathon shoes under $150")` returns ranked, constraint-filtered results from the CLI. React renders the mock customer view.
> **🔻 Behind?** Shrink the catalog to 60 products. Keyword search now, embeddings on Day 3.

### Day 2 — Agents and the A2A hop (10h)

| Hours | Work |
|---|---|
| 3h | ADK orchestrator + Discovery Agent. Intent extraction → structured constraints → MCP calls. Get one end-to-end conversational turn working. |
| 3h | **Inventory Agent as a separate Cloud Run service** — A2A JSON-RPC server, `/.well-known/agent.json` agent card. Orchestrator discovers and calls it over the wire. |
| 2h | FastAPI `/chat` with **SSE streaming of agent traces** — every delegation, tool call, and result streams to the client |
| 2h | Wire React to the real API. Build `AgentTrace.tsx`. |

> **✅ Checkpoint 2:** Typing the Act 1 query in the browser returns real results, and the trace panel shows the orchestrator delegating to Discovery and calling Inventory **across a network boundary**.
> **🔻 Behind?** Run the Inventory Agent A2A server on localhost instead of Cloud Run. Still a genuine cross-process A2A call; deploy it Day 4.

### Day 3 — AP2 and intelligence (10h)

| Hours | Work |
|---|---|
| 1h | `ap2/validator.py` **test-first** — 7 reason codes + happy path |
| 2h | `ap2/signing.py` + mandate dataclasses + `create_cart` with price verification + Firestore reservation transaction |
| 2h | `authorize_checkout` end to end, plus the **`Tamper` button** and the rejection UI with mandate diff |
| 2h | `03_forecast.sql` — `ARIMA_PLUS` model, forecast table, `forecast_stockout` tool with confidence + revenue-at-risk |
| 3h | Manager dashboard: risk table, forecast chart, audit trail view |

> **✅ Checkpoint 3 — the critical one:** Acts 1 and 2 run start to finish in the browser, **including the live rejection.**
> **🔻 Behind?** 🚨 **This is the Streamlit decision point.** If React is eating you alive, keep `CustomerView` in React (judges see it most) and rebuild the manager dashboard in Streamlit in 2 hours. A working Act 3 in plain Streamlit beats a half-built React dashboard. Decide here — not on Day 4.

### Day 4 — Closing the loop (10h)

| Hours | Work |
|---|---|
| 2h | Pub/Sub topic + Cloud Run push consumer: sales event → Firestore update → risk recompute → dashboard alert |
| 2h | Merchandising Agent: PO drafting with lead time, MOQ, budget constraints, **visible reasoning** |
| 2h | Manager approval flow → AP2-governed approval → `agent_audit` row visible live |
| 2h | Deploy everything to Cloud Run. Run the **full demo end to end three times.** |
| 2h | `demo/reset.py` — one command to clean state. Explainability polish: confidence scores, "insufficient data" honesty paths. |

> **✅ Checkpoint 4:** All four acts run clean, from a cold reset, deployed.

### Day 5 — Rehearsal and hardening (6h, then stop)

- [ ] **Rehearse 5+ times with a timer.** Four minutes is shorter than it sounds.
- [ ] Record a **backup video** of a clean run — the single highest-ROI hour of the week. Conference wifi has ended more hackathon runs than bugs have.
- [ ] Prep Q&A: *Why not Cloud SQL? Is the payment real? What if the LLM hallucinates a price? What's actually A2A here vs. in-process?*
- [ ] Freeze the code. **No new features after Day 5 noon.** Fix only demo-path breakage.
- [ ] Architecture diagram for the slide — one image, the closed loop

---

## 8. Triage ladder — if you're behind, cut in this order

Cut from the bottom. Never cut upward past a line you haven't reached.

1. Explainability polish (confidence badges, assumption text)
2. Cross-store availability badge
3. Merchandising Agent → replace with a pre-computed PO draft, approval flow stays real
4. Pub/Sub → **superseded.** Social-signal ingestion is the trigger now, and it needs no topic-creation permission (SOCIAL_SIGNALS.md §6). Run it on a timer or a button; the narrative gets stronger, not weaker.
5. React manager dashboard → Streamlit
6. BigQuery ML forecast → simple velocity-based linear projection *(still honest, just less sophisticated)*
7. — **hard floor** —
8. **Never cut:** AP2 tamper rejection · the A2A hop · the agent trace panel · MCP-only data access · **the baseline-vs-fused $ delta (G8.5)**

Items 1–6 are survivable losses. Items below the floor are the pitch itself.

---

## 9. Known risks

| Risk | Mitigation |
|---|---|
| **React burns the schedule (highest risk)** | Mock-first Day 1, hard Streamlit decision at Checkpoint 3. Do not let this decision slide to Day 4. |
| ADK + A2A API churn — these move fast | Pin exact versions Day 0. Budget 2h of Day 2 for docs-vs-reality gaps; this is normal, not a crisis. |
| Vertex AI quota / cold starts mid-demo | Request quota Day 0. Set Cloud Run `min-instances=1` before demo day. Warm every path in rehearsal. |
| BigQuery ML forecast is garbage on synthetic data | Plant clean weekly seasonality in the seed generator. Validate forecast output Day 3, not Day 4. |
| Live demo fails | Backup video. Non-negotiable. |
| Scope creep from the original architecture doc | The cut list in §2 is a commitment, not a suggestion. Reread it when tempted. |

---

## 10. What makes this win

Most hackathon entries in this category will be a chatbot over a product table with a Gemini call and a slide listing protocol names.

This one shows, on screen, in under four minutes:

- **A rejection.** Authorization that actually refuses a tampered cart — almost nobody demos a guardrail *working*
- **A forecast that beats the industry standard, in dollars.** Baseline vs. fused, side by side, on one SKU — the $300B problem made concrete
- **An unprompted alert.** The system reacting to data with no human in the loop
- **A visible agent trace** across a real service boundary
- **A human approving spend** with a cryptographic audit trail behind it

Not a checklist of advanced services — a closed loop where the interesting part is what the AI is *not permitted to do*.
