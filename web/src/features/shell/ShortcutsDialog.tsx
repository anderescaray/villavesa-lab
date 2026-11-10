import { useApp } from '@/app/store';
import { Dialog, Kbd } from '@/components/ui';
import { useT, type MessageKey } from '@/i18n';

const GROUPS: { title: MessageKey; items: { keys: string[]; label: MessageKey }[] }[] = [
  {
    title: 'shortcuts.playback',
    items: [
      { keys: ['Space'], label: 'shortcuts.playPause' },
      { keys: ['←', '→'], label: 'shortcuts.step' },
      { keys: ['Shift', '←', '→'], label: 'shortcuts.stepFine' },
      { keys: ['S'], label: 'shortcuts.speed' },
    ],
  },
  {
    title: 'shortcuts.navigation',
    items: [
      { keys: ['1', '–', '5'], label: 'shortcuts.views' },
      { keys: ['/'], label: 'shortcuts.search' },
      { keys: ['Esc'], label: 'shortcuts.clear' },
      { keys: ['['], label: 'shortcuts.panel' },
      { keys: ['T'], label: 'shortcuts.theme' },
      { keys: ['?'], label: 'shortcuts.help' },
    ],
  },
];

export function ShortcutsDialog() {
  const t = useT();
  const open = useApp((s) => s.shortcutsOpen);
  const set = useApp((s) => s.set);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => set({ shortcutsOpen: o })}
      title={t('shortcuts.title')}
      closeLabel={t('common.close')}
    >
      <div
        data-testid="shortcuts-dialog"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: 'var(--space-6)',
        }}
      >
        {GROUPS.map((g) => (
          <section key={g.title}>
            <h3
              style={{
                marginBottom: 'var(--space-2)',
                color: 'var(--text-tertiary)',
                fontSize: 'var(--text-11)',
                fontWeight: 520,
                letterSpacing: 'var(--tracking-caps)',
                textTransform: 'uppercase',
              }}
            >
              {t(g.title)}
            </h3>
            <dl style={{ margin: 0, display: 'grid', gap: 2 }}>
              {g.items.map((it) => (
                <div
                  key={it.label}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 12,
                    minHeight: 32,
                    borderBottom: '1px solid var(--divider)',
                  }}
                >
                  <dt style={{ fontSize: 'var(--text-13)' }}>{t(it.label)}</dt>
                  <dd style={{ margin: 0, display: 'flex', gap: 4, alignItems: 'center' }}>
                    {it.keys.map((k) =>
                      k === '–' ? (
                        <span key={k} style={{ color: 'var(--text-tertiary)' }}>
                          –
                        </span>
                      ) : (
                        <Kbd key={k}>{k}</Kbd>
                      ),
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </Dialog>
  );
}
