/** Dev-only component gallery (`/#/dev/components`) used for design review screenshots. */
import { Bus, Map as MapIcon, Search } from 'lucide-react';
import { useState } from 'react';
import { useApp } from '@/app/store';
import {
  Badge,
  Button,
  EmptyState,
  IconButton,
  Kbd,
  Legend,
  LineBadge,
  MiniBarChart,
  Popover,
  SegmentedControl,
  Select,
  Skeleton,
  Slider,
  SparkBars,
  Stat,
  Surface,
  Switch,
  Tabs,
  toast,
  ToastRegion,
} from '@/components/ui';
import { ISO_COLORS, SEQUENTIAL_BLUE, DIVERGING } from '@/lib/palettes';
import { usePreferenceEffects } from '@/app/preferences';

const LINES = [
  ['L01', '#9C9100', '#FFFFFF'],
  ['L04', '#DC291E', '#FFFFFF'],
  ['L05', '#002596', '#FFFFFF'],
  ['L09', '#EF8200', '#000000'],
  ['L12', '#77B800', '#000000'],
  ['L24', '#FFD451', '#000000'],
  ['N05', '#DE7477', '#000000'],
  ['L6S', '#C97683', '#000000'],
] as const;

function Row({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ display: 'grid', gridTemplateColumns: '160px 1fr', gap: 24, padding: '20px 0', borderTop: '1px solid var(--divider)' }}>
      <h2 style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 520 }}>{title}</h2>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>{children}</div>
    </section>
  );
}

