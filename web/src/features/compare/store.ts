/**
 * Compare view UI state: which scenario is compared (the editor's or the optimizer's last
 * proposal), what the map shows, where the swipe divider is, and the report form.
 */
import { create } from 'zustand';

export type CompareSource = 'store' | 'optimizer';
export type CompareMode = 'network' | 'access' | 'delta';

export interface CompareState {
  /** null = automatic: the editor's scenario when it has edits, else the optimizer's proposal */
  source: CompareSource | null;
  mode: CompareMode;
  category: string;
  /** swipe divider position, 0..1 of the visible map area */
  split: number;
  reportTitle: string | null;
  reportLang: 'es' | 'en' | null;
  setSource: (s: CompareSource | null) => void;
  setMode: (m: CompareMode) => void;
  setCategory: (c: string) => void;
  setSplit: (v: number) => void;
  setReport: (patch: { title?: string | null; lang?: 'es' | 'en' | null }) => void;
}

export const useCompare = create<CompareState>()((set) => ({
  source: null,
  mode: 'network',
  category: 'hospital',
  split: 0.5,
  reportTitle: null,
  reportLang: null,
  setSource: (source) => set({ source }),
  setMode: (mode) => set({ mode }),
  setCategory: (category) => set({ category }),
  setSplit: (v) => set({ split: Math.min(0.98, Math.max(0.02, v)) }),
  setReport: (p) =>
    set((s) => ({
      reportTitle: p.title !== undefined ? p.title : s.reportTitle,
      reportLang: p.lang !== undefined ? p.lang : s.reportLang,
    })),
}));
