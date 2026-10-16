# Groundswell — Technical Specification v2.0

**Version 2.0 · 2026-10-16 · Google Cloud Hackathon Submission**

> **Governing thesis:** Agents propose. Deterministic code disposes.

---

## 1. What Groundswell Is

A **two-sided agentic commerce platform** for multi-retailer, multi-warehouse footwear retail.

| Side | Agents do | Agents are never allowed to |
|---|---|---|
| **Shopper** | Discover products, build cart, authorize via AP2 | Set prices · approve payments · write SQL |
| **Retailer/Manager** | Read demand signals, fuse forecasts, draft POs, analyze sales | Approve POs · modify prices · submit to suppliers |

---

## 2. Real Retail Data Model

### Why this matters

Most hackathon demos model retail as: `products → sales → stores`. Real retail is:

```
Retailer (brand/chain)
  └── Warehouses (regional distribution centers)
        └── Stores (retail locations served by nearest warehouse)
              └── Store Inventory (what's on the shelf)
        └── Warehouse Inventory (what's in the DC)
  └── Purchase Orders (from supplier → warehouse)
  └── Replenishment Orders (from warehouse → store)
```

A **stockout at a store** doesn't always mean reorder from supplier. First check: does the nearest warehouse have stock? If yes → warehouse-to-store replenishment (days). If no → reorder from supplier (weeks).

### Entity hierarchy

```
Retailer
├── Warehouse A (Midwest DC)        ← serves STR-01 through STR-06
│     ├── Warehouse Inventory        ← on_hand, reserved, safety_stock
│     └── Inbound POs from Suppliers
├── Warehouse B (West DC)           ← serves STR-07 through STR-12
│     └── ...
└── Stores (12 total, 6 per region)
      ├── Store Inventory            ← on_hand per SKU per store
      └── Replenishment Orders       ← warehouse → store transfers
```

### BigQuery schema

| Table | Key columns | Purpose |
|---|---|---|
| `retailers` | retailer_id, name, type | Brand/chain identity |
| `warehouses` | warehouse_id, retailer_id, region, capacity_units | Distribution centers |
| `stores` | store_id, retailer_id, warehouse_id, region | Physical retail locations |
| `products` | sku, retailer_id, category, price, unit_cost, embedding | Catalog with vectors |
| `variants` | variant_id, sku, size, width, color | Size/color matrix |
| `warehouse_inventory` | warehouse_id, sku, on_hand, reserved, safety_stock | DC stock |
| `store_inventory` | store_id, sku, on_hand, reserved | Shelf stock |
| `sales` | store_id, sku, sale_date, units, revenue | 18mo history |
| `social_signals` | platform, post_text, sku, engagement_score | Raw posts |
| `suppliers` | supplier_id, lead_time_days, moq, reliability | Vendor data |
| `purchase_orders` | warehouse_id, sku, qty, status | Supplier → warehouse |
| `replenishment_orders` | warehouse_id, store_id, sku, qty, status | DC → store transfers |
| `stockout_forecast` | sku, store_id, horizon_days, forecast_value | ARIMA_PLUS output |
| `fused_forecast` | sku, baseline_units, fused_units, surge_multiplier | Signal-enhanced |
| `agent_audit` | agent, tool, decision, latency_ms | Full observability |

### Firestore collections

| Collection | Purpose |
|---|---|
| `sessions/` | Shopper session context (ECF layer) |
| `carts/` | Active carts with line items |
| `mandates/` | AP2 intent + cart mandates |
| `warehouse_inventory/` | Real-time DC stock (transactional) |
| `store_inventory/` | Real-time store stock (transactional) |
| `purchase_orders/` | PO lifecycle (pending → approved → submitted) |
| `replenishment_orders/` | DC → store transfer lifecycle |

---

## 3. Platform Alignment

