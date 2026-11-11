import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  CloudOff,
  FileText,
  GitCompareArrows,
  RotateCw,
  Sparkles,
} from 'lucide-react';
import { Fragment, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNetwork } from '@/api/queries';
import type { Edit, Evaluation } from '@/api/types';
import type { ScenarioEdit } from '@/api/scenario';
import { useApp } from '@/app/store';
import {
  AnimatedNumber,
  Button,
  EmptyState,
  IconButton,
  LineBadge,
  SegmentedControl,
  Skeleton,
  Slider,
  Switch,
  toast,
} from '@/components/ui';
import { useWindowStart } from '@/features/accessibility/useAccessibility';
import { ACC_WINDOW } from '@/features/accessibility/useAccessibility';
import { buildNetworkModel } from '@/features/network/model';
import { useScenario } from '@/features/scenario/store';
import { useT, type MessageKey } from '@/i18n';
import { displayName, formatClock, formatNumber } from '@/lib/format';
import { fitBounds, boundsOf } from '@/map/camera';
import { useCompare } from '@/features/compare/store';
import {
  formatEuros,
  formatMin1,
  formatSigned,
  formatSignedPct,
  formatSignedTime,
} from './fmt';
import {
  BUDGET_PCT_MAX,
  BUDGET_PCT_MIN,
  BUDGET_PCT_STEP,
  budgetValue,
  frequencyChange,
  groupExplanation,
  historySeries,
  linearScale,
  maxContribution,
  niceTicks,
  readTradeoff,
  stageStates,
  stagesFor,
  yDomain,
} from './model';
import { TradeoffChart } from './TradeoffChart';
import { THRESHOLD, previewedPoint, useOptimizer, type StoredResult } from './store';
import { useDiff } from './useDiff';
import s from './Optimizer.module.css';

declare global {
  interface Window {
    /** exposed for e2e tests and debugging */
    __vlabOptimizer?: typeof useOptimizer;
  }
}

/** Render a translated template with React nodes in place of `{name}` placeholders. */
function rich(template: string, nodes: Record<string, ReactNode>): ReactNode {
  return template.split(/(\{\w+\})/g).map((part, i) => {
    const m = /^\{(\w+)\}$/.exec(part);
    return <Fragment key={i}>{m && m[1]! in nodes ? nodes[m[1]!] : part}</Fragment>;
  });
}

/** Today's budget numbers from `/api/network` (the resource the optimizer is bound by). */
function useTodayTotals(base: Edit[] | null) {
  const day = useApp((st) => st.day);
  const q = useNetwork(day, base && base.length ? base : null);
  return q.data?.totals ?? null;
}

function useWindow() {
  const day = useApp((st) => st.day);
  const start = useWindowStart();
  return useMemo(() => ({ day, start, duration: ACC_WINDOW }), [day, start]);
}

