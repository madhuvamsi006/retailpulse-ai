# Social Demand Signals — the differentiator

**Status:** design frozen 2026-10-15 · **Goals:** G8.1–G8.5 · **Cost:** ~7h, one day

---

## 1. Why this exists

Every other entry in this category will show a chatbot and a forecast chart. The forecast will
be ARIMA over sales history — which is exactly what every retailer already runs, and exactly
what loses **$300B/yr in markdowns and stockouts**. Batch models trained on history are
structurally blind to demand that has no history yet: a video goes viral Tuesday, the shelf is
empty Thursday, the reorder lands three weeks later into dead demand.

Groundswell closes that gap. The claim is narrow and defensible:

> **Baseline forecasting answers "what did this SKU do?" We also answer "what is about to happen to it?"**

---

## 2. The pipeline

```
social_signals (BigQuery)          weather / trends (optional, real APIs)
raw post text, engagement, geo                 │
        │                                      │
        ▼                                      │
  ┌─────────────────┐                          │
  │  Signal Agent   │   Gemini on Vertex AI    │
  │  (LLM)          │   unstructured → struct  │
  └────────┬────────┘                          │
           │   {entity, category, sentiment,   │
           │    momentum, geo, horizon_days,   │
           │    confidence}                    │
           ▼                                   │
  ┌─────────────────┐                          │
  │  SKU Mapper     │   reuses Day 0           │
  │  (CODE)         │   embeddings +           │
  └────────┬────────┘   VECTOR_SEARCH          │
           │                                   │
           ▼                                   ▼
  ┌───────────────────────────────────────────────┐
  │  Fusion (CODE — deterministic, capped)        │
  │  surge = f(momentum, confidence, corroborate) │
  └────────┬──────────────────────────────────────┘
           │
           ▼
   fused_forecast = arima_baseline x surge_multiplier
           │
           ▼
  ┌─────────────────┐
  │ Merchandising   │   PO draft, visible reasoning
  │ Agent (LLM)     │
  └────────┬────────┘
           ▼
   Manager approves → AP2-governed → audit row
```

**The thesis holds:** the LLM *extracts* and *explains*. It never multiplies the final number
and never writes a PO. Fusion and the cap are deterministic Python — the same rule that governs
`ap2/validator.py`.

---

## 3. Data sourcing — tier the risk, name the limitation

| Tier | Source | Real? | Risk | Decision |
|---|---|---|---|---|
| **1** | `social_signals` BQ table — ~300 seeded posts (captions, comments, review snippets) with timestamps, engagement, geo | Synthetic corpus | **None** | ✅ **Build on this** |
| **2** | Open-Meteo weather API (free, no key) | Real | Low — corporate TLS | 🟡 Try Day 4, cheap |
| **3** | Google Trends via `pytrends` | Real | Medium — unofficial, rate-limited, TLS | 🟡 One keyword, hard timeout, cached fallback |
| **4** | Live TikTok / Reddit / X APIs | Real | **High** — keys, approval, quotas, TLS interception | ❌ **Cut. Do not attempt.** |

### Say this out loud in the demo

> *"The social corpus is synthetic — I'm not pulling live TikTok from a hackathon sandbox.
> What's real is the extraction: Gemini reads raw unstructured post text and produces a
> structured demand signal, and the fusion math is real and deterministic."*

Judges reward a named limitation and punish a discovered one. Tiers 2 and 3 exist only so you
can add *"weather and Trends are live calls"* — a true sentence worth ten seconds.

### Seeding the corpus

Plant one genuine viral event, starting **3 days before "today"**:

| Day | Posts | Shape |
|---|---|---|
| −3 | 2 | low engagement, vague wording |
| −2 | 11 | rising; one named creator, 40k likes |
| −1 | 60 | steep; engagement 10x, geo-clustered to 2 regions |
| 0 | — | still climbing |

Plus noise: ~240 unrelated posts across other categories, so the Signal Agent has to actually
discriminate. **A corpus with one obvious signal and no noise is visibly fake.**

---

## 4. Fusion math — deterministic, capped, explainable

```python
SURGE_CAP = 4.0          # never let one trend 10x an order
MIN_CONFIDENCE = 0.55    # below this, the signal is logged, not applied

def surge_multiplier(sig) -> float:
    if sig.confidence < MIN_CONFIDENCE:
        return 1.0
    raw   = 1.0 + (sig.momentum * sig.confidence)
    corr  = 1.0 + 0.25 * (sig.source_count - 1)      # corroboration across sources
    decay = max(0.0, 1.0 - (sig.days_ahead / sig.horizon_days))
    return min(SURGE_CAP, 1.0 + (raw - 1.0) * corr * decay)
```

