<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **graph_surge_pricing** (8332 symbols, 13975 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/graph_surge_pricing/context` | Codebase overview, check index freshness |
| `gitnexus://repo/graph_surge_pricing/clusters` | All functional areas |
| `gitnexus://repo/graph_surge_pricing/processes` | All execution flows |
| `gitnexus://repo/graph_surge_pricing/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

## Skill and documentation routing

Before implementing, reviewing, debugging, or refactoring, inspect the skills available in the current session and use the smallest relevant set. Read each selected `SKILL.md` completely before taking task actions. If a referenced skill is unavailable, state that briefly and continue with the safest equivalent workflow.

### Backend and codebase work

- Use `gitnexus-exploring` to understand unfamiliar services, execution flows, and dependencies before editing.
- Use `gitnexus-impact-analysis` before changing symbols, `gitnexus-debugging` for defect investigation, and `gitnexus-refactoring` for structural changes.
- Use `gsd-code-review`, `gsd-debug`, or `gsd-secure-phase` when the task specifically requires code quality review, systematic debugging, or security verification.
- Trace the complete request/data flow and preserve existing API, schema, error-handling, validation, and observability contracts.

### Database work

- Use `postgresql-table-design` for PostgreSQL schemas, constraints, indexes, and data modeling.
- Use `sql-optimization-patterns` for query plans, indexing strategy, and SQL performance work.
- Use `database-migration` for schema migrations, rollback planning, and migration safety.
- Before changing persistence behavior, inspect the current schema, migrations, ORM models, queries, and affected backend callers. Never infer a database contract from UI code alone.

### Frontend work

- For existing UI improvements, prefer `redesign-existing-projects` together with the most appropriate design skill.
- Use `design-taste-frontend`, `gpt-taste`, `high-end-visual-design`, `minimalist-ui`, `industrial-brutalist-ui`, `stitch-design-taste`, or `impeccable` according to the requested visual direction; do not combine unrelated styles by default.
- Use `image-to-code` when implementing from a visual reference, and `imagegen-frontend-web` or `imagegen-frontend-mobile` when new visual assets are required.
- Preserve the project's component system, responsive behavior, accessibility, loading/error/empty states, and backend data contracts.

### Project documentation to read when relevant

- Start with `docs/README.md`, `docs/ai-context/READ_FIRST.md`, `docs/ai-context/CURRENT_STATE.md`, and `docs/implementation/TASKS.md`. Read Git status before edits; preserve pre-existing changes and deletions. A planned task does not authorize implementation by itself.
- Data, features, labels, or D/S: read `docs/contracts/DATA_SCHEMA.md`, `docs/contracts/MODEL_IO_CONTRACT.md`, the active pipeline README/config, and the selected dataset's metadata. The active GeoMobiNet config is `pipeline/configs/geomobinet.yaml`; legacy workflows may resolve data through `data/CURRENT.json` and the release manifest. Do not mix their data contracts or hardcode paths, days, or snapshot counts. Treat `oracle/` as diagnostics only, never model input; preserve old releases and never delete them as cleanup.
- Forecast/model work: read `docs/model/forecasting_contract.md`, the preserved handoff `docs/model/duocast_model.md`, and `pipeline/README.md`. Revised design agreed 2026-10-17: DuoCast uses a Temporal GRU, Spatial GATv2, directed Mobility GATv2, gated fusion, and independent demand/supply heads; it has no separate Geo Encoder or static-geography input. The current GeoMobiNet implementation/config may still contain a static-geo branch and must not be relabeled as DuoCast without explicit adaptation plus data/code/checkpoint parity. Demand is confirmed valid booking requests, and GGSO v1 effective available supply is the online idle dispatch-eligible driver stock (not capacity K). Q/capacity details remain open in GD-02/03.
- GGSO response/candidate/optimization: read the relevant files under `docs/model/`, their contracts under `docs/contracts/`, and `docs/technical_report/GGSO_DESIGN_REFERENCE.md`. Read `docs/technical_report/README.md` for provenance: the design reference is an extract, not the full report. Preserve source equations and explicitly record missing estimator, support, pricing, or solver settings in `docs/implementation/DECISION_LOG.md`.
- ML pipeline, training, evaluation, or CLI: read `pipeline/README.md`, active config/source, `docs/implementation/IMPLEMENTATION_PLAN.md`, and relevant files under `docs/evaluation/`. The default CLI dispatches to GeoMobiNet; legacy commands require their explicit route. Do not infer test results or run training from a docs request.
- Backend/decision integration: read `docs/backend/decision_pipeline.md`, `docs/contracts/CANDIDATE_POLICY_CONTRACT.md`, and `backend/README.md`; inspect actual consumer contracts. Whole-network GGSO validation certifies only the full optimized recommendation. GD-07 permits Accept Selected and manual one-hex edits through backend per-hex safeguards without immediate network revalidation/re-optimization. Those operator actions are not guaranteed to satisfy the original network BR/no-loss certificate. At the next 5-minute decision, GGSO uses current effective pricing from a new snapshot and recommends again. No production-mode change/publication without explicit authorization.
- Frontend/page/component/visualization: read `docs/frontend/` plus the actual backend contract. Preserve historical docs; do not fabricate legacy ratio/Pressure/Revision fields from new forecast outputs. Read known issues for stale historical cross-references.
- Business claims: use the source register/design reference, evaluation protocol, and actual experiment artifacts. Estimated GMV is not realized causal uplift; missing results remain missing.
- Documentation maintenance: use `gsd-docs-update` when available; otherwise read sources, edit narrowly, and inspect read-back/diffs. For docs-only requests, edit Markdown only; do not change code, configs, schemas, tests, data, or runtime state. Do not restore removed legacy docs merely to satisfy old links.

Read only the documentation needed for the task and relevant cross-references. Live code/configs describe implementation evidence; source reports/specs describe intended design. Record mismatches in `docs/implementation/DECISION_LOG.md`, not silent algorithm or semantic changes. Keep approved contracts, implementation, tests, and docs synchronized when the task authorizes those changes. Preserve the generated GitNexus block and existing skill-routing rules above.
