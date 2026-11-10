/**
 * deck.gl layer registry. Feature modules own their layers and publish them here by id with an
 * explicit z-order; the registry pushes the ordered list into the single MapboxOverlay.
 * Per-frame layers (buses) call `set` from a clock subscription — no React involved.
 */
import type { Layer } from '@deck.gl/core';
import type { MapboxOverlay } from '@deck.gl/mapbox';

export const DECK_ORDER = {
  isochronePin: 10,
  busHalo: 50,
  bus: 51,
  editor: 80,
} as const;

export class DeckRegistry {
  private overlay: MapboxOverlay | null = null;
  private layers = new Map<string, { layer: Layer; order: number }>();
  private scheduled = 0;

  attach(overlay: MapboxOverlay | null) {
    this.overlay = overlay;
    this.flush();
  }

  set(id: string, layer: Layer | null, order: number, immediate = false) {
    if (layer) this.layers.set(id, { layer, order });
    else this.layers.delete(id);
    if (immediate) this.flush();
    else this.schedule();
  }

  remove(id: string) {
    this.set(id, null, 0);
  }

  private schedule() {
    if (this.scheduled) return;
    this.scheduled = requestAnimationFrame(() => {
      this.scheduled = 0;
      this.flush();
    });
  }

  flush() {
    if (!this.overlay) return;
    const layers = [...this.layers.values()].sort((a, b) => a.order - b.order).map((l) => l.layer);
    this.overlay.setProps({ layers });
  }

  pick(x: number, y: number, layerIds: string[], radius = 6) {
    if (!this.overlay) return null;
    try {
      return this.overlay.pickObject({ x, y, radius, layerIds });
    } catch {
      return null;
    }
  }
}

export const deckRegistry = new DeckRegistry();
