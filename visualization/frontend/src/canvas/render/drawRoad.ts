// ─────────────────────────────────────────────────────────────────────────────
// drawRoad.ts — Background grid and road rendering.
//
// Road points are built incrementally into roadBuffer[runName][robotId] from
// the backend-supplied display.road_center field.  The same update path works
// for both replay and live-streaming.
//
// All robots share one world coordinate frame — coordinates from the backend
// are used directly without any local-to-global transform.
//
// Progressive reveal: each robot's road is only shown up to that robot's
// current position plus a small lookahead (~3.6 m), so the road unfolds
// as playback advances.
//
// Local view (focusRobotId set):
//   - Road centreline coloured by curvature heatmap (same as global view).
//   - Lookahead extended vs global (~15 m vs ~3.6 m) but bounded — streaming safe.
//   - Road fill and lane edges are slightly more prominent.
// ─────────────────────────────────────────────────────────────────────────────

import { state } from '../state';
import { w2c } from '../camera';
import { robotFrame, hexA, PALETTE, LANE_HALF, MIN_ROAD_DIST, CURV_MIN, TRIM_BATCH_RATIO } from '../constants';

// ── Curvature cache ───────────────────────────────────────────────────────────
// curvature[i] = |Δyaw / ds| between buf[i] and buf[i+1].  Once a segment
// is in the buffer it never changes, so we compute each entry exactly once
// and extend the array lazily as new road points arrive.
// Key: "<runName>:<robotId>"
const _curvCache = new Map<string, number[]>();

