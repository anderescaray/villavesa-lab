import { useMemo } from 'react';
import { useAccessibilityQuery, useNetwork, useZones } from '@/api/queries';
import { useEvaluation, type ScenarioEdit } from '@/api/scenario';
import type { Edit } from '@/api/types';
import { useApp } from '@/app/store';
import { ACC_WINDOW, useWindowStart } from '@/features/accessibility/useAccessibility';
import { buildNetworkModel } from '@/features/network/model';
import { THRESHOLD, useOptimizer } from '@/features/optimizer/store';
import { scenarioHash, useScenario } from '@/features/scenario/store';
import { useT } from '@/i18n';
import { formatNumber } from '@/lib/format';
import { useCompare, type CompareSource } from './store';

/**
 * Everything the compare view needs: which scenario is compared (the editor's or the
 * optimizer's last proposal), its evaluation against today, both networks and, in the
 * accessibility mode, both per-zone time surfaces.
 */
export function useCompareData(enabled = true) {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const day = useApp((st) => st.day);
  const edits = useScenario((st) => st.edits);
  const storeName = useScenario((st) => st.name);
  const last = useOptimizer((st) => st.last);
  const pref = useCompare((st) => st.source);
  const mode = useCompare((st) => st.mode);
  const start = useWindowStart();

  const available: Record<CompareSource, boolean> = {
    store: edits.length > 0,
    optimizer: !!last?.result.scenario.length,
  };
  const source: CompareSource | null =
    pref && available[pref]
      ? pref
      : available.store
        ? 'store'
        : available.optimizer
          ? 'optimizer'
          : null;

  const scenario = useMemo<Edit[] | null>(() => {
    if (source === 'store') return edits as unknown as Edit[];
    if (source === 'optimizer' && last) return last.result.scenario;
    return null;
  }, [source, edits, last]);

  const name =
    source === 'store'
      ? storeName || t('cmp.sourceStore')
      : last
        ? t(last.result.budget.kind === 'fleet' ? 'opt.scenarioFleet' : 'opt.scenarioHours', {
            n: formatNumber(last.result.budget.value ?? last.today, lang, 0),
          })
        : '';

  const window = useMemo(() => ({ day, start, duration: ACC_WINDOW }), [day, start]);
  const key = useMemo(
    () => (scenario ? scenarioHash(scenario as ScenarioEdit[]) : 'none'),
    [scenario],
  );
  const evaluation = useEvaluation(
    enabled && scenario ? (scenario as ScenarioEdit[]) : null,
    key,
    window,
    THRESHOLD,
  );
  const todayQ = useNetwork(day, null);
  const scenQ = useNetwork(day, enabled ? scenario : null);
  const today = useMemo(() => (todayQ.data ? buildNetworkModel(todayQ.data) : null), [todayQ.data]);
  const proposal = useMemo(
    () => (scenQ.data && scenario ? buildNetworkModel(scenQ.data) : null),
    [scenQ.data, scenario],
  );

  const wantAcc = enabled && mode === 'access' && !!scenario;
  const accToday = useAccessibilityQuery(
    wantAcc ? { window, scenario: null, threshold: THRESHOLD } : null,
  );
  const accScenario = useAccessibilityQuery(
    wantAcc ? { window, scenario, threshold: THRESHOLD } : null,
  );
  const { data: zones } = useZones(enabled);

  return {
    source,
    available,
    scenario,
    name,
    window,
    evaluation,
    today,
    proposal,
    accToday,
    accScenario,
    zones,
  };
}

export type CompareData = ReturnType<typeof useCompareData>;
