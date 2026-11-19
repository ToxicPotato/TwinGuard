const SPOOF_KIND_LABELS: Record<string, string> = {
  zeroed: 'ZERO',
  underreported: 'LOW',
  overreported: 'HIGH',
  fixed: 'FIXED',
  ramped: 'RAMP',
};

/** Return a short badge tag for a velocity_spoof_kind string. */
export function spoofKindLabel(kind: string): string {
  return SPOOF_KIND_LABELS[kind] ?? kind.toUpperCase();
}
