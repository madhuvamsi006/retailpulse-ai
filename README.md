# RetailPulse AI

**Agentic Commerce Intelligence Platform** — a hackathon prototype.

> **Agents propose. Deterministic code disposes.**
>
> A closed loop: understand customer intent → recommend only *viable* products → detect
> inventory risk → propose corrective action → enforce cryptographic authorization before
> any money or stock moves. The LLM never touches the database and never approves a payment.

## The four demo acts

| Act | What it shows |
|---|---|
| **1. Discovery** | Constraint-aware search — budget and stock are hard filters applied in code, not suggestions to a model |
| **2. Authorization** | AP2 mandates signed with Ed25519 → then a tampered cart is **rejected live** |
| **3. Risk** | Dashboard lights up unprompted — forecast stockout with revenue at risk |
| **4. Replenishment** | Agent drafts a PO with visible reasoning; a human approves; audit row lands in BigQuery |

## Stack

| Layer | Technology |
|---|---|
| Agents | Gemini on Vertex AI · ADK · A2A · MCP · AP2 |
| Data | BigQuery (analytics, vector search, ARIMA_PLUS) · Firestore (operational) |
| Infra | Cloud Run · Pub/Sub |
| Frontend | React + Vite + FastAPI (SSE agent traces) |

## Docs

| File | Purpose |
|---|---|
| [BUILD_PLAN.md](./BUILD_PLAN.md) | Full 5-day plan, demo script, architecture, triage ladder |
| [CHECKLIST.md](./CHECKLIST.md) | Goal-by-goal checklist with binary done-tests |
| [PERMISSIONS.md](./PERMISSIONS.md) | GCP access audit, blockers, workarounds |

## Status

🚧 Day 0 — setup. See [CHECKLIST.md](./CHECKLIST.md).

## Note

Payment execution is **simulated**. AP2 is an authorization protocol, not a payment processor.
What is real here is mandate signing, validation, and rejection.
