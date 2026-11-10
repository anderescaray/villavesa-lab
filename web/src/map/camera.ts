import type { LngLatBoundsLike, Map as MlMap, PaddingOptions } from 'maplibre-gl';
import { useApp } from '@/app/store';
import { prefersReducedMotion } from '@/lib/motion';

export const DEFAULT_CENTER: [number, number] = [-1.644, 42.8125];
export const DEFAULT_ZOOM = 12.4;

/** Camera padding that keeps content clear of the side panel and floating surfaces. */
export function contentPadding(extra: Partial<PaddingOptions> = {}): PaddingOptions {
  const { panelOpen } = useApp.getState();
  const w = window.innerWidth;
  const overlayPanel = w < 1024;
  const left = 56 + (panelOpen && !overlayPanel ? 360 : 0) + 32;
  return {
    top: 72 + (extra.top ?? 0),
    bottom: 120 + (extra.bottom ?? 0),
    left: left + (extra.left ?? 0),
    right: 48 + (extra.right ?? 0),
  };
}

export function fitBounds(map: MlMap, bounds: LngLatBoundsLike, extra?: Partial<PaddingOptions>) {
  map.fitBounds(bounds, {
    padding: contentPadding(extra),
    duration: prefersReducedMotion() ? 0 : 700,
    maxZoom: 15.5,
    essential: false,
  });
}

export function boundsOf(
  coords: Iterable<[number, number]>,
): [[number, number], [number, number]] | null {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of coords) {
    if (x < minX) minX = x;
    if (y < minY) minY = y;
    if (x > maxX) maxX = x;
    if (y > maxY) maxY = y;
  }
  return Number.isFinite(minX)
    ? [
        [minX, minY],
        [maxX, maxY],
      ]
    : null;
}
