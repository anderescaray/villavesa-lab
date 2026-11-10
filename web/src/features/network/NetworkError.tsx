import { CloudOff, RotateCw } from 'lucide-react';
import { Button, EmptyState } from '@/components/ui';
import { useT } from '@/i18n';

export function NetworkError({ onRetry }: { onRetry: () => void }) {
  const t = useT();
  return (
    <div style={{ padding: 'var(--space-6) var(--space-5)' }} data-testid="network-error">
      <EmptyState
        icon={<CloudOff strokeWidth={1.5} />}
        title={t('error.title')}
        body={t('error.body')}
        actions={
          <Button variant="secondary" onClick={onRetry}>
            <RotateCw strokeWidth={1.75} />
            {t('error.retry')}
          </Button>
        }
      />
    </div>
  );
}
