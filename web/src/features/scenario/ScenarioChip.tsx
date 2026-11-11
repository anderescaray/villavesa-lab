/**
 * "Scenario · N changes" chip in the top bar, visible in every view while a scenario is active,
 * so the user always knows whether the map shows today's network or the edited one. It toggles a
 * baseline peek and discards the scenario (undoable from the editor).
 */
import { Eye, EyeOff, X } from 'lucide-react';
import { useApp } from '@/app/store';
import { IconButton, Surface, toast } from '@/components/ui';
import { useT } from '@/i18n';
import { useScenario } from './store';
import s from '@/features/editor/Editor.module.css';

export function ScenarioChip() {
  const t = useT();
  const n = useScenario((st) => st.edits.length);
  const peek = useScenario((st) => st.peekBaseline);
  const setPeek = useScenario((st) => st.setPeek);
  const clear = useScenario((st) => st.clear);
  const setView = useApp((st) => st.setView);
  if (!n) return null;
  return (
    <Surface className={s.chip} data-peek={peek} data-testid="scenario-chip">
      <span className={s.chipDot} aria-hidden />
      <button
        type="button"
        className={s.chipLabel}
        style={{ border: 0, background: 'none', padding: 0 }}
        onClick={() => setView('scenario')}
      >
        {peek
          ? t('editor.chip.baseline')
          : n === 1
            ? t('editor.chip.scenario1')
            : t('editor.chip.scenario', { n })}
      </button>
      <IconButton
        size="sm"
        label={peek ? t('editor.chip.showScenario') : t('editor.chip.showBaseline')}
        pressed={peek}
        onClick={() => setPeek(!peek)}
        data-testid="scenario-peek"
      >
        {peek ? <EyeOff strokeWidth={1.5} /> : <Eye strokeWidth={1.5} />}
      </IconButton>
      <IconButton
        size="sm"
        label={t('editor.chip.discard')}
        onClick={() => {
          clear();
          toast(t('editor.chip.discarded'));
        }}
      >
        <X strokeWidth={1.5} />
      </IconButton>
    </Surface>
  );
}
