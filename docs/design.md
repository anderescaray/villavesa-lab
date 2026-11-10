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
6. **Honest UI.** Limitations from `/api/meta.data_notes` (mock data, gravity-model demand,
   fleet estimate) are always one click away under *About the data*. The UI never renders an
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
- The mock isochrones (`web/mocks/`) are synthetic and visibly circular around stops. Their
  shape quality depends on the real engine.
- `data_notes` come from the API in English. They are not localised (see the proposed contract
  change in the M6 report).

## Development

```bash
cd web
npm ci
npm run fixtures        # build mock-API fixtures from data/raw/gtfs_tuc_pamplona.zip (git-ignored)
npm run dev:mock        # http://localhost:3000 with the mock API (VITE_MOCK_API=1)
npm run dev             # proxies /api to http://localhost:8000 (override with VITE_API_PROXY)
npm run lint && npm run typecheck && npm test && npm run build
npm run e2e -- --trace off   # Playwright, mock API + blank basemap (VITE_BASEMAP=none)
npm run screenshots          # docs/screenshots/*.png
```