Every term is defensible in Q&A:

- **Cap** — one video does not justify a 10x PO
- **Confidence floor** — weak signals are recorded, not acted on
- **Corroboration** — two independent sources beat one loud one
- **Decay** — surges fade; a 14-day horizon should not inflate day 13

---

## 5. 💰 The money moment — baseline vs. fused, side by side

The single highest-value screen in the build. **Split the panel.**

| | Baseline (ARIMA_PLUS only) | Groundswell (fused) |
|---|---|---|
| 7-day forecast | 31 units | **142 units** |
| Reorder qty | 40 | **160** |
| Outcome | Stockout day 4 | Demand captured |
| Lost demand | 180 units | 0 |
| **Revenue impact** | **−$25,200** | **$0** |

> **One SKU. One week. $25,200.** Then: *"There are 1,200 variants in this catalog."*

Show the **confidence score and the cap** right next to it. The honesty is the credibility.

### Why this beats a chart

You already have to build the ARIMA baseline for G5.1. The fused number costs one extra column.
The *contrast* is therefore nearly free — and it is the whole pitch: it shows the judge the gap
you close, in dollars, instead of asserting it on a slide.

---

## 6. It also solves the Pub/Sub blocker

Act 3's "unprompted alert" currently depends on **G6.1 Pub/Sub**, which is 🟡 blocked pending
admin (`PERMISSIONS.md` §2). The planned fallback was a *"Simulate weekend spike"* button —
honest, but visibly a demo crutch.

**Signal ingestion replaces it.** The trigger becomes *"ingest the last 24h of social signals"* —
a real pipeline step that genuinely recomputes risk, on a timer or a button. No topic-creation
permission required, and the narrative gets **stronger**, not weaker:

> *"A trend broke overnight. Nobody asked the system anything — it re-forecast and raised the alert."*

If the admin grants Pub/Sub later, the same consumer fires from a topic. One line changes.

---

## 7. Goals

| ☐ | ID | Goal | Done when | Hrs |
|---|---|---|---|---|
| ☐ | **G8.1** | `social_signals` seeded: ~300 posts, one planted 4-day viral ramp + noise | Querying the table shows a clean engagement ramp on one variant and nothing obvious elsewhere | 1 |
| ☐ | **G8.2** | **Signal Agent** — Gemini extracts structured signal from raw post text | Raw caption in → `{entity, category, sentiment, momentum, geo, horizon_days, confidence}` out, schema-validated | 2 |
| ☐ | **G8.3** | **SKU Mapper** — signal entity → `variant_id`s via existing embeddings | *"those grey cushioned runners"* maps to Pegasus 41, **not** the trail shoe | 1 |
| ☐ | **G8.4** | **Fusion** — deterministic, capped, writes `fused_forecast` | Unit tests: cap holds at 4x · sub-threshold confidence → 1.0 · decay reduces far-horizon | 1.5 |
| ☐ | **G8.5** | 🎯 **Baseline-vs-fused split panel with $ delta** | Both numbers on screen from live data, with confidence and cap shown | 1.5 |

**Total ≈ 7h.** Slot after G5.2, before G6.2.

---

## 8. What this displaces

Adding a day means losing a day. Pay for it here, in order:

1. **G6.1 Pub/Sub** → superseded by §6. Pure win, no loss.
2. **G6.2 Merchandising Agent reasoning** → degrade to a template-filled PO draft if needed.
   The *approval* flow (G6.3) and the audit row stay real — that is the part judges test.
3. **Cross-store availability badge** → already cut #2 on the ladder.

**Do not pay for it** out of G4.x (AP2 tamper rejection), G3.2 (A2A hop), G3.4 (trace panel),
or G2.3 (MCP-only access). Those are the non-negotiables and they stay non-negotiable.

---

## 9. Revised triage position

| Priority | Item |
|---|---|
| 🔒 **NEVER CUT** | G8.5 baseline-vs-fused $ delta — *this is the new pitch* |
| 🔒 **NEVER CUT** | G4.4 · G3.2 · G2.3 · G3.4 *(unchanged)* |
| ✂️ Cut 1st | Tier 2/3 live weather + Trends calls → seeded only |
| ✂️ Cut 2nd | G8.3 embedding SKU mapper → hardcoded signal→SKU map |
| ✂️ Cut 3rd | G8.2 Signal Agent → pre-extracted signals in the seed table |

Note the shape: you can cut **all the way down to a seeded fused forecast** and the money moment
in §5 still runs. The demo degrades gracefully to the end.
