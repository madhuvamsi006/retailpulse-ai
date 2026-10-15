# Groundswell

**Agentic Commerce Intelligence Platform** — a hackathon prototype.

Two sides, one loop:

- **Buyer side** — agents discover products under hard constraints and transact under
  cryptographic authorization
- **Seller side** — agents read demand signals the industry's batch forecasts cannot see,
  and propose replenishment a human approves

> **Agents propose. Deterministic code disposes.**
>
> A closed loop: understand customer intent → recommend only *viable* products → detect
> inventory risk → propose corrective action → enforce cryptographic authorization before
> any money or stock moves. The LLM never touches the database and never approves a payment.

## The four demo acts

| Act | What it shows |
|---|---|
| **1. Discovery** | Constraint-aware search — budget and stock are hard filters applied in code, not suggestions to a model |
| **2. Two rejections** | A prompt injection blocked by Model Armor at ingress, then a tampered cart **rejected live** by the AP2 validator |
| **3. Signals** | A trend breaks → dashboard lights up unprompted → **baseline forecast 31 units vs. fused 142, −$25,200 on one SKU** |
| **4. Replenishment** | Agent drafts a PO with visible reasoning; a human approves; audit row lands in BigQuery |

## Stack

| Layer | Technology |
|---|---|
| Agents | Gemini 3.1 on Vertex AI · **ADK 2.0 Workflow Runtime** · A2A · MCP · AP2 |
| Security | **Model Armor** (ingress + egress) · internal-only Cloud Run ingress · MCP chokepoint |
| Evaluation | **`adk eval`** · 4 golden EvalSets · trajectory + constraint + adversarial scoring |
| Data | BigQuery (analytics, vector search, ARIMA_PLUS, social signals) · Firestore (operational) |
| Infra | Cloud Run · Pub/Sub |
| Frontend | React + Vite + FastAPI (SSE agent traces) |

## Docs

| File | Purpose |
|---|---|
| [BUILD_PLAN.md](./BUILD_PLAN.md) | Full 5-day plan, demo script, architecture, triage ladder |
| [CHECKLIST.md](./CHECKLIST.md) | Goal-by-goal checklist with binary done-tests |
| [SPECIFICATION.md](./SPECIFICATION.md) | **Full technical spec** — platform alignment, security, evaluation, demo narrative, deck + video outlines |
| [SOCIAL_SIGNALS.md](./SOCIAL_SIGNALS.md) | The differentiator — signal → SKU → capped fusion → the $ delta |
| [PERMISSIONS.md](./PERMISSIONS.md) | GCP access audit, blockers, workarounds |

## Status

🚧 Day 0 — setup. See [CHECKLIST.md](./CHECKLIST.md).

## Note

Payment execution is **simulated**. AP2 is an authorization protocol, not a payment processor.
What is real here is mandate signing, validation, and rejection.

The social corpus is **synthetic**. What is real is the extraction — Gemini reading raw
unstructured post text into a structured demand signal — and the deterministic, capped fusion
that turns it into a forecast.
