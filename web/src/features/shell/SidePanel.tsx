import { PanelLeftClose } from 'lucide-react';
import { useApp } from '@/app/store';
import { IconButton } from '@/components/ui';
import { NetworkPanel } from '@/features/network/NetworkPanel';
import { PlannedView } from '@/features/views/PlannedView';
import { useT } from '@/i18n';
import { Wordmark } from './Brand';
import s from './Shell.module.css';

/** The slim side panel: brand bar + the active view's content. */
export function SidePanel() {
  const t = useT();
  const view = useApp((st) => st.view);
  const open = useApp((st) => st.panelOpen);
  const set = useApp((st) => st.set);
  return (
    <aside className={s.panel} data-open={open} aria-hidden={!open} data-testid="side-panel">
      <div className={s.panelBar}>
        <Wordmark />
        <IconButton label={t('shell.collapsePanel')} shortcut="[" size="sm" onClick={() => set({ panelOpen: false })}>
          <PanelLeftClose strokeWidth={1.5} />
        </IconButton>
      </div>
      <div className={s.panelBody}>
        {view === 'network' ? (
          <NetworkPanel />
        ) : (
          <div className={s.panelScroll}>
            <PlannedView view={view} />
          </div>
        )}
      </div>
    </aside>
  );
}
