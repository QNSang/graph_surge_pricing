<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **graph_surge_pricing** (7224 symbols, 12168 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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

- Data, feature, label, or D/S work: read `docs/data/metadata.md` first (tables, columns, D/S definition, coding rules), then `data/CURRENT.json` and the release's `schema.yaml`. Generation details are in `docs/data/mock_data_spec_hcmc.md` and `tools/mock_v2/README.md`. Never hardcode the dataset path, 61 days, or 8640 snapshots; read them from `data/CURRENT.json` and `meta/manifest.json`. Treat `oracle/` as diagnostics only, never model input. Archive old releases under `data/_archive/`; never delete them.
- Model, target, feature, controller, or surge-policy changes: read `docs/model/technical_report.md`, `pipeline/configs/feature_contract.json`, `pipeline/configs/benchmark_plan.json`, and `pipeline/configs/train.yaml`.
- ML pipeline, training, evaluation, or CLI changes: read the relevant files under `docs/ml_pipeline/` and the active pipeline configs.
- Frontend, page, component, visualization, or API-integration changes: read the relevant files under `docs/frontend/` plus the backend contract used by that UI.
- Stakeholder-facing output or business claims: read the relevant files under `docs/stakeholder/` and verify claims against the technical report and current code.
- Documentation maintenance: use `gsd-docs-update` when the request is a broader documentation generation or verification task.

Read only the documentation needed for the task, but follow cross-references needed to resolve the contract. Treat live code and executable configs as implementation evidence; if they disagree with a specification or report, do not silently choose one—identify the mismatch, determine the intended source of truth from the task context, and keep code, configs, tests, and docs synchronized.
