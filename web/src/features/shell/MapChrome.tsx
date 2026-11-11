import { Maximize, Minus, MousePointerClick, PanelLeftOpen, Plus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useMeta } from '@/api/queries';
import { useApp } from '@/app/store';
import { IconButton, Surface } from '@/components/ui';
import { useT } from '@/i18n';
import { fitBounds } from '@/map/camera';
import { useMapContext } from '@/map/MapContext';
import s from './Shell.module.css';

export function PanelToggle() {
  const t = useT();
  const open = useApp((st) => st.panelOpen);
  const set = useApp((st) => st.set);
  if (open) return null;
  return (
    <Surface className={s.panelToggle} style={{ padding: 4 }}>
      <IconButton
        label={t('shell.expandPanel')}
        shortcut="["
        tooltipSide="right"
        onClick={() => set({ panelOpen: true })}
      >
        <PanelLeftOpen strokeWidth={1.5} />
      </IconButton>
    </Surface>
  );
}

export function MapControls() {
  const t = useT();
  const { map } = useMapContext();
  const { data: meta } = useMeta();
  const iso = useApp((st) => st.isoOrigin);
  return (
    <Surface className={s.mapControls} style={iso ? undefined : undefined}>
      <IconButton
        size="sm"
        tooltipSide="left"
        label={t('map.zoomIn')}
        onClick={() => map?.zoomIn({ duration: 200 })}
      >
        <Plus strokeWidth={1.5} />
      </IconButton>
      <IconButton
        size="sm"
        tooltipSide="left"
        label={t('map.zoomOut')}
        onClick={() => map?.zoomOut({ duration: 200 })}
      >
        <Minus strokeWidth={1.5} />
      </IconButton>
      <IconButton
        size="sm"
        tooltipSide="left"
        label={t('map.resetView')}
        onClick={() => {
          if (map && meta)
            fitBounds(map, [
              [meta.bbox[0], meta.bbox[1]],
              [meta.bbox[2], meta.bbox[3]],
            ]);
        }}
      >
        <Maximize strokeWidth={1.5} />
      </IconButton>
    </Surface>
  );
}

const HINT_KEY = 'vlab.isoHintSeen';

/** One-time, quiet hint that the map is clickable; disappears after the first isochrone. */
export function IsochroneHint() {
  const t = useT();
  const view = useApp((st) => st.view);
  const iso = useApp((st) => st.isoOrigin);
  const selected = useApp((st) => st.selectedRouteId);
  const [seen, setSeen] = useState(() => {
    try {
      return localStorage.getItem(HINT_KEY) === '1';
    } catch {
      return false;
    }
  });
  useEffect(() => {
    if (iso && !seen) {
      setSeen(true);
      try {
        localStorage.setItem(HINT_KEY, '1');
      } catch {
        /* storage unavailable */
      }
    }
  }, [iso, seen]);
  if (seen || iso || selected || view !== 'network') return null;
  return (
    <Surface className={s.hint} role="note">
      <MousePointerClick strokeWidth={1.5} />
      {t('iso.hint')}
    </Surface>
  );
}
