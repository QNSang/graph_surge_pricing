<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **graph_surge_pricing** (9858 symbols, 16349 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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

<!-- active-duocast-routing -->

Current implementation: read `docs/implementation/PIPELINE_REFACTOR_STATUS.md`, `pipeline/README.md` and `pipeline/DATA_INPUTS.md`. Active modules use `train/duocast`, `train/responses` and `inferences`. DuoCast checkpoints must satisfy the active architecture and semantic contract. Official-data eligibility is still a separate gate.

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

Project-specific document routing is maintained in `AGENTS.md` under the heading with this name. Read and follow that routing alongside the GitNexus and skill rules above; do not maintain a second conflicting list of legacy paths here.

Start with `docs/README.md`, `docs/ai-context/READ_FIRST.md`, `docs/ai-context/CURRENT_STATE.md`, and `docs/implementation/TASKS.md`. Then load only the relevant module specification and contracts. Use `docs/implementation/DECISION_LOG.md` for unresolved decisions and `docs/ai-context/KNOWN_ISSUES.md` for stale historical references.

The active forecast route is DuoCast. Do not equate request demand with confirmed booking demand, equate idle supply with capacity, or map legacy ratio/controller outputs to GGSO decisions. The local design reference is an extract; provenance is in `docs/technical_report/README.md`.

Read Git status before edits and preserve pre-existing modifications/deletions. Never hardcode dataset paths/days/snapshot counts; inspect the selected active configuration and dataset metadata. Legacy workflows may use `data/CURRENT.json` and a release manifest; do not mix their contracts with DuoCast inputs. Treat `oracle/` as diagnostics only, never model input; preserve old releases and never delete them as cleanup.

Use `gsd-docs-update` for documentation maintenance when available; otherwise use source review, narrow edits, read-back and diff inspection. For docs-only requests, change Markdown only: no code/config/schema/test/data edits, training, service execution, publication, or restoration of removed legacy documents. A task in the backlog does not authorize implementation.

Live code/configs are implementation evidence; reports/specifications describe intended design. Identify mismatches explicitly and keep approved contracts, implementation, tests, and docs synchronized only within the user's authorized scope. Preserve the generated GitNexus block and other skill-routing rules above.
