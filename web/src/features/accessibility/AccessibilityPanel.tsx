import { ChevronRight, CloudOff, RotateCw } from 'lucide-react';
import { Fragment, useCallback, useMemo, type ReactNode } from 'react';
import { useMeta } from '@/api/queries';
import type { Accessibility, AccessibilityCategory } from '@/api/types';
import { ACC_THRESHOLDS, useApp } from '@/app/store';
import {
  AnimatedNumber,
  Button,
  EmptyState,
  SegmentedControl,
  Skeleton,
  Tooltip,
} from '@/components/ui';
import { isMessageKey, noteText, poiLabel, useT, type MessageKey, type TFunction } from '@/i18n';
import {
  formatClock,
  formatCompact,
  formatDuration,
  formatNumber,
  formatPercent,
  localeOf,
} from '@/lib/format';
import { CumulativeChart } from './CumulativeChart';
import { readConcentration, sortCategories } from './model';
import { ACC_WINDOW, useAccessibility } from './useAccessibility';
import s from './Accessibility.module.css';

/** Category phrase used inside sentences ("a un hospital"), with a humanised fallback. */
export function destPhrase(t: TFunction, id: string): string {
  const key = `acc.dest.${id}`;
  return isMessageKey(key) ? t(key) : poiLabel(t, id).toLowerCase();
}

/** Render a translated template with React nodes in place of `{name}` placeholders. */
function rich(template: string, nodes: Record<string, ReactNode>): ReactNode {
  return template.split(/(\{\w+\})/g).map((part, i) => {
    const m = /^\{(\w+)\}$/.exec(part);
    return <Fragment key={i}>{m && m[1]! in nodes ? nodes[m[1]!] : part}</Fragment>;
  });
}

export function AccessibilityPanel() {
  const t = useT();
  const day = useApp((st) => st.day);
  const threshold = useApp((st) => st.accThreshold);
  const set = useApp((st) => st.set);
  const { req, query, data, stale } = useAccessibility();
  const start = req?.window.start ?? 8 * 3600;
  const from = formatClock(start);
  const to = formatClock(start + ACC_WINDOW);

  return (
    <div className={s.panel} data-testid="view-accessibility" aria-busy={query.isFetching}>
      <header className={s.header}>
        <h1 className={s.title}>{t('acc.title')}</h1>
        <Tooltip content={t('acc.windowHint', { from, to })}>
          <span className={s.window} data-testid="acc-window" tabIndex={0}>
            {t('acc.window', { day: t(`day.${day}`), from, to })}
          </span>
        </Tooltip>
      </header>
      <div className={s.control}>
        <span className={s.controlLabel}>{t('acc.threshold')}</span>
        <SegmentedControl<`${number}`>
          size="sm"
          fullWidth
          label={t('acc.threshold')}
          value={`${threshold}`}
          onChange={(v) => set({ accThreshold: Number(v) })}
          options={ACC_THRESHOLDS.map((v) => ({
            value: `${v}` as `${number}`,
            label: t('acc.minutes', { n: v / 60 }),
          }))}
        />
      </div>

      {query.isError && !data ? (
        <div className={s.error} data-testid="acc-error">
          <EmptyState
            icon={<CloudOff strokeWidth={1.5} />}
            title={t('acc.error')}
            body={t('error.body')}
            actions={
              <Button variant="secondary" onClick={() => void query.refetch()}>
                <RotateCw strokeWidth={1.75} />
                {t('acc.retry')}
              </Button>
            }
          />
        </div>
      ) : !data ? (
        <PanelSkeleton label={t('acc.loading')} />
      ) : (
        <div className={s.body} data-stale={stale}>
          <Headline data={data} />
          <CategoryList data={data} />
          <CurveBlock data={data} />
          <EquityBlock data={data} />
          <About />
        </div>
      )}
      <span className={s.srOnly} aria-live="polite">
        {data && !stale ? t('acc.window', { day: t(`day.${day}`), from, to }) : ''}
      </span>
    </div>
  );
}

function useSelected(data: Accessibility): AccessibilityCategory | undefined {
  const category = useApp((st) => st.accCategory);
  return data.categories.find((c) => c.id === category) ?? data.categories[0];
}

