# Network Console implementation — 12/10/2026

## Scope and reference

Implemented the approved Graph Surge screenshot direction in `ui/app`: dark navy, orange/cyan/slate/violet recommendation colors, top navigation, upper map/selected-hex split, lower queue/network-connections split, and a full-width replay strip. `App.tsx` now renders `NetworkConsole` while retaining existing playback, scenario publication and initial-selection hooks.

The screenshot is a visual reference only. Hex IDs, counts, positions, price values, timestamps, reasons and OD volumes come from existing project data/adapters. No screenshot numbers, fake uplift, fake forecast horizons or production execution claims are introduced.

## Files

- `ui/app/src/App.tsx`: new console entry; existing playback and selection hooks retained.
- `ui/app/src/components/console/NetworkConsole.tsx`: header, selected hex, observed base-surge mini chart, actions, queue, Incoming/Outgoing table and replay controls.
- `ui/app/src/components/console/NetworkMap.tsx`: actual H3 polygon geometry, curved directed OD relations, independent layer toggles, selection, pan/zoom, optional animation, map attribution and graceful tile failure handling.
- `ui/app/src/components/console/network.ts`: presentation-only helpers for completed-window OD, visibility limits, geometry and value formatting.
- `ui/app/src/styles/network-console.css`: responsive reference layout and palette, scoped to the new console, with reduced-motion behavior.
- `ui/app/src/__tests__/networkConsole.test.ts`: seven test cases for palette, completed OD windows, invalid records, hybrid visibility, geometry and missing-value formatting.
- `ui/app/src/components/map3d/` (13/10/2026, 3D map):
  - `MapSlot.tsx`: lazy-loads the 3D map behind Suspense and an error boundary. It defaults to 3D when WebGL2 is available, keeps the SVG `NetworkMap` as the 2D mode and no-WebGL fallback, and persists the mode in `localStorage` (`gc.mapMode`, read and written inside try/catch).
  - `Surge3DMap.tsx`: MapLibre map plus a deck.gl `MapboxOverlay` (interleaved). Handles picking and tooltips, the toolbar (3D/2D, OD Flow, Animate flows), zoom/Fit All/Focus Selected/Reset, the legend, the intro reveal, the selection halo, particles and reduced motion.
  - `layers.ts`: the deck layers — shadow, footprint, extruded columns, selected outline/halo, REVIEW `!` marker, OD arcs and arrowheads, particles.
  - `scale.ts`, `palette.ts`, `odGeometry.ts`, `camera.ts`, `focus.ts`: pure helpers. `focus.ts` is a small bus, so fly-to fires only from queue clicks.
- `ui/app/src/__tests__/map3d.test.ts`: height scale, arc geometry, edge roles and widths, palette disjointness.

## Renderer and basemap

**Update 13/10/2026:** the console map now has a GPU 3D mode. It uses **MapLibre GL 6.11.2 and deck.gl 9.4.0** (`@deck.gl/core`, `@deck.gl/layers`, `@deck.gl/mapbox`, `@luma.gl/core`), all pinned exactly in `ui/app/package.json`. The SVG `NetworkMap` stays in place as the 2D mode and as the fallback when WebGL2 is missing or the 3D map throws.

Integration notes:
- MapLibre 5.x is affected by advisory GHSA-jrc7-96c5-q579, so we stay on 6.x. `npm audit` reports 0 vulnerabilities.
- deck.gl 9.4 reads `map.transform`, which MapLibre 6 moved to `map._camera.transform`. `Surge3DMap.tsx` adds a getter only when `map.transform` is missing. This shim relies on a private MapLibre field: re-check it when upgrading either library, and remove it once deck.gl supports MapLibre 6 natively.
- luma.gl 9.4.2 resizes its default framebuffer only when it resizes the canvas itself. MapLibre owns the canvas, so after a container resize (window resize, layout change) deck kept drawing into the old-size viewport: columns shrank towards the bottom-left and everything above the old height was cut off. `Surge3DMap.tsx` resizes that framebuffer to the canvas on MapLibre `resize` and on deck `onResize`, then repaints. This relies on private luma fields (`__deck`, `canvasContext._framebuffer`): re-check on upgrade and remove once luma handles externally sized canvases.
- The worker is loaded through `maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url` plus `setWorkerUrl`, which Vite needs.
- The 3D bundle is code-split with `React.lazy`. Vite's chunk-size warning for that chunk is expected.

