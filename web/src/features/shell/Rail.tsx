import {
  BarChart3,
  GitCompareArrows,
  Keyboard,
  Map as MapIcon,
  PencilRuler,
  Sparkles,
} from 'lucide-react';
import type { ComponentType } from 'react';
import { useApp, VIEWS, type ViewId } from '@/app/store';
import { Tooltip } from '@/components/ui';
import { useT, type MessageKey } from '@/i18n';
import { BrandMark } from './Brand';
import s from './Shell.module.css';

export const VIEW_META: Record<
  ViewId,
  { icon: ComponentType<{ strokeWidth?: number }>; label: MessageKey }
> = {
  network: { icon: MapIcon, label: 'nav.network' },
  accessibility: { icon: BarChart3, label: 'nav.accessibility' },
  scenario: { icon: PencilRuler, label: 'nav.scenario' },
  optimizer: { icon: Sparkles, label: 'nav.optimizer' },
  compare: { icon: GitCompareArrows, label: 'nav.compare' },
};

export function Rail() {
  const t = useT();
  const view = useApp((st) => st.view);
  const setView = useApp((st) => st.setView);
  const set = useApp((st) => st.set);
  return (
    <nav className={s.rail} aria-label={t('nav.label')}>
      <Tooltip content={t('app.tagline')} side="right">
        <button
          type="button"
          className={s.brand}
          aria-label={t('app.name')}
          onClick={() => setView('network')}
        >
          <BrandMark size={28} />
        </button>
      </Tooltip>
      <div className={s.nav}>
        {VIEWS.map((v, i) => {
          const { icon: Icon, label } = VIEW_META[v];
          return (
            <Tooltip key={v} content={t(label)} shortcut={String(i + 1)} side="right">
              <button
                type="button"
                className={s.navItem}
                aria-label={t(label)}
                aria-current={view === v ? 'page' : undefined}
                onClick={() => {
                  setView(v);
                  set({ panelOpen: true });
                }}
                data-testid={`nav-${v}`}
              >
                <Icon strokeWidth={1.5} />
              </button>
            </Tooltip>
          );
        })}
      </div>
      <div className={s.railBottom}>
        <Tooltip content={t('shell.shortcuts')} shortcut="?" side="right">
          <button
            type="button"
            className={s.navItem}
            aria-label={t('shell.shortcuts')}
            onClick={() => set({ shortcutsOpen: true })}
            data-testid="open-shortcuts"
          >
            <Keyboard strokeWidth={1.5} />
          </button>
        </Tooltip>
      </div>
    </nav>
  );
}