function Headline({ data }: { data: Accessibility }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const cat = useSelected(data);
  const fmtN = useCallback((n: number) => formatNumber(Math.round(n / 100) * 100, lang), [lang]);
  const fmtPct = useCallback((n: number) => formatPercent(n, lang), [lang]);
  if (!cat) return null;
  const missing = Math.max(0, data.population - cat.pop_within);
  const share = data.population ? missing / data.population : 0;
  const min = data.threshold / 60;
  const dest = destPhrase(t, cat.id);
  const sentence =
    missing < 50
      ? t('acc.headlineAll', { dest, min })
      : rich(t('acc.headline', { dest, min }), {
          n: (
            <strong className={s.headNum}>
              <AnimatedNumber value={missing} format={fmtN} />
            </strong>
          ),
          pct: <AnimatedNumber value={share} format={fmtPct} />,
        });
  return (
    <section className={s.headline} data-testid="acc-headline">
      <p className={s.headText}>{sentence}</p>
      <p className={s.headSub}>
        {t('acc.headlineSub', { total: formatNumber(data.population, lang) })}
      </p>
    </section>
  );
}

function CategoryList({ data }: { data: Accessibility }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const selected = useApp((st) => st.accCategory);
  const set = useApp((st) => st.set);
  const { data: meta } = useMeta();
  const essential = new Set(meta?.essential_categories ?? []);
  const cats = useMemo(() => sortCategories(data.categories), [data.categories]);
  const fmtPct = useCallback((n: number) => formatPercent(n, lang), [lang]);
  return (
    <section className={s.section}>
      <div className={s.listHead} aria-hidden>
        <span>{t('acc.destinations')}</span>
        <span className={s.colRight}>{t('acc.colWithin', { min: data.threshold / 60 })}</span>
        <span className={s.colRight}>{t('acc.colMedian')}</span>
      </div>
      <ul className={s.catList} data-testid="acc-categories">
        {cats.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              className={s.catRow}
              aria-pressed={c.id === selected}
              aria-label={`${poiLabel(t, c.id)}: ${formatPercent(c.share_within, lang)}, ${t('acc.colMedian')} ${formatDuration(c.median_time)}`}
              onClick={() => set({ accCategory: c.id })}
              data-testid={`acc-cat-${c.id}`}
            >
              <span className={s.catMain}>
                <span className={s.catName}>
                  {poiLabel(t, c.id)}
                  {essential.has(c.id) ? (
                    <span className={s.essential} title={t('acc.essential')} />
                  ) : null}
                </span>
                <span className={s.catBar} aria-hidden>
                  <span style={{ transform: `scaleX(${c.share_within})` }} />
                </span>
              </span>
              <span className={s.catPct}>
                <AnimatedNumber value={c.share_within} format={fmtPct} duration={300} />
              </span>
              <span className={s.catMed}>{formatDuration(c.median_time)}</span>
            </button>
          </li>
        ))}
      </ul>
      {essential.size ? (
        <p className={s.footnote}>
          <span className={s.essential} aria-hidden /> {t('acc.essential')}
        </p>
      ) : null}
    </section>
  );
}

function CurveBlock({ data }: { data: Accessibility }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const cat = useSelected(data);
  if (!cat) return null;
  return (
    <section className={s.section}>
      <h2 className={s.sectionTitle}>
        {t('acc.curve')}
        <span className={s.sectionMeta}>{poiLabel(t, cat.id)}</span>
      </h2>
      <CumulativeChart
        curve={cat.curve}
        threshold={data.threshold}
        lang={lang}
        label={t('acc.curveAria', { dest: destPhrase(t, cat.id) })}
      />
    </section>
  );
}