Display semantics (scale `demo-v1`):
- Column height is `clamp(|delta_applied| / 0.40, 0, 1) × 180 m`, so +x and −x give the same height.
- HOLD and REVIEW are flat. REVIEW and any non-finite or missing delta show a `!` marker and never get a column.
- Height is the size of the proposed correction after policy limits. It is **not** model confidence, market quality or impact. The legend says so on screen.
- Color always follows `proposal.status`: INCREASE `#F0643B`, DECREASE `#12A3C9`, HOLD `#AEB7C4`, REVIEW `#8B6CF0`. Accepting a proposal changes neither color nor height.
- OD colors are incoming `#0D9488` and outgoing `#DB2777` (pink; changed from the spec indigo `#4F46E5`, which read too close to REVIEW violet `#8B6CF0`). They are disjoint from the recommendation colors and represent hourly request flow, not a causal effect of the model.
- The tooltip shows `Visual height: N% of configured scale`.

Palette tokens: `--increase`, `--decrease` and `--review` in `tokens.css` and `network-console.css` now use the colors above. REVIEW changed from amber `#f3ab1b` to violet. `network.ts` `ACTION_COLORS`/`OD_COLORS` re-export `map3d/palette.ts`, so the 2D and 3D maps share one source.

Camera and motion:
- Pitch 42°, bearing 10°. Fit is 600 ms; fly-to is 700 ms and triggers only from the queue. Panning never auto-recenters.
- Columns reveal ring by ring once on load. Height and color changes on replay transition over 350–500 ms. Selection shows a one-shot halo.
- OD particles are off by default and purely symbolic.
- With `prefers-reduced-motion`, all of the above is disabled and the Animate control is greyed out.

The default raster basemap uses standard OpenStreetMap tiles with visible attribution, transformed visually into a dark low-contrast background. Only visible tiles are requested; there is no offline/bulk downloader. Network access is required for streets, but H3 polygons, edges, queue and actions do not depend on successful tile loads. Map requests reveal the viewed tile area to the tile provider; no rider/driver identifiers or model feature payloads are sent.

Optional Vite environment configuration:

```env
# Disable external tiles for an offline/private environment:
VITE_BASEMAP_PROVIDER=none
# Or use an approved compatible raster tile template:
# VITE_BASEMAP_TILE_URL=https://approved-provider.example/{z}/{x}/{y}.png
# VITE_BASEMAP_ATTRIBUTION=Your required provider attribution
```

A hosted production map provider, its terms and quotas remain a separate deployment decision.

## Data and workflow boundaries

- Uses existing `DATASET`, snapshot/decision store, `OverrideDrawer`, `BatchReview`, `AuditLog` and tested base-history adapter.
- OD records use only the completed hour before cutoff. Self-loops and zero-flow records are not rendered as inter-hex flow. Invalid records are omitted and counted.
- Incoming/outgoing edge colors are distinct from recommendation colors. OD volume means request-flow aggregate, not tracked drivers or causal model contribution.
- Connection distance is labeled approximate straight-line centroid distance, not route distance. Trend is shown only when the previous completed-hour record exists.
- The detail panel has one **Insight** tab (plus Recommendations in the map view), replacing the former Explanation and Network tabs and their summary boxes. It shows:
  - Market: demand and effective supply now vs the previous 5-minute snapshot (pale bar = previous, solid = now, shared axis), with both timestamps labelled. D/S history stays in the chart under the map;
  - OD flow: a diverging total (incoming left, outgoing right) and one row per partner hex with an in/out bar for the last completed hour. A bar selects that edge on the map; the hex id selects the partner. The top 5 rows show by default, and the list expands when a lower-ranked edge is selected;
  - Last 1h line for the selected hex: same Dem, Short and Share figures as the queue columns;
  - Reasons & data provenance, collapsed.
  All values come from the existing snapshot and OD data; nothing new is derived for display.
