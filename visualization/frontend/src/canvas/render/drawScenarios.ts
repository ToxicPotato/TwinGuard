// ─────────────────────────────────────────────────────────────────────────────
// drawScenarios.ts — Scenario twin overlay rendering.
//
// Draws a warning indicator over robots where a scenario flag is active.
// One function per entry point (local view / global view) so callers stay
// simple. Add new scenario visuals here without touching other draw modules.
// ─────────────────────────────────────────────────────────────────────────────

import { state } from '../state';
import { w2c } from '../camera';
import { RL, rrect } from '../constants';

const WARN_COLOR  = '#ff3b3b';
const WARN_BG     = 'rgba(255,40,40,0.15)';
const LABEL_FONT  = 'bold 11px monospace';

/** Draw warning indicator above one robot at world position (wx, wy). */
function drawWarning(wx: number, wy: number, label: string): void {
  const [px, py] = w2c(wx, wy);
  const bodyHalf = (RL * state.robotSizeM * state.scale) / 2;
  const cx = state.cx;

  // Offset so the badge sits above the robot body
  const bx = px;
  const by = py - bodyHalf - 18;

  // Measure text width for pill background
  cx.font = LABEL_FONT;
  const tw = cx.measureText(label).width;
  const ph = 14;
  const pw = tw + 10;

  // Pill background
  cx.save();
  cx.shadowColor = WARN_COLOR;
  cx.shadowBlur  = 8;
  cx.fillStyle   = WARN_BG;
  cx.strokeStyle = WARN_COLOR;
  cx.lineWidth   = 1.2;
  rrect(cx, bx - pw / 2, by - ph / 2, pw, ph, 3);
  cx.fill();
  cx.stroke();

  // Label text
  cx.shadowBlur  = 0;
  cx.fillStyle   = WARN_COLOR;
  cx.textAlign   = 'center';
  cx.textBaseline = 'middle';
  cx.fillText(label, bx, by);
  cx.restore();
}

/** Return the scenario labels for one robot, or null if absent. */
function scenarioLabels(fr: any, robotId: string): Record<string, unknown> | null {
  return fr?.scenario?.per_robot?.[robotId] ?? null;
}

/** Build a short badge label from the scenario payload. */
function scenarioBadge(labels: Record<string, unknown>): string | null {
  if (!labels.velocity_spoof) return null;

  const kind = typeof labels.velocity_spoof_kind === 'string' ? labels.velocity_spoof_kind : '';
  const tag = {
    zeroed: 'ZERO',
    underreported: 'LOW',
    overreported: 'HIGH',
    fixed: 'FIXED',
    ramped: 'RAMP',
  }[kind] ?? 'SPOOF';

  return `VEL ${tag}`;
}

/** Draw scenario overlays for one robot (local view). */
export function drawScenarioOverlayLocal(fr: any, robotId: string, r: any): void {
  const labels = scenarioLabels(fr, robotId);
  if (!labels) return;
  const badge = scenarioBadge(labels);
  if (badge) drawWarning(r.x, r.y, badge);
}

/** Draw scenario overlays for all visible robots (global view). */
export function drawScenarioOverlaysGlobal(
  fr: any,
  ids: string[],
  vis: (id: string) => boolean,
): void {
  const runAlign = (state.SIM?.meta?.sheet)
    ? (state.alignmentState[state.SIM.meta.sheet as string] || {})
    : {};

  ids.forEach(id => {
    if (!vis(id) || !runAlign[id]) return;
    const r = fr?.robots?.[id];
    if (!r) return;
    const labels = scenarioLabels(fr, id);
    if (!labels) return;
    const badge = scenarioBadge(labels);
    if (badge) drawWarning(r.x, r.y, badge);
  });
}
