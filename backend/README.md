# Graph Surge Recommendation API (backend)

FastAPI + PostgreSQL backend for the surge-pricing **DEMO/REPLAY** product. It replays historical snapshots, serves
provider recommendations, and records operator decisions: accept, keep base, override, and batch accept. Every
decision is idempotent and audited. The specification is [docs/backend/spec_backend.md](../docs/backend/spec_backend.md).

> Decisions are always `execution_mode: "DEMO"` with `production_effective: false`. There is no code path to a
> production pricing gateway, and the database rejects any decision that is not `DEMO`.

## Layout

```
app/
  api/v1/read.py     snapshots, recommendations, read-model, regions, providers, policy, hex history
  api/v1/write.py    decisions, batches, demo sessions, audit events
  services/          business rules (eligibility, decisions, batch, replay, audit); they own transactions
  repositories/      SQLAlchemy queries only
  domain/            enums, Decimal surge rules, eligibility, time/cursor helpers
  providers/         RecommendationProvider contract: mock, precomputed (surge_proposal_v1), gnn_adapter (stub)
  ingestion/         active dataset loader, snapshot builder, recommendation importer
  db/                ORM models and Alembic migrations
config/policy.yaml   surge limits, policy version, batch-plan TTL, mock controller parameters
scripts/             import_dataset.py, init_test_db.sql
tests/               unit/, integration/ (BE-01..BE-24), e2e/ (spec §15.4 flow)
```

The layers run API → Service → Repository → DB. The backend never imports `surge_ml`; the mock provider ports
the controller formula from `pipeline/src/surge_ml/controller.py`.

## Quick start

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Python 3.12+.

```bash
cd backend
cp .env.example .env                       # DATABASE_URL, TEST_DATABASE_URL, DEMO_TOKENS, CORS_ORIGINS
docker compose up -d db                    # Postgres 16 on localhost:5433 (also creates surge_test)
uv sync
uv run alembic upgrade head

# Import one day of the active dataset (resolved from data/CURRENT.json) and publish mock recommendations.
uv run python scripts/import_dataset.py --provider mock
# Optional: a wider window and/or precomputed GNN proposals (surge_proposal_v1 JSON files)
uv run python scripts/import_dataset.py --from-date 2026-01-05 --to-date 2026-01-07 --provider mock
uv run python scripts/import_dataset.py --provider precomputed --source <dir with proposals_k*.json>

uv run uvicorn app.main:app --reload       # http://localhost:8000/docs
```

### GNN recommendations (precomputed)

TD-04 is decided as precomputed for the MVP: the model runs offline in `pipeline/` and the backend imports its
output. The backend still never imports `surge_ml` or torch.

```bash
cd ../pipeline
uv run surge-ml prepare
uv run surge-ml train --variant gru_gatv2_40 --seed 42   # writes runs/<study_id>/gru_gatv2_40/seed_42/best.pt
cd ../backend
powershell -File scripts/build_gnn_demo.ps1               # or scripts/build_gnn_demo.sh
```

The script runs `surge-ml surge --split test` (one batched forecast for every eligible cutoff of the test split,
one `proposals_k{k}.json` each plus `index.json`), then `import_dataset.py --provider precomputed`. Without
`--from-date/--to-date`, the import covers exactly the days the files cover. It refuses files whose
`data_fingerprint` differs from the active dataset, and exits 1 if any file's cutoff matches no snapshot.
Proposals carry `deployment_eligible: false` and an uncalibrated controller, so they are for demo/replay only.

The dataset path, number of days and hex count are never hardcoded. They come from `data/CURRENT.json` and the
release's `meta/manifest.json`, and the import checks the dataset fingerprint against the manifest. Re-running an
import is a no-op: snapshots are keyed on dataset, region, cutoff and node mapping, and recommendation sets on a
content hash.

To run the containerised API instead, use `docker compose --profile api up --build`.

## Auth

Static demo bearer tokens come from `DEMO_TOKENS` (`token:actor_id:ROLE`, comma separated). Defaults:

| Token | Actor | Role |
|---|---|---|
| `demo-operator-token` | `operator_01` | OPERATOR: read, decide, batch |
| `demo-viewer-token` | `viewer_01` | VIEWER: read only |

The actor is always taken from the token, never from the request body. Operators can only write to their own
demo sessions.

