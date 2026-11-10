import type { ReactNode } from 'react';
import { useMeta } from '@/api/queries';
import { DAY_TYPES } from '@/api/types';
import { useApp } from '@/app/store';
import { Popover, Skeleton } from '@/components/ui';
import { useT } from '@/i18n';
import { formatNumber, localeOf } from '@/lib/format';
import s from './AboutPopover.module.css';

export function AboutPopover({ trigger }: { trigger: ReactNode }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const open = useApp((st) => st.aboutOpen);
  const set = useApp((st) => st.set);
  const { data: meta } = useMeta();
  const date = (iso: string) =>
    new Intl.DateTimeFormat(localeOf(lang), {
      day: 'numeric',
      month: 'short',
      timeZone: 'UTC',
    }).format(new Date(`${iso}T12:00:00Z`));

  return (
    <Popover
      trigger={trigger}
      open={open}
      onOpenChange={(o) => set({ aboutOpen: o })}
      label={t('about.title')}
    >
      <div className={s.root} data-testid="about-popover">
        <div className={s.head}>
          <h2 className={s.title}>{t('about.title')}</h2>
        </div>
        {meta ? (
          <>
            <dl className={s.dl}>
              <dt>{t('about.feed')}</dt>
              <dd>{t('about.feedValue', { agency: meta.feed.agency })}</dd>
              <dt>{t('about.validity')}</dt>
              <dd>
                {date(meta.feed.start_date)} – {date(meta.feed.end_date)}
              </dd>
              <dt>{t('about.reference')}</dt>
              <dd>{DAY_TYPES.map((d) => date(meta.days[d])).join(' · ')}</dd>
              <dt>{t('about.population')}</dt>
              <dd>{formatNumber(meta.population, lang)}</dd>
            </dl>
            <div className={s.section}>
              <h3 className={s.sectionTitle}>{t('about.limitations')}</h3>
              <ul className={s.notes}>
                {meta.data_notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </div>
          </>
        ) : (
          <div className={s.dl} aria-label={t('about.loading')}>
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} height={12} style={{ gridColumn: '1 / -1' }} />
            ))}
          </div>
        )}
        <p className={s.foot}>{t('about.basemap')}</p>
      </div>
    </Popover>
  );
}