export default function DevGallery() {
  usePreferenceEffects();
  const set = useApp((s) => s.set);
  const theme = useApp((s) => s.theme);
  const [seg, setSeg] = useState<'a' | 'b' | 'c'>('a');
  const [sel, setSel] = useState<'weekday' | 'saturday'>('weekday');
  const [sw, setSw] = useState(true);
  const [sl, setSl] = useState(40);
  const [tab, setTab] = useState<'one' | 'two'>('one');
  const [value, setValue] = useState(12345);
  return (
    <div style={{ height: '100vh', overflow: 'auto', background: 'var(--bg)' }}>
      <div style={{ maxWidth: 980, margin: '0 auto', padding: '40px 24px 80px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <h1 style={{ fontSize: 28, fontWeight: 600, letterSpacing: '-0.022em' }}>Components</h1>
          <SegmentedControl
            label="Theme"
            value={theme}
            onChange={(v) => set({ themePref: v })}
            options={[
              { value: 'light', label: 'Light' },
              { value: 'dark', label: 'Dark' },
            ]}
          />
        </div>
        <Row title="Button">
          <Button variant="primary">Primary action</Button>
          <Button>Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button size="sm">
            <Search strokeWidth={1.75} /> Small
          </Button>
          <Button disabled>Disabled</Button>
        </Row>
        <Row title="IconButton">
          <IconButton label="Map" shortcut="1">
            <MapIcon strokeWidth={1.5} />
          </IconButton>
          <IconButton label="Bus" variant="secondary">
            <Bus strokeWidth={1.5} />
          </IconButton>
          <IconButton label="Pressed" pressed>
            <Bus strokeWidth={1.5} />
          </IconButton>
        </Row>
        <Row title="SegmentedControl">
          <SegmentedControl label="Demo" value={seg} onChange={setSeg} options={[{ value: 'a', label: '30×' }, { value: 'b', label: '60×' }, { value: 'c', label: '120×' }]} />
          <SegmentedControl size="sm" label="Demo sm" value={seg} onChange={setSeg} options={[{ value: 'a', label: 'ES' }, { value: 'b', label: 'EN' }, { value: 'c', label: 'EU' }]} />
        </Row>
        <Row title="Select / Switch / Slider">
          <Select label="Day" value={sel} onChange={setSel} options={[{ value: 'weekday', label: 'Weekday' }, { value: 'saturday', label: 'Saturday' }]} />
          <Switch checked={sw} onChange={setSw}>
            Night lines
          </Switch>
          <div style={{ width: 200 }}>
            <Slider label="Demo" value={sl} onChange={setSl} min={0} max={100} />
          </div>
        </Row>
        <Row title="Tabs">
          <div style={{ width: 320 }}>
            <Tabs label="Demo" value={tab} onChange={setTab} tabs={[{ value: 'one', label: 'Overview' }, { value: 'two', label: 'Stops' }]} />
          </div>
        </Row>
        <Row title="Badges">
          {LINES.map(([n, c, tc]) => (
            <LineBadge key={n} shortName={n} color={c} textColor={tc} />
          ))}
          <LineBadge size="lg" shortName="L04" color="#DC291E" textColor="#FFFFFF" />
          <Badge>Weekday</Badge>
          <Badge tone="accent">Modified</Badge>
          <Kbd>?</Kbd>
          <Kbd>Space</Kbd>
        </Row>
        <Row title="Stat">
          <Stat label="Population" value={value} format={(n) => Math.round(n).toLocaleString('es-ES')} delta={3200} higherIsBetter />
          <Stat label="Mean travel time" value={1620} format={(n) => `${Math.round(n / 60)} min`} delta={-42} formatDelta={(n) => `${Math.round(n)} s`} higherIsBetter={false} />
          <Stat size="lg" label="Fleet" value={140} format={(n) => String(Math.round(n))} />
          <Button size="sm" onClick={() => setValue((v) => v + 5000)}>
            Animate
          </Button>
        </Row>
        <Row title="Charts">
          <SparkBars values={[0, 2, 6, 8, 7, 6, 6, 6, 7, 8, 8, 6, 4, 2]} width={84} height={18} label="Demo" highlight={4} />
          <div style={{ width: 320 }}>
            <MiniBarChart values={[0, 2, 6, 8, 7, 6, 6, 6, 7, 8, 8, 6, 4, 2]} labels={Array.from({ length: 14 }, (_, i) => `${i + 6}:00`)} formatValue={String} label="Demo" tickEvery={4} />
          </div>
        </Row>
        <Row title="Legend">
          <Legend title="Travel time" items={ISO_COLORS[theme].map((c, i) => ({ color: c, label: `${(i + 1) * 15} min` }))} />
          <div style={{ width: 240 }}>
            <Legend variant="ramp" title="Sequential" items={SEQUENTIAL_BLUE.map((c, i) => ({ color: c, label: i % 3 === 0 ? `${i * 10}%` : '' }))} />
          </div>
          <div style={{ width: 240 }}>
            <Legend
              variant="ramp"
              title="Diverging"
              items={[...DIVERGING[theme].neg, DIVERGING[theme].mid, ...[...DIVERGING[theme].pos]].map((c, i) => ({
                color: c,
                label: i === 0 ? 'Loses' : i === 3 ? '0' : i === 6 ? 'Gains' : '\u2009'.repeat(i),
              }))}
            />
          </div>
        </Row>
        <Row title="Skeleton">
          <div style={{ width: 240, display: 'grid', gap: 8 }}>
            <Skeleton height={14} width="70%" />
            <Skeleton height={10} />
            <Skeleton height={10} width="40%" />
          </div>
        </Row>
        <Row title="Surface / Popover / Toast">
          <Surface style={{ padding: 16, width: 240 }}>Floating surface</Surface>
          <Popover trigger={<Button>Open popover</Button>}>
            <div style={{ padding: 16 }}>Popover content</div>
          </Popover>
          <Button onClick={() => toast('Link copied to clipboard')}>Toast</Button>
        </Row>
        <Row title="EmptyState">
          <div style={{ width: 320 }}>
            <EmptyState icon={<MapIcon strokeWidth={1.5} />} eyebrow="Upcoming view" title="Accessibility" body="What share of residents can reach key destinations within 30 minutes." points={['Share by destination', 'Under-served areas', 'Equity by income']} />
          </div>
        </Row>
      </div>
      <ToastRegion />
    </div>
  );
}
