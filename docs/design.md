# Design system: villavesa lab web

This document covers how the web app looks and behaves, and how to extend it. The source of
truth for values is the code. This doc explains the choices behind them.

- Tokens: `web/src/styles/tokens.css`
- Data-viz palettes: `web/src/lib/palettes.ts`
- Primitives: `web/src/components/ui/`
- Live gallery (dev only): `npm run dev`, then `/#/dev/components`
- Screenshots: `docs/screenshots/` (`npm run screenshots`)

## Principles

1. **The map is the hero.** It stays mounted edge to edge behind every view. All other UI is
   either the slim side panel (360 px) or a small floating surface over the map: the time
   control, map controls, top-right cluster and isochrone card.
2. **Data in front, basemap behind.** The OpenFreeMap *positron* style is re-themed at load
   time (`map/basemap.ts`) to make the basemap quieter. Labels get muted ink and roads become
   white-on-grey (light) or grey-on-black (dark). Water and parks get a slight tint. Both
   themes come from the same source style, so they read as one product. Network layers sit
   above neighbourhood labels and below settlement names.
3. **One accent, used sparingly.** Villavesa red is used only for the primary action (play),
   the active nav item, the playhead and the isochrone origin pin. Everything else is neutral.
4. **Dense but calm.** We use hairline dividers instead of cards, an 8 px grid and tabular
   numerals for every metric. Each view has one primary action.
5. **Motion explains state changes.** Durations are 150/200/250 ms with one easing. Isochrone
   bands reveal smallest first and crossfade when the origin moves. Numbers tween. All motion
   respects `prefers-reduced-motion`, and the clock also starts paused in that mode.
6. **Honest UI.** Limitations from `/api/meta.data_notes` (gravity-model demand, dasymetric
   population, activity proxy, timetable-based times; translated by `key`) are always one click away under *About the data*. The UI never renders an
   unknown value as zero; it shows "—".

## Tokens

| Group      | Values                                                                                                           |
| ---------- | ---------------------------------------------------------------------------------------------------------------- |
| Type       | Inter Variable (self-hosted via `@fontsource-variable`), scale 11/12/13/14/16/20/28, body 13 px; weights 420/520/600; `cv11 ss01 ss03`; tabular nums for metrics |
| Space      | 4 px half-step, then 8/12/16/20/24/32/40/48                                                                      |
| Radius     | 4 (chips, badges), 6 (small controls), 8 (controls), 12 (floating surfaces)                                       |
| Controls   | 24/28/32/40 px heights; icons are lucide at 16 px with a 1.5 stroke                                              |
| Elevation  | `--shadow-float` (hairline ring plus one soft shadow) for map surfaces; `--shadow-overlay` for popovers and dialogs. Nothing else has a shadow |
| Motion     | `--dur-fast` 150 ms, `--dur` 200 ms, `--dur-slow` 250 ms; `--ease` cubic-bezier(0.2, 0, 0, 1), `--ease-out` for entrances |
| Accent     | light `#d0142c` (5.5:1 with white text), dark `#e02a40` (4.6:1 with white text); accent text `#c3122a` / `#ff6b7c` |
| Neutrals   | light: white surfaces, `#f5f6f7` sunken, ink `#0f1216` / `#555b65` / `#6c727c`. Dark (chosen, not inverted): `#0b0c0e` bg, `#131417` surface, `#1a1b1f` raised, ink `#eceef1` / `#a3a8b1` / `#8b919b` |

Contrast is enforced by tests. `src/lib/color.test.ts` parses `tokens.css` and asserts WCAG AA
(≥ 4.5:1) for every text role on every surface in both themes, and for button text on the
accent.

### Line colours

The GTFS `route_color` is used everywhere: map, chips, tooltips, line detail.

- **Badges** keep the exact GTFS colour. Their text uses the operator's `route_text_color` when
  it reaches AA. When it does not, we switch to near-black or white, and to pure black for
  mid-tones such as `#607C8C`. A test checks that all 45 colours in the feed reach AA. Very
  light colours get a hairline ring.
