import { Info, Link2, Monitor, Moon, Sun } from 'lucide-react';
import { useApp, type ThemePref } from '@/app/store';
import { IconButton, SegmentedControl, Surface, toast } from '@/components/ui';
import { LANGS, useT, type Lang } from '@/i18n';
import { ScenarioChip } from '@/features/scenario/ScenarioChip';
import { AboutPopover } from './AboutPopover';
import s from './Shell.module.css';

const LANG_LABEL: Record<Lang, string> = { es: 'ES', en: 'EN', eu: 'EU' };
const LANG_NAME: Record<Lang, string> = { es: 'Español', en: 'English', eu: 'Euskara' };

export function TopControls() {
  const t = useT();
  const lang = useApp((st) => st.lang);
  const themePref = useApp((st) => st.themePref);
  const set = useApp((st) => st.set);
  return (
    <div className={s.topRight}>
      <ScenarioChip />
      <Surface className={s.cluster}>
        <SegmentedControl<Lang>
          size="sm"
          label={t('shell.language')}
          value={lang}
          onChange={(l) => set({ lang: l })}
          options={LANGS.map((l) => ({ value: l, label: LANG_LABEL[l], ariaLabel: LANG_NAME[l] }))}
        />
        <span className={s.clusterDivider} />
        <SegmentedControl<ThemePref>
          size="sm"
          label={t('shell.theme')}
          value={themePref}
          onChange={(p) => set({ themePref: p })}
          options={[
            {
              value: 'light',
              label: <Sun strokeWidth={1.75} />,
              ariaLabel: t('theme.light'),
              tooltip: t('theme.light'),
            },
            {
              value: 'dark',
              label: <Moon strokeWidth={1.75} />,
              ariaLabel: t('theme.dark'),
              tooltip: t('theme.dark'),
            },
            {
              value: 'system',
              label: <Monitor strokeWidth={1.75} />,
              ariaLabel: t('theme.system'),
              tooltip: t('theme.system'),
            },
          ]}
        />
        <span className={s.clusterDivider} />
        <IconButton
          size="sm"
          label={t('shell.copyLink')}
          onClick={() => {
            void navigator.clipboard?.writeText(window.location.href).then(
              () => toast(t('shell.linkCopied')),
              () => undefined,
            );
          }}
        >
          <Link2 strokeWidth={1.5} />
        </IconButton>
        <AboutPopover
          trigger={
            <IconButton size="sm" label={t('shell.about')} data-testid="open-about">
              <Info strokeWidth={1.5} />
            </IconButton>
          }
        />
      </Surface>
    </div>
  );
}
