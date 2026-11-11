import {
  CloudOff,
  Download,
  ExternalLink,
  Printer,
  RotateCw,
  Sparkles,
  PencilRuler,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import type { ReportRequest } from '@/api/optimizer';
import type { Evaluation } from '@/api/types';
import { useApp } from '@/app/store';
import {
  Button,
  EmptyState,
  LineBadge,
  SegmentedControl,
  Select,
  Skeleton,
  toast,
} from '@/components/ui';
import { CATEGORY_ORDER } from '@/features/accessibility/model';
import { translateWarning, warningNames } from '@/features/scenario/warnings';
import { summarize } from '@/features/editor/model';
import type { ScenarioEdit } from '@/api/scenario';
import { THRESHOLD } from '@/features/optimizer/store';
import {
  formatEuros,
  formatSignedEuros,
  formatMin1,
  formatSigned,
  formatSignedTime,
} from '@/features/optimizer/fmt';
import { poiLabel, useT, type TFunction } from '@/i18n';
import type { Lang } from '@/i18n';
import { formatNumber, formatMinutes, formatPercent } from '@/lib/format';
import { useCompare, type CompareMode } from './store';
import { categoryRows, rankRoutes, summaryRows, type TableRow } from './model';
import { runReport, type ReportAction } from './report';
import { useCompareData } from './useCompareData';
import s from './Compare.module.css';

export function ComparePanel() {
  const t = useT();
  const data = useCompareData();
  const setView = useApp((st) => st.setView);
  const mode = useCompare((st) => st.mode);
  const setMode = useCompare((st) => st.setMode);
  const setSource = useCompare((st) => st.setSource);
  const category = useCompare((st) => st.category);
  const setCategory = useCompare((st) => st.setCategory);
  const ev = data.evaluation.data;

  if (!data.scenario) {
    return (
      <div className={s.panel} data-testid="view-compare">
        <div className={s.scroll}>
          <div className={s.empty} data-testid="compare-empty">
            <EmptyState
              icon={<ArrowsIcon />}
              title={t('cmp.emptyTitle')}
              body={t('cmp.emptyBody')}
              actions={
                <>
                  <Button
                    variant="secondary"
                    onClick={() => setView('scenario')}
                    data-testid="compare-open-editor"
                  >
                    <PencilRuler strokeWidth={1.75} />
                    {t('cmp.openEditor')}
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => setView('optimizer')}
                    data-testid="compare-open-optimizer"
                  >
                    <Sparkles strokeWidth={1.75} />
                    {t('cmp.openOptimizer')}
                  </Button>
                </>
              }
            />
          </div>
        </div>
      </div>
    );
  }

  const cats = ev ? categoryRows(ev, CATEGORY_ORDER).map((c) => c.id) : [];
  return (
    <div className={s.panel} data-testid="view-compare">
      <div className={s.scroll}>
        <div className={s.eyebrow}>{t('cmp.title')}</div>
        <h1 className={s.title} data-testid="compare-title">
          {t('cmp.today')} → {data.name}
        </h1>
        <div className={s.controls}>
          {data.available.store && data.available.optimizer ? (
            <SegmentedControl<'store' | 'optimizer'>
              size="sm"
              fullWidth
              label={t('cmp.comparing')}
              value={data.source ?? 'store'}
              onChange={(v) => setSource(v)}
              options={[
                { value: 'store', label: t('cmp.sourceStore') },
                { value: 'optimizer', label: t('cmp.sourceOpt') },
              ]}
            />
          ) : null}
          <SegmentedControl<CompareMode>
            size="sm"
            fullWidth
            label={t('cmp.mode')}
            value={mode}
            onChange={setMode}
            options={[
              { value: 'network', label: t('cmp.modeNetwork') },
              { value: 'access', label: t('cmp.modeAccess') },
              { value: 'delta', label: t('cmp.modeDelta') },
            ]}
          />
          {mode === 'access' ? (
            <Select
              size="sm"
              label={t('cmp.dest')}
              value={category}
              onChange={setCategory}
              options={(cats.length ? cats : [category]).map((c) => ({
                value: c,
                label: poiLabel(t, c),
              }))}
            />
          ) : null}
        </div>

        {data.evaluation.isError && !ev ? (
          <div className={s.empty}>
            <EmptyState
              icon={<CloudOff strokeWidth={1.5} />}
              title={t('cmp.error')}
              body={String((data.evaluation.error as Error | null)?.message ?? '')}
              actions={
                <Button variant="secondary" onClick={() => void data.evaluation.refetch()}>
                  <RotateCw strokeWidth={1.75} />
                  {t('cmp.retry')}
                </Button>
              }
            />
          </div>
        ) : !ev ? (
          <div className={s.skel} aria-label={t('cmp.computing')} data-testid="compare-skeleton">
            <Skeleton height={16} width="50%" />
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} height={12} width={`${60 + ((i * 17) % 35)}%`} />
            ))}
          </div>
        ) : (
          <>
            <SummaryTable ev={ev} />
            <People ev={ev} />
            <RoutesTable ev={ev} data={data} />
            <Changes data={data} />
            {ev.warnings.length ? (
              <section className={s.section}>
                <h2 className={s.sectionTitle}>{t('cmp.warnings')}</h2>
                <ul className={s.warnings}>
                  {ev.warnings.map((w, i) => (
                    <li key={i}>
                      {translateWarning(
                        w,
                        t,
                        warningNames(
                          [data.proposal, data.today],
                          (data.scenario ?? []) as ScenarioEdit[],
                        ),
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        )}
        <ReportForm data={data} />
      </div>
      <ReportFooter data={data} />
    </div>
  );
}

function ArrowsIcon() {
  return <Sparkles strokeWidth={1.5} />;
}

// ---------------------------------------------------------------------------------- table

function deltaTone(row: TableRow): 'good' | 'bad' | 'flat' {
  if (Math.abs(row.delta) < 1e-9) return 'flat';
  return row.delta < 0 === (row.better === 'lower') ? 'good' : 'bad';
}

function fmtRow(id: string, n: number, lang: Lang): string {
  switch (id) {
    case 'meanTime':
      return formatMin1(n, lang);
    case 'costDay':
    case 'costYear':
      return formatEuros(n, lang);
    case 'busHours':
    case 'km':
      return formatNumber(n, lang, 0);
    default:
      return formatNumber(n, lang, 0);
  }
}

function fmtDelta(id: string, d: number, lang: Lang): string {
  switch (id) {
    case 'meanTime':
      return formatSignedTime(d, lang);
    case 'costDay':
    case 'costYear':
      return formatSignedEuros(d, lang);
    case 'accIndex':
      return formatSigned(d, lang, 1);
    default:
      return formatSigned(d, lang, 0);
  }
}

function SummaryTable({ ev }: { ev: Evaluation }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const rows = useMemo(() => summaryRows(ev), [ev]);
  const cats = useMemo(() => categoryRows(ev, CATEGORY_ORDER), [ev]);
  const label = (id: string) =>
    t(
      id === 'fleet'
        ? 'cmp.fleet'
        : id === 'busHours'
          ? 'cmp.busHours'
          : id === 'km'
            ? 'cmp.km'
            : id === 'costDay'
              ? 'cmp.costDay'
              : id === 'costYear'
                ? 'cmp.costYear'
                : id === 'meanTime'
                  ? 'cmp.meanTime'
                  : id === 'accIndex'
                    ? 'cmp.accIndex'
                    : 'cmp.underserved',
    );
  return (
    <section className={s.section} data-testid="compare-table">
      <table className={s.table}>
        <thead>
          <tr>
            <th
              scope="col"
              className="sr-only"
              style={{
                position: 'absolute',
                width: 1,
                height: 1,
                overflow: 'hidden',
                clip: 'rect(0 0 0 0)',
              }}
            >
              {t('cmp.table')}
            </th>
            <th scope="col">{t('cmp.colToday')}</th>
            <th scope="col">{t('cmp.colScenario')}</th>
            <th scope="col" className={s.dcol} />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} data-testid={`row-${r.id}`}>
              <td>{label(r.id)}</td>
              <td>{fmtRow(r.id, r.before, lang)}</td>
              <td>{fmtRow(r.id, r.after, lang)}</td>
              <td className={`${s.dcol} ${s.delta}`} data-tone={deltaTone(r)}>
                {fmtDelta(r.id, r.delta, lang)}
              </td>
            </tr>
          ))}
          <tr className={s.subhead}>
            <td colSpan={4}>{t('cmp.within', { min: THRESHOLD / 60 })}</td>
          </tr>
          {cats.map((c) => (
            <tr key={c.id} data-testid={`row-cat-${c.id}`}>
              <td>{poiLabel(t, c.id)}</td>
              <td>{formatNumber(c.before, lang)}</td>
              <td>{formatNumber(c.after, lang)}</td>
              <td className={`${s.dcol} ${s.delta}`} data-tone={deltaTone(c)}>
                {formatSigned(c.delta, lang)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function People({ ev }: { ev: Evaluation }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  return (
    <section className={s.section}>
      <h2 className={s.sectionTitle}>{t('cmp.people')}</h2>
      <dl className={s.people} data-testid="compare-people">
        <div>
          <dd>{formatNumber(ev.delta.people_gaining, lang)}</dd>
          <dt>{t('cmp.gaining')}</dt>
        </div>
        <div>
          <dd>{formatNumber(ev.delta.people_losing, lang)}</dd>
          <dt>{t('cmp.losing')}</dt>
        </div>
      </dl>
    </section>
  );
}

// ---------------------------------------------------------------------------------- routes

const ROUTES_SHOWN = 8;

function RoutesTable({ ev, data }: { ev: Evaluation; data: ReturnType<typeof useCompareData> }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const [all, setAll] = useState(false);
  const ranked = useMemo(() => rankRoutes(ev.routes), [ev.routes]);
  if (!ranked.length) return null;
  const shown = all ? ranked : ranked.slice(0, ROUTES_SHOWN);
  const model = data.proposal ?? data.today;
  return (
    <section className={s.section} data-testid="compare-routes">
      <h2 className={s.sectionTitle}>
        {t('cmp.routes')}
        <span className={s.sectionMeta}>{ranked.length}</span>
      </h2>
      <table className={s.table}>
        <thead>
          <tr>
            <th scope="col" />
            <th scope="col">{t('cmp.rTrips')}</th>
            <th scope="col">{t('cmp.rHeadway')}</th>
            <th scope="col">{t('cmp.rFleet')}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => {
            const route = model?.routeById.get(r.id);
            return (
              <tr key={r.id}>
                <td>
                  <span className={s.badge}>
                    <LineBadge
                      shortName={route?.short_name ?? r.id}
                      color={route?.color ?? '#888888'}
                      textColor={route?.text_color}
                    />
                  </span>
                </td>
                <td>
                  {formatNumber(r.trips[0], lang)} → {formatNumber(r.trips[1], lang)}
                </td>
                <td>
                  {formatMinutes(r.headway_peak[0], lang)} →{' '}
                  {formatMinutes(r.headway_peak[1], lang)}
                </td>
                <td>
                  {r.fleet[0]} → {r.fleet[1]}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {ranked.length > ROUTES_SHOWN ? (
        <Button size="sm" variant="ghost" className={s.more} onClick={() => setAll((v) => !v)}>
          {all ? '−' : `+${ranked.length - ROUTES_SHOWN}`}
        </Button>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------------- changes

const CHANGES_SHOWN = 6;

function Changes({ data }: { data: ReturnType<typeof useCompareData> }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const [all, setAll] = useState(false);
  const scenario = data.scenario;
  const items = useMemo(
    () =>
      ((scenario ?? []) as unknown as ScenarioEdit[]).map((e) =>
        summarize(e, t as TFunction, lang, data.today),
      ),
    [scenario, t, lang, data.today],
  );
  if (!items.length) return null;
  const shown = all ? items : items.slice(0, CHANGES_SHOWN);
  return (
    <section className={s.section} data-testid="compare-changes">
      <h2 className={s.sectionTitle}>
        {t('cmp.changes')}
        <span className={s.sectionMeta}>{items.length}</span>
      </h2>
      <ul className={s.changes}>
        {shown.map((it, i) => {
          const r = it.routeId ? data.today?.routeById.get(it.routeId) : undefined;
          const badge = it.badge ?? (r ? { shortName: r.short_name, color: r.color } : null);
          return (
            <li key={i} className={s.change}>
              <span className={s.badge}>
                {badge ? (
                  <LineBadge
                    shortName={badge.shortName}
                    color={badge.color}
                    textColor={r?.text_color}
                  />
                ) : null}
              </span>
              <span className={s.changeText}>
                {it.title}
                <span className={s.changeDetail}>{it.detail}</span>
              </span>
            </li>
          );
        })}
      </ul>
      {items.length > CHANGES_SHOWN ? (
        <Button size="sm" variant="ghost" className={s.more} onClick={() => setAll((v) => !v)}>
          {all ? '−' : `+${items.length - CHANGES_SHOWN}`}
        </Button>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------------- report

function useReportRequest(data: ReturnType<typeof useCompareData>): ReportRequest | null {
  const lang = useApp((st) => st.lang);
  const title = useCompare((st) => st.reportTitle);
  const rl = useCompare((st) => st.reportLang);
  if (!data.scenario) return null;
  return {
    scenario: data.scenario,
    window: data.window,
    threshold: THRESHOLD,
    lang: rl ?? (lang === 'en' ? 'en' : 'es'),
    title: title ?? data.name,
  };
}

function ReportForm({ data }: { data: ReturnType<typeof useCompareData> }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const title = useCompare((st) => st.reportTitle);
  const rl = useCompare((st) => st.reportLang);
  const setReport = useCompare((st) => st.setReport);
  return (
    <section className={s.section} data-testid="compare-report">
      <h2 className={s.sectionTitle}>{t('cmp.report')}</h2>
      <div className={s.field}>
        <label className={s.fieldLabel} htmlFor="report-title">
          {t('cmp.reportTitle')}
        </label>
        <input
          id="report-title"
          className={s.input}
          value={title ?? data.name}
          maxLength={120}
          onChange={(e) => setReport({ title: e.target.value })}
          data-testid="report-title"
        />
      </div>
      <div className={s.field}>
        <span className={s.fieldLabel}>{t('cmp.reportLang')}</span>
        <SegmentedControl<'es' | 'en'>
          size="sm"
          fullWidth
          label={t('cmp.reportLang')}
          value={rl ?? (lang === 'en' ? 'en' : 'es')}
          onChange={(v) => setReport({ lang: v })}
          options={[
            { value: 'es', label: 'Español' },
            { value: 'en', label: 'English' },
          ]}
        />
      </div>
      <p className={s.hint}>{t('cmp.reportHint')}</p>
    </section>
  );
}

function ReportFooter({ data }: { data: ReturnType<typeof useCompareData> }) {
  const t = useT();
  const req = useReportRequest(data);
  const [busy, setBusy] = useState<ReportAction | null>(null);
  const run = async (action: ReportAction) => {
    if (!req || busy) return;
    setBusy(action);
    try {
      const ok = await runReport(action, req);
      if (!ok) toast(t('cmp.popupBlocked'));
    } catch {
      toast(t('cmp.reportError'));
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className={s.footer}>
      <Button
        variant="primary"
        className={s.full}
        disabled={!req || !!busy}
        onClick={() => void run('open')}
        data-testid="report-open"
      >
        <ExternalLink strokeWidth={1.75} />
        {busy === 'open' ? t('cmp.reportBusy') : t('cmp.open')}
      </Button>
      <div className={s.actions}>
        <div className={s.actionsRow}>
          <Button
            size="sm"
            variant="secondary"
            disabled={!req || !!busy}
            onClick={() => void run('download')}
            data-testid="report-download"
          >
            <Download strokeWidth={1.5} />
            {t('cmp.download')}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={!req || !!busy}
            onClick={() => void run('print')}
            data-testid="report-print"
          >
            <Printer strokeWidth={1.5} />
            {t('cmp.print')}
          </Button>
        </div>
      </div>
    </div>
  );
}

export { formatPercent };
