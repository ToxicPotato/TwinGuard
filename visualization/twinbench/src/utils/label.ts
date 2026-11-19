import type { LiveFrame } from '../types';

/** Formats a robot ID for display. 'rob1' → 'ROB 1', 'rob12' → 'ROB 12' */
export function robotLabel(id: string | number | null | undefined, compact = false): string {
  if (id == null || id === '') return compact ? 'R?' : 'ROBOT ?';
  const text = String(id);
  if (/^rob\d+$/i.test(text)) {
    const n = text.slice(3);
    return compact ? `R${n}` : `ROB ${n}`;
  }
  return compact ? text : text.toUpperCase();
}

/**
 * Returns each assessed platoon component as its own ordered robot-id array.
 * Falls back to a single group from fallbackIds when no assessment is present.
 */
export function assessedChainComponents(frame: LiveFrame | null): string[][] {
  const components = frame?.low_res?.platoon?.assessment?.components ?? null;
  if (!Array.isArray(components) || components.length === 0) {
    return [];
  }
  return components
    .map((c) => (Array.isArray(c.order) ? (c.order as string[]) : []))
    .filter((o) => o.length > 0);
}

export function chainComponents(
  frame: LiveFrame | null,
  fallbackIds: string[],
): string[][] {
  const components = assessedChainComponents(frame);
  if (components.length > 0) {
    return components;
  }
  return fallbackIds.length > 0 ? [fallbackIds] : [];
}

/**
 * Returns the robot directly ahead of `follower` in its component chain,
 * or null if the follower is a leader or not found.
 */
export function leaderOf(
  follower: string,
  frame: LiveFrame | null,
): string | null {
  const comps = assessedChainComponents(frame);
  for (const c of comps) {
    const idx = c.indexOf(follower);
    if (idx > 0) return c[idx - 1];
  }
  return null;
}

/** State labels matching the ST array in canvas/constants.ts */
export const STATE_LABELS = [
  'AUTONOMOUS',
  'CANDIDATE',
  'ALIGNING',
  'PLATOONING',
  'RECOVERY',
] as const;

/** State colors matching canvas.css --s0 through --s4 */
export const STATE_COLORS = [
  '#00e5ff', // AUTONOMOUS
  '#ffe040', // CANDIDATE
  '#ff9100', // ALIGNING
  '#00ff88', // PLATOONING
  '#ff3060', // RECOVERY
] as const;
