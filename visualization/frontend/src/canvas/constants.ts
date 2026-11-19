// ─────────────────────────────────────────────────────────────────────────────
// constants.ts — State definitions, colour palette, visual/physics constants,
//               and low-level canvas utility functions (hexA, rrect).
//
// Nothing in this file has external dependencies — load it first.
// ─────────────────────────────────────────────────────────────────────────────

// ── State machine ─────────────────────────────────────────────────────────────
// Must match the active_state values in routed_signals.
export const ST = [
  { label: 'AUTONOMOUS', color: '#00e5ff' },  // 0 — lane keeping, no platoon
  { label: 'CANDIDATE',  color: '#ffe040' },  // 1 — wants to join a platoon
  { label: 'ALIGNING',   color: '#ff9100' },  // 2 — positioning before joining
  { label: 'PLATOONING', color: '#00ff88' },  // 3 — active platoon, V2V in use
  { label: 'RECOVERY',   color: '#ff3060' },  // 4 — lost sensor, waiting
];

// ── Robot colour palette (up to 8 robots) ────────────────────────────────────
export const PALETTE = [
  '#00e5ff', '#ff6b35', '#b44fff', '#39d353',
  '#ff6b9d', '#fbbf24', '#60a5fa', '#a3e635',
];

// ── Physical / visual constants ───────────────────────────────────────────────

// Robot VISUAL body size in world metres used only for rendering on the canvas.
// The real JetBot is ~0.1 m; we draw it larger so it is visible at typical zoom.
// For the physical body-length correction applied to the distance sensor (d),
// see CFG.robotLength below.
export const RL = 0.25;              // visual render length (m) — NOT the physical robot length
export const RW = 0.18;              // visual render width  (m)

export const LANE_HALF  = 2.25;      // half of the lane width (m) — total lane = 4.5 m
export const FOV_RANGE  = 4.0;       // lane camera range (m)
export const FOV_HALF   = Math.PI / 6; // half-angle of camera FOV cone (30° → 60° total)

// TARGET_GAP: ideal centre-to-centre gap in a platoon (m), used for gap-health
// colour coding on platoon links. Must match CFG.robotLength assumption:
// at TARGET_GAP the robots are at ideal spacing, not touching.
export const TARGET_GAP = 5.0;

export function robotFrame(fr: any, id: string): any | null {
  if (!fr) return null;
  if (fr.robots) return fr.robots[id] ?? null;
  return fr[id] ?? null;
}

export const VEL_SCALE  = 0.15;      // world-metres per m/s for the velocity arrow
                               // (0.15 → arrow = 0.75 m at 5 m/s)

export const MIN_ROAD_DIST = 0.3;    // minimum distance (m) between consecutive road buffer points
export const CURV_MIN      = 0.01;   // floor for curvature scale (rad/m) — avoids div-by-zero
                               // on perfectly straight test paths
export const TRIM_BATCH_RATIO = 0.1; // fraction of a buffer's max length to remove in one batch
                               // splice — shared by liveMode (frame buffer) and drawRoad
                               // (road buffer) so both use the same trim aggressiveness

// ── Tuning constants ──────────────────────────────────────────────────────────
// Single source of truth for all thresholds and magic numbers used across
// draw_trail, draw_sensors, draw_global, panel, main, and camera.
// Change here — takes effect everywhere.
export const TUNING = {
  // Panel / HUD warning thresholds
  WARN_LE:  0.3,    // m   — lateral error: yellow warning
  ALERT_LE: 0.6,    // m   — lateral error: red alert
  WARN_HE:  0.1,    // rad — heading error: yellow warning
  ALERT_HE: 0.3,    // rad — heading error: red alert

  // Gap health (fraction of TARGET_GAP) — used in draw_trail.js
  GAP_CLOSE:  0.70, // below → too close (red)
  GAP_OK_LOW: 0.85, // below → slightly close (orange)
  GAP_OK_HI:  1.25, // above → too far (yellow)

  // Camera zoom limits (px/m) — used in camera.ts
  SCALE_MIN: 8,
  SCALE_MAX: 400,

  // Drawing sizes (canvas pixels)
  BADGE_OFFSET_PX:    22,   // vertical offset above robot label for alignment badge
  RETICLE_RADIUS_PX:  14,   // radius of leader-tracking crosshair ring
  STATE_MARKER_PX:    5.5,  // radius of state-transition dot on trail
  TRAIL_SAMPLE_EVERY: 3,    // draw every Nth frame (at 60 Hz: 3 → ~50 ms, visually smooth)

  // Robot card gauge full-scale values — used in robotCard.ts setGaugeValue()
  GAUGE_MAX_WH:  12,    // rad/s — wheel speed gauge full scale
  GAUGE_MAX_LE:  0.30,  // m     — lateral error gauge full scale
  GAUGE_MAX_HE:  0.25,  // rad   — heading error gauge full scale
  GAUGE_MAX_RC:  0.50,  // rad/m — routed curvature gauge full scale
  GAUGE_MAX_VV:  1.50,  // m/s   — routed velocity gauge full scale
  GAUGE_MAX_LC:  0.50,  // rad/m — raw lane curvature gauge (sensor_bus.lane_state.curvature)
  GAUGE_MAX_RAW: 0.30,  // m/rad — raw camera le_raw / he_raw gauge (sensor_bus.leader_state)
};

// ── Short state labels ────────────────────────────────────────────────────────
// Used by drawStateTransitions() for transition markers on the trail.
// Must stay in sync with the ST array above (same order, same length).
export const SHORT = ['AUT', 'CND', 'ALN', 'PLT', 'RCV'];

// ── User-overridable physics config ──────────────────────────────────────────
// robotLength: physical robot body length in simulation coordinates.
// Derived from Run 6 Excel data: median(c2c − d) = 4.84 m across 16 000
// valid sensor frames (std = 0.022 m, highly consistent across both pairs).
// Formula: d_sensor = c2c − leaderLength/2 − followerLength/2
//          → correction = leaderLength/2 + followerLength/2 = robotLength
//            (when both robots are the same model)
// NOTE: RL = 0.25 above is the VISUAL render size only — unrelated to this.
export const CFG = {
  robotLength: 4.84,   // m — correction from front-to-back d → centre-to-centre gap
};

/** Centre-to-centre gap from a raw front-to-back sensor reading. */
export function correctedGap(d: number): number {
  return d + CFG.robotLength;
}

// ── Low-level canvas helpers ──────────────────────────────────────────────────

/**
 * Convert a CSS hex colour + alpha into an rgba() string.
 * @param h  Hex colour, e.g. '#00e5ff'
 * @param a  Alpha 0.0–1.0
 */
export function hexA(h: string, a: number): string {
  const r = parseInt(h.slice(1, 3), 16);
  const g = parseInt(h.slice(3, 5), 16);
  const b = parseInt(h.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${a})`;
}

/**
 * Draw a rounded rectangle path on a 2D canvas context.
 * Call cx.fill() / cx.stroke() after this to render it.
 */
export function rrect(c: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  c.beginPath();
  c.moveTo(x + r, y);
  c.lineTo(x + w - r, y);         c.arcTo(x + w, y,     x + w, y + r,     r);
  c.lineTo(x + w, y + h - r);     c.arcTo(x + w, y + h, x + w - r, y + h, r);
  c.lineTo(x + r, y + h);         c.arcTo(x,     y + h, x,     y + h - r, r);
  c.lineTo(x, y + r);             c.arcTo(x,     y,     x + r, y,         r);
  c.closePath();
}
