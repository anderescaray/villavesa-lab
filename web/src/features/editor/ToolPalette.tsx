/**
 * Floating tool palette of the editor (top centre of the map) with a one-line hint for the active
 * tool, and the editor's keyboard shortcuts (V F P S L, Esc, Enter, Backspace, ⌘Z / ⇧⌘Z). The
 * key handler runs in the capture phase so the editor's keys win over the global ones (S, Esc)
 * while this view is active.
 */
import { useEffect } from 'react';
import { useApp } from '@/app/store';
import { IconButton, Surface } from '@/components/ui';
import { useScenario } from '@/features/scenario/store';
import { useT, type MessageKey } from '@/i18n';
import { cancelDraft, finishDraft, popWaypoint, startDraft } from './actions';
import { TOOL_ICON } from './EditorPanel';
import { newLinePalette, nextLineName, useBaselineModel } from './model';
import { TOOLS, TOOL_KEYS, useEditor, type Tool } from './state';
import s from './Editor.module.css';

const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement &&
  (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));

function useStartDraw() {
  const base = useBaselineModel();
  return () => {
    const edits = useScenario.getState().edits;
    startDraft(
      nextLineName(edits, base?.routes.map((r) => r.short_name) ?? []),
      newLinePalette(base?.routes.map((r) => r.color) ?? [])[0]!,
    );
  };
}

export function useEditorShortcuts() {
  const active = useApp((st) => st.view === 'scenario');
  const startDraw = useStartDraw();
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (document.querySelector('[role="dialog"][data-state="open"], [role="listbox"]')) return;
      const ed = useEditor.getState();
      const mod = e.metaKey || e.ctrlKey;
      if (mod && (e.key === 'z' || e.key === 'Z')) {
        if (isTyping(e.target)) return;
        e.preventDefault();
        const sc = useScenario.getState();
        if (e.shiftKey) sc.redo();
        else sc.undo();
        return;
      }
      if (mod && e.key === 'y') {
        e.preventDefault();
        useScenario.getState().redo();
        return;
      }
      if (e.key === 'Escape') {
        if (ed.draft) {
          cancelDraft();
          e.preventDefault();
        } else if (ed.escape()) e.preventDefault();
        return;
      }
      if (mod || e.altKey || isTyping(e.target)) return;
      if (ed.draft) {
        if (e.key === 'Enter') {
          finishDraft();
          e.preventDefault();
          return;
        }
        if (e.key === 'Backspace' || e.key === 'Delete') {
          popWaypoint();
          e.preventDefault();
          return;
        }
      }
      const tool = (Object.keys(TOOL_KEYS) as Tool[]).find(
        (k) => TOOL_KEYS[k].toLowerCase() === e.key.toLowerCase(),
      );
      if (!tool) return;
      e.preventDefault();
      e.stopPropagation();
      if (tool === 'draw') {
        if (!ed.draft) startDraw();
      } else ed.setTool(tool);
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [active, startDraw]);
}

const HINT: Record<Tool, MessageKey> = {
  select: 'editor.hint.select',
  frequency: 'editor.hint.frequency',
  priority: 'editor.hint.priority',
  stop: 'editor.hint.stop',
  draw: 'editor.hint.draw',
};
const NAME: Record<Tool, MessageKey> = {
  select: 'editor.tool.select',
  frequency: 'editor.tool.frequency',
  priority: 'editor.tool.priority',
  stop: 'editor.tool.stop',
  draw: 'editor.tool.draw',
};

export function ToolPalette() {
  const t = useT();
  const active = useApp((st) => st.view === 'scenario');
  const tool = useEditor((st) => st.tool);
  const routeId = useEditor((st) => st.routeId);
  const adding = useEditor((st) => st.addingStop);
  const corridor = useEditor((st) => st.corridor);
  const setTool = useEditor((st) => st.setTool);
  const draft = useEditor((st) => st.draft);
  const startDraw = useStartDraw();
  useEditorShortcuts();
  if (!active) return null;
  const hint: MessageKey =
    tool === 'priority' && routeId
      ? corridor.start
        ? 'editor.hint.priorityEnd'
        : 'editor.hint.priorityStart'
      : tool === 'stop' && adding
        ? 'editor.hint.addStop'
        : tool === 'draw' && draft && draft.waypoints.length >= 2
          ? 'editor.hint.drawMore'
          : HINT[tool];
  return (
    <div className={s.palette}>
      <Surface className={s.tools} role="toolbar" aria-label={t('editor.tools')} data-testid="tool-palette">
        {TOOLS.map((k) => {
          const Icon = TOOL_ICON[k];
          return (
            <IconButton
              key={k}
              size="sm"
              label={t(NAME[k])}
              shortcut={TOOL_KEYS[k]}
              pressed={tool === k}
              data-testid={`tool-${k}`}
              onClick={() => (k === 'draw' ? !draft && startDraw() : setTool(k))}
            >
              <Icon strokeWidth={1.5} />
            </IconButton>
          );
        })}
      </Surface>
      <Surface className={s.toolHint} key={hint} role="status" data-testid="tool-hint">
        {t(hint)}
      </Surface>
    </div>
  );
}