- **Map strokes** keep the same hue but are nudged in lightness until they clear a minimum
  contrast against the basemap (1.5:1 light, 2.2:1 dark), using `ensureContrast`. This keeps
  navy lines (L05, L18) visible on the dark map without inventing new colours.
- On shared corridors, more frequent lines draw on top (`line-sort-key` = trips per day). A
  background-coloured casing separates crossing lines. Hovering or selecting a line dims the
  rest to 16 % and redraws the line wider with its own casing. Corridor-aware line offsetting is
  a known gap (see below).

## Data-viz palettes (`lib/palettes.ts`)

All palettes were checked with the dataviz skill's palette validator
(`validate_palette.js`). That script checks single hue, monotone lightness, step gaps, and the
contrast of the end step against the surface.

| Palette                    | Light                                   | Dark                                    | Use |
| -------------------------- | --------------------------------------- | --------------------------------------- | --- |
| Isochrone (ordinal, 3)     | `#1c5cab` `#3987e5` `#86b6ef` (15→45 min) | `#5598e7` `#2a78d6` `#184f95`            | Nested isochrone bands. Passes ordinal checks on both surfaces (end step ≥ 2:1) |
| Sequential (continuous, 7) | `#cde2fb` → `#0d366b`                   | same ramp                               | Choropleths (M7). Light end may recede (continuous) |
| Diverging (3 + mid + 3)    | red arm `#b3262f…#f2a7a2`, grey `#eceef0`, blue arm `#9ec5f4…#1c5cab` | own steps, grey `#2a2d32` | Gains and losses (M8/M10) |

**Why these are colour-blind safe.** Each sequential or ordinal ramp is a single hue that
encodes order only through lightness, so the order survives every type of colour-vision
deficiency. The diverging pair is blue against red, with a neutral grey midpoint (no hue at
zero). It stays separable under deuteranopia and protanopia because the arms also differ in
lightness. Blue for isochrones was chosen because it does not compete with the accent red. It
also stays readable under the multicoloured line network, because the fills are translucent and
each band has a 1 px outline in its own step.

**Isochrone rendering.** The bands are nested polygons drawn as stacked translucent fills (light
0.30/0.20/0.12, dark 0.30/0.18/0.10), smallest band on top, plus hairline outlines. The stacking
darkens the inner band naturally. In dark mode the "more access = brighter" convention is
inverted on purpose, so the 15-minute core glows.

## Components (`components/ui`)

All primitives are accessible. They are built on Radix primitives where interaction is
non-trivial (tooltip, popover, dialog, select, toggle group, slider, switch, tabs), and every
one follows the token system.

| Component                         | Notes |
| --------------------------------- | ----- |
| `Button`                          | primary / secondary / ghost, sm / md |
| `IconButton`                      | always has a label, which doubles as the tooltip; optional shortcut hint |
| `SegmentedControl`                | single select with roving focus; used for speed, language, theme, direction and mode |
| `Select`                          | Radix select in popper mode |
| `Slider`, `Switch`, `Tabs`        | |
| `Tooltip`, `Popover`, `Dialog`    | Dialog focuses itself on open (no stray focus ring) |
| `Badge`, `LineBadge`              | `LineBadge` handles text contrast automatically |
| `Stat`, `AnimatedNumber`          | Number tweens write `textContent` (no re-render per frame); `Stat` shows signed deltas with icon + colour, never colour alone |
| `Skeleton`, `EmptyState`, `Toast` | Skeletons everywhere instead of spinners |
| `Kbd`, `Legend`                   | `Legend` has swatch and ramp variants; ink-coloured text |
| `SparkBars`, `MiniBarChart`       | Hand-rolled SVG. `MiniBarChart` has hover tooltips, a baseline hairline and no grid |
| `Surface`                         | the floating-surface container |

## Layout and responsiveness

- **≥ 1024 px:** a 56 px rail and a 360 px panel sit side by side. Floating UI centres on the
  remaining map area through the `--map-left` CSS variable.
- **< 1024 px (tablet):** the panel becomes an overlay drawer. It starts closed so the map is
  visible on load, and the first tap on the map closes it. The time control wraps the scrubber
  onto its own row. The isochrone card stays top-right with a bounded height.

