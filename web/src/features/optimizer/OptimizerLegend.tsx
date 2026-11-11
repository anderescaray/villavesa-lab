import { useApp } from '@/app/store';
import { Surface } from '@/components/ui';
import { useT } from '@/i18n';
import { DIVERGING } from '@/lib/palettes';
import { useOptimizer } from './store';
import { useDiff } from './useDiff';
import s from './Optimizer.module.css';

/** Floating legend of the animated diff (bottom-left of the map). */
export function OptimizerLegend() {
  const t = useT();
  const view = useApp((st) => st.view);
  const theme = useApp((st) => st.theme);
  const last = useOptimizer((st) => st.last);
  const diff = useDiff(view === 'optimizer');
  if (view !== 'optimizer' || !diff || !diff.evaluation || !diff.scenario.length) return null;
  const kinds = new Set(last?.result.explanation.map((e) => e.kind) ?? []);
  const hasNew =
    diff.from === 'result' ? kinds.has('new_line') : !!diff.proposal?.routes.some((r) => r.added);
  const hasStops =
    diff.from === 'result'
      ? kinds.has('stop')
      : !!diff.proposal?.network.stops.some((x) => x.removed);
  const p = DIVERGING[theme];
  const ramp = [p.pos[2]!, p.pos[1]!, p.pos[0]!, p.neg[2]!, p.neg[1]!, p.neg[0]!];
  return (
    <Surface
      className={s.legend}
      role="group"
      aria-label={t('opt.legend')}
      data-testid="opt-legend"
    >
      <div className={s.legendTitle}>{t('opt.legend')}</div>
      <ul className={s.legendItems}>
        <li>
          <span className={s.stroke} style={{ height: 5 }} />
          {t('opt.legendUp')}
        </li>
        <li>
          <span className={s.stroke} style={{ height: 2, opacity: 0.45 }} />
          {t('opt.legendDown')}
        </li>
        {hasNew ? (
          <li>
            <span className={`${s.stroke} ${s.strokeNew}`} style={{ height: 4 }} />
            {t('opt.legendNew')}
          </li>
        ) : null}
        {hasStops ? (
          <li>
            <span className={s.ring} />
            {t('opt.legendStop')}
          </li>
        ) : null}
      </ul>
      <div className={s.legendRamp}>
        <div className={s.legendTitle} style={{ textTransform: 'none', letterSpacing: 0 }}>
          {t('opt.legendTime')}
        </div>
        <div className={s.ramp} aria-hidden>
          {ramp.map((c) => (
            <span key={c} style={{ background: c }} />
          ))}
        </div>
        <div className={s.rampLabels} aria-hidden>
          <span>{t('opt.legendFaster')}</span>
          <span>{t('opt.legendSlower')}</span>
        </div>
      </div>
    </Surface>
  );
}