- The compact Recommendation Queue shows one line per hex: short H3 id (the six unused res-7 `f` digits removed; full id and zone in the tooltip), surge base → proposed, Δ, **Short 1h** and **Share**. Computed in `console/marketScale.ts` from snapshots at or before the cutoff only:
  - Short 1h = Σ max(0, demand − effective supply) per 5-minute window over the last 12 windows, in requests. Surplus windows do not offset shortage. The bar uses neutral slate, not a recommendation color;
  - Share = the hex's share of city demand from the first snapshot of the day up to the cutoff.
  - Surge values in the compact queue omit the × suffix (the Surge header tooltip says it is a multiplier). Share is shown as an amber chip whose intensity is the hex's share relative to the largest share in the city; amber is not a recommendation or OD color.
  - A **Surge 1h** column after Hex shows a sparkline of the observed base (bidding) surge over the last hour up to the cutoff (13 points at 5-minute steps). It comes from `buildSurgeHistory`, the same source as the Surge History chart. It is drawn as a blue step line (`#2f6fde`, the same for every row and not a recommendation, OD or Share color) with a light fill. It breaks on missing values or gaps and marks the current value with a dot. Its width follows the queue panel width through a container query: 36 px when narrow, 56 px from 400 px, 72 px from 500 px. The scale is per row with a 0.20 minimum span. It shows no proposed surge and no forecast (`console/QueueSparkline.tsx`).
  - The per-row Accept column is removed from the compact queue. Accept happens through the checkboxes plus Accept Selected or Accept All. A decided row shows its status icon in the checkbox cell.
  - Short 1h and Share headers sort descending; clicking again returns to queue priority order.
  - GMV is not shown: the dataset does not generate GMV (`docs/data/metadata.md`). A GMV share can replace or join Share once the backend provides a per-hex GMV field.
- The action bar no longer prints the HOLD and REVIEW lock messages (`HOLD_NO_ACTION`, `REVIEW_MANUAL_ONLY`, `REVIEW_BLOCKED`). The buttons stay disabled exactly as before, and the other lock messages (replay, superseded, expired, offline, contract) still show.
- REVIEW proposal values are not offered for acceptance or override. Existing capability checks and demo service revalidation remain in place.
- Accept All reviews the fixed eligible set for the current snapshot, not only visible/filter-matching rows. Accept Selected uses the selected IDs/versions. Both retain the existing batch confirmation dialog.
- Manual edits reuse the existing decision workflow and do not overwrite original proposals or base history.
- The existing frontend's REPLAY mode is still read-only. This UI update does not implement the separate backend spec's planned demo-session replay writes.
- Decision History groups the decisions sent in one Accept Selected / Accept All action into one collapsible entry. The entry shows the hex count, per-status counts, and the cutoff and versions shared by the group. Grouping uses the `batch_key` that `submitBatch` already creates (now kept on each `AuditEvent`), not timestamps, so separate single accepts made in the same minute stay separate. The log is still append-only, and grouping only affects how it is displayed (`domain/auditGroups.ts`).
- Each History row reads `<short hex id>: Xác nhận tăng|giảm <base> → <requested>` (likewise `Điều chỉnh` for manual edits). The zone and full id are in the tooltip. The base is the proposal's `s_bid` when the request was made, kept client-side in the store (`baseAtRequest`) and not sent to the service. Up or down comes from comparing requested with base. When base is unknown, the row falls back to the plain action label.
- History rows drop the "demo" markers from the status label, actor and version ids (for example `demo-policy.v1.2-illustrative` shows as `policy.v1.2-illustrative`). This is display only: stored events, ids and other labels are unchanged, the full actor and versions stay in the tooltip, and the console still shows DEMO mode elsewhere.
- Decision history still has the persistence guarantees of the existing demo store; this update does not claim a new backend connection or durable persistence across reloads.
- The Latest button is not labeled Live production. The UI explicitly identifies synthetic/demo forecasts.

## Verification status

Updated 13/10/2026 in `ui/app`:

- `npm run typecheck`: pass.
- `npm test`: 73 tests pass (includes `map3d.test.ts` and `auditGroups.test.ts`).
- `npm run build`: pass (chunk-size warning only).
- Browser check: Vite dev server driven by Playwright with headless Chromium on SwiftShader, at 1440×900 and 1280×720, with no console errors. Checked:
  - extruded columns and colors;
  - tooltips;
  - fly-to from the queue;
  - OD arcs with role colors and arrowheads;
  - replay updates height and color while keeping the selection;
  - particles toggle;
  - 2D/3D switch;
  - reduced motion disables Animate;
  - with WebGL disabled, the 2D fallback is shown and the 3D switch is disabled;
  - Insight tab charts, and that clicking an OD bar selects the edge (`aria-pressed`).
- Not measured: FPS, and real-GPU performance. First 3D load under SwiftShader takes about 5–8 s, which depends on the environment.

No model, training pipeline, dataset, backend, surge guardrails or production pricing were changed. No Git commit or deployment was performed.

To inspect locally, open a terminal in `ui/app`, run `npm run dev`, and open the URL reported by Vite. The legacy `ui/dashboard.html` is not the updated React app.
