/**
 * Basemap: OpenFreeMap "positron" vector style, re-themed at load time so the data stays in
 * front — quiet labels, subtle roads, barely tinted water and parks. Both themes are derived
 * from the same source style so they read as one product. `VITE_BASEMAP=none` gives a blank
 * style (tests, CI, offline).
 */
import type { LayerSpecification, StyleSpecification } from 'maplibre-gl';
import type { Theme } from '@/app/store';

const POSITRON = 'https://tiles.openfreemap.org/styles/positron';

export const BASEMAP_MODE: 'openfreemap' | 'none' =
  import.meta.env.VITE_BASEMAP === 'none' ? 'none' : 'openfreemap';

interface BasemapPalette {
  background: string;
  water: string;
  waterLine: string;
  park: string;
  wood: string;
  residential: string;
  building: string;
  buildingOutline: string;
  roadMinor: string;
  roadMajor: string;
  roadCasing: string;
  motorway: string;
  motorwayCasing: string;
  path: string;
  rail: string;
  aeroway: string;
  boundary: string;
  label: string;
  labelStrong: string;
  roadLabel: string;
  waterLabel: string;
  halo: string;
}

export const BASEMAP_PALETTES: Record<Theme, BasemapPalette> = {
  light: {
    background: '#f3f4f5',
    water: '#dde3e8',
    waterLine: '#d3dbe2',
    park: '#e8ede9',
    wood: '#e6ebe7',
    residential: '#eff0f1',
    building: '#e7e8ea',
    buildingOutline: '#dfe0e3',
    roadMinor: '#ffffff',
    roadMajor: '#ffffff',
    roadCasing: '#e1e3e6',
    motorway: '#ffffff',
    motorwayCasing: '#d6d9dd',
    path: '#e9eaec',
    rail: '#dadce0',
    aeroway: '#eceef0',
    boundary: '#c6cad0',
    label: '#7b818a',
    labelStrong: '#5a6069',
    roadLabel: '#9da3ab',
    waterLabel: '#8b9aa8',
    halo: '#f3f4f5',
  },
  dark: {
    background: '#0e0f11',
    water: '#141a20',
    waterLine: '#18202a',
    park: '#111513',
    wood: '#111513',
    residential: '#111214',
    building: '#16171a',
    buildingOutline: '#1b1c20',
    roadMinor: '#1d1f23',
    roadMajor: '#25282d',
    roadCasing: '#16181b',
    motorway: '#2b2e34',
    motorwayCasing: '#1a1c20',
    path: '#18191c',
    rail: '#23262b',
    aeroway: '#18191c',
    boundary: '#33373e',
    label: '#7c828b',
    labelStrong: '#979da6',
    roadLabel: '#5c626a',
    waterLabel: '#526170',
    halo: '#0e0f11',
  },
};

type Role = keyof BasemapPalette | 'hide' | 'keep';

/** Map a positron layer id to a palette role. Order matters (first match wins). */
const RULES: [RegExp, Role][] = [
  [/shield|^road_shield/, 'hide'],
  [/^background$/, 'background'],
  [/^water$/, 'water'],
  [/^waterway$/, 'waterLine'],
  [/^park$/, 'park'],
  [/landcover_wood/, 'wood'],
  [/landcover_(ice|glacier)/, 'park'],
  [/landuse_residential/, 'residential'],
  [/^building$/, 'building'],
  [/motorway.*casing/, 'motorwayCasing'],
  [/motorway/, 'motorway'],
  [/major_casing/, 'roadCasing'],
  [/major_inner|major_subtle/, 'roadMajor'],
  [/highway_minor/, 'roadMinor'],
  [/highway_path/, 'path'],
  [/road_area_pier|road_pier/, 'background'],
  [/railway.*dashline/, 'background'],
  [/railway/, 'rail'],
  [/aeroway/, 'aeroway'],
  [/^boundary/, 'boundary'],
  [/^highway-name|waterway_line_label/, 'roadLabel'],
  [/^water_name/, 'waterLabel'],
  [/label_(city|town|state|country)/, 'labelStrong'],
  [/^label_|^airport/, 'label'],
];

const roleOf = (id: string): Role => RULES.find(([re]) => re.test(id))?.[1] ?? 'keep';

function themeLayer(layer: LayerSpecification, p: BasemapPalette): LayerSpecification | null {
  const role = roleOf(layer.id);
  if (role === 'hide') return null;
  if (role === 'keep') return layer;
  const c = p[role];
  const paint = { ...(layer as { paint?: Record<string, unknown> }).paint } as Record<
    string,
    unknown
  >;
  switch (layer.type) {
    case 'background':
      paint['background-color'] = c;
      break;
    case 'fill':
      paint['fill-color'] = c;
      if (role === 'building') paint['fill-outline-color'] = p.buildingOutline;
      break;
    case 'line':
      paint['line-color'] = c;
      if (role === 'boundary') paint['line-opacity'] = 0.7;
      break;
    case 'symbol':
      paint['text-color'] = c;
      paint['text-halo-color'] = p.halo;
      paint['text-halo-width'] = 1.2;
      paint['text-halo-blur'] = 0.4;
      break;
    default:
      break;
  }
  return { ...layer, paint } as LayerSpecification;
}

let sourceStyle: Promise<StyleSpecification> | null = null;
function fetchSource(): Promise<StyleSpecification> {
  sourceStyle ??= fetch(POSITRON).then((r) => {
    if (!r.ok) throw new Error(`basemap style ${r.status}`);
    return r.json() as Promise<StyleSpecification>;
  });
  sourceStyle.catch(() => {
    sourceStyle = null;
  });
  return sourceStyle;
}

export function blankStyle(theme: Theme): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: 'background',
        type: 'background',
        paint: { 'background-color': BASEMAP_PALETTES[theme].background },
      },
    ],
  };
}

/** Themed basemap style; falls back to the blank style if the tiles host is unreachable. */
export async function loadBasemapStyle(theme: Theme): Promise<StyleSpecification> {
  if (BASEMAP_MODE === 'none') return blankStyle(theme);
  try {
    const src = await fetchSource();
    const p = BASEMAP_PALETTES[theme];
    const layers = src.layers
      .map((l) => themeLayer(l, p))
      .filter((l): l is LayerSpecification => l !== null);
    return { ...src, layers };
  } catch {
    return blankStyle(theme);
  }
}

/**
 * Id of the first basemap layer our data layers are inserted below: place labels stay on top
 * of the network; street names go underneath lines.
 */
export function dataLayerAnchor(style: StyleSpecification | undefined): string | undefined {
  // neighbourhood labels (label_other) sit under the network; settlements stay on top
  return style?.layers.find((l) => /^label_(village|town|state|city|country)|^airport/.test(l.id))
    ?.id;
}
