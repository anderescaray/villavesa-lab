import { ArrowLeft } from 'lucide-react';
import type { ViewId } from '@/app/store';
import { useApp } from '@/app/store';
import { Button, EmptyState } from '@/components/ui';
import { VIEW_META } from '@/features/shell/Rail';
import { useT } from '@/i18n';

type PlannedId = Exclude<ViewId, 'network'>;

/**
 * Designed empty state for views delivered in later milestones: says exactly what the view will
 * do (both languages) and offers the one useful action now.
 */
export function PlannedView({ view }: { view: PlannedId }) {
  const t = useT();
  const setView = useApp((s) => s.setView);
  const Icon = VIEW_META[view].icon;
  return (
    <div data-testid={`view-${view}`}>
      <EmptyState
        icon={<Icon strokeWidth={1.5} />}
        eyebrow={t('empty.planned')}
        title={t(`${view}.title`)}
        body={t(`${view}.lead`)}
        points={[t(`${view}.point1`), t(`${view}.point2`), t(`${view}.point3`)]}
        actions={
          <Button variant="secondary" onClick={() => setView('network')}>
            <ArrowLeft strokeWidth={1.75} />
            {t('empty.back')}
          </Button>
        }
      />
    </div>
  );
}
