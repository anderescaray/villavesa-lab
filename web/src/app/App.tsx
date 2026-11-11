import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { useApp } from '@/app/store';
import { ToastRegion, TooltipProvider } from '@/components/ui';
import { AccessibilityLayers } from '@/features/accessibility/AccessibilityLayers';
import { AccessibilityLegend } from '@/features/accessibility/AccessibilityLegend';
import { EditorInteractions } from '@/features/editor/EditorInteractions';
import { EditorLayers } from '@/features/editor/EditorLayers';
import { ImpactCard } from '@/features/editor/ImpactCard';
import { ToolPalette } from '@/features/editor/ToolPalette';
import { IsochroneCard } from '@/features/isochrone/IsochroneCard';
import { IsochroneLayers } from '@/features/isochrone/IsochroneLayers';
import { BusesLayer } from '@/features/network/BusesLayer';
import { MapInteractions } from '@/features/network/MapInteractions';
import { BusTooltip, StopPopover } from '@/features/network/MapPopovers';
import { NetworkLayers } from '@/features/network/NetworkLayers';
import { useVehicleModel } from '@/features/network/model';
import { IsochroneHint, MapControls, PanelToggle } from '@/features/shell/MapChrome';
import { Rail } from '@/features/shell/Rail';
import { ShortcutsDialog } from '@/features/shell/ShortcutsDialog';
import { SidePanel } from '@/features/shell/SidePanel';
import { TopControls } from '@/features/shell/TopControls';
import s from '@/features/shell/Shell.module.css';
import { clock, startClock } from '@/features/time/clock';
import { TimeControl } from '@/features/time/TimeControl';
import { clampIntoService, madridSecondsNow } from '@/lib/format';
import { prefersReducedMotion } from '@/lib/motion';
import { MapCanvas } from '@/map/MapCanvas';
import { usePreferenceEffects } from './preferences';
import { useGlobalShortcuts } from './shortcuts';
import { startUrlSync, type UrlState } from './url';

const DevGallery = import.meta.env.DEV ? lazy(() => import('@/features/dev/DevGallery')) : null;

/**
 * Once the timetable is known: start at the URL time, or now (Europe/Madrid) clamped into the
 * service day, and play at a calm speed (unless the URL says play=0 or motion is reduced).
 */
function useInitialClock(initial: UrlState) {
  const { model } = useVehicleModel();
  const done = useRef(false);
  useEffect(() => {
    if (!model || done.current) return;
    done.current = true;
    const target = clampIntoService(initial.t ?? madridSecondsNow(), model.from, model.to - 60);
    clock.setState({
      domain: [model.from, model.to],
      time: target,
      // analysis views read the clock as a time-of-day setting: they start paused
      playing:
        useApp.getState().view !== 'accessibility' && (initial.play ?? !prefersReducedMotion()),
    });
  }, [model, initial]);
}

export function App({ initial }: { initial: UrlState }) {
  const panelOpen = useApp((st) => st.panelOpen);
  const [isDev, setIsDev] = useState(() => window.location.hash.startsWith('#/dev'));
  usePreferenceEffects();
  useGlobalShortcuts();
  useInitialClock(initial);
  useEffect(() => startClock(), []);
  useEffect(() => startUrlSync(), []);
  useEffect(() => {
    const onHash = () => setIsDev(window.location.hash.startsWith('#/dev'));
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  if (isDev && DevGallery) {
    return (
      <TooltipProvider>
        <Suspense fallback={null}>
          <DevGallery />
        </Suspense>
      </TooltipProvider>
    );
  }

  return (
    <TooltipProvider>
      <div className={s.app} data-panel={panelOpen ? 'open' : 'closed'}>
        <MapCanvas>
          <NetworkLayers />
          <AccessibilityLayers />
          <IsochroneLayers />
          <BusesLayer />
          <MapInteractions />
          <EditorLayers />
          <EditorInteractions />
          <ToolPalette />
          <ImpactCard />
          <StopPopover />
          <BusTooltip />
          <IsochroneHint />
          <PanelToggle />
          <TopControls />
          <IsochroneCard />
          <AccessibilityLegend />
          <MapControls />
          <TimeControl />
        </MapCanvas>
        <SidePanel />
        <Rail />
        <ShortcutsDialog />
        <ToastRegion />
      </div>
    </TooltipProvider>
  );
}
