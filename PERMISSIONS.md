# RetailPulse AI — Permissions & Access

**Audited:** 2026-10-12 · **Account:** `madhu.vamsituraka@mastechdigital.com` · **Project:** `ctoteam`

> `ctoteam` is a **busy shared corporate project** — 40+ BigQuery datasets, 25+ service accounts, 4 Firestore DBs from other teams' work. You are **not** owner. Namespace everything and touch nothing that isn't yours.

---

## 1. ✅ What you already have (verified)

| Permission | Unlocks | Goal |
|---|---|---|
| `serviceusage.services.enable` | Enable APIs | G0.1 |
| `bigquery.datasets.create` | Create `retailpulse` dataset | G1.2 |
| `bigquery.jobs.create` | Run all queries | G1.2 |
| `bigquery.connections.create` | **Remote model for `ML.GENERATE_EMBEDDING`** | G1.3 |
| `bigquery.models.create` | **`ARIMA_PLUS` forecast model** | G5.1 |
| `datastore.databases.create` | Create a Firestore Native DB | G4.3 |
| `datastore.entities.create` | Read/write Firestore | G4.3 |
| `aiplatform.endpoints.predict` | Call Gemini on Vertex AI | G3.1 |
| `run.services.create` | Deploy Cloud Run services | G0.4, G6.4 |
| `run.services.setIamPolicy` | **Make services public** (demo frontend can reach API) | G6.4 |
| `artifactregistry.repositories.create` | Container images | G0.4 |
| `cloudbuild.builds.create` | Build containers | G0.4 |
| `storage.buckets.create` | Build staging | G0.4 |
| `iam.serviceAccounts.actAs` | **Deploy Cloud Run *as* an existing SA** | G0.2 |

**All required APIs are already enabled** — `aiplatform`, `bigquery`, `bigqueryconnection`, `bigquerystorage`, `firestore`, `datastore`, `run`, `pubsub`, `cloudbuild`, `artifactregistry`, `secretmanager`. G0.1 is effectively done.

---

## 2. ❌ What you're missing (4 blockers)

| Permission | Blocks | Severity |
|---|---|---|
| `iam.serviceAccounts.create` | **G0.2 — can't create service accounts** | 🔴 High — this is Proof #2 |
| `resourcemanager.projects.setIamPolicy` | **G0.2 — can't grant IAM roles** | 🔴 High |
| `pubsub.topics.create` + `subscriptions.create` | **G6.1 — no event-driven loop** | 🟡 Medium — has a fallback |
| `secretmanager.secrets.create` | Secret storage | 🟢 Low — use Cloud Run env vars |
| `cloudscheduler.jobs.create` | Scheduled jobs | 🟢 Low — already cut from scope |

### Blocker impact on the pitch

**G0.2 is Proof #2** — *"the agent runtime service account has zero direct write roles."* Without SA creation + role granting, you cannot make that claim IAM-enforced. This matters because it's one of your three non-negotiables.

**G6.1 (Pub/Sub)** was already cut #4 on the triage ladder, so this is a soft loss — but it costs you the "unprompted alert" moment in Act 3 unless you take a workaround.

---

## 3. Three routes past the blockers

| Route | Effort | Gets you | Recommendation |
|---|---|---|---|
| **A. Ask the GCP admin** | 1 message, hours–1 day | Everything. Full IAM proof + real Pub/Sub. | ⭐ **Do this first — template in §4** |
| **B. Your own GCP project** | 1–2h | Full owner, zero org-policy surprises, $300 trial credits | ⭐ **Best fallback. Start in parallel.** |
| **C. Process-enforced boundary** | 0h (already in design) | A weaker but *honest* version of Proof #2 | Safety net — assume this works |

### Route C explained — the honest fallback

Even with no IAM control, the boundary is still real and still demonstrable:

- The **MCP server is the only component holding database credentials**
- Agent processes receive an **HTTP client only** — no BigQuery client, no Firestore client, no connection string
- `grep -r "bigquery.Client\|firestore.Client" agents/` returns **zero hits** ← demo this live

**Say this out loud:** *"In production this boundary is IAM-enforced — the agent service account has no data roles. In this shared corporate project I can't mint service accounts, so it's process-enforced: the agent runtime has no database client at all. Here's the grep."*

Judges respect a named limitation far more than a vague claim. Route C is a perfectly good demo.

### Pub/Sub fallback (if Route A fails)

Replace the topic with a **"Simulate weekend spike"** button that calls the Cloud Run consumer endpoint directly. The consumer code is identical — only the trigger changes. Say: *"Event-driven architecture; the Pub/Sub trigger is swapped for a manual one here so I can control demo timing."* That sentence is true and costs you nothing.

---

## 4. 📋 Admin request — copy-paste this