## Interaction model

- **Click priority on the map:** bus → stop → line (3 px tolerance) → empty map, which drops an
  isochrone. Stops are only clickable where they are drawn.
- **Keyboard:** Space plays or pauses. ← / → step 5 min (Shift steps 1 min). `S` cycles speed.
  `1`–`5` switch views. `/` searches. Esc peels the selection back one layer (stop → isochrone →
  line → search). `[` toggles the panel, `T` the theme, `?` opens help.
- **URL:** view, line, direction, stop, day, time, language, isochrone origin and time, mode and
  play state are all kept in the hash (`app/url.ts`), so any state can be shared as a link.

## Architecture: how to add a view and a layer

```
src/
  api/          types.ts (mirror of docs/api.md), client.ts (only HTTP), queries.ts (TanStack Query)
  app/          store.ts (zustand UI state), url.ts, shortcuts.ts, preferences.ts, App.tsx
  map/          MapCanvas (single MapLibre map + deck.gl MapboxOverlay), basemap theming,
                deckRegistry (ordered deck layers), maplibreLayers helpers, camera
  features/     network/ (layers, buses, panel, line detail, interactions), isochrone/,
                time/ (clock + TimeControl), shell/ (rail, panel, top controls), views/, dev/
  components/ui primitives
  lib/          vehicles (interpolation engine), format, color, palettes, motion
  i18n/         dict.ts (es source, en/eu typed Record<MessageKey,string>), index.ts (useT)
```

**Adding a view (e.g. Accessibility, M7):**

1. Create `features/accessibility/AccessibilityPanel.tsx` (the panel content) and any map
   layers as separate null-rendering components.
2. In `features/shell/SidePanel.tsx`, render the panel for `view === 'accessibility'` instead of
   `PlannedView`.
3. Mount the layer components inside `<MapCanvas>` in `app/App.tsx`. Each one should read
   `useApp((s) => s.view)` and hide itself when its view is not active.
4. Add copy keys to `i18n/dict.ts`. The type system forces all three languages to have them.

**Adding a map layer:**

- *MapLibre (fills, lines, symbols):* write a null-rendering component that uses
  `useMapContext()`. Add sources and layers in an effect keyed on `styleVersion`, because theme
  changes reload the style. Push state changes with `setPaint` / `setFilter`. Insert below the
  network with `beforeId = ROUTE_LAYERS.casing`, or use `anchor` to sit above it.
- *deck.gl (points, animated or editable geometry):* build the layer and publish it with
  `deckRegistry.set(id, layer, DECK_ORDER.x)`. Per-frame layers subscribe to `clock` directly;
  see `BusesLayer.tsx`. Picking is available through `deckRegistry.pick`.
- *Before/after comparison (M10):* mount a second `MapCanvas` that shares the camera through
  `map.on('move')` sync, or clip a deck layer with a `ClipExtension` / scissor mask. The
  context-based design allows multiple map instances.

**Animation clock.** `features/time/clock.ts` is a vanilla zustand store advanced by a single
`requestAnimationFrame` loop. React components select coarse values such as the minute, so they
re-render at most once per simulated minute. Bus interpolation (`lib/vehicles.ts`) runs on flat
typed arrays and costs about 30 µs per frame for about 130 active buses (measured on the weekday
fixture), so the map is limited by GPU compositing, not JavaScript.

## Known gaps (design)

- No corridor-aware line offsetting yet. Lines on shared streets overlap, ordered by frequency.

## Development

```bash
cd web
npm ci
npm run dev             # proxies /api to http://localhost:8000 (override with VITE_API_PROXY);
                        # start the engine first: VLAB_SYNC_LOAD=1 uv run uvicorn vlab_api.main:app --port 8000
npm run lint && npm run typecheck && npm test && npm run build
npm run e2e -- --trace off   # Playwright: starts the REAL engine on :8100 + Vite with a blank basemap
npm run screenshots          # docs/screenshots/*.png (real engine + real tiles; ONLY=08 to filter)
```

## Accessibility view (M7)

