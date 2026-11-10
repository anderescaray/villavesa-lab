/** Global keyboard shortcuts. Inputs keep their keys (except Esc); dialogs handle their own Esc. */
import { useEffect } from 'react';
import { clockActions } from '@/features/time/clock';
import { VIEWS, useApp, type ThemePref } from './store';

const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement &&
  (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));

const isInteractive = (el: EventTarget | null) =>
  el instanceof HTMLElement &&
  (['BUTTON', 'A'].includes(el.tagName) || ['slider', 'radio', 'tab', 'option', 'menuitem'].includes(el.getAttribute('role') ?? ''));

const NEXT_THEME: Record<ThemePref, ThemePref> = { light: 'dark', dark: 'system', system: 'light' };

export function useGlobalShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
      const app = useApp.getState();
      if (document.querySelector('[role="dialog"][data-state="open"], [role="listbox"]') && e.key !== '?') return;
      if (e.key === 'Escape') {
        if (app.aboutOpen) return;
        if (app.clearTop()) e.preventDefault();
        return;
      }
      if (isTyping(e.target)) return;
      switch (e.key) {
        case ' ':
          if (isInteractive(e.target)) return;
          clockActions.toggle();
          break;
        case 'ArrowLeft':
        case 'ArrowRight':
          if (isInteractive(e.target) && (e.target as HTMLElement).getAttribute('role') === 'slider') return;
          if (isInteractive(e.target) && (e.target as HTMLElement).getAttribute('role') === 'radio') return;
          clockActions.step((e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 60 : 300));
          break;
        case '/':
          app.set({ view: 'network', panelOpen: true, selectedRouteId: null });
          requestAnimationFrame(() => window.dispatchEvent(new Event('vlab:focus-search')));
          break;
        case '?':
          app.set({ shortcutsOpen: !app.shortcutsOpen });
          break;
        case '[':
          app.set({ panelOpen: !app.panelOpen });
          break;
        case 't':
        case 'T':
          app.set({ themePref: NEXT_THEME[app.themePref] });
          break;
        case 's':
        case 'S':
          clockActions.cycleSpeed();
          break;
        default:
          if (/^[1-5]$/.test(e.key)) {
            app.set({ view: VIEWS[Number(e.key) - 1]!, panelOpen: true });
            break;
          }
          return;
      }
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
