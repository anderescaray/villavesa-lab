/**
 * Scenario editor side panel: the change list (with inline edit, delete, undo/redo) and the
 * inspector of the active tool (frequency, bus priority, stop, new line).
 */
import {
  ArrowRight,
  CircleDot,
  Gauge,
  MousePointer2,
  Redo2,
  Spline,
  Timer,
  Trash2,
  TriangleAlert,
  Undo2,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type {
  AddRouteEdit,
  AddStopEdit,
  Period,
  ScenarioEdit,
  SetHeadwayEdit,
  SpeedUpEdit,
} from '@/api/scenario';
import { HEADWAY_MAX_S, HEADWAY_MIN_S } from '@/api/scenario';
import type { Route } from '@/api/types';
import { useApp } from '@/app/store';
import {
  Button,
  IconButton,
  Kbd,
  LineBadge,
  SegmentedControl,
  Slider,
  Switch,
  Tooltip,
} from '@/components/ui';
import { useNetworkModel, type NetworkModel } from '@/features/network/model';
import { useScenario } from '@/features/scenario/store';
import { useT, type TFunction } from '@/i18n';
import { displayName, formatMinutes, formatNumber } from '@/lib/format';
import { cancelDraft, finishDraft, headwayEditIndex, startDraft, upsertHeadway } from './actions';
import {
  HEADWAY_STEPS_MIN,
  corridorOf,
  distanceM,
  nearestStepIndex,
  newLinePalette,
  newStopId,
  nextLineName,
  summarize,
  useBaselineModel,
} from './model';
import { useEditor, type Tool } from './state';
import { useDraftSnap, useDraftStops } from './useDraft';
import { useLiveEvaluation } from './useLiveEvaluation';
import s from './Editor.module.css';

export const TOOL_ICON: Record<Tool, typeof Timer> = {
  select: MousePointer2,
  frequency: Timer,
  priority: Gauge,
  stop: CircleDot,
  draw: Spline,
};

const EDIT_ICON: Record<ScenarioEdit['type'], typeof Timer> = {
  set_headway: Timer,
  scale_frequency: Timer,
  speed_up: Gauge,
  remove_stop: CircleDot,
  move_stop: CircleDot,
  add_stop: CircleDot,
  remove_route: Trash2,
  add_route: Spline,
};

export function EditorPanel() {
  const t = useT();
  const edits = useScenario((st) => st.edits);
  const canUndo = useScenario((st) => st.past.length > 0);
  const canRedo = useScenario((st) => st.future.length > 0);
  const undo = useScenario((st) => st.undo);
  const redo = useScenario((st) => st.redo);
  const clear = useScenario((st) => st.clear);
  const tool = useEditor((st) => st.tool);
  const routeId = useEditor((st) => st.routeId);
  const stopId = useEditor((st) => st.stopId);
  const mod = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl+';

  let inspector: ReactNode = null;
  if (tool === 'draw') inspector = <DrawInspector />;
  else if (tool === 'priority') inspector = <PriorityInspector />;
  else if (tool === 'stop' || stopId) inspector = <StopInspector />;
  else if (tool === 'frequency' || routeId) inspector = <FrequencyInspector />;

  return (
    <div className={s.panel} data-testid="view-scenario">
      <div className={s.scroll}>
        <header className={s.header}>
          <h1 className={s.title}>{t('editor.title')}</h1>
          <div className={s.headerActions}>
            <IconButton
              size="sm"
              label={t('editor.undo')}
              shortcut={`${mod}Z`}
              disabled={!canUndo}
              onClick={undo}
            >
              <Undo2 strokeWidth={1.5} />
            </IconButton>
            <IconButton
              size="sm"
              label={t('editor.redo')}
              shortcut={`⇧${mod}Z`}
              disabled={!canRedo}
              onClick={redo}
            >
              <Redo2 strokeWidth={1.5} />
            </IconButton>
            <IconButton
              size="sm"
              label={t('editor.clearAll')}
              disabled={!edits.length}
              onClick={clear}
              data-testid="editor-clear"
            >
              <Trash2 strokeWidth={1.5} />
            </IconButton>
          </div>
        </header>
        <p className={s.sub}>
          {edits.length
            ? edits.length === 1
              ? t('editor.changesCount1')
              : t('editor.changesCount', { n: edits.length })
            : t('editor.baselineNote')}
        </p>
        {edits.length ? <ChangeList /> : inspector ? null : <EntryPoints />}
        {inspector ? <section className={s.section}>{inspector}</section> : null}
        {edits.length && !inspector ? <EntryPoints compact /> : null}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ entry points

function EntryPoints({ compact }: { compact?: boolean }) {
  const t = useT();
  const setTool = useEditor((st) => st.setTool);
  const edits = useScenario((st) => st.edits);
  const base = useBaselineModel();
  const entries: { tool: Tool; title: string; body: string }[] = [
    {
      tool: 'frequency',
      title: t('editor.entry.frequency'),
      body: t('editor.entry.frequencyBody'),
    },
    { tool: 'priority', title: t('editor.entry.priority'), body: t('editor.entry.priorityBody') },
    { tool: 'stop', title: t('editor.entry.stop'), body: t('editor.entry.stopBody') },
    { tool: 'draw', title: t('editor.entry.draw'), body: t('editor.entry.drawBody') },
  ];
  const keys: Record<Tool, string> = {
    select: 'V',
    frequency: 'F',
    priority: 'P',
    stop: 'S',
    draw: 'L',
  };
  return (
    <section className={s.section} data-testid="editor-entries">
      {compact ? <div className={s.eyebrow}>{t('editor.addChange')}</div> : null}
      <div className={s.entries}>
        {entries.map((e) => {
          const Icon = TOOL_ICON[e.tool];
          return (
            <button
              key={e.tool}
              type="button"
              className={s.entry}
              data-testid={`entry-${e.tool}`}
              onClick={() => {
                if (e.tool === 'draw') {
                  const existing = base?.routes.map((r) => r.color) ?? [];
                  startDraft(
                    nextLineName(edits, base?.routes.map((r) => r.short_name) ?? []),
                    newLinePalette(existing)[0]!,
                  );
                } else setTool(e.tool);
              }}
            >
              <span className={s.entryIcon}>
                <Icon strokeWidth={1.5} />
              </span>
              <span>
                <span className={s.entryTitle}>{e.title}</span>
                {compact ? null : <span className={s.entryBody}>{e.body}</span>}
              </span>
              <Kbd>{keys[e.tool]}</Kbd>
            </button>
          );
        })}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ change list

function EditBadge({
  routeId,
  badge,
  model,
  fallback,
}: {
  routeId: string | null;
  badge?: { shortName: string; color: string };
  model: NetworkModel | null;
  fallback: typeof Timer;
}) {
  const r = routeId ? model?.routeById.get(routeId) : undefined;
  if (badge) return <LineBadge size="sm" shortName={badge.shortName} color={badge.color} />;
  if (r)
    return (
      <LineBadge size="sm" shortName={r.short_name} color={r.color} textColor={r.text_color} />
    );
  const Icon = fallback;
  return (
    <span className={s.glyph}>
      <Icon strokeWidth={1.75} />
    </span>
  );
}

function ChangeList() {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const edits = useScenario((st) => st.edits);
  const remove = useScenario((st) => st.remove);
  const editing = useEditor((st) => st.editing);
  const setEd = useEditor((st) => st.set);
  const base = useBaselineModel();
  return (
    <section className={s.section}>
      <ul className={s.changes} data-testid="change-list" aria-label={t('editor.changes')}>
        {edits.map((e, i) => {
          const sum = summarize(e, t, lang, base);
          const open = editing === i;
          return (
            <li key={i} className={s.change} data-open={open} data-testid="change-row">
              <div className={s.changeRow}>
                <EditBadge
                  routeId={sum.routeId}
                  badge={sum.badge}
                  model={base}
                  fallback={EDIT_ICON[e.type]}
                />
                <button
                  type="button"
                  className={s.changeMain}
                  aria-expanded={open}
                  onClick={() => setEd({ editing: open ? null : i })}
                >
                  <span className={s.changeTitle}>{sum.title}</span>
                  <span className={s.changeDetail}>{sum.detail}</span>
                </button>
                <span className={s.changeActions}>
                  <IconButton
                    size="sm"
                    label={t('editor.deleteChange')}
                    onClick={() => {
                      remove(i);
                      setEd({ editing: null });
                    }}
                  >
                    <X strokeWidth={1.5} />
                  </IconButton>
                </span>
              </div>
              {open ? <InlineEditor index={i} edit={e} /> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function InlineEditor({ index, edit }: { index: number; edit: ScenarioEdit }) {
  const t = useT();
  const update = useScenario((st) => st.update);
  switch (edit.type) {
    case 'set_headway':
      return (
        <div className={s.inline}>
          <HeadwayControl
            value={edit.headway}
            onCommit={(h) => update(index, { ...edit, headway: h })}
          />
          <PeriodControl
            value={edit.period}
            onChange={(p) => update(index, { ...edit, period: p })}
          />
        </div>
      );
    case 'speed_up':
      return (
        <div className={s.inline}>
          <FactorControl
            value={edit.factor}
            onChange={(f) => update(index, { ...edit, factor: f })}
          />
        </div>
      );
    case 'add_stop':
      return (
        <div className={s.inline}>
          <NameInput
            value={edit.name}
            label={t('editor.stop.name')}
            onCommit={(name) => update(index, { ...edit, name } as AddStopEdit)}
          />
        </div>
      );
    case 'add_route':
      return (
        <div className={s.inline}>
          <HeadwayControl
            value={edit.headway}
            onCommit={(h) => update(index, { ...edit, headway: h } as AddRouteEdit)}
          />
        </div>
      );
    default:
      return (
        <div className={s.inline}>
          <span className={s.muted}>{t('editor.noParams')}</span>
        </div>
      );
  }
}

// ------------------------------------------------------------------ controls

function useCommit<T>(value: T, onCommit: (v: T) => void, ms = 250) {
  const [local, setLocal] = useState(value);
  const last = useRef(value);
  const cb = useRef(onCommit);
  cb.current = onCommit;
  useEffect(() => {
    if (value !== last.current) {
      last.current = value;
      setLocal(value);
    }
  }, [value]);
  useEffect(() => {
    if (local === last.current) return;
    const id = window.setTimeout(() => {
      last.current = local;
      cb.current(local);
    }, ms);
    return () => window.clearTimeout(id);
  }, [local, ms]);
  return [local, setLocal] as const;
}

/** Headway: snapped slider (2–60 min) + exact numeric input (minutes, decimals allowed). */
export function HeadwayControl({
  value,
  onCommit,
}: {
  value: number;
  onCommit: (seconds: number) => void;
}) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const [local, setLocal] = useCommit(value, onCommit);
  const [text, setText] = useState(() => formatMinutes(value, lang));
  useEffect(() => setText(formatMinutes(local, lang)), [local, lang]);
  const commitText = () => {
    const m = Number(text.replace(',', '.'));
    if (!Number.isFinite(m)) return setText(formatMinutes(local, lang));
    const sec = Math.round(Math.min(HEADWAY_MAX_S, Math.max(HEADWAY_MIN_S, m * 60)));
    setLocal(sec);
    setText(formatMinutes(sec, lang));
  };
  return (
    <div className={s.field}>
      <div className={s.fieldRow}>
        <span className={s.label}>{t('editor.freq.every')}</span>
        <label className={s.numberInput}>
          <input
            inputMode="decimal"
            aria-label={t('editor.freq.minutes')}
            value={text}
            data-testid="headway-input"
            onChange={(e) => setText(e.target.value)}
            onBlur={commitText}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitText();
            }}
          />
          <span>min</span>
        </label>
      </div>
      <Slider
        label={t('editor.freq.headway')}
        min={0}
        max={HEADWAY_STEPS_MIN.length - 1}
        value={nearestStepIndex(local)}
        valueText={t('editor.freq.everyN', { min: formatMinutes(local, lang) })}
        onChange={(i) => setLocal(HEADWAY_STEPS_MIN[i]! * 60)}
      />
    </div>
  );
}

function PeriodControl({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  const t = useT();
  return (
    <SegmentedControl<Period>
      size="sm"
      fullWidth
      label={t('editor.freq.period')}
      value={value}
      onChange={onChange}
      options={[
        { value: 'all', label: t('editor.period.all') },
        { value: 'peak', label: t('editor.period.peak') },
        { value: 'offpeak', label: t('editor.period.offpeak') },
      ]}
    />
  );
}

const FACTORS = ['1.1', '1.2', '1.3', '1.4', '1.5'] as const;
function FactorControl({ value, onChange }: { value: number; onChange: (f: number) => void }) {
  const t = useT();
  const v = FACTORS.reduce((a, b) =>
    Math.abs(Number(b) - value) < Math.abs(Number(a) - value) ? b : a,
  );
  return (
    <div className={s.field}>
      <span className={s.label}>{t('editor.priority.gain')}</span>
      <SegmentedControl<(typeof FACTORS)[number]>
        size="sm"
        fullWidth
        label={t('editor.priority.gain')}
        value={v}
        onChange={(f) => onChange(Number(f))}
        options={FACTORS.map((f) => ({
          value: f,
          label: `+${Math.round((Number(f) - 1) * 100)} %`,
        }))}
      />
    </div>
  );
}

function NameInput({
  value,
  label,
  onCommit,
  placeholder,
}: {
  value: string;
  label: string;
  onCommit: (v: string) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <input
      className={s.textInput}
      aria-label={label}
      placeholder={placeholder ?? label}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => text !== value && onCommit(text)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
      }}
    />
  );
}

// ------------------------------------------------------------------ line picker

function LinePicker({ hint }: { hint: string }) {
  const t = useT();
  const { model } = useNetworkModel();
  const pick = useEditor((st) => st.pickRoute);
  const routes = model?.routes ?? [];
  return (
    <div className={s.field}>
      <span className={s.muted}>{hint}</span>
      <div
        className={s.badgeGrid}
        role="group"
        aria-label={t('editor.pickLine')}
        data-testid="line-picker"
      >
        {routes.map((r) => (
          <Tooltip key={r.id} content={displayName(r.long_name)}>
            <button
              type="button"
              className={s.badgeBtn}
              aria-label={`${r.short_name} · ${displayName(r.long_name)}`}
              onClick={() => pick(r.id)}
            >
              <LineBadge shortName={r.short_name} color={r.color} textColor={r.text_color} />
            </button>
          </Tooltip>
        ))}
      </div>
    </div>
  );
}

function LineHead({ route, onClose }: { route: Route; onClose: () => void }) {
  const t = useT();
  return (
    <div className={s.fieldRow}>
      <div className={s.lineHead}>
        <LineBadge
          size="lg"
          shortName={route.short_name}
          color={route.color}
          textColor={route.text_color}
        />
        <span className={s.lineName}>{displayName(route.long_name)}</span>
      </div>
      <IconButton size="sm" label={t('editor.otherLine')} onClick={onClose}>
        <X strokeWidth={1.5} />
      </IconButton>
    </div>
  );
}

// ------------------------------------------------------------------ frequency

const headwayOf = (r: Route, p: Period) =>
  p === 'peak' ? r.stats.headway_peak : p === 'offpeak' ? r.stats.headway_offpeak : r.stats.headway;

function FrequencyInspector() {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const routeId = useEditor((st) => st.routeId);
  const period = useEditor((st) => st.period);
  const setEd = useEditor((st) => st.set);
  const pick = useEditor((st) => st.pickRoute);
  const edits = useScenario((st) => st.edits);
  const removeEdit = useScenario((st) => st.remove);
  const add = useScenario((st) => st.add);
  const base = useBaselineModel();
  const { model } = useNetworkModel();
  const { data: ev, stale } = useLiveEvaluation();
  const route = routeId
    ? (base?.routeById.get(routeId) ?? model?.routeById.get(routeId))
    : undefined;
  if (!route) return <LinePicker hint={t('editor.freq.pick')} />;
  const current = headwayOf(route, period);
  const idx = headwayEditIndex(edits, route.id, period);
  const value = idx >= 0 ? (edits[idx] as SetHeadwayEdit).headway : (current ?? 600);
  const res = ev?.routes.find((r) => r.id === route.id);
  const removed = edits.some((e) => e.type === 'remove_route' && e.route_id === route.id);
  return (
    <div className={s.inspector} data-testid="frequency-inspector">
      <LineHead route={route} onClose={() => pick(null)} />
      <PeriodControl value={period} onChange={(p) => setEd({ period: p })} />
      <div className={s.compare}>
        <span>
          <span className={s.label}>{t('editor.freq.current')}</span>
          <span className={s.compareValue}>
            {t('editor.freq.everyN', { min: formatMinutes(current, lang) })}
          </span>
        </span>
        <ArrowRight className={s.compareArrow} strokeWidth={1.5} />
        <span>
          <span className={s.label}>{t('editor.freq.new')}</span>
          <span className={s.compareValue} data-testid="headway-new">
            {t('editor.freq.everyN', { min: formatMinutes(value, lang) })}
          </span>
        </span>
      </div>
      <HeadwayControl
        key={`${route.id}|${period}`}
        value={value}
        onCommit={(h) => upsertHeadway(route.id, period, h)}
      />
      {res ? (
        <dl className={s.kv} style={{ opacity: stale ? 0.5 : 1 }} data-testid="route-resources">
          <ResRow label={t('editor.res.fleet')} pair={res.fleet} lang={lang} />
          <ResRow label={t('editor.res.busHours')} pair={res.bus_hours} lang={lang} digits={1} />
          <ResRow label={t('editor.res.trips')} pair={res.trips} lang={lang} />
        </dl>
      ) : null}
      <div className={s.actions}>
        {idx >= 0 ? (
          <Button size="sm" variant="secondary" onClick={() => removeEdit(idx)}>
            {t('editor.freq.reset')}
          </Button>
        ) : null}
        {!removed && !route.added ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              add({ type: 'remove_route', route_id: route.id });
              pick(null);
            }}
          >
            <Trash2 strokeWidth={1.5} />
            {t('editor.freq.removeLine')}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function ResRow({
  label,
  pair,
  lang,
  digits = 0,
}: {
  label: string;
  pair: [number, number] | [number | null, number | null];
  lang: 'es' | 'en' | 'eu';
  digits?: number;
}) {
  const [a, b] = pair;
  const d = a !== null && b !== null ? b - a : null;
  return (
    <>
      <dt>{label}</dt>
      <dd>{formatNumber(a, lang, digits)}</dd>
      <dd className={s.kvArrow}>→</dd>
      <dd>
        <strong>{formatNumber(b, lang, digits)}</strong>
        {d ? (
          <span className={s.tag}>
            {' '}
            ({d > 0 ? '+' : '−'}
            {formatNumber(Math.abs(d), lang, digits)})
          </span>
        ) : null}
      </dd>
    </>
  );
}

// ------------------------------------------------------------------ bus priority

function PriorityInspector() {
  const t = useT();
  const routeId = useEditor((st) => st.routeId);
  const direction = useEditor((st) => st.direction);
  const corridor = useEditor((st) => st.corridor);
  const setCorridor = useEditor((st) => st.setCorridor);
  const setEd = useEditor((st) => st.set);
  const pick = useEditor((st) => st.pickRoute);
  const add = useScenario((st) => st.add);
  const { model } = useNetworkModel();
  const route = routeId ? model?.routeById.get(routeId) : undefined;
  const c = useMemo(
    () =>
      route && corridor.start && corridor.end
        ? corridorOf(route, corridor.start, corridor.end, direction)
        : null,
    [route, corridor.start, corridor.end, direction],
  );
  if (!route || !model) return <LinePicker hint={t('editor.priority.pick')} />;
  const pattern = route.patterns.find((p) => p.direction === direction) ?? route.patterns[0];
  const lengthM = c
    ? (c.pattern.stop_offsets[c.pattern.stop_ids.indexOf(c.stopIds[c.stopIds.length - 1]!)] ?? 0) -
      (c.pattern.stop_offsets[c.pattern.stop_ids.indexOf(c.stopIds[0]!)] ?? 0)
    : 0;
  const onStop = (id: string) => {
    if (!corridor.start || corridor.end || id === corridor.start)
      setCorridor({ start: id, end: null });
    else if (corridorOf(route, corridor.start, id, direction)) setCorridor({ end: id });
    else setCorridor({ start: id, end: null });
  };
  const inRange = new Set(c?.stopIds ?? []);
  return (
    <div className={s.inspector} data-testid="priority-inspector">
      <LineHead route={route} onClose={() => pick(null)} />
      {route.patterns.length > 1 ? (
        <SegmentedControl<'0' | '1'>
          size="sm"
          fullWidth
          label={t('editor.direction')}
          value={String(pattern?.direction ?? 0) as '0' | '1'}
          onChange={(d) => {
            setEd({ direction: Number(d) });
            setCorridor({ start: null, end: null });
          }}
          options={route.patterns.map((p) => ({
            value: String(p.direction) as '0' | '1',
            label: t('editor.towards', { headsign: displayName(p.headsign) }),
          }))}
        />
      ) : null}
      <span className={s.muted}>
        {!corridor.start
          ? t('editor.priority.pickStart')
          : !corridor.end
            ? t('editor.priority.pickEnd')
            : t('editor.priority.segment', {
                n: (c?.stopIds.length ?? 1) - 1,
                km: formatNumber(lengthM / 1000, useApp.getState().lang, 1),
              })}
      </span>
      <ul className={s.stopList} aria-label={t('editor.stops')}>
        {pattern?.stop_ids.map((id) => {
          const st = model.stopById.get(id);
          const isEnd = id === corridor.start || id === corridor.end;
          return (
            <li key={id}>
              <button
                type="button"
                className={s.stopItem}
                data-in={inRange.has(id)}
                onClick={() => onStop(id)}
                style={{
                  color: isEnd ? model.mapColor(route.id, useApp.getState().theme) : undefined,
                }}
              >
                <span className={s.dot} data-fill={isEnd} />
                <span className={s.stopName} style={{ color: 'var(--text)' }}>
                  {st ? displayName(st.name) : id}
                </span>
                <span className={s.tag}>
                  {id === corridor.start
                    ? t('editor.priority.start')
                    : id === corridor.end
                      ? t('editor.priority.end')
                      : ''}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <FactorControl value={corridor.factor} onChange={(f) => setCorridor({ factor: f })} />
      <Switch checked={corridor.allLines} onChange={(v) => setCorridor({ allLines: v })}>
        <span className={s.label}>{t('editor.priority.allLines')}</span>
      </Switch>
      <Button
        variant="primary"
        disabled={!c}
        data-testid="priority-apply"
        onClick={() => {
          if (!c) return;
          const edit: SpeedUpEdit = {
            type: 'speed_up',
            route_id: corridor.allLines ? null : route.id,
            stop_ids: c.stopIds,
            factor: corridor.factor,
          };
          add(edit);
          setCorridor({ start: null, end: null });
        }}
      >
        {t('editor.priority.apply')}
      </Button>
    </div>
  );
}

// ------------------------------------------------------------------ stops

function StopInspector() {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const stopId = useEditor((st) => st.stopId);
  const routeId = useEditor((st) => st.routeId);
  const direction = useEditor((st) => st.direction);
  const adding = useEditor((st) => st.addingStop);
  const pending = useEditor((st) => st.pendingStop);
  const setEd = useEditor((st) => st.set);
  const pick = useEditor((st) => st.pickRoute);
  const edits = useScenario((st) => st.edits);
  const add = useScenario((st) => st.add);
  const removeEdit = useScenario((st) => st.remove);
  const { model } = useNetworkModel();
  const base = useBaselineModel();
  const [far, setFar] = useState(false);
  useEffect(() => {
    const on = () => setFar(true);
    window.addEventListener('vlab:editor-addstop-far', on);
    return () => window.removeEventListener('vlab:editor-addstop-far', on);
  }, []);
  useEffect(() => setFar(false), [pending]);
  if (!model) return null;

  // add-stop flow
  if (adding) {
    const route = routeId ? model.routeById.get(routeId) : undefined;
    if (!route) return <LinePicker hint={t('editor.stop.addPick')} />;
    const after = pending ? model.stopById.get(pending.afterStopId) : undefined;
    return (
      <div className={s.inspector} data-testid="addstop-inspector">
        <LineHead route={route} onClose={() => setEd({ addingStop: false, pendingStop: null })} />
        {route.patterns.length > 1 ? (
          <SegmentedControl<'0' | '1'>
            size="sm"
            fullWidth
            label={t('editor.direction')}
            value={String(direction) as '0' | '1'}
            onChange={(d) => setEd({ direction: Number(d), pendingStop: null })}
            options={route.patterns.map((p) => ({
              value: String(p.direction) as '0' | '1',
              label: t('editor.towards', { headsign: displayName(p.headsign) }),
            }))}
          />
        ) : null}
        <span className={far ? `${s.muted} ${s.error}` : s.muted}>
          {far
            ? t('editor.stop.tooFar')
            : pending
              ? t('editor.stop.after', { stop: after ? displayName(after.name) : '' })
              : t('editor.stop.addHint')}
        </span>
        {pending ? (
          <>
            <input
              className={s.textInput}
              aria-label={t('editor.stop.name')}
              placeholder={t('editor.stop.name')}
              value={pending.name}
              autoFocus
              onChange={(e) => setEd({ pendingStop: { ...pending, name: e.target.value } })}
            />
            <Button
              variant="primary"
              data-testid="addstop-apply"
              onClick={() => {
                add({
                  type: 'add_stop',
                  stop_id: newStopId(),
                  name: pending.name.trim() || t('editor.stop.newName', { line: route.short_name }),
                  lon: Math.round(pending.lon * 1e6) / 1e6,
                  lat: Math.round(pending.lat * 1e6) / 1e6,
                  route_id: pending.routeId,
                  direction: pending.direction,
                  after_stop_id: pending.afterStopId,
                });
                setEd({ pendingStop: null });
              }}
            >
              {t('editor.stop.addApply')}
            </Button>
          </>
        ) : null}
      </div>
    );
  }

  const stop = stopId ? model.stopById.get(stopId) : undefined;
  if (!stop)
    return (
      <div className={s.inspector}>
        <span className={s.muted}>{t('editor.stop.hint')}</span>
        <Button
          variant="secondary"
          onClick={() => setEd({ addingStop: true })}
          data-testid="addstop-start"
        >
          {t('editor.stop.addToLine')}
        </Button>
      </div>
    );
  const moveIdx = edits.findIndex((e) => e.type === 'move_stop' && e.stop_id === stop.id);
  const orig = base?.stopById.get(stop.id);
  const moved = moveIdx >= 0 && orig ? distanceM([orig.lon, orig.lat], [stop.lon, stop.lat]) : 0;
  return (
    <div className={s.inspector} data-testid="stop-inspector">
      <div className={s.fieldRow}>
        <span className={s.lineName}>{displayName(stop.name)}</span>
        <IconButton size="sm" label={t('editor.close')} onClick={() => setEd({ stopId: null })}>
          <X strokeWidth={1.5} />
        </IconButton>
      </div>
      <div className={s.badgeGrid}>
        {stop.routes.map((id) => {
          const r = model.routeById.get(id);
          return r ? (
            <button
              key={id}
              type="button"
              className={s.badgeBtn}
              aria-pressed={routeId === id}
              aria-label={r.short_name}
              onClick={() => pick(routeId === id ? null : id)}
            >
              <LineBadge
                size="sm"
                shortName={r.short_name}
                color={r.color}
                textColor={r.text_color}
              />
            </button>
          ) : null;
        })}
      </div>
      {stop.removed ? (
        <span className={s.muted}>{t('editor.stop.isRemoved')}</span>
      ) : (
        <div className={s.actions}>
          <Button
            size="sm"
            variant="secondary"
            data-testid="stop-remove-all"
            onClick={() => {
              add({ type: 'remove_stop', stop_id: stop.id });
              setEd({ stopId: null });
            }}
          >
            {t('editor.stop.removeAll')}
          </Button>
          {routeId && stop.routes.includes(routeId) ? (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => add({ type: 'remove_stop', stop_id: stop.id, route_id: routeId })}
            >
              {t('editor.stop.removeLine', {
                line: model.routeById.get(routeId)?.short_name ?? '',
              })}
            </Button>
          ) : null}
        </div>
      )}
      <span className={s.muted}>
        {moveIdx >= 0
          ? t('editor.stop.moved', { m: formatNumber(moved, lang) })
          : t('editor.stop.dragHint')}
      </span>
      {moveIdx >= 0 ? (
        <Button size="sm" variant="ghost" onClick={() => removeEdit(moveIdx)}>
          {t('editor.stop.resetMove')}
        </Button>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ draw a new line

function DrawInspector() {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const draft = useEditor((st) => st.draft);
  const setDraft = useEditor((st) => st.setDraft);
  const edits = useScenario((st) => st.edits);
  const base = useBaselineModel();
  const { rows, snap } = useDraftStops();
  const { pending, query } = useDraftSnap();
  const [incomplete, setIncomplete] = useState(false);
  useEffect(() => {
    const on = () => setIncomplete(true);
    window.addEventListener('vlab:editor-draft-incomplete', on);
    return () => window.removeEventListener('vlab:editor-draft-incomplete', on);
  }, []);
  const palette = useMemo(() => newLinePalette(base?.routes.map((r) => r.color) ?? []), [base]);
  if (!draft) {
    return (
      <div className={s.inspector}>
        <span className={s.muted}>{t('editor.draw.intro')}</span>
        <Button
          variant="primary"
          onClick={() =>
            startDraft(
              nextLineName(edits, base?.routes.map((r) => r.short_name) ?? []),
              palette[0]!,
            )
          }
        >
          {t('editor.draw.start')}
        </Button>
      </div>
    );
  }
  const included = rows.filter((r) => r.included).length;
  return (
    <div className={s.inspector} data-testid="draw-inspector">
      <div className={s.fieldRow}>
        <div className={s.lineHead}>
          <LineBadge size="lg" shortName={draft.shortName || '?'} color={draft.color} />
          <span className={s.lineName}>{t('editor.draw.title')}</span>
        </div>
        <span className={s.muted} data-testid="draft-length">
          {snap ? `${formatNumber(snap.length_m / 1000, lang, 1)} km` : '—'}
          {pending && draft.waypoints.length >= 2 ? ' ·' : ''}
        </span>
      </div>
      <span className={s.muted}>
        {draft.waypoints.length < 2 ? t('editor.draw.hintStart') : t('editor.draw.hintMore')}
      </span>
      <SegmentedControl<'wp' | 'stop'>
        size="sm"
        fullWidth
        label={t('editor.draw.clickAdds')}
        value={draft.placeStops ? 'stop' : 'wp'}
        onChange={(v) => setDraft({ placeStops: v === 'stop' })}
        options={[
          { value: 'wp', label: t('editor.draw.addWaypoint') },
          { value: 'stop', label: t('editor.draw.addStop') },
        ]}
      />
      {snap?.warnings.length || query.isError ? (
        <div className={s.notice} role="status">
          <TriangleAlert strokeWidth={1.75} />
          <span>{query.isError ? t('editor.draw.snapError') : t('editor.draw.snapWarning')}</span>
        </div>
      ) : null}
      <div className={s.field}>
        <div className={s.fieldRow}>
          <span className={s.eyebrow}>{t('editor.draw.stops', { n: included })}</span>
        </div>
        {rows.length ? (
          <ul className={s.stopList} data-testid="draft-stops">
            {rows.map((r) => (
              <li key={r.key}>
                <button
                  type="button"
                  className={s.stopItem}
                  data-off={!r.included}
                  aria-pressed={r.included}
                  style={{ color: draft.color }}
                  onClick={() => {
                    if (!r.existing)
                      setDraft({ newStops: draft.newStops.filter((n) => n.key !== r.key) });
                    else
                      setDraft({
                        excluded: r.included
                          ? [...draft.excluded, r.key]
                          : draft.excluded.filter((k) => k !== r.key),
                      });
                  }}
                >
                  <span className={s.dot} data-fill={r.included} />
                  <span
                    className={s.stopName}
                    style={{ color: r.included ? 'var(--text)' : undefined }}
                  >
                    {r.existing ? displayName(r.name) : r.name || t('editor.stop.unnamed')}
                  </span>
                  <span className={s.tag}>{r.existing ? '' : t('editor.draw.newTag')}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <span className={s.muted}>{t('editor.draw.noStops')}</span>
        )}
      </div>
      <div className={s.fieldRow}>
        <div className={s.field} style={{ flex: '0 0 72px' }}>
          <span className={s.label}>{t('editor.draw.shortName')}</span>
          <input
            className={s.textInput}
            maxLength={4}
            aria-label={t('editor.draw.shortName')}
            value={draft.shortName}
            onChange={(e) => setDraft({ shortName: e.target.value.toUpperCase() })}
          />
        </div>
        <div className={s.field}>
          <span className={s.label}>{t('editor.draw.color')}</span>
          <div className={s.swatches} role="group" aria-label={t('editor.draw.color')}>
            {palette.map((c) => (
              <button
                key={c}
                type="button"
                className={s.swatch}
                style={{ background: c }}
                aria-label={c}
                aria-pressed={draft.color === c}
                onClick={() => setDraft({ color: c })}
              />
            ))}
          </div>
        </div>
      </div>
      <HeadwayControl value={draft.headway} onCommit={(h) => setDraft({ headway: h })} />
      <Switch checked={draft.bidirectional} onChange={(v) => setDraft({ bidirectional: v })}>
        <span className={s.label}>{t('editor.draw.bidirectional')}</span>
      </Switch>
      {incomplete && included < 2 ? (
        <span className={`${s.muted} ${s.error}`}>{t('editor.draw.needStops')}</span>
      ) : null}
      <div className={s.actions}>
        <Button variant="secondary" onClick={cancelDraft}>
          {t('editor.cancel')}
          <Kbd>Esc</Kbd>
        </Button>
        <Button
          variant="primary"
          disabled={included < 2 || draft.waypoints.length < 2}
          onClick={() => finishDraft()}
          data-testid="draft-finish"
        >
          {t('editor.draw.finish')}
        </Button>
      </div>
    </div>
  );
}

export type { TFunction };
