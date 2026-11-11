import type { Accessibility, ZonesGeoJSON } from '@/api/types';
import { useApp } from '@/app/store';
import { isMessageKey, poiLabel, useT, type TFunction } from '@/i18n';
import { formatCurrency, formatDuration, formatNumber, formatPercent } from '@/lib/format';
import type { CellHover, PoiHover } from './AccessibilityLayers';
import s from './Accessibility.module.css';

function nearLabel(t: TFunction, id: string) {
  const key = `acc.near.${id}`;
  return isMessageKey(key) ? t(key) : poiLabel(t, id);
}

/** Hover card for a 200 m cell: residents, time to the nearest destination, activity, income. */
export function CellTooltip({
  hover,
  data,
  zones,
}: {
  hover: CellHover;
  data: Accessibility;
  zones: ZonesGeoJSON | undefined;
}) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const category = useApp((st) => st.accCategory);
  const threshold = data.threshold;
  const i = hover.zone;
  const pop = data.zones.population[i] ?? 0;
  const time = data.zones.time[category]?.[i] ?? null;
  const jobs = data.zones.jobs_30[i];
  const income = data.zones.income[i] ?? null;
  const municipality = zones?.features[i]?.properties.municipality;
  const within = time !== null && time <= threshold;
  const flip = hover.x > window.innerWidth - 300;
  return (
    <div
      className={s.cellTip}
      style={{ left: hover.x, top: hover.y }}
      data-flip={flip}
      role="tooltip"
      data-testid="cell-tooltip"
    >
      <div className={s.tipHead}>
        <span className={s.tipTitle}>{municipality ?? t('acc.cell')}</span>
        <span className={s.tipSub}>{t('acc.residents', { n: formatNumber(pop, lang) })}</span>
      </div>
      <dl className={s.tipDl}>
        <dt>{nearLabel(t, category)}</dt>
        <dd>
          <span className={s.tipDot} data-ok={within} aria-hidden />
          {time === null ? t('acc.unreachable') : formatDuration(time)}
        </dd>
        <dt>{t('acc.tipJobs')}</dt>
        <dd>{formatPercent(jobs, lang)}</dd>
        <dt>{t('acc.tipIncome')}</dt>
        <dd>{income === null ? '—' : formatCurrency(income, lang)}</dd>
      </dl>
    </div>
  );
}

export function PoiTooltip({ hover }: { hover: PoiHover }) {
  return (
    <div
      className={s.poiTip}
      style={{ left: hover.x, top: hover.y }}
      role="tooltip"
      data-testid="poi-tooltip"
    >
      {hover.name}
    </div>
  );
}
