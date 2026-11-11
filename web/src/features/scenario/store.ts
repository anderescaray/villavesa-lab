/**
 * The working scenario, shared by the whole app (M8). A scenario is an ordered list of edits
 * (docs/api.md); the server is stateless and caches results by the hash of the list.
 *
 * - Persisted to localStorage (edits + name), so a page reload keeps the user's work.
 * - Undo/redo over the edit list (bounded history, not persisted).
 * - `peekBaseline` temporarily shows today's network without discarding the edits.
 * - The Optimizer loads its proposal with `setEdits`; Compare reads `edits`.
 */
import { useMemo } from 'react';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import { asEdits, type ScenarioEdit } from '@/api/scenario';
import type { Edit } from '@/api/types';

const HISTORY = 100;

export interface ScenarioState {
  edits: ScenarioEdit[];
  name: string;
  past: ScenarioEdit[][];
  future: ScenarioEdit[][];
  /** show the baseline everywhere while keeping the edits */
  peekBaseline: boolean;
}

export interface ScenarioActions {
  add: (edit: ScenarioEdit) => void;
  update: (index: number, edit: ScenarioEdit) => void;
  remove: (index: number) => void;
  clear: () => void;
  setEdits: (edits: ScenarioEdit[], name?: string) => void;
  setName: (name: string) => void;
  undo: () => void;
  redo: () => void;
  setPeek: (peek: boolean) => void;
}

const commit = (s: ScenarioState, edits: ScenarioEdit[]): Partial<ScenarioState> => ({
  edits,
  past: [...s.past, s.edits].slice(-HISTORY),
  future: [],
  peekBaseline: false,
});

export const useScenario = create<ScenarioState & ScenarioActions>()(
  persist(
    (set, get) => ({
      edits: [],
      name: '',
      past: [],
      future: [],
      peekBaseline: false,
      add: (edit) => set((s) => commit(s, [...s.edits, edit])),
      update: (index, edit) =>
        set((s) =>
          index < 0 || index >= s.edits.length
            ? {}
            : commit(
                s,
                s.edits.map((e, i) => (i === index ? edit : e)),
              ),
        ),
      remove: (index) =>
        set((s) =>
          commit(
            s,
            s.edits.filter((_, i) => i !== index),
          ),
        ),
      clear: () => {
        if (get().edits.length) set((s) => ({ ...commit(s, []), name: '' }));
      },
      setEdits: (edits, name) => set((s) => ({ ...commit(s, [...edits]), name: name ?? s.name })),
      setName: (name) => set({ name }),
      undo: () =>
        set((s) => {
          const prev = s.past[s.past.length - 1];
          if (!prev) return {};
          return {
            edits: prev,
            past: s.past.slice(0, -1),
            future: [s.edits, ...s.future].slice(0, HISTORY),
            peekBaseline: false,
          };
        }),
      redo: () =>
        set((s) => {
          const next = s.future[0];
          if (!next) return {};
          return {
            edits: next,
            past: [...s.past, s.edits].slice(-HISTORY),
            future: s.future.slice(1),
            peekBaseline: false,
          };
        }),
      setPeek: (peekBaseline) => set({ peekBaseline }),
    }),
    {
      name: 'vlab.scenario.v1',
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ edits: s.edits, name: s.name }),
      merge: (persisted, current) => {
        const p = persisted as Partial<ScenarioState> | undefined;
        return {
          ...current,
          edits: Array.isArray(p?.edits) ? p.edits.filter(isEditLike) : [],
          name: typeof p?.name === 'string' ? p.name : '',
        };
      },
    },
  ),
);

function isEditLike(e: unknown): e is ScenarioEdit {
  return !!e && typeof e === 'object' && typeof (e as { type?: unknown }).type === 'string';
}

/** Canonical JSON (sorted keys) — the same edit list always yields the same string. */
export function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    const o = value as Record<string, unknown>;
    return `{${Object.keys(o)
      .filter((k) => o[k] !== undefined)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical(o[k])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

/** Stable, short hash of an edit list (FNV-1a 32-bit over the canonical JSON). */
export function scenarioHash(edits: readonly ScenarioEdit[]): string {
  if (!edits.length) return 'baseline';
  const str = canonical(edits);
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return `s${(h >>> 0).toString(36)}${str.length.toString(36)}`;
}

/** The edits the rest of the app should render: null = baseline (no edits, or peeking). */
export function useActiveScenario(): Edit[] | null {
  const edits = useScenario((s) => s.edits);
  const peek = useScenario((s) => s.peekBaseline);
  return useMemo(() => (edits.length && !peek ? asEdits(edits) : null), [edits, peek]);
}