| Gemini Enterprise Agent Platform | Groundswell | Status |
|---|---|---|
| **ADK 2.0 Workflow Runtime** | 6 agents + 3 deterministic nodes | 🟢 |
| **A2A Orchestration** | Inventory Agent as separate Cloud Run service | 🟢 |
| **MCP (15 tools)** | All data access — commerce + analytics + warehouse | 🟢 |
| **AP2 Authorization** | Ed25519 mandates, 7 reason codes | 🟢 |
| **Model Armor** | Ingress + egress on /chat | 🟢 |
| **Agent Evaluation** | 85 golden cases, 5 suites, trajectory scoring | 🟢 |
| **Agent Observability** | Live SSE trace panel + BigQuery audit | 🟢 |
| **Gemini 2.0 Flash** | All LLM agents via Vertex AI | 🟢 |
| **BigQuery + ARIMA_PLUS** | 18mo sales, vector search, forecasting | 🟢 |
| **Cloud Run ingress controls** | Internal-only for MCP + A2A | 🟢 |
| **Enterprise Context Fabric** | Real-time context injection per request | 🟢 |
| **Enterprise Knowledge Fabric** | Product graph, entity resolver, patterns | 🟢 |
| **Agent Identity** | Process-enforced isolation (no DB client in agents) | 🔵 |
| **Agent Gateway** | MCP server as single policy chokepoint | 🔵 |
| **Agent Sessions** | Firestore sessions/ collection | 🔵 |
| **Agent Registry** | Version-controlled manifests | ⚪ |

---

## 4. Architecture

```
Shopper/Manager ──HTTPS──► gs-api (public Cloud Run)
                                │
                    ┌───────────▼───────────┐
                    │   MODEL ARMOR ingress  │ ← rejection #1
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  ECF: Context Fabric   │ ← session + inventory + signals
                    │  EKF: Knowledge Fabric │ ← entity resolve + product graph
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────────────────────────┐
                    │     ADK 2.0 Workflow Runtime               │
                    │                                            │
                    │  orchestrator ──┬── discovery_agent        │
                    │                 ├── signal_agent           │
                    │                 ├── commerce_agent         │
                    │                 ├── merchandising_agent    │
                    │                 └── analyst_agent          │
                    │                                            │
                    │  ░ deterministic nodes ░                   │
                    │  • ap2.validator          (no LLM)         │ ← rejection #2
                    │  • fusion.surge_multiplier (no LLM)        │
                    │  • ranking.constraint_filter (no LLM)      │
                    └──────┬───────────────────┬────────────────┘
                           │ A2A               │ MCP (only data path)
                           ▼                   ▼
              gs-inventory-a2a          gs-mcp (15 tools)
              (internal only)           (internal only)
                                              │
                         ┌────────────────────┼──────────────────┐
                         ▼                    ▼                  ▼
                    BigQuery              Firestore         Vertex AI
                    (catalog,sales        (inventory,       (Gemini 2.0,
                     signals,audit)        carts,mandates,   embeddings)
                                          POs,transfers)
```

---

## 5. Agent Roster

| Agent | Type | Tools | Never does |
|---|---|---|---|
| `orchestrator` | LLM | delegates only | touch DB |
| `discovery_agent` | LLM | search_products, forecast_stockout | set prices |
| `signal_agent` | LLM | get_social_signals → extract struct | approve POs |
| `commerce_agent` | LLM | create_cart (re-reads prices) | set prices |
| `merchandising_agent` | LLM | request_replenishment (draft only) | approve POs |
| `analyst_agent` | LLM | 6 analytics tools (read-only) | modify data |
| `ap2.validator` | **function** | — | call LLM |
| `fusion.surge_multiplier` | **function** | — | call LLM |
| `ranking.constraint_filter` | **function** | — | call LLM |

---

## 6. Security

### Model Armor
- Ingress: `sanitizeUserPrompt` before orchestrator sees the message
- Egress: `sanitizeModelResponse` before browser sees the answer
- Catches: prompt injection, PII (card numbers), jailbreaks, malicious URLs
- Known limit: 512 token window on injection filter — stated proactively