function _getCurvCache(runName: string, robotId: string, buf: any[]): number[] {
  const key = runName + ':' + robotId;
  let cache = _curvCache.get(key);
  if (!cache) { cache = []; _curvCache.set(key, cache); }
  const needed = buf.length - 1;
  for (let i = cache.length; i < needed; i++) {
    const ds = Math.hypot(buf[i + 1].x - buf[i].x, buf[i + 1].y - buf[i].y);
    if (ds <= 0.001) { cache.push(0); continue; }
    let dYaw = buf[i + 1].yaw - buf[i].yaw;
    dYaw = ((dYaw + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
    cache.push(Math.abs(dYaw) / ds);
  }
  return cache;
}

export function clearCurvCache(runName?: string): void {
  if (runName === undefined) {
    _curvCache.clear();
    return;
  }
  const prefix = runName + ':';
  for (const key of _curvCache.keys()) {
    if (key.startsWith(prefix)) _curvCache.delete(key);
  }
}

/**
 * Recompute the 95th-percentile curvature scale for a live run from the
 * current (post-trim) curvature cache.  Called after any road-buffer trim so
 * the heatmap normalisation tracks the retained window rather than history
 * that has already been evicted.
 */
function _recomputeLiveCurvatureScale(runName: string): void {
  const prefix = runName + ':';
  const allCurvs: number[] = [];
  for (const [key, cache] of _curvCache) {
    if (!key.startsWith(prefix)) continue;
    for (const v of cache) allCurvs.push(v);
  }
  if (allCurvs.length > 0) {
    allCurvs.sort((a, b) => a - b);
    const p95 = allCurvs[Math.floor(allCurvs.length * 0.95)];
    state.curvatureScale[runName] = Math.max(CURV_MIN, p95);
  } else {
    state.curvatureScale[runName] = CURV_MIN;
  }
}


/**
 * Append backend-derived road-centre points for all robots in one frame to
 * roadBuffer. No-ops if the new point is within MIN_ROAD_DIST of the last
 * buffered point.
 */
// Maximum road buffer length per robot in live mode.
// ~450 m of road at 0.3 m spacing — enough context for any live session.
// Replay runs are never capped (they are static after initRoadBuffers).
const ROAD_BUFFER_MAX = 1500;

export function updateRoadBuffer(runName: string, frame: any): void {
  if (!state.roadBuffer[runName]) state.roadBuffer[runName] = {};
  const roadCenter = frame.display?.road_center ?? {};
  const isLiveRun = runName === state.LIVE_RUN;
  let didTrim = false;
  state.RUNS[runName].meta.robots.forEach((id: string) => {
    const rc = roadCenter[id];
    if (!rc) return;
    if (!state.roadBuffer[runName][id]) state.roadBuffer[runName][id] = [];
    const buf = state.roadBuffer[runName][id];
    const last = buf.length > 0 ? buf[buf.length - 1] : null;
    if (!last || Math.hypot(rc.x - last.x, rc.y - last.y) >= MIN_ROAD_DIST) {
      buf.push({ x: rc.x, y: rc.y, yaw: rc.yaw });
    }
    // In live mode: cap buffer to avoid unbounded memory growth.
    // Trim a batch of 10 % when limit is hit — amortises the O(n) splice cost.
    if (isLiveRun && buf.length > ROAD_BUFFER_MAX) {
      const trimCount = Math.max(1, Math.floor(ROAD_BUFFER_MAX * TRIM_BATCH_RATIO));
      buf.splice(0, trimCount);
      // Keep curvature cache aligned after trim.
      const key = runName + ':' + id;
      const curvEntry = _curvCache.get(key);
      if (curvEntry) curvEntry.splice(0, trimCount);
      // Rebase the global-map progress index so addToGlobalMap() still sees
      // the surviving buffer entries.  Without this adjustment the stored index
      // is larger than the trimmed buffer length and the forward-extension loop
      // skips all new road points until the buffer grows past the stale value.
      const idxMap = state._globalMapIdx[runName];
      if (idxMap && idxMap[id] !== undefined) {
        idxMap[id] = Math.max(0, idxMap[id] - trimCount);
      }
      didTrim = true;
    }
  });
  // Recompute the heatmap normalisation scale from the surviving cache entries
  // so it tracks the retained window rather than evicted history.
  if (isLiveRun && didTrim) {
    _recomputeLiveCurvatureScale(runName);
  }
}


/**
 * Build the full road buffer for a run from all its frames, then compute
 * the curvature scale (95th percentile) used by the heatmap.
 * Called once on run load.
 */
export function initRoadBuffers(runName: string): void {
  state.roadBuffer[runName] = {};
  clearCurvCache(runName);
  state.RUNS[runName].frames.forEach((frame: any) => updateRoadBuffer(runName, frame));

  const allCurvs: number[] = [];
  Object.values(state.roadBuffer[runName]).forEach((buf: any) => {
    for (let i = 0; i < buf.length - 1; i++) {
      const ds = Math.hypot(buf[i + 1].x - buf[i].x, buf[i + 1].y - buf[i].y);
      if (ds > 0.001) allCurvs.push(Math.abs(buf[i + 1].yaw - buf[i].yaw) / ds);
    }
  });

  if (allCurvs.length > 0) {
    allCurvs.sort((a, b) => a - b);
    const p95 = allCurvs[Math.floor(allCurvs.length * 0.95)];
    state.curvatureScale[runName] = Math.max(CURV_MIN, p95);
  } else {
    state.curvatureScale[runName] = CURV_MIN;
  }
}


/** Draw a 1-metre metric grid across the visible viewport. */
export function drawGrid(): void {
  state.cx.strokeStyle = 'rgba(18,32,52,0.9)';
  state.cx.lineWidth   = 0.5;

  const pad = 3;
  const x0  = Math.floor(state.vx - state.W / state.scale / 2 - pad);
  const x1  = Math.ceil (state.vx + state.W / state.scale / 2 + pad);
  const y0  = Math.floor(state.vy - state.H / state.scale / 2 - pad);
  const y1  = Math.ceil (state.vy + state.H / state.scale / 2 + pad);

  state.cx.beginPath();
  for (let gx = x0; gx <= x1; gx++) {
    const [px] = w2c(gx, 0);
    state.cx.moveTo(px, 0); state.cx.lineTo(px, state.H);
  }
  for (let gy = y0; gy <= y1; gy++) {
    const [, py] = w2c(0, gy);
    state.cx.moveTo(0, py); state.cx.lineTo(state.W, py);
  }
  state.cx.stroke();

  state.cx.fillStyle  = 'rgba(40,60,90,0.8)';
  state.cx.font       = '12px JetBrains Mono,monospace';
  state.cx.textAlign  = 'center';
  const s5 = Math.floor(x0 / 5) * 5;
  for (let gx = s5; gx <= x1; gx += 5) {
    const [px] = w2c(gx, 0);
    state.cx.fillText(gx + 'm', px, state.H - 7);
  }
}


/**
 * Draw the road for one robot using its road buffer.
 *
 * In ALL view (focusRobotId === null):
 *   - Progressive reveal: road shown only up to the robot's current position
 *     plus a ~3.6 m lookahead (12 pts × 0.3 m).
 *   - Centreline coloured by curvature heatmap.
 *
 * In LOCAL view (focusRobotId === robotId):
 *   - Lookahead extended to ~15 m (50 pts).
 *   - Road fill and lane edges are slightly more opaque.
 */
export function drawRobotRoad(buf: any[], r: any, col: string, robotId: string): void {
  const isLocal = state.focusRobotId === robotId;

  let nearIdx = 0, nearDist = Infinity;
  buf.forEach((pt, i) => {
    const d = Math.hypot(pt.x - r.x, pt.y - r.y);
    if (d < nearDist) { nearDist = d; nearIdx = i; }
  });

  const lookahead = isLocal ? 50 : 12;
  const cutIdx    = Math.min(nearIdx + lookahead, buf.length - 1);
  const visible   = buf.slice(0, cutIdx + 1);
  if (visible.length < 2) return;

  const left: [number, number][] = [], right: [number, number][] = [], center: [number, number][] = [];
  visible.forEach((pt: any) => {
    const s = Math.sin(pt.yaw), c = Math.cos(pt.yaw);
    left  .push([pt.x - LANE_HALF * s, pt.y + LANE_HALF * c]);
    right .push([pt.x + LANE_HALF * s, pt.y - LANE_HALF * c]);
    center.push([pt.x, pt.y]);
  });

  const lpts = left  .map(([wx, wy]) => w2c(wx, wy));
  const rpts = right .map(([wx, wy]) => w2c(wx, wy));
  const cc   = center.map(([wx, wy]) => w2c(wx, wy));

  // Road fill
  state.cx.beginPath();
  lpts.forEach(([px, py], i) => i === 0 ? state.cx.moveTo(px, py) : state.cx.lineTo(px, py));
  rpts.slice().reverse().forEach(([px, py]) => state.cx.lineTo(px, py));
  state.cx.closePath();
  state.cx.fillStyle = hexA(col, isLocal ? 0.07 : 0.04);
  state.cx.fill();

  // Lane boundary lines
  state.cx.strokeStyle = hexA(col, isLocal ? 0.30 : 0.18);
  state.cx.lineWidth   = isLocal ? 2.0 : 1.5;
  state.cx.setLineDash([]);
  [lpts, rpts].forEach(pts => {
    state.cx.beginPath();
    pts.forEach(([px, py], i) => i === 0 ? state.cx.moveTo(px, py) : state.cx.lineTo(px, py));
    state.cx.stroke();
  });

  // Centreline — curvature heatmap.
  // Use cached per-segment curvature values (computed once, extended lazily).
  const curvCache = _getCurvCache(state.SIM.meta.sheet, robotId, buf);

  state.cx.lineWidth = isLocal ? 3 : 2;
  state.cx.setLineDash([]);
  const alphaBase  = isLocal ? 0.30 : 0.15;
  const alphaRange = isLocal ? 0.55 : 0.45;
  const kScale = state.curvatureScale[state.SIM.meta.sheet] || CURV_MIN;
  for (let i = 0; i < cc.length - 1; i++) {
    const t = Math.min((curvCache[i] ?? 0) / kScale, 1);
    const rv = Math.round(t * 255);
    const g  = Math.round((1 - t) * 200);
    const b  = Math.round((1 - t) * 60);
    state.cx.strokeStyle = `rgba(${rv},${g},${b},${alphaBase + t * alphaRange})`;
    state.cx.beginPath();
    state.cx.moveTo(cc[i][0], cc[i][1]);
    state.cx.lineTo(cc[i + 1][0], cc[i + 1][1]);
    state.cx.stroke();
  }

  // Direction chevrons every ~5 m
  const chevStep = Math.max(10, Math.round(5 / MIN_ROAD_DIST));
  for (let i = chevStep; i < cc.length; i += chevStep) {
    const [x1, y1] = cc[i - 1];
    const [x2, y2] = cc[i];
    const ang = Math.atan2(y2 - y1, x2 - x1);
    const [cpx, cpy] = cc[i];
    const sz = 5;
    state.cx.save();
    state.cx.translate(cpx, cpy);
    state.cx.rotate(ang);
    state.cx.strokeStyle = hexA(col, isLocal ? 0.38 : 0.22);
    state.cx.lineWidth   = isLocal ? 1.5 : 1.2;
    state.cx.beginPath();
    state.cx.moveTo(-sz, -sz * 0.5);
    state.cx.lineTo(0, 0);
    state.cx.lineTo(-sz,  sz * 0.5);
    state.cx.stroke();
    state.cx.restore();
  }
}
