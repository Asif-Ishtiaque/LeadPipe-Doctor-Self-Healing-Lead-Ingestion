# QuaLead AI: LeadPipe Doctor -- Self-Healing Lead Ingestion Agent

Messy leads go in (Facebook webhook JSON, Instagram CSV, Google Form CSV,
landing-page JSON) and clean, validated, deduplicated, scored leads come
out -- in one canonical schema, regardless of source. Every lead comes out
with a **quality score (0-100)**, a plain-English **diagnosis** of why it
scored that way, and a **recommended next action** for the sales rep. When
the cleaning code itself breaks on a batch it's never seen before, the
agent reads the traceback, asks a local LLM to patch the broken function,
and retries automatically before ever bothering a human.

100% free and open source. No paid APIs, no cloud LLM calls -- everything
(LLM, embeddings, vector store, database, ML) runs locally.

## The problem

Every lead source names its fields differently, formats phone numbers
differently, and breaks your ingestion code in a new way eventually. Most
pipelines handle this by having an engineer notice the crash, read the
traceback, patch the code, redeploy. LeadPipe Doctor closes that loop
inside the pipeline itself: a LangGraph agent catches the exception,
hands the traceback and the offending source file to a local LLM
(Ollama), validates and applies the LLM's patch, and re-runs the batch --
up to 3 times -- before giving up and routing the batch to a human review
queue.

## Architecture

```
                    ┌─────────────────────────────────────────────────┐
                    │                  Ingestion                       │
   Facebook JSON ──►│  app/ingestion/{facebook,instagram,             │
   Instagram CSV ──►│  google_form,landing_page}.py                    │
   Google Form CSV─►│  -> flat list[dict], one shape per source        │
   Landing page ───►│                                                   │
                    └───────────────────────┬───────────────────────────┘
                                             ▼
                    ┌─────────────────────────────────────────────────┐
                    │         Schema profiling + RAG mapping           │
                    │  app/mapping/profiler.py, mapper.py, rag_store.py│
                    │  ChromaDB stores canonical field descriptions +  │
                    │  past (source, field) -> canonical decisions.    │
                    │  Ollama (qwen2.5) proposes new mappings, grounded │
                    │  in the ChromaDB context. Falls back to a         │
                    │  synonym/fuzzy heuristic if Ollama is down.       │
                    └───────────────────────┬───────────────────────────┘
                                             ▼
        ┌────────────────────────────────────────────────────────────────┐
        │                  Self-healing agent (LangGraph)                 │
        │                       app/agent/graph.py                        │
        │                                                                  │
        │   ┌──────────────┐  error   ┌──────┐  healed  ┌──────────────┐  │
        │   │ run_pipeline │─────────►│ heal │─────────►│ run_pipeline │  │
        │   └──────┬───────┘          └──┬───┘  (retry) └──────────────┘  │
        │          │ success             │ can't heal                    │
        │          ▼                     ▼                               │
        │         END              ┌─────────────┐                       │
        │                          │ human_review│──► data/human_review/ │
        │                          └─────────────┘     queue.jsonl       │
        │                                                                  │
        │  run_pipeline = cleaning (app/cleaning) -> validation            │
        │  (app/validation, Pydantic) -> dedup (app/deduplication,         │
        │  exact email/phone match) -> scoring (app/scoring, rule engine)  │
        │                                                                  │
        │  heal = capture traceback -> ask Ollama to rewrite                │
        │  app/cleaning/transforms.py -> validate the patch is syntactically│
        │  sound and didn't drop required functions -> write it to disk    │
        └────────────────────────────────────────────────────────────────┘
                                             ▼
                    ┌─────────────────────────────────────────────────┐
                    │     Postgres (leads, duplicates, invalid,        │
                    │     healing_events) + MLflow (scoring experiments)│
                    └───────────────────────┬───────────────────────────┘
                                             ▼
                              Streamlit dashboard (dashboard/)
```

## Tech stack, why, and license