> **Subject: GCP access request — hackathon prototype on `ctoteam`**
>
> Hi — I'm building a hackathon prototype (RetailPulse AI) on `ctoteam` and need a small, scoped set of permissions. Everything will be namespaced `retailpulse_*` / `rp-*` and I won't touch existing datasets or services.
>
> **Option 1 (preferred) — create two service accounts and grant:**
>
> | Service account | Roles | Scope |
> |---|---|---|
> | `rp-agent-runtime@ctoteam.iam.gserviceaccount.com` | `roles/aiplatform.user`, `roles/run.invoker` | **Deliberately no data access** |
> | `rp-mcp-tools@ctoteam.iam.gserviceaccount.com` | `roles/bigquery.jobUser` (project)<br>`roles/bigquery.dataViewer` (dataset `retailpulse` only)<br>`roles/bigquery.dataEditor` (table `retailpulse.agent_audit` only)<br>`roles/datastore.user` (database `retailpulse-db` only) | Dataset/table/DB scoped |
>
> Plus `roles/iam.serviceAccountUser` for me on both, so I can deploy as them.
>
> **Option 2 (simpler) — grant me `roles/iam.serviceAccountAdmin` scoped to the project**, and I'll create and configure them myself.
>
> **Also useful but optional:** one Pub/Sub topic `retailpulse-sales-events` + a push subscription, or `roles/pubsub.editor`.
>
> The point of the split is a security demo: the AI agent runtime is provably unable to write to the database. Happy to walk through it.

---

## 5. ⚠️ Project-specific gotchas (found during audit)

| # | Finding | Action |
|---|---|---|
| 1 | **Firestore default DB is `DATASTORE_MODE`** — unusable for Firestore Native, and **cannot be converted** | Create a **named Native DB**: `gcloud firestore databases create --database=retailpulse-db --location=us-central1 --type=firestore-native`. You have the permission. Pass `database="retailpulse-db"` in every client call. |
| 2 | **Shared project, 40+ datasets** — `Retail_data_sks` already exists | Namespace everything: dataset `retailpulse`, Cloud Run `rp-*`, Firestore `retailpulse-db`, GCS `rp-*`. Never `DROP` anything you didn't create. |
| 3 | **`ML.GENERATE_EMBEDDING` needs a BQ connection**, and that connection's auto-created SA needs `roles/aiplatform.user` | You can create the connection ✅ but **may not be able to grant it the role** ❌ → likely needs the admin. **Test this on Day 0, not Day 1** — it's the hidden path to G1.3. |
| 4 | Corporate org policy may block `allUsers` on Cloud Run | You have `run.services.setIamPolicy` ✅, but domain-restricted sharing can still refuse. **Test with the hello-world on Day 0.** If blocked: run React locally against an authenticated API. |

---

## 6. 💻 Local tooling — 2 gaps

| Tool | Status | Action |
|---|---|---|
| gcloud 583.0.0 | ✅ | — |
| Docker 29.5.3 | ✅ | — |
| **Python 3.14.6** | 🔴 **Too new** | `google-adk` and several GCP libs have no 3.14 wheels yet. **Install Python 3.12** and build the venv on it. Do this before anything else — it will waste half a day if you discover it on Day 1. |
| **Node.js** | 🔴 **Not installed** | Required for React/Vite. Install Node 20 LTS. |

```bash
# Python 3.12 venv (after installing 3.12)
py -3.12 -m venv .venv && source .venv/Scripts/activate
python --version   # must print 3.12.x

# Node 20 LTS — winget
winget install OpenJS.NodeJS.LTS
```

---

## 7. Target IAM design (for Route A or B)

The split that makes Proof #2 true:

| Identity | Roles | Deliberately denied |
|---|---|---|
| `rp-agent-runtime` | `aiplatform.user`, `run.invoker` | **All BigQuery, all Firestore** |
| `rp-mcp-tools` | `bigquery.jobUser`, `dataViewer` on dataset, `dataEditor` on `agent_audit` **table only**, `datastore.user` on `retailpulse-db` | Project-wide data access |
| `rp-inventory-a2a` | `aiplatform.user`, `run.invoker` | All data access |
| `rp-event-consumer` | `datastore.user`, `bigquery.jobUser`, `dataViewer` | Write access to business tables |

Two details worth knowing:

- **Table-level `dataEditor` on `agent_audit` only** is the elegant part — the tools layer can append audit rows but cannot mutate sales or product data. Easy to show, hard to argue with.
- **Firestore IAM is coarse** — `datastore.user` grants read/write across the whole database; there is no per-collection IAM. Scope it to the `retailpulse-db` database and enforce the rest in Security Rules + validated tool code. **Don't overclaim this one if a judge asks.**

---