### AP2 Authorization
- Shopper signs **Intent Mandate**: budget_max, categories, expiry (Ed25519)
- Merchant signs **Cart Mandate**: exact line items, prices from catalog
- Validator checks: hash match, signature, price drift <1%, budget, qty, expiry
- 7 deterministic reject codes — zero model calls

### The two-rejection demo
| # | Attack | Control | Result |
|---|---|---|---|
| 1 | Prompt injection in chat | Model Armor | `BLOCKED — PROMPT_INJECTION_DETECTED` |
| 2 | Cart qty tampered after signing | AP2 validator | `REJECTED — CART_HASH_MISMATCH` |

---

## 7. Forecast Demo

| | Baseline ARIMA | Groundswell Fused |
|---|---|---|
| 7-day forecast | **31 units** | **142 units** |
| Reorder | 40 | 160 |
| Days until stockout | 4 | — (demand captured) |
| Revenue impact | **−$25,200** | **$0** |

The fused forecast uses a **capped 4× surge multiplier** applied to the ARIMA baseline.
Cap is deliberate — one viral video should not justify a 10× PO. Confidence-floored at 0.55.

---

## 8. Evaluation

85 golden cases across 5 suites:

| Suite | Cases | Pass criterion |
|---|---|---|
| Discovery trajectory | 20 | Tool trajectory ≥ 0.85 |
| Signal extraction | 15 | Negative cases must NOT fire (zero false surges) |
| Commerce / AP2 | 10 | Price always re-read from catalog |
| Adversarial | 25 | Zero successful bypasses |
| Analyst | 15 | Read-only enforced; data cited in every answer |

---

## 9. Warehouse + Replenishment Flow

When a manager sees a demand signal:

```
Signal detected (e.g. Pegasus 41 viral)
        │
        ▼
analyst_agent: "Do we have DC stock?"
        │
   ┌────▼────┐         ┌─────────────────────┐
   │ DC has  │──YES──► │ Draft replenishment  │
   │ stock?  │         │ order: DC → Store    │
   └────┬────┘         │ (days, not weeks)    │
        │NO            └─────────────────────┘
        ▼
merchandising_agent: Draft PO to supplier
        │ (requires manager Approve)
        ▼
PO: Supplier → Warehouse → Store
    (weeks)     (days)
```

This two-tier replenishment is a real operational advantage. A typical retailer treats every stockout as a supplier reorder. Groundswell checks DC stock first — reducing reorder lead time from 7 days to 1 day in many cases.

---

## 10. Honest Limitations

| Item | Reality |
|---|---|
| Social corpus | Synthetic (6 seeded posts). Gemini extraction and fusion math are real. |
| AP2 settlement | Sandbox — no real payment processor. Signing and rejection are real. |
| Agent Identity | Process-enforced isolation (grep proof available live). Not IAM-enforced. |
| Agent Gateway | MCP server is our single chokepoint. Not the managed platform service. |
| Model Armor | 512 token injection filter. We screen the user turn, not full history. |
| ML.GENERATE_EMBEDDING | Not available (IAM). We pre-generate embeddings via Vertex REST and store in BQ. |

---

## 11. What We Claim vs What We Ship

### 🟢 Fully built and demonstrated
- ADK 2.0 agents with deterministic nodes
- MCP server (15 tools, parameterized SQL, single data path)
- A2A inventory agent (separate Cloud Run, `/.well-known/agent.json`)
- AP2 validator (Ed25519, 7 reason codes, 100% unit tested)
- Model Armor ingress + egress
- ECF + EKF context and knowledge injection
- Manager Analyst Agent (6 analytics tools, conversational)
- Live SSE trace panel
- 85 golden eval cases

### 🔵 Same control, different implementation
- Agent Identity → process isolation, no DB client in agent runtimes
- Agent Gateway → MCP server as single policy-enforcing chokepoint
- Agent Sessions → Firestore `sessions/` collection

### ⚪ Architecture only (roadmap slide)
- Agent Registry
- Agent Simulation / Optimizer
- Threat / Anomaly Detection
