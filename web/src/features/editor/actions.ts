/**
 * Imperative editor actions shared by the panel, the map and the keyboard: upserting edits,
 * starting/finishing the new-line draft.
 */
import type { Period, ScenarioEdit, SetHeadwayEdit } from '@/api/scenario';
import { useScenario } from '@/features/scenario/store';
import { buildAddRoute, type DraftStopRow } from './useDraft';
import { emptyDraft, useEditor } from './state';

/** Latest ordered stop rows of the draft (written by `useDraftStops`). */
let draftRows: DraftStopRow[] = [];
export const setDraftRows = (rows: DraftStopRow[]) => {
  draftRows = rows;
};

/** Index of the `set_headway` edit of a line and period (one per pair). */
export const headwayEditIndex = (edits: ScenarioEdit[], routeId: string, period: Period) =>
  edits.findIndex((e) => e.type === 'set_headway' && e.route_id === routeId && e.period === period);

export function upsertHeadway(routeId: string, period: Period, headway: number) {
  const sc = useScenario.getState();
  const edit: SetHeadwayEdit = { type: 'set_headway', route_id: routeId, headway, period };
  const i = headwayEditIndex(sc.edits, routeId, period);
  if (i >= 0) {
    const cur = sc.edits[i] as SetHeadwayEdit;
    if (cur.headway !== headway) sc.update(i, edit);
  } else sc.add(edit);
}

export function startDraft(shortName: string, color: string) {
  useEditor.getState().set({
    tool: 'draw',
    draft: emptyDraft(shortName, color),
    routeId: null,
    stopId: null,
  });
}

/** Commit the draft as one `add_route` edit. Returns false when it is not complete. */
export function finishDraft(): boolean {
  const ed = useEditor.getState();
  if (!ed.draft) return false;
  const sc = useScenario.getState();
  const edit = buildAddRoute(ed.draft, draftRows, sc.edits);
  if (!edit) {
    window.dispatchEvent(new CustomEvent('vlab:editor-draft-incomplete'));
    return false;
  }
  sc.add(edit);
  ed.set({ draft: null, tool: 'select' });
  return true;
}

export function cancelDraft() {
  useEditor.getState().set({ draft: null, tool: 'select' });
}

export function popWaypoint() {
  const ed = useEditor.getState();
  const d = ed.draft;
  if (!d) return;
  if (d.placeStops && d.newStops.length) ed.setDraft({ newStops: d.newStops.slice(0, -1) });
  else if (d.waypoints.length) ed.setDraft({ waypoints: d.waypoints.slice(0, -1) });
}
