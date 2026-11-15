import { useCallback, useEffect, useMemo, useState } from 'react';
import type { EnvStatus, ShipState, ZoneId } from '../../api/types';
import { CREW_HEX, initials } from '../../lib/format';
import { hexToRgb } from '../../scene3d/engine';
import { loadShipAsset } from '../../scene3d/shipAsset';
import type { Part } from '../../scene3d/geometry';
import { SHIP_ZONES } from '../../scene3d/models';
import { Viewport, type Anchor } from '../../scene3d/Viewport';
import { useApp } from '../../state/AppState';
import { cx, Icon, type IconName } from '../../ui';

export const ENV_ICON: Record<EnvStatus, IconName> = { nominal: 'checkCircle', attention: 'info', high: 'alert' };
export const ENV_TEXT: Record<EnvStatus, string> = { nominal: 'text-good', attention: 'text-attention', high: 'text-high' };
const SELECT_RGB = hexToRgb('#4fd1e8');
const HOVER_RGB = hexToRgb('#cfe9eb');
const SHIP_CAMERA = { yaw: -0.42, pitch: 0.36, dist: 24, target: [0.3, 0, 0] as [number, number, number], fov: 0.72 };
const EMPTY_MODEL: Part[] = [];

/**
 * Spacecraft digital twin used by Mission Control and SYMBIOSIS.
 * The modeller's GLB is normalized into the shared viewport frame; triangle groups map approximately to zones.
 */
export function ShipTwin({ ship, zoneId, crewId, onZone, onCrew, showCrew = true, height = 460, colourByStatus = false, focusSelected = false, className }: {
  ship: ShipState; zoneId: ZoneId; crewId?: string | null; onZone: (z: ZoneId) => void; onCrew?: (id: string) => void;
  showCrew?: boolean; height?: number | string; colourByStatus?: boolean; focusSelected?: boolean; className?: string;
}) {
  const { reducedMotion } = useApp();
  const [model, setModel] = useState<Part[]>(EMPTY_MODEL);
  const [modelError, setModelError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    loadShipAsset().then(
      (parts) => { if (alive) setModel(parts); },
      (error: unknown) => { if (alive) setModelError(error instanceof Error ? error.message : String(error)); },
    );
    return () => { alive = false; };
  }, []);
  const dim = useCallback((id: string | null) => (id === null || id === zoneId || !focusSelected ? 1 : 0.62), [zoneId, focusSelected]);
  const [hover, setHover] = useState<string | null>(null);
  const highlight = useMemo(() => {
    const h: Record<string, { color: [number, number, number]; amount: number }> = {};
    if (colourByStatus) for (const z of ship.zones) if (z.environment.status !== 'nominal') h[z.id] = { color: hexToRgb(z.environment.status === 'high' ? '#e58c7a' : '#dda85e'), amount: 0.3 };
    if (hover && hover !== zoneId) h[hover] = { color: HOVER_RGB, amount: 0.22 };
    h[zoneId] = { color: SELECT_RGB, amount: 0.38 };
    return h;
  }, [ship, zoneId, hover, colourByStatus]);
  const anchors = useMemo(() => buildAnchors(ship, zoneId, crewId ?? null, onZone, showCrew ? onCrew : undefined), [ship, zoneId, crewId, onZone, onCrew, showCrew]);
  return (
    <div className={cx('always-dark stage relative overflow-hidden rounded-xl', className)}>
      <Viewport model={model} initialCamera={SHIP_CAMERA} highlight={highlight} anchors={anchors} height={height} reducedMotion={reducedMotion} dim={dim}
        focus={focusSelected ? SHIP_ZONES[zoneId].centre : null} pickThroughTransparent={false}
        onPick={(id) => { if (id) onZone(id as ZoneId); }} onHover={setHover}
        ariaLabel="Interactive spacecraft GLB. Drag or use arrow keys to rotate, scroll or plus/minus to zoom, 0 to reset. Click a zone to select it."
        instructions="Drag / arrow keys rotate · scroll / ± zoom · 0 reset · click a zone" />
      {model.length === 0 && (
        <div role={modelError ? 'alert' : 'status'} className="absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded-lg border border-line bg-[#0c1422]/90 px-3 py-1.5 text-xs text-ink-2">
          {modelError ? `Could not load carablik.glb: ${modelError}` : 'Loading spacecraft model…'}
        </div>
      )}
    </div>
  );
}

function buildAnchors(s: ShipState, zoneId: ZoneId, crewId: string | null, onZone: (z: ZoneId) => void, onCrew?: (id: string) => void): Anchor[] {
  const anchors: Anchor[] = s.zones.map((z) => ({
    id: 'label-' + z.id,
    pos: SHIP_ZONES[z.id].label,
    render: ({ front }) => (
      <button type="button" onClick={() => onZone(z.id)} aria-label={`${z.name}, ${z.environment.status}`}
        className={cx('flex min-h-7 items-center gap-1 whitespace-nowrap rounded-full border px-2.5 text-[11px] font-medium shadow',
          z.id === zoneId ? 'border-[#4fd1e8] bg-[#1d6f8a] text-white' : 'border-[#56708c] bg-[#0c1422]/90 text-[#a9b8ca]', !front && 'opacity-60')}>
        {z.environment.status !== 'nominal' && <Icon name={ENV_ICON[z.environment.status]} size={12} className={z.id === zoneId ? '' : z.environment.status === 'high' ? 'text-[#e58c7a]' : 'text-[#dda85e]'} />}
        {z.name}
      </button>
    ),
  }));
  if (!onCrew) return anchors;
  const used: Record<string, number> = {};
  for (const c of s.crew) {
    const i = used[c.zone] ?? 0;
    used[c.zone] = i + 1;
    const slots = SHIP_ZONES[c.zone].crewSlots;
    anchors.push({
      id: 'crew-' + c.id,
      pos: slots[i % slots.length],
      render: ({ front }) => (
        <button type="button" onClick={() => onCrew(c.id)} aria-label={`${c.name} – ${c.activity}`} title={`${c.name} · ${c.activity}`}
          className={cx('grid h-7 w-7 place-items-center rounded-full border-2 text-[10px] font-bold text-white shadow-lg', crewId === c.id && 'ring-2 ring-white', !front && 'opacity-60')}
          style={{ background: CREW_HEX[c.id], borderColor: '#101827' }}>
          {initials(c.name)}
        </button>
      ),
    });
  }
  return anchors;
}