## API (prefix `/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/snapshots` | Cursor-paginated snapshots (`region_id`, `dataset_id`, `from_ts`, `to_ts`) |
| GET | `/snapshots/{id}` | Snapshot detail, dataset, recommendation sets, prev/next navigation |
| GET | `/snapshots/{id}/recommendations` | Filters: `action`, `eligibility`, `decision_status` (needs `demo_session_id`), `hex_id`, `recommendation_set_id` |
| GET | `/snapshots/{id}/summary` | Counts by action, eligibility and decision status; Accept All candidates |
| GET | `/snapshots/{id}/read-model` | Map, queue and panel data from one snapshot identity: per hex geometry, market state, proposal, eligibility, capabilities and decision |
| GET | `/regions/{id}/hexes` | Hex geography (polygons, ring-1 neighbours) |
| GET | `/recommendations/{proposal_id}` | Proposal detail with limits and market state |
| GET | `/providers`, `/policies/current` | Provider metadata, read-only policy |
| GET | `/hexes/{hex_id}/history` | `series` = `BASE_BIDDING`, `DEMAND`, `EFFECTIVE_SUPPLY` or `OBSERVED_DS`. Nulls and gaps are kept with a `reason`. `FORECAST_DS` returns 422 `SERIES_UNAVAILABLE` |
| POST | `/demo-sessions` · GET `/demo-sessions/{id}` · GET `/demo-sessions/{id}/decisions` | Demo sessions |
| POST | `/decisions` | `ACCEPT_PROPOSAL`, `KEEP_BIDDING` or `OVERRIDE_PROPOSAL` (schema `surge-decision.v1`) |
| GET | `/decisions`, `/decisions/{id}`, `/decisions/by-idempotency/{key}` | Decision history and outcome lookup by idempotency key |
| POST | `/batches/preview` | Freeze a plan (`ALL_ELIGIBLE` or `SELECTED`) |
| POST | `/decisions/batch` | Commit a plan. Each item has its own transaction, so a batch can partially succeed; retrying resumes it |
| GET | `/batches/{id}` | Batch result |
| GET | `/audit-events` | Append-only audit log, cursor-paginated |
| GET | `/health`, `/metrics` | DB health, in-process counters (not under `/api/v1`) |

Example decision:

```bash
curl -X POST http://localhost:8000/api/v1/decisions \
  -H "Authorization: Bearer demo-operator-token" -H "Content-Type: application/json" \
  -d '{"schema_version":"surge-decision.v1","demo_session_id":"<uuid>","idempotency_key":"intent_001",
       "proposal_id":"prop_...","expected_proposal_version":"1","snapshot_id":"snap_...",
       "action":"OVERRIDE_PROPOSAL","requested_surge":"1.30","reason":"Manual adjustment"}'
```

Errors use one envelope: `{"error": {"code", "message", "details", "correlation_id"}}`. Every response carries
`X-Correlation-ID`, and a replayed idempotent response also carries `Idempotent-Replayed: true`.

## Rules worth knowing

- **Surge values** are decimal strings computed with `Decimal`. They are never clamped: an out-of-range value is
  rejected with `SURGE_LIMIT_EXCEEDED`, `INVALID_SURGE_STEP` or `INVALID_SURGE_PRECISION`. Limits live in
  `config/policy.yaml`; the current values are placeholders until TD-08 is approved.
- **Eligibility** (`ELIGIBLE`, `BLOCKED`, `EXPIRED`, `SUPERSEDED`, `UNKNOWN`) is computed on the server on every read
  and checked again on every write. It does not depend on the proposal's action.
  - The newest published set of a snapshot is current; older sets are `SUPERSEDED`.
  - Proposals never expire in `DEMO_REPLAY` mode. Only batch plans expire, after `batch_plan_ttl_minutes`.
- **Capabilities:**
  - `accept` is allowed for INCREASE and DECREASE.
  - `keep_bidding` is allowed for everything except REVIEW.
  - `override` is allowed for INCREASE and DECREASE, and for HOLD when `allow_hold_override` is set.
  - REVIEW proposals cannot be decided in the MVP.
  - When a proposal already has a final decision in the session, all capabilities are off.
- **Invalid provider rows** are stored as `INVALID` with their errors and are never coerced to HOLD. A set that fails
  contract checks is stored as `REJECTED` with no rows.
- **Concurrency:** the decision, its audit event and its idempotency record are written in one transaction, with the
  recommendation row locked (`FOR UPDATE`). A partial unique index allows only one final decision per proposal per
  demo session.
- **About the many REVIEW proposals in mock data:** the ported controller returns REVIEW when local D/S is below `q_min`,
  which happens at night when demand is zero. This is expected controller behaviour, not a bug.

## Tests

```bash
uv run pytest                 # unit + integration + e2e (integration needs TEST_DATABASE_URL)
uv run pytest tests/unit      # no database needed
```

Integration tests rebuild the schema of the database named in `TEST_DATABASE_URL` and refuse to run unless its name
ends in `_test`. They then seed a small synthetic snapshot set, so they do not depend on the active dataset.
They cover BE-01 to BE-24, including concurrent decisions, an injected audit failure, and resuming an interrupted
batch. The E2E test runs the 14-step flow from spec §15.4. If the sandbox blocks the system temp directory, add
`--basetemp <dir>`.

## Not in scope yet

- Online GNN inference (`app/providers/gnn_adapter.py` stays a stub; the MVP uses precomputed proposals).
- Switching the frontend (`ui/app`) from `ui/data.json` to this API.
- Open decisions: TD-06 (HOLD override, behind a config flag), TD-08 (limit values), TD-09 (retention).