Question it answers: *who can reach what by bus today, and who is left out?*

- **Window.** The clock sets the analysis time: its time snapped to the half hour is the
  window start (one hour, departures every 10 min, mean travel time per D-006). The clock pauses
  when the view opens and requests are debounced (250 ms) while scrubbing. The window is always
  spelled out (`Laborable · 08:00–09:00`). Day type comes from the time bar; the threshold
  (15/30/45/60 min) from the panel.
- **Map.** The 1,794 cells are a MapLibre `fill` under the network, with colours in
  `feature-state`. Two copies of the source (slots a/b) crossfade in 200 ms when the metric,
  category, threshold or window changes. While the next window computes, the previous map stays
  at 45 % opacity, so nothing flashes. Alpha is baked per cell from residents
  (`residentWeight`: hidden at 0, floor 0.32, saturating at 400 residents), so empty fields
  never dominate. Metrics (`features/accessibility/model.ts`):
  - *time to nearest destination*: 7 sequential-blue steps of 10 min plus a neutral grey for
    "> cap / unreachable". Short = most prominent: darkest on the light map, lightest on the dark
    map (same convention as isochrones);
  - *under-served*: neutral grey within the threshold, then the warm arm of the diverging palette
    for +10 / +20 / more-or-unreachable (not the accent red);
  - *activity in 30 min* (`jobs_30`) and *income per person* (equity context): sequential blue.
  Bus lines stay as quiet context (55 % opacity, thinner, no stops, no animated buses, no
  isochrones). POIs of the selected category are small ink dots with the name on hover. Cell
  hover gives an outline plus a tooltip (municipality, residents, time to nearest, activity,
  income).
- **Legend.** A floating surface at the bottom left holds the metric selector, the units, the bin
  edges and the opacity rule.
- **Panel.** It reads top to bottom as a story. A headline sentence carries the key number
  (animated, rounded to 100 people). A destination list follows, with a hairline bar, the share
  within the threshold and the median time; clicking a row selects the category for the map and
  charts, and essential categories are dotted. Next comes the cumulative curve (SVG, threshold
  marked, value labelled in the empty quadrant). Then equity: quintile bars with the
  overall-average tick, income ranges on hover, a plain-language reading of the concentration
  index (±0.03 dead band) and the under-served population across essential categories. A
  collapsed "About this analysis" holds the method and data notes.
- **States.** Skeleton on the first load. The previous content is dimmed while refetching. On
  error, an inline message with retry. While the engine is loading (502/503/504), queries retry
  quietly every 1.5 s. URL keys: `cat`, `metric`, `thr` (minutes) next to `day` and `t`.

## Scenario editor (M8)

Screenshots: `docs/screenshots/editor-*.png` (`node web/scripts/screenshots-editor.mjs` against a
running dev or preview server, `BASE_URL=…`).

- **One working scenario for the whole app.** `features/scenario/store.ts` (zustand, persisted
  to `localStorage` as `vlab.scenario.v1`) holds the ordered edit list, its name and undo/redo
  history. `useActiveScenario()` feeds the network, vehicles and isochrone hooks, so every view
  shows the edited network while edits exist. A "Scenario · N changes" chip in the top bar
  (`ScenarioChip`) is visible in every view. It peeks at the baseline (eye) or discards the
  scenario, and a discard can be undone. The Optimizer loads a proposal with `setEdits`.
- **Layout.** The side panel holds the change list (compact rows with a line badge, a readable
  summary, inline edit and delete) and the inspector of the active tool. The live impact sits on
  a floating card at the right of the map, so it is always visible while editing. The tool
  palette (Select · Frequency · Priority · Stop · Draw: `V F P S L`) is a vertical strip at the
  top-left of the map, with a one-line hint for the active tool. Esc peels back one layer at a
  time; ⌘/Ctrl+Z and ⇧⌘Z undo and redo.
- **Map treatment.** The base network goes quiet as in the analysis view, and buses are hidden
  so they do not compete with the data. Modified lines, the line under edit and the hovered line
  are redrawn wide with a casing. New lines get a dashed centre line, and removed lines are ghosted
  (grey, dashed) from the baseline geometry. Stops carry their state: removed (hollow, grey),
  added (solid ink), or moved (thick ring with a dashed tether to the original spot).