export function OptimizerPanel() {
  const run = useOptimizer((st) => st.run);
  const last = useOptimizer((st) => st.last);
  const [setup, setSetup] = useState(false);
  useEffect(() => {
    window.__vlabOptimizer = useOptimizer;
  }, []);
  return (
    <div className={s.panel} data-testid="view-optimizer">
      {run.phase === 'running' ? (
        <RunningView />
      ) : run.phase === 'error' ? (
        <ErrorView onBack={() => setSetup(true)} />
      ) : last && !setup ? (
        <ResultView last={last} onRerun={() => setSetup(true)} />
      ) : (
        <SetupView hasResult={!!last} onBack={() => setSetup(false)} onStarted={() => setSetup(false)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------- setup

function SetupView({
  hasResult,
  onBack,
  onStarted,
}: {
  hasResult: boolean;
  onBack: () => void;
  onStarted: () => void;
}) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const settings = useOptimizer((st) => st.settings);
  const setSettings = useOptimizer((st) => st.setSettings);
  const start = useOptimizer((st) => st.start);
  const cancelled = useOptimizer((st) => st.run.cancelled);
  const edits = useScenario((st) => st.edits);
  const window = useWindow();
  const useBase = settings.fromScenario && edits.length > 0;
  const totals = useTodayTotals(useBase ? (edits as unknown as Edit[]) : null);
  const today = totals ? (settings.budgetKind === 'fleet' ? totals.fleet : totals.bus_hours) : null;
  const same = settings.budgetPct === 0;
  const value = today === null ? null : budgetValue(today, settings.budgetPct, settings.budgetKind);
  const anyMove = Object.values(settings.moves).some(Boolean);
  const fmt = (n: number) => formatNumber(n, lang, 0);
  const fleet = settings.budgetKind === 'fleet';

  const question =
    value === null
      ? null
      : t(
          fleet
            ? same
              ? 'opt.questionFleetSame'
              : 'opt.questionFleet'
            : same
              ? 'opt.questionHoursSame'
              : 'opt.questionHours',
          { n: fmt(value) },
        );

  const from = formatClock(window.start);
  const to = formatClock(window.start + window.duration);

  return (
    <>
      <div className={s.scroll}>
        <div className={s.eyebrow}>{t('opt.title')}</div>
        {question ? (
          <h1 className={s.question} data-testid="opt-question">
            {question}
          </h1>
        ) : (
          <div style={{ paddingTop: 4 }} aria-hidden>
            <Skeleton height={22} width="90%" />
            <Skeleton height={22} width="55%" style={{ marginTop: 8 }} />
          </div>
        )}
        <p className={s.lead}>{t('opt.lead')}</p>
        {hasResult ? (
          <Button variant="ghost" size="sm" className={s.backLink} onClick={onBack}>
            <ArrowRight strokeWidth={1.75} />
            {t('opt.previewBack')}
          </Button>
        ) : null}

        <section className={s.section} aria-labelledby="opt-budget">
          <h2 className={s.label} id="opt-budget">
            {t('opt.budget')}
            <span className={s.value} data-testid="opt-budget-value">
              {value === null
                ? '—'
                : same
                  ? t('opt.budgetSame')
                  : formatSignedPct(settings.budgetPct, lang, 0)}
            </span>
          </h2>
          <SegmentedControl<'fleet' | 'bus_hours'>
            size="sm"
            fullWidth
            label={t('opt.budgetKind')}
            value={settings.budgetKind}
            onChange={(budgetKind) => setSettings({ budgetKind })}
            options={[
              { value: 'fleet', label: t('opt.budgetFleet') },
              { value: 'bus_hours', label: t('opt.budgetHours') },
            ]}
          />
          <div className={s.sliderWrap}>
            <Slider
              label={t('opt.budgetAria')}
              min={BUDGET_PCT_MIN}
              max={BUDGET_PCT_MAX}
              step={BUDGET_PCT_STEP}
              value={settings.budgetPct}
              onChange={(budgetPct) => setSettings({ budgetPct })}
              valueText={
                value === null
                  ? undefined
                  : fleet
                    ? t('opt.tipBudgetFleet', { n: fmt(value) })
                    : t('opt.tipBudgetHours', { n: fmt(value) })
              }
            />
            <div className={s.ticks} aria-hidden>
              <span>{formatSignedPct(BUDGET_PCT_MIN, lang, 0)}</span>
              <span data-today="true">
                {value === null || today === null
                  ? ''
                  : t(fleet ? 'opt.budgetFleetValue' : 'opt.budgetHoursValue', {
                      n: fmt(value),
                      today: fmt(today),
                    })}
              </span>
              <span>{formatSignedPct(BUDGET_PCT_MAX, lang, 0)}</span>
            </div>
          </div>
        </section>

        <section className={s.section} aria-labelledby="opt-change">
          <h2 className={s.label} id="opt-change">
            {t('opt.change')}
          </h2>
          <div className={s.moves}>
            {(
              [
                ['frequency', 'opt.mFreq', 'opt.mFreqHint'],
                ['stops', 'opt.mStops', 'opt.mStopsHint'],
                ['new_lines', 'opt.mNew', 'opt.mNewHint'],
              ] as const
            ).map(([move, title, hint]) => (
              <div key={move} className={s.move}>
                <Switch
                  checked={settings.moves[move]}
                  onChange={(c) => setSettings({ moves: { ...settings.moves, [move]: c } })}
                >
                  <span data-testid={`opt-move-${move}`}>{t(title)}</span>
                </Switch>
                <p className={s.moveHint}>{t(hint)}</p>
              </div>
            ))}
          </div>
        </section>

        <section className={s.section} aria-labelledby="opt-objective">
          <h2 className={s.label} id="opt-objective">
            {t('opt.objective')}
          </h2>
          <SegmentedControl<'accessibility' | 'travel_time'>
            size="sm"
            fullWidth
            label={t('opt.objective')}
            value={settings.objective}
            onChange={(objective) => setSettings({ objective })}
            options={[
              { value: 'accessibility', label: t('opt.objAcc') },
              { value: 'travel_time', label: t('opt.objTime') },
            ]}
          />
          <p className={s.hint}>
            {t(settings.objective === 'accessibility' ? 'opt.objHint.accessibility' : 'opt.objHint.travel_time')}
          </p>
        </section>

        <section className={s.section} aria-labelledby="opt-window">
          <h2 className={s.label} id="opt-window">
            {t('opt.window')}
          </h2>
          <div className={s.windowRow}>
            <span className={s.windowValue} data-testid="opt-window">
              {t('opt.windowValue', { day: t(`day.${window.day}`), from, to })}
            </span>
            <span className={s.windowHint}>{t('opt.windowHint')}</span>
          </div>
        </section>

        {edits.length > 0 ? (
          <section className={s.section}>
            <Switch
              checked={settings.fromScenario}
              onChange={(fromScenario) => setSettings({ fromScenario })}
            >
              <span data-testid="opt-from-scenario">{t('opt.fromScenario')}</span>
            </Switch>
            <p className={s.moveHint}>{t('opt.fromScenarioHint', { n: edits.length })}</p>
          </section>
        ) : null}

        <section className={s.section}>
          <details className={s.disclosure}>
            <summary>
              <ChevronRight strokeWidth={1.75} aria-hidden />
              {t('opt.advanced')}
            </summary>
            <div className={s.disclosureBody}>
              <h3 className={s.label}>{t('opt.timeLimit')}</h3>
              <SegmentedControl<'30' | '60' | '120'>
                size="sm"
                fullWidth
                label={t('opt.timeLimit')}
                value={String(settings.timeLimit) as '30' | '60' | '120'}
                onChange={(v) => setSettings({ timeLimit: Number(v) })}
                options={(['30', '60', '120'] as const).map((v) => ({
                  value: v,
                  label: t('opt.seconds', { n: v }),
                }))}
              />
              <p className={s.hint}>{t('opt.timeHint')}</p>
            </div>
          </details>
        </section>

        {cancelled ? <p className={s.note}>{t('opt.cancelNote')}</p> : null}
        <HowItWorks />
      </div>
      <div className={s.footer}>
        <Button
          variant="primary"
          className={s.full}
          disabled={!anyMove || today === null}
          data-testid="opt-run"
          onClick={() => {
            if (today === null) return;
            onStarted();
            void start({
              window,
              today,
              base: useBase ? (edits as unknown as Edit[]) : null,
            });
          }}
        >
          <Sparkles strokeWidth={1.75} />
          {t('opt.run')}
        </Button>
        {!anyMove ? <p className={s.hint}>{t('opt.needMove')}</p> : null}
      </div>
    </>
  );
}

function HowItWorks() {
  const t = useT();
  return (
    <section className={s.section}>
      <details className={`${s.disclosure} ${s.how}`} data-testid="opt-how">
        <summary>
          <ChevronRight strokeWidth={1.75} aria-hidden />
          {t('opt.how')}
        </summary>
        <ul>
          <li>{t('opt.how1')}</li>
          <li>{t('opt.how2')}</li>
          <li>{t('opt.how3')}</li>
          <li>{t('opt.how4')}</li>
        </ul>
        <p>{t('opt.limits')}</p>
      </details>
    </section>
  );
}

// ---------------------------------------------------------------------------------- running

function useElapsed(since: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, []);
  return Math.max(0, Math.round((now - since) / 1000));
}

function RunningView() {
  const t = useT();
  const run = useOptimizer((st) => st.run);
  const cancel = useOptimizer((st) => st.cancel);
  const settings = useOptimizer((st) => st.settings);
  const moves = (Object.keys(settings.moves) as (keyof typeof settings.moves)[]).filter(
    (m) => settings.moves[m],
  );
  const stages = stagesFor(moves);
  const states = stageStates(stages, run.stage, false);
  const elapsed = useElapsed(run.startedAt);
  const hist = historySeries(run.history);
  return (
    <>
      <div className={s.scroll} aria-busy="true" data-testid="opt-running">
        <div className={s.eyebrow}>{t('opt.title')}</div>
        <h1 className={s.question}>{t('opt.running')}</h1>
        <div className={s.progress} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(run.progress * 100)}>
          <span style={{ transform: `scaleX(${Math.max(0.02, run.progress)})` }} />
        </div>
        {run.status === 'queued' ? (
          <p className={s.queued} data-testid="opt-queued">
            {t('opt.queued')}
          </p>
        ) : null}
        <ol className={s.stageList} aria-label={t('opt.stages')}>
          {states.map(({ id, state }, i) => (
            <li key={id} className={s.stage} data-state={state} aria-current={state === 'active' ? 'step' : undefined}>
              <span className={s.stageIcon}>
                {state === 'done' ? <Check strokeWidth={2} aria-hidden /> : <span className={s.dot} />}
              </span>
              {t(`opt.stage.${id}` as MessageKey)}
              {i === 0 ? <span className={s.elapsed}>{t('opt.seconds', { n: elapsed })}</span> : null}
            </li>
          ))}
        </ol>
        {hist.x.length > 1 ? (
          <div className={s.block}>
            <h2 className={s.label}>{t('opt.history')}</h2>
            <HistoryChart plot={hist} />
          </div>
        ) : null}
        {run.log.length ? (
          <div className={s.block}>
            <h2 className={s.label}>{t('opt.log')}</h2>
            <ul className={s.log} data-testid="opt-log">
              {run.log.slice(-6).map((l, i) => (
                <li key={`${l.t}-${i}`}>
                  <time>{l.t.toFixed(1)}</time>
                  <span>{l.msg}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
      <div className={s.footer}>
        <Button variant="secondary" className={s.full} onClick={cancel} data-testid="opt-cancel">
          {t('opt.cancel')}
        </Button>
        <p className={s.hint}>{t('opt.cancelNote')}</p>
      </div>
    </>
  );
}

function HistoryChart({ plot }: { plot: { x: number[]; y: number[] } }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const W = 320;
  const H = 96;
  const m = { l: 34, r: 6, t: 6, b: 16 };
  const xs = linearScale([Math.min(...plot.x), Math.max(...plot.x, plot.x[0]! + 1)], [m.l, W - m.r]);
  const [lo, hi] = yDomain(plot.y);
  const ys = linearScale([lo, hi], [H - m.b, m.t]);
  const d = plot.x.map((x, i) => `${i ? 'L' : 'M'}${xs(x).toFixed(1)},${ys(plot.y[i]!).toFixed(1)}`).join('');
  const ticks = niceTicks(lo, hi, 3);
  return (
    <svg className={s.chart} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t('opt.historyAria')} data-testid="opt-history">
      {ticks.map((v) => (
        <g key={v}>
          <line className={v === 0 ? s.axisZero : s.axis} x1={m.l} x2={W - m.r} y1={ys(v)} y2={ys(v)} />
          <text className={s.tick} x={m.l - 5} y={ys(v) + 3.5} textAnchor="end">
            {formatNumber(v, lang, Number.isInteger(v) ? 0 : 1)} %
          </text>
        </g>
      ))}
      <path className={s.chartLine} d={d} />
      <text className={s.tick} x={W - m.r} y={H - 2} textAnchor="end">
        {t('opt.historyX')}
      </text>
    </svg>
  );
}

function ErrorView({ onBack }: { onBack: () => void }) {
  const t = useT();
  const run = useOptimizer((st) => st.run);
  return (
    <div className={s.scroll} data-testid="opt-error">
      <div className={s.errorBox}>
        <EmptyState
          icon={<CloudOff strokeWidth={1.5} />}
          title={t('opt.error')}
          body={run.error ?? undefined}
          actions={
            <Button variant="secondary" onClick={onBack}>
              <RotateCw strokeWidth={1.75} />
              {t('opt.retry')}
            </Button>
          }
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------- result

function Delta({
  value,
  text,
  lowerIsBetter = true,
}: {
  value: number;
  text: string;
  lowerIsBetter?: boolean;
}) {
  const tone = Math.abs(value) < 1e-9 ? 'flat' : (value < 0) === lowerIsBetter ? 'good' : 'bad';
  return (
    <span className={s.delta} data-tone={tone}>
      {text}
    </span>
  );
}

function ResultView({ last, onRerun }: { last: StoredResult; onRerun: () => void }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const setView = useApp((st) => st.setView);
  const replay = useOptimizer((st) => st.replay);
  const setPreview = useOptimizer((st) => st.setPreview);
  const point = useOptimizer(previewedPoint);
  const diff = useDiff();
  const setSource = useCompare((st) => st.setSource);
  const ev: Evaluation = diff?.evaluation ?? last.result.evaluation;
  const isPoint = !!point;
  const kind = last.result.budget.kind;
  const budget = point ? point.budget : (last.result.budget.value ?? last.today);
  const scenario = (point ? point.scenario : last.result.scenario) as Edit[];
  const same = Math.abs(budget - last.today) < 0.5;
  const fmt = (n: number) => formatNumber(n, lang, 0);
  const timeObjective = last.objective === 'travel_time';
  const pct = ev.delta.objective_pct;
  const dtime = ev.delta.mean_travel_time;
  const improved = timeObjective ? dtime < -0.5 : pct > 0.05;

  const budgetPhrase = t(
    kind === 'fleet'
      ? same
        ? 'opt.withFleetSame'
        : 'opt.withFleet'
      : same
        ? 'opt.withHoursSame'
        : 'opt.withHours',
    { n: fmt(budget) },
  );
  const people = -ev.delta.underserved_population;
  const fmtN100 = useCallback((n: number) => formatNumber(Math.round(n / 100) * 100, lang), [lang]);
  const fmtPct = useCallback((n: number) => formatSignedPct(n, lang), [lang]);
  const fmtSec = useCallback((n: number) => formatNumber(Math.round(Math.abs(n)), lang) + ' s', [lang]);

  const metricTpl = timeObjective ? 'opt.metricTime' : 'opt.metricAcc';
  const headline = improved ? (
    <>
      {rich(t(metricTpl, { pct: '{pct}', sec: '{sec}' }), {
        pct: (
          <strong>
            <AnimatedNumber value={pct} format={fmtPct} duration={700} />
          </strong>
        ),
        sec: (
          <strong>
            <AnimatedNumber value={dtime} format={fmtSec} duration={700} />
          </strong>
        ),
      })}{' '}
      {budgetPhrase}
    </>
  ) : (
    t('opt.headNone')
  );

  const name = t(kind === 'fleet' ? 'opt.scenarioFleet' : 'opt.scenarioHours', { n: fmt(budget) });
  const apply = () => {
    useScenario.getState().setEdits(scenario as unknown as ScenarioEdit[], name);
    toast(t('opt.applied', { name }));
  };
  const goCompare = (to: 'compare') => {
    setSource('optimizer');
    setView(to);
  };
  const win = last.window;

  return (
    <>
      <div className={s.scroll} data-testid="opt-result">
        <div className={s.eyebrow}>
          {t('opt.title')}
          <IconButton label={t('opt.replay')} size="sm" onClick={replay} data-testid="opt-replay">
            <RotateCw strokeWidth={1.5} />
          </IconButton>
        </div>
        {isPoint ? (
          <div className={s.preview} data-testid="opt-preview">
            <span>
              {t('opt.previewing', {
                budget: t(kind === 'fleet' ? 'opt.tipBudgetFleet' : 'opt.tipBudgetHours', { n: fmt(budget) }),
              })}
            </span>
            <Button size="sm" variant="ghost" onClick={() => setPreview({ kind: 'result' })}>
              {t('opt.previewBack')}
            </Button>
          </div>
        ) : null}
        <p className={s.headline} data-testid="opt-headline">
          {headline}
        </p>
        {improved && Math.abs(people) >= 50 ? (
          <p className={s.sub}>
            {rich(t(people > 0 ? 'opt.subPeople' : 'opt.subPeopleMore', { n: '{n}' }), {
              n: <AnimatedNumber value={Math.abs(people)} format={fmtN100} duration={700} />,
            })}
          </p>
        ) : null}
        <p className={s.meta}>
          {t('opt.resultFor', {
            day: t(`day.${win.day}`),
            from: formatClock(win.start),
            to: formatClock(win.start + win.duration),
            s: formatNumber(last.result.elapsed_s, lang, 0),
          })}
          {last.fromScenario ? ` · ${t('opt.fromScenarioNote')}` : ''}
        </p>

        <section className={s.section}>
          <dl className={s.kpis} data-testid="opt-kpis">
            <dt>{t('opt.kMean')}</dt>
            <dd>
              {formatMin1(ev.scenario.mean_travel_time, lang)}
              <Delta value={dtime} text={formatSignedTime(dtime, lang)} />
            </dd>
            <dt>{t('opt.kUnder')}</dt>
            <dd>
              {fmt(ev.scenario.underserved_population)}
              <Delta
                value={ev.delta.underserved_population}
                text={formatSigned(ev.delta.underserved_population, lang)}
              />
            </dd>
            <dt>{kind === 'fleet' ? t('opt.kFleet') : t('opt.kHours')}</dt>
            <dd>
              {kind === 'fleet'
                ? t('opt.usedOf', { used: fmt(ev.scenario.fleet), budget: fmt(budget) })
                : t('opt.usedOf', { used: fmt(ev.scenario.bus_hours), budget: fmt(budget) })}
              <Delta
                value={kind === 'fleet' ? ev.delta.fleet : ev.delta.bus_hours}
                text={formatSigned(kind === 'fleet' ? ev.delta.fleet : ev.delta.bus_hours, lang)}
              />
            </dd>
            <dt>{kind === 'fleet' ? t('opt.kHours') : t('opt.kFleet')}</dt>
            <dd>
              {kind === 'fleet' ? fmt(ev.scenario.bus_hours) : fmt(ev.scenario.fleet)}
              <Delta
                value={kind === 'fleet' ? ev.delta.bus_hours : ev.delta.fleet}
                text={formatSigned(kind === 'fleet' ? ev.delta.bus_hours : ev.delta.fleet, lang)}
              />
            </dd>
            <dt>{t('opt.kCost')}</dt>
            <dd>
              {formatEuros(ev.scenario.cost_eur_year, lang)}
              <Delta
                value={ev.delta.cost_eur_year}
                text={formatEuros(ev.delta.cost_eur_year, lang).replace(/^(?=\d)/, '+')}
              />
            </dd>
          </dl>
        </section>

        {!isPoint ? <Explanation last={last} /> : null}

        <section className={s.section}>
          <Tradeoff last={last} />
        </section>

        <HowItWorks />
      </div>
      <div className={s.footer}>
        <Button variant="primary" className={s.full} onClick={apply} data-testid="opt-apply">
          <Check strokeWidth={1.75} />
          {t('opt.apply')}
        </Button>
        <div className={s.footerRow}>
          <Button size="sm" variant="secondary" onClick={() => goCompare('compare')} data-testid="opt-compare">
            <GitCompareArrows strokeWidth={1.5} />
            {t('opt.compare')}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => goCompare('compare')}>
            <FileText strokeWidth={1.5} />
            {t('opt.report')}
          </Button>
          <Button size="sm" variant="ghost" onClick={onRerun} data-testid="opt-rerun">
            {t('opt.rerun')}
          </Button>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------------- explanation

const SHOWN = 6;

function Explanation({ last }: { last: StoredResult }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const day = useApp((st) => st.day);
  const setFocus = useOptimizer((st) => st.setFocus);
  const diff = useDiff();
  const todayQ = useNetwork(day, null);
  const today = useMemo(() => (todayQ.data ? buildNetworkModel(todayQ.data) : null), [todayQ.data]);
  const [all, setAll] = useState(false);
  const groups = useMemo(() => groupExplanation(last.result.explanation), [last.result.explanation]);
  const max = maxContribution(last.result.explanation);
  const kind = last.result.budget.kind;
  const info = useCallback(
    (id: string | null) => (id ? (diff?.proposal?.routeById.get(id) ?? today?.routeById.get(id)) : undefined),
    [diff?.proposal, today],
  );
  const flyTo = (routeId: string | null, stopId?: string) => {
    const map = window.__vlabMap;
    if (!map) return;
    const r = info(routeId);
    const coords: [number, number][] = [];
    if (r) for (const p of r.patterns) for (const c of p.path) coords.push(c);
    else if (stopId) {
      const st = today?.stopById.get(stopId);
      if (st) coords.push([st.lon, st.lat], [st.lon + 0.004, st.lat + 0.003], [st.lon - 0.004, st.lat - 0.003]);
    }
    const b = boundsOf(coords);
    if (b) fitBounds(map, b);
  };

  const total = last.result.explanation.length;
  if (!total) return null;
  const lines = all ? groups.lines : groups.lines.slice(0, SHOWN);
  const res = (n: number) =>
    n === 0
      ? ''
      : t(kind === 'fleet' ? 'opt.busesDelta' : 'opt.hoursDelta', { n: formatSigned(n, lang, kind === 'fleet' ? 0 : 1) });

  return (
    <section className={s.section} data-testid="opt-explanation">
      <h2 className={s.sectionTitle}>{t('opt.explain')}</h2>
      <p className={s.sectionLead}>{t('opt.explainLead')}</p>

      {groups.newLines.length ? (
        <div className={s.group}>
          <h3 className={s.groupTitle}>{t('opt.newLines')}</h3>
          <ul className={s.items}>
            {groups.newLines.map((it, i) => {
              const r = info(it.route_id);
              return (
                <li key={`n${i}`}>
                  <button
                    type="button"
                    className={s.item}
                    onMouseEnter={() => setFocus(it.route_id)}
                    onMouseLeave={() => setFocus(null)}
                    onFocus={() => setFocus(it.route_id)}
                    onBlur={() => setFocus(null)}
                    onClick={() => flyTo(it.route_id)}
                  >
                    <span className={s.badgeBox}>
                      <LineBadge shortName={String(it.params.route ?? r?.short_name ?? '+')} color={r?.color ?? '#1F6FEB'} textColor={r?.text_color} />
                    </span>
                    <span className={s.itemMain}>
                      <span className={s.itemTitle}>
                        {displayName(String(it.params.from ?? ''))}
                        <ArrowRight strokeWidth={1.75} aria-hidden />
                        {displayName(String(it.params.to ?? ''))}
                      </span>
                      <span className={s.itemSub}>
                        {t('opt.newLineMeta', {
                          min: formatNumber(Number(it.params.headway ?? 0) / 60, lang, 0),
                          fleet: formatNumber(Number(it.params.fleet ?? 0), lang, 0),
                          km: formatNumber(Number(it.params.length_km ?? 0), lang, 1),
                          stops: formatNumber(Number(it.params.n_stops ?? 0), lang, 0),
                        })}
                      </span>
                    </span>
                    <span className={s.itemRes}>{res(Number(it.params.fleet ?? 0))}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {groups.lines.length ? (
        <div className={s.group}>
          <h3 className={s.groupTitle}>
            {t('opt.lines')}
            <span>{groups.lines.length}</span>
          </h3>
          <ul className={s.items} data-testid="opt-lines">
            {lines.map((it) => {
              const c = frequencyChange(it);
              const r = info(it.route_id);
              return (
                <li key={`${it.route_id}-${it.text_key}`}>
                  <button
                    type="button"
                    className={s.item}
                    onMouseEnter={() => setFocus(it.route_id)}
                    onMouseLeave={() => setFocus(null)}
                    onFocus={() => setFocus(it.route_id)}
                    onBlur={() => setFocus(null)}
                    onClick={() => flyTo(it.route_id)}
                  >
                    <span className={s.badgeBox}>
                      <LineBadge shortName={c.route} color={r?.color ?? '#888888'} textColor={r?.text_color} />
                    </span>
                    <span className={s.itemMain}>
                      <span className={s.itemTitle} data-dir={c.up ? 'up' : 'down'}>
                        {c.up ? <ArrowUpRight strokeWidth={2} aria-hidden /> : <ArrowDownRight strokeWidth={2} aria-hidden />}
                        {t('opt.every', { from: c.fromMin, to: c.toMin })}
                      </span>
                    </span>
                    <span className={s.itemRes}>{res(c.resource)}</span>
                    <span className={s.contrib} data-neg={c.contribution < 0} aria-hidden title={t('opt.contribution')}>
                      <span style={{ transform: `scaleX(${Math.max(0.03, Math.abs(c.contribution) / max)})` }} />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
          {groups.lines.length > SHOWN ? (
            <Button size="sm" variant="ghost" className={s.more} onClick={() => setAll((v) => !v)}>
              {all ? '−' : `+${groups.lines.length - SHOWN}`}
            </Button>
          ) : null}
        </div>
      ) : null}

      {groups.stops.length ? (
        <div className={s.group}>
          <h3 className={s.groupTitle}>
            {t('opt.stopsRemoved')}
            <span>{groups.stops.length}</span>
          </h3>
          <ul className={s.items}>
            {groups.stops.slice(0, all ? undefined : SHOWN).map((it, i) => (
              <li key={`s${i}`}>
                <button
                  type="button"
                  className={s.item}
                  onMouseEnter={() => setFocus(null, String(it.params.stop_id ?? ''))}
                  onMouseLeave={() => setFocus(null)}
                  onClick={() => flyTo(null, String(it.params.stop_id ?? ''))}
                >
                  <span />
                  <span className={s.itemMain}>
                    <span className={s.itemTitle}>{displayName(String(it.params.name ?? it.params.stop_id ?? ''))}</span>
                  </span>
                  <span />
                </button>
              </li>
            ))}
          </ul>
          <p className={s.stopsNote}>{t('opt.stopsNote')}</p>
        </div>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------------- trade-off

function Tradeoff({ last }: { last: StoredResult }) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const tradeoff = useOptimizer((st) => st.tradeoff);
  const trade = useOptimizer((st) => st.trade);
  const startTradeoff = useOptimizer((st) => st.startTradeoff);
  const preview = useOptimizer((st) => st.preview);
  const setPreview = useOptimizer((st) => st.setPreview);
  const totals = useTodayTotals(null);
  const kind = tradeoff?.result.budget_kind ?? last.result.budget.kind;
  const today = totals ? (last.result.budget.kind === 'fleet' ? totals.fleet : totals.bus_hours) : null;
  const reading = useMemo(() => (tradeoff ? readTradeoff(tradeoff.result) : null), [tradeoff]);
  const sel = preview.kind === 'point' ? preview.budget : null;
  const fmt = (n: number) => formatNumber(n, lang, 0);

  return (
    <div data-testid="opt-tradeoff">
      <h2 className={s.sectionTitle}>{t('opt.trade')}</h2>
      <p className={s.sectionLead}>{t('opt.tradeLead')}</p>
      {trade.phase === 'running' ? (
        <div aria-busy="true">
          <div className={s.progress} role="progressbar" aria-valuenow={Math.round(trade.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ transform: `scaleX(${Math.max(0.03, trade.progress)})` }} />
          </div>
          <Skeleton height={150} />
          <p className={s.note}>{t('opt.tradeRunning')}</p>
        </div>
      ) : (
        <>
          {tradeoff ? (
            <>
              <TradeoffChart result={tradeoff.result} selected={sel} onSelect={(b) => setPreview({ kind: 'point', budget: b })} />
              {reading ? (
                <p className={s.reading} data-testid="opt-reading">
                  {readingText(t, lang, reading, kind, fmt)}
                </p>
              ) : null}
              <p className={s.hint}>{t('opt.pointHint')}</p>
            </>
          ) : null}
          {trade.phase === 'error' ? <p className={s.note}>{t('opt.tradeError')}: {trade.error}</p> : null}
          <Button
            variant="secondary"
            size="sm"
            className={tradeoff ? s.more : undefined}
            disabled={today === null}
            data-testid="opt-trade-run"
            onClick={() => today !== null && void startTradeoff({ window: last.window, today })}
          >
            <RotateCw strokeWidth={1.5} />
            {t('opt.tradeRun')}
          </Button>
        </>
      )}
    </div>
  );
}

function readingText(
  t: ReturnType<typeof useT>,
  lang: 'es' | 'en' | 'eu',
  r: ReturnType<typeof readTradeoff>,
  kind: 'fleet' | 'bus_hours',
  fmt: (n: number) => string,
): string {
  const parts: string[] = [];
  if (r.sameBudgetGain !== null && r.sameBudgetGain > 0.05)
    parts.push(t('opt.readSame', { pct: formatSignedPct(r.sameBudgetGain, lang).replace(/^\+/, '') }));
  if (r.breakEven)
    parts.push(
      t(kind === 'fleet' ? 'opt.readBreakEven' : 'opt.readBreakEvenHours', {
        n: fmt(r.breakEven.budget),
        saved: `${formatNumber(r.breakEven.savedPct, lang, 0)} %`,
      }),
    );
  if (r.marginal)
    parts.push(
      r.diminishing
        ? t('opt.readDiminishing', {
            a: formatNumber(r.marginal.first, lang, 2),
            b: formatNumber(r.marginal.second, lang, 2),
          })
        : t('opt.readLinear'),
    );
  return parts.join(' ');
}

export { THRESHOLD };