## 8. Revised Day 0 checklist

| ☐ | ID | Task | Note |
|---|---|---|---|
| ☐ | **G0.0a** | Install Python 3.12, create venv | 🔴 Blocks everything |
| ☐ | **G0.0b** | Install Node 20 LTS | 🔴 Blocks React |
| ☐ | **G0.0c** | **Send the admin request (§4)** | Do first — it runs in the background while you build |
| ☐ | **G0.0d** | Start a personal GCP project in parallel (Route B) | Insurance |
| ☐ | ~~G0.1~~ | ~~Enable APIs~~ | ✅ **Already done** |
| ☐ | **G0.2** | SA split — *blocked, pending admin* | Fall back to Route C |
| ☐ | **G0.2b** | Create Firestore Native DB `retailpulse-db` | You have permission ✅ |
| ☐ | **G0.2c** | **Create BQ connection + test `ML.GENERATE_EMBEDDING`** | Hidden blocker — test tonight |
| ☐ | **G0.3** | Pin deps on Python 3.12 | `==` everywhere |
| ☐ | **G0.4** | Hello-world to Cloud Run + **test public access** | Proves pipeline + org policy |
| ☐ | **G0.5** | Check Vertex AI quota | — |

---

## 9. Day 0 results — what was actually tested (2026-10-12)

### ✅ Provisioned

| Resource | Value | Note |
|---|---|---|
| BigQuery dataset | `ctoteam.retailpulse` | **`us-central1`** — not `US` |
| Firestore Native DB | `retailpulse-db` | `us-central1`. Pass `database="retailpulse-db"` in **every** client call. |
| BQ connection | `ctoteam.us-central1.retailpulse-conn` | Created, but **unusable** — see below |

### 🔴 Confirmed blocker: `ML.GENERATE_EMBEDDING` is dead

The connection SA `bqcx-1035117862188-jlow@gcp-sa-bigquery-condel` needs `roles/aiplatform.user`
and we cannot grant it. Verified error:

> `does not have the permission to access or use the endpoint. Please grant the 'Agent Platform User' role`

### ✅ Workaround proven end to end — G1.3 is NOT blocked

`VECTOR_SEARCH` only needs embeddings **stored in a column**. Only *generating* them needs the
remote model. We have `aiplatform.endpoints.predict`, so Python generates them directly.

**Verified pipeline:** Vertex `text-embedding-005` REST (768-dim) → NDJSON → `bq load`
(`FLOAT64 REPEATED`) → `VECTOR_SEARCH(... distance_type => 'COSINE')`

Live result for query *"shoes for running a marathon"*:

| Rank | Product | Cosine distance |
|---|---|---|
| 1 | Max cushioned **road** shoe, marathon training | **0.2300** |
| 2 | Trail shoe, aggressive lugs | 0.3330 |
| 3 | Leather dress oxford | 0.4532 |

**This is the G1.3 done-test, passing.** Semantic ranking is correct — road beats trail.

**Architecture change:** embed in Python at seed time and at query time; never in SQL.
This is *better* for the demo — no dependency on a connection grant, and query-time embedding
is a single REST call we already control.

### 🟡 Still blocked

| Item | Status |
|---|---|
| Service account creation + IAM grants (G0.2) | Pending admin — fall back to Route C |
| Pub/Sub topics (G6.1) | Pending admin — fall back to "Simulate spike" button |

### ⚠️ Org policy: `constraints/gcp.resourceLocations`

`US` multi-region is **blocked** for new resources (older datasets predate the policy).
**Everything must be `us-central1`.** Applies to BigQuery, Firestore, and Cloud Run.

### 🌐 Corporate TLS interception

The network re-signs TLS with a corporate root CA. Windows trusts it; bundled CA stores do not.
Fix applied for git (full validation preserved, nothing weakened):

```bash
# 70 Windows root CAs exported to ~/.certs/ca-bundle.pem
git config --global http.sslBackend openssl
git config --global http.sslCAInfo "C:/Users/MadhuVamsiTuraka/.certs/ca-bundle.pem"
```

**The same wall will hit `pip`, `npm`, and `requests`.** Pre-emptive fix:

```bash
export REQUESTS_CA_BUNDLE="C:/Users/MadhuVamsiTuraka/.certs/ca-bundle.pem"
export PIP_CERT="C:/Users/MadhuVamsiTuraka/.certs/ca-bundle.pem"
npm config set cafile "C:/Users/MadhuVamsiTuraka/.certs/ca-bundle.pem"
```

Note: `curl` on Windows uses schannel and ignores `--cacert`; and PowerShell's
`Invoke-RestMethod` trips Google's bot filter (HTTP 417). **Use `curl` with `-o` for Google
APIs** — shell `>` redirects proved unreliable here.