- **Delta choropleth.** The 200 m cells are coloured by Δ demand-weighted mean travel time on
  the diverging palette (`DIVERGING`). Blue means faster, red means slower, and there are 3 steps
  per arm with edges at 30 s, 1 min and 2 min. Cells with |Δ| < 30 s stay blank, so only
  meaningful change shows. Colours live in feature-state, and the layer dims to 40 % while the
  next evaluation computes.
- **Live diff.** `/api/scenario/evaluate` is called 300 ms after the last change, and results
  are cached by the canonical-JSON hash of the edit list. The previous numbers stay on screen,
  dimmed, while the next result loads, and `elapsed_ms` is shown in the card footer. Gains and
  losses always carry an arrow or a sign, so colour is never the only cue. A 422 from the API is
  shown inline with its message.
- **Drawing a line.** Each click adds a waypoint. Snapping is debounced (180 ms), and the raw
  polyline shows faintly under the snapped path while a request is in flight. Existing stops
  within the server's radius are proposed. Stops of the same name on both kerbs within 80 m count
  as one, because a bidirectional line reverses the stop list. Each proposed stop can be toggled
  off, and the "New stop" click mode adds stops of your own. Colours come from a candidate list
  picked greedily to be as far as possible (redmean distance) from every GTFS line colour and from
  each other.
- **Known gaps.** Stop drag uses MapLibre pointer events and has no touch support. The
  Accessibility view still requests the baseline (`scenario: null`). Edits are not in the URL;
  `localStorage` is enough per the brief.

## Optimizer view (M10)

One question, one primary action. The panel asks "With the same N buses, what is the best
network?" (the sentence follows the budget slider and unit) and exposes only: budget (fleet or
bus-hours, -20 % to +20 %), what may change (frequencies, stop consolidation, new lines, each
with a one-line explanation), the objective and the analysis window (read from the time control,
shown explicitly). Time limit lives under "Advanced". **Optimizar** is the only red button.

- **Running** shows the real stage list driven by the job's `stage` (ticks as stages complete),
  a quiet log and a small live SVG of the objective versus evaluations. Cancel only stops
  polling: the server has no cancel, and the UI says so.
- **Result** is revealed on the map as an animated diff (about 1.4 s, replayable, instant under
  `prefers-reduced-motion`): lines that gain frequency thicken and brighten, lines that lose it
  thin and fade, new lines draw themselves (`line-gradient`), removed stops shrink away, then the
  travel-time change choropleth (blue faster, red slower, only |change| >= 30 s) fades in. Line
  state is feature-state (`p`), so a frame is a few dozen `setFeatureState` calls. The base
  network steps back through `diffActive` in the app store.
- The panel headline uses animated numbers, followed by key deltas and a ranked explanation
  (line badge in GTFS colour, "every 11 min to every 7 min", buses freed or used, a bar for its
  contribution). Hover or focus an item to isolate that line on the map; click to frame it.
- **Budget versus benefit**: SVG chart, today's network as the red point at (today's budget, 0)
  so the "same buses, better network" gap is a dashed bracket; click a point to preview it.
  The sentence under it is computed (same-budget gain, break-even budget, diminishing returns).
- The last result, settings and curve persist in localStorage (`vlab.optimizer.v1`).

## Compare view (M10)

Compares today with the editor's scenario (or, when the editor is empty, the optimizer's last
proposal; a switch appears when both exist). The map area holds two MapLibre maps (today left,
scenario right) clipped by a draggable divider (`clip-path`, role slider: arrows, Shift for big
steps, Home/End). Their cameras follow the main map through a re-entrancy lock, so the zoom
buttons and drag on any map keep all in sync. Content: network (line width proportional to daily
trips), accessibility (time to the chosen destination each side) or the single difference map.
The panel has the before/after table, people gaining/losing, changed lines, a plain-language
change list and the report form (title, language; open, download, print/PDF via `/api/report`).