function EquityBlock({ data }: { data: Accessibility }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const cat = useSelected(data);
  const { data: meta } = useMeta();
  const fmtN = useCallback((n: number) => formatNumber(Math.round(n / 100) * 100, lang), [lang]);
  if (!cat) return null;
  const quintiles = [...data.equity.quintiles].sort((a, b) => a.q - b.q);
  const ci = data.equity.concentration_index[cat.id];
  const reading = readConcentration(ci);
  const dest = destPhrase(t, cat.id);
  const ciText = ci === undefined ? '' : formatNumber(ci, lang, 2).replace(/^(?=\d)/, '+');
  const essentials = (meta?.essential_categories ?? []).map((c) =>
    poiLabel(t, c).toLocaleLowerCase(localeOf(lang)),
  );
  const list = new Intl.ListFormat(localeOf(lang), { type: 'conjunction' }).format(essentials);
  const under = data.summary.underserved_population;
  const overall = cat.share_within;
  const eur = (n: number) => formatCompact(n, lang) + ' €';
  return (
    <section className={s.section} data-testid="acc-equity">
      <h2 className={s.sectionTitle}>
        {t('acc.equity')}
        <span className={s.sectionMeta}>{poiLabel(t, cat.id)}</span>
      </h2>
      <p className={s.lead}>{t('acc.equityLead')}</p>
      <ul className={s.qList}>
        {quintiles.map((q) => {
          const v = q.share_within[cat.id] ?? null;
          return (
            <li key={q.q}>
              <Tooltip
                content={t('acc.incomeRange', {
                  min: eur(q.income_min),
                  max: eur(q.income_max),
                  pop: formatNumber(q.population, lang),
                })}
              >
                <div className={s.qRow} tabIndex={0} data-testid={`acc-q${q.q}`}>
                  <span className={s.qName}>
                    Q{q.q}
                    {q.q === 1 ? <span className={s.qHint}>{t('acc.lowIncome')}</span> : null}
                    {q.q === quintiles.length ? (
                      <span className={s.qHint}>{t('acc.highIncome')}</span>
                    ) : null}
                  </span>
                  <span className={s.qTrack} aria-hidden>
                    <span className={s.qBar} style={{ transform: `scaleX(${v ?? 0})` }} />
                    <span className={s.qAvg} style={{ left: `${overall * 100}%` }} />
                  </span>
                  <span className={s.qVal}>{formatPercent(v, lang)}</span>
                </div>
              </Tooltip>
            </li>
          );
        })}
      </ul>
      <p className={s.qLegend} aria-hidden>
        <span className={s.qAvgKey} /> {t('acc.average')} {formatPercent(overall, lang)}
      </p>
      {reading ? (
        <p className={s.reading} data-testid="acc-ci">
          {t(`acc.ci.${reading}` as MessageKey, { dest, ci: ciText })}
        </p>
      ) : null}
      <div className={s.under} data-testid="acc-underserved">
        <h3 className={s.underTitle}>{t('acc.underservedTitle')}</h3>
        <p className={s.underText}>
          {rich(
            t('acc.underserved', {
              min: data.threshold / 60,
              list,
            }),
            {
              n: (
                <strong className={s.underNum}>
                  <AnimatedNumber value={under} format={fmtN} />
                </strong>
              ),
              pct: formatPercent(data.population ? under / data.population : null, lang),
            },
          )}
        </p>
      </div>
    </section>
  );
}

function About() {
  const t = useT();
  const { data: meta } = useMeta();
  const keys = ['demand_gravity', 'population_dasymetric', 'activity_proxy', 'schedule_based'];
  const notes = (meta?.data_notes ?? []).filter((n) => keys.includes(n.key));
  return (
    <details className={s.about} data-testid="acc-about">
      <summary>
        <ChevronRight strokeWidth={1.75} aria-hidden />
        {t('acc.about')}
      </summary>
      <ul>
        <li>{t('acc.aboutMethod')}</li>
        {notes.map((n) => (
          <li key={n.key}>{noteText(t, n)}</li>
        ))}
      </ul>
    </details>
  );
}

function PanelSkeleton({ label }: { label: string }) {
  return (
    <div className={s.body} aria-label={label} data-testid="acc-skeleton">
      <div className={s.headline}>
        <Skeleton height={20} width="92%" />
        <Skeleton height={20} width="64%" style={{ marginTop: 8 }} />
        <Skeleton height={10} width="70%" style={{ marginTop: 12 }} />
      </div>
      <div className={s.section}>
        {Array.from({ length: 7 }, (_, i) => (
          <div key={i} className={s.skelRow}>
            <Skeleton height={10} width={`${50 + ((i * 23) % 40)}%`} />
            <Skeleton height={4} width={72} />
            <Skeleton height={10} width={32} />
          </div>
        ))}
      </div>
      <div className={s.section}>
        <Skeleton height={120} />
      </div>
    </div>
  );
}