100% free and open source, zero paid APIs and zero API keys anywhere in
this repo (grep it: there's nothing to configure). Every model, library,
and service below is either open-weight/open-source or free to run
locally without an account.

| Tool | Role | Why this one | License |
|---|---|---|---|
| **Ollama (qwen2.5:3b by default)** | Field-mapping LLM + code-patching LLM | Free, runs fully local, no API keys, no rate limits, no data leaves the machine -- required for a pipeline that ingests PII. 3b is the default so the whole stack fits comfortably in ~4GB of RAM; bump `OLLAMA_MODEL` to `qwen2.5:7b` in docker-compose.yml for better patch quality if your machine has 8GB+ to spare for Docker. | Ollama: MIT. Qwen2.5 weights: Apache-2.0 |
| **LangGraph** | Self-healing agent orchestration | The retry/heal/human-review loop is a small explicit state machine, which is exactly what LangGraph's `StateGraph` models -- conditional edges instead of hand-rolled retry loops scattered through the code. | MIT |
| **FastAPI** | HTTP entrypoint | Async-native, Pydantic-native (shares the same validation models), minimal boilerplate for a handful of ingest/stats routes. | MIT |
| **pandas** | CSV parsing, batch transforms | Standard for tabular ingestion (Instagram/Google Form CSVs) and for feeding the DataFrame-shaped stats the dashboard needs. | BSD-3-Clause |
| **Pydantic** | Canonical schema + validation | Gives us one model (`app/schema/canonical.py:Lead`) that's simultaneously the validation layer, the FastAPI request/response shape, and the ML feature source of truth. | MIT |
| **PostgreSQL (DuckDB fallback)** | Storage | Postgres in docker-compose for concurrent read/write from the API + dashboard; DuckDB locally so the pipeline runs with zero infra for development. Same SQLAlchemy code path either way. | PostgreSQL License (MIT-like) / DuckDB: MIT |
| **ChromaDB** | RAG memory for field mapping | Stores canonical schema descriptions and every past field-mapping decision as embeddings, so mapping quality compounds instead of re-asking the LLM the same question for every batch. | Apache-2.0 |
| **nomic-embed-text (via Ollama)** | Embeddings | Free, local, good enough for short field-name-plus-sample-value strings. | Apache-2.0 |
| **Rule engine + XGBoost** | Lead scoring | Production scoring is a transparent, clamped-linear rule engine over named quality signals -- every point decomposes into a reason the diagnosis text can name, and it uses the full 0-100 range. An XGBoost model is also trained on the rule engine's pseudo-labels and tracked in MLflow as the drop-in path for when real conversion outcomes exist; it is not the live scorer today because a tree ensemble compresses the range of the linear rule it's mimicking (measured in Limitations). | XGBoost: Apache-2.0 |
| **rapidfuzz** | Field-mapping heuristic fallback | Fast fuzzy string matching in C, used when the LLM can't resolve a field mapping (`app/mapping/mapper.py`). No longer used for deduplication -- see Limitations for why fuzzy name matching was removed from dedup. | MIT |
| **MLflow** | Scoring experiment tracking | Free, local tracking server; logs the XGBoost hyperparameters/MAE for every training run. | Apache-2.0 |
| **Streamlit** | Dashboard | Fastest way to get a real, interactive dashboard out of pandas DataFrames with no separate frontend build. | Apache-2.0 |
| **Faker** | Synthetic data generation | Realistic names/emails/phones for the 100k+ row demo dataset. | MIT |
| **Docker Compose** | Orchestration | One command spins up Postgres, Ollama, ChromaDB, the API, and the dashboard together. | Apache-2.0 (the Compose CLI/spec; Docker Desktop itself is free for this kind of use but proprietary -- the Docker *Engine* and everything this repo's code depends on is open source) |

Full license texts are in each package's own repository; none of them
require a purchased license, subscription, or API key for the way this
project uses them.

## Project structure

```
leadpipe-doctor/
├── app/
│   ├── main.py            FastAPI entrypoint
│   ├── ingestion/          per-source raw-format parsers
│   ├── schema/              canonical Pydantic Lead model
│   ├── mapping/             schema profiling + LLM/RAG field mapping
│   ├── cleaning/            pandas transforms (the code the agent patches)
│   ├── validation/          Pydantic-based row validation
│   ├── deduplication/       exact email/phone match dedup
│   ├── scoring/             XGBoost + rule-based scoring, plus diagnosis.py
│   │                        (human-readable "why" + suggested rep action)
│   ├── agent/                LangGraph self-healing loop
│   └── utils/                config + storage
├── tests/                    pytest suite (schema, transforms, dedup,
│                             scoring, diagnosis, self-heal guards)
├── data/
│   ├── sample_pack/           committed ~100k-row demo dataset (see its own README)
│   ├── raw/                   gitignored scratch space for freshly generated data
│   ├── processed/             local DuckDB file (dev mode)
│   └── human_review/          queue.jsonl of unrecoverable batches
├── scripts/
│   ├── generate_data.py      generates a fresh N-row messy dataset
│   ├── replay.py              ingests data/sample_pack/ through a running API
│   └── demo_self_heal.py     intentionally breaks + heals the pipeline
├── ml/
│   ├── train.py               trains the XGBoost scorer
│   └── models/                 trained model artifact
├── dashboard/
│   └── streamlit_app.py
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## Quickstart (3 commands)

```bash
git clone https://github.com/Asif-Ishtiaque/LeadPipe-Doctor-Self-Healing-Lead-Ingestion.git
cd LeadPipe-Doctor-Self-Healing-Lead-Ingestion
docker compose up -d          # start Postgres, Ollama, ChromaDB, API, dashboard
python3 -m scripts.replay     # feed the committed 100k+ sample pack into the running API
```

Then open:
- Dashboard: http://localhost:8501 -- should show ~90k clean leads, duplicates, and invalid rows within a few minutes
- API docs: http://localhost:8000/docs

`docker compose up -d` also starts `ollama-init`, a one-shot container
that pulls `qwen2.5:3b` and `nomic-embed-text` automatically the first
time -- give it a few minutes on a fresh machine before running the
replay step, or watch it with `docker compose logs -f ollama-init`.

To run without Docker (development mode, uses DuckDB instead of Postgres):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload          # terminal 1
streamlit run dashboard/streamlit_app.py   # terminal 2
```

In development mode, field mapping automatically falls back to the
synonym/fuzzy heuristic and self-healing routes straight to human review
if Ollama isn't running locally -- see Limitations.

## Tests

```bash
.venv/bin/python3 -m pytest tests/ -v
```

No network, no Docker, no Ollama needed -- everything here runs against
plain Python objects and tmp_path fixtures. Coverage focuses on the
highest-stakes and most recently-hardened logic:

- **Self-healing's safety guards** (`tests/test_healer.py`): the AST
  patch validator (rejects invalid syntax, rejects a patch that drops a
  required function), the backup-before-write apply step and rollback,
  and the NotHealable fast path that skips a doomed LLM call for
  exceptions outside transforms.py's scope. Every test monkeypatches
  `TRANSFORMS_PATH` to a tmp file -- none of them touch the real
  `app/cleaning/transforms.py`.
- **Schema/cleaning "flag, never drop" contract**
  (`tests/test_schema.py`, `test_transforms.py`, `test_features.py`):
  first_name/last_name/email/phone_e164/consent all degrade gracefully
  (to `None` or a safe default) instead of raising, no matter how dirty
  the input -- locks in the fix for a real external-review finding (see
  Limitations).
- **Dedup's exact-match design** (`tests/test_dedup.py`): merges on
  exact email/phone identity, and explicitly proves the false-positive
  case that got fuzzy name matching removed (`fuzz.ratio("jon li", "jan
  li")` and `fuzz.ratio("mohammed ali", "muhammad ali")` are both 83.3 --
  two different people must never merge just because their names look
  alike).

## Data

`data/sample_pack/` is a committed, deterministic ~100,000-row synthetic
dataset spanning all 4 sources (see `data/sample_pack/README.md` for the
exact file formats and the messiness rules baked into each one -- bad
phone formats, malformed emails, missing fields, and cross-source
duplicates). This is what `scripts/replay.py` ingests and what the demo
video runs against.

`data/raw/` is a gitignored scratch space for generating your *own* fresh
messy dataset on demand: `python3 -m scripts.generate_data --total 50000`.

## Fine-tune notes

No model weights are fine-tuned in this project -- both LLM roles (field
mapping and code-patching) run the stock `qwen2.5` instruct model as-is.
Two things stand in for fine-tuning instead:

- **Field mapping improves over time without retraining.** Every
  (source, field name) mapping the LLM resolves gets embedded and stored
  in ChromaDB (`app/mapping/rag_store.py`). The next batch from the same
  source reuses that decision for free instead of re-asking the LLM --
  this is the project's answer to "learning from data" without needing
  a training loop.
- **Prompt iteration is the real tuning lever for this model size.** The
  smaller `qwen2.5:3b` (chosen for its ~2GB memory footprint) initially
  answered "unknown" for casually-phrased fields like *"What's your
  name?"* even when the correct canonical field was right there in its
  retrieved context. Adding a handful of few-shot examples to
  `app/mapping/mapper.py`'s prompt fixed this measurably -- see git
  history for the before/after. If you have the RAM for `qwen2.5:7b`
  instead, prompt engineering matters less; the tradeoff is memory vs.
  how much prompting effort the smaller model needs.
- **An XGBoost scorer *is* trained and tracked in MLflow** (a separate,
  traditional ML step, not the LLM) -- but production scoring is the
  transparent rule engine, not the model. See `ml/train.py`,
  `app/scoring/scorer.py`, and Limitations below for why (short version: a
  tree ensemble compresses the range of the deterministic linear rule it's
  trained to mimic, so the model is the future-real-labels path rather
  than today's scorer).

## Demo video

[link to demo video -- add once recorded/uploaded]

## Demo walkthrough

1. **Load messy data**: `python3 -m scripts.replay` ingests the committed
   `data/sample_pack/` (or generate your own fresh batch first with
   `python3 -m scripts.generate_data --total 50000 --out-dir data/raw`,
   which produces inconsistent phone formats, malformed emails, missing
   fields, and cross-source duplicates).
2. **Show clean output**: open the dashboard, or `GET /leads`, to see the
   canonical, validated, scored output. Every record's `raw_payload`
   field carries the exact original messy input alongside the cleaned
   canonical fields, so a single row shows one lead's full journey --
   messy source dict in, canonical Postgres row out -- side by side.
3. **Break the schema intentionally**: `python3 -m scripts.demo_self_heal`
   patches `app/cleaning/transforms.py` with a bug (phone normalization
   stops casting input to `str`), then feeds it a batch with an integer
   phone number to trigger a real, uncaught `TypeError`.
4. **Show self-healing**: the same script's output shows the LangGraph
   agent catching the exception, asking Ollama to rewrite
   `transforms.py`, and successfully retrying -- or, if Ollama isn't
   running, routing straight to `data/human_review/queue.jsonl`. This can
   take 1-3 minutes on CPU-only inference; see Recording notes for the
   demo video.
5. **Show deduplication**: the dashboard's "Duplicates removed" metric and
   the union-find clustering in `app/deduplication/dedup.py` show
   cross-source duplicate detection on exact email/phone match (see
   Limitations for why this is exact-match only, not fuzzy name matching).
6. **Show scoring**: every lead carries a 0-100 quality score, a
   plain-English diagnosis, and a recommended action (dashboard Leads tab
   -> Lead insights). Scoring is the transparent rule engine, so a score
   always decomposes into named reasons. `python3 -m ml.train` also trains
   an XGBoost model on the rule engine's pseudo-labels and logs it to
   MLflow (http://localhost:5000) -- the tracked learning path for when
   real conversion outcomes exist (see Limitations for why it isn't the
   live scorer).

## Limitations and future work

- **The schema used to violate its own brief -- fixed.** An external
  review found `first_name`/`last_name`/`email`/`phone_e164`/`consent`
  hard-required on the `Lead` model, so any lead with one bad field
  (a junk phone number, a malformed email, a missing name) was rejected
  to `invalid_leads` wholesale instead of being flagged -- on one real
  Facebook sample batch, 238 of 393 leads (60%) were silently dropped
  this way, the majority from `normalize_phone` rejecting NANP's 555
  exchange (exactly what Faker generates for synthetic phone numbers).
  The brief is explicit that a lead a business paid for is never deleted
  for having dirty data. Fixed: those four fields are now nullable (plus
  `created_at`, which defaults to now() instead of failing), missing/
  ambiguous consent defaults to `False` (TCPA-safe) instead of `None`,
  `normalize_phone` now accepts anything `is_possible_number` instead of
  the stricter `is_valid_number`, and a lead with no contactable
  identifier at all (no email *and* no phone) is flagged rather than
  silently treated as a normal clean record. See `tests/test_schema.py`,
  `test_transforms.py`, and `test_features.py` for the regression
  coverage locking this in. What still legitimately lands in
  `invalid_leads` is now a much narrower set -- structural failures
  Pydantic can't gracefully coerce around (e.g. a `source` value outside
  the known enum, or a name/string field past its length limit) -- rather
  than "any single field was dirty."
- **Cross-batch dedup's race protection is Postgres-only.** A QA audit
  found concurrent requests for the same lead could each see "not found"
  and each insert their own "clean" row (confirmed with 20 real threads:
  all 20 inserted separately). Fixed with a `pg_advisory_xact_lock` per
  email/phone around the check-then-insert in
  `app/utils/storage.py:persist_leads_atomic`, serializing only requests
  racing on the *same* identifier. DuckDB (the local dev fallback) has no
  equivalent primitive, so that path is still technically racy there --
  acceptable for now since DuckDB only supports one writer process at all,
  making true concurrent writes an edge case already.
- **Model size is a memory/quality tradeoff.** `qwen2.5:3b` is the default
  because it reliably loads in ~4GB of RAM alongside Postgres, ChromaDB,
  and the API -- important on machines with 8GB total RAM, where Docker
  Desktop can't safely be given enough memory for `qwen2.5:7b` (a 7B model
  needs ~5-6GB+ of headroom on top of everything else and will get OOM-
  killed on a tight budget). If your machine has more RAM to spare, set
  `OLLAMA_MODEL: qwen2.5:7b` in docker-compose.yml (and pull it via
  `docker compose exec ollama-init ollama pull qwen2.5:7b`) for
  meaningfully better field-mapping and code-patching quality.
- **Production scoring is the rule engine, not the trained model -- on
  purpose.** With no historical "did this lead convert" outcomes, the
  XGBoost model can only be trained on pseudo-labels from the rule engine,
  so it can never be *better* than the rule engine -- only a lossier copy.
  A calibration pass measured exactly how lossy: the model reproduced the
  rule engine to within ~1 point on held-out *synthetic* data (validation
  MAE ~1.2) yet missed *real* leads by ~21 points and never predicted
  above ~56, so 0% of leads reached the 70+ band even though ~two-thirds
  genuinely qualify. That's structural -- a gradient-boosted tree ensemble
  compresses the range of a deterministic *linear* target (shallow trees
  average toward the mean; deep trees overfit the zero-signal features),
  and no hyperparameter setting fixed it without trading one failure for
  the other. So the transparent rule engine scores in production (exact,
  explainable, full-range, and it matches the diagnosis text line for
  line), while the model stays trained + tracked in MLflow as the drop-in
  path for when real conversion labels exist -- at which point it would be
  predicting something the rule engine can't. `USE_XGBOOST_SCORER=1` flips
  the model into the serving path for experimentation. Re-run
  `scripts/rescore.py` after any scoring-logic change to back-fill scores
  on already-stored rows.
- **The score distribution reflects the (optimistic) synthetic data.**
  On the sample pack ~66% of *valid* leads land in the High band -- not
  because the scorer is undiscriminating but because the invalid/incomplete
  rows are already filtered to `invalid_leads` before scoring, leaving a
  valid population that is ~100% complete and ~76% consented, i.e.
  genuinely mostly-good. A steeper prioritization funnel needs more
  *variance* in the input data (missing fields, more corporate-vs-free
  mix, more consent spread), not a heavier arbitrary penalty -- the score
  can only spread as much as the underlying signals do.
- **Self-healing has no offline fallback.** Rewriting code is
  fundamentally an LLM task; if Ollama is unreachable, the agent can't
  self-heal and routes straight to human review. Field mapping, by
  contrast, does have a heuristic fallback and keeps working offline.
- **Self-healing patches one file.** The agent is scoped to rewriting
  `app/cleaning/transforms.py` specifically. A bug in ingestion, mapping,
  validation, or scoring code is out of scope for this loop and would
  need the same pattern extended to those modules.
- **Dedup is exact email/phone match only, deliberately.** It used to
  also merge on fuzzy name similarity, but a QA audit proved that's
  unsound: `fuzz.ratio("jon li", "jan li")` and
  `fuzz.ratio("mohammed ali", "muhammad ali")` both score 83.3, yet one
  pair is almost certainly different people and the other is almost
  certainly the same person -- no threshold or corroborating signal
  (same email domain, same phone prefix) reliably tells them apart in
  realistic bulk data, and getting it wrong silently destroys real lead
  data (1,110 distinct people collapsed to 12 survivors in one test
  batch before this was fixed). Exact matching can't produce false
  positives, at the cost of missing "same person, different email and
  phone, recognizable name" cases -- see `app/deduplication/dedup.py`
  for the full writeup. Cross-batch dedup (checking new leads against
  everything already in Postgres, not just the current request) was
  added for the same reason: real sources deliver one lead per request,
  so batch-only dedup rarely fired in practice.
- **Disposable-email and placeholder-name detection are curated lists,
  not exhaustive.** `app/scoring/features.py` has ~30 known disposable
  domains and ~25 keyboard-mash/test tokens; both are a floor against
  the cheapest, most common gaming attempts (a QA audit found a
  mailinator.com spam submission outscoring a real Gmail signup before
  this), not a complete solution. A production version would use a
  maintained third-party disposable-domain list and real name-plausibility
  modeling instead of a static blocklist.
- **Patch safety is syntax + required-function-presence only.** The agent
  validates that the LLM's rewritten file parses and keeps every expected
  function name, but doesn't run a full test suite against it before
  applying it. A stricter version would run existing unit tests against
  the patch before accepting it, and roll back automatically if the
  retry still fails.
- **No schema migration tool.** `app/utils/storage.py` has a best-effort
  `_ensure_columns` helper that adds missing columns to already-existing
  tables when the `Lead` schema grows a new field, since there's no
  Alembic (or equivalent) here. Fine for a project at this stage; a real
  production deployment would want proper migrations.

## Screenshots:
  <img width="2878" height="1616" alt="image" src="https://github.com/user-attachments/assets/0df8fd49-6db9-4d6d-bff8-fdf6644570a4" />
  <img width="2878" height="1620" alt="image" src="https://github.com/user-attachments/assets/e771d822-9586-4c0b-ac92-8f188808c61a" />
  <img width="2878" height="1612" alt="image" src="https://github.com/user-attachments/assets/d86c42c3-1ff2-4edf-9511-43dc69e8d3f0" />
  <img width="2876" height="1610" alt="image" src="https://github.com/user-attachments/assets/fd60350a-dc0d-453c-9007-2382c65ef5a1" />




