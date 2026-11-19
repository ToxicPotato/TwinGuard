import { state } from '../state';

export function formatStructureStatus(value: string | null | undefined): string {
  if (!value || value === 'empty') return 'empty';
  return value.replaceAll('_', ' ');
}

export function robotLabel(id: string | number | null | undefined, compact = false) {
  if (id == null || id === '') return compact ? 'R?' : 'ROBOT ?';
  const text = String(id);
  if (/^rob\d+$/i.test(text)) {
    const n = text.slice(3);
    return compact ? `R${n}` : `ROB ${n}`;
  }
  return compact ? text : text.toUpperCase();
}

export function trackingStatusLabel(value: string | null | undefined) {
  if (!value) return '-';
  if (value === 'observed') return 'observed';
  if (value === 'not_observed') return 'not observed';
  if (value === 'unknown') return 'unknown';
  return value.replace(/_/g, ' ');
}

export function chainTerminationLabel(value: string | null | undefined) {
  if (!value) return '-';
  if (value === 'visible_front_reached') return 'visible front reached';
  if (value === 'upstream_not_in_frame') return 'upstream not in frame';
  if (value === 'cycle_detected') return 'cycle detected';
  if (value === 'unresolved') return 'unresolved';
  return value.replace(/_/g, ' ');
}

/**
 * Returns each assessed platoon component as its own ordered robot-id array.
 * Falls back to all robots in a single group when no assessment is available.
 *
 * @param twinKey  Which twin assessment to read components from.
 *                 Defaults to 'low_res'. Pass 'high_res' when grouping the
 *                 high-res summary so each column uses its own partitioning.
 */
export function chainComponents(fr: any, twinKey: 'low_res' | 'high_res' = 'low_res'): string[][] {
  const components = fr[twinKey]?.platoon?.assessment?.components ?? null;
  if (Array.isArray(components) && components.length > 0) {
    return components
      .map((c: any) => (Array.isArray(c.order) ? c.order : []) as string[])
      .filter((o: string[]) => o.length > 0);
  }
  return state.SIM ? [state.SIM.meta.robots.slice()] : [];
}

/** Flat ordered list across all platoon components — used for draw ordering and chain-index lookups. */
export function chainOrder(fr: any): string[] {
  return chainComponents(fr, 'low_res').flat();
}
