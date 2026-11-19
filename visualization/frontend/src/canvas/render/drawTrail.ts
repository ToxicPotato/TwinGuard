// ─────────────────────────────────────────────────────────────────────────────
// drawTrail.ts — State-coloured trail, state-transition markers,
//               twin-assessed platoon links, and the trail state legend.
// ─────────────────────────────────────────────────────────────────────────────

import { state } from '../state';
import { w2c } from '../camera';
import { robotFrame, hexA, ST, SHORT, TARGET_GAP, TUNING } from '../constants';


// ── Transition cache ──────────────────────────────────────────────────────────
// Replaces the O(n) frame scan in drawStateTransitions with O(k) where
// k = number of state transitions per robot (typically <20).
//
// Live mode: populated incrementally via recordStateTransition() as each frame
//            arrives in liveMode.ts.
// Replay:    populated once on run load via buildTransitionCacheFromFrames().

type Transition = { fi: number; x: number; y: number; st: number };
const _transitionCache = new Map<string, Transition[]>();

// ── Trail start cache ─────────────────────────────────────────────────────────
// First buffer index where each robot appears — avoids re-scanning from frame 0
// on every drawTrail() call for robots that join mid-session.
const _trailStartCache = new Map<string, number>();

// Monotonically increasing counter so panel.ts can detect when the cache has
// been invalidated (e.g. by live-mode reset) even if the SIM reference is the
// same object it was before entering live mode.
let _cacheGeneration = 0;
export function getTransitionCacheGeneration(): number { return _cacheGeneration; }

export function clearTransitionCache(): void {
  _cacheGeneration++;
  _transitionCache.clear();
  _trailStartCache.clear();
}

/**
 * Shift all cached fi values after a live buffer splice of `k` frames.
 * Entries that shift below 0 are discarded (they are no longer in the buffer).
 */
export function shiftTransitionCache(k: number): void {
  for (const [id, transitions] of _transitionCache) {
    const shifted = transitions
      .map(t => ({ ...t, fi: t.fi - k }))
      // Discard fi === 0: a transition shifted to the first retained frame
      // had its "before" state trimmed away and is no longer meaningful.
      .filter(t => t.fi > 0);
    if (shifted.length > 0) _transitionCache.set(id, shifted);
    else _transitionCache.delete(id);
  }
  for (const [id, start] of _trailStartCache) {
    _trailStartCache.set(id, Math.max(0, start - k));
  }
}

/** Record one state transition for a robot (called from liveMode per frame). */
export function recordStateTransition(
  id: string, fi: number, x: number, y: number, st: number,
): void {
  let arr = _transitionCache.get(id);
  if (!arr) { arr = []; _transitionCache.set(id, arr); }
  arr.push({ fi, x, y, st });
}

/**
 * Scan all replay frames once and build the complete transition + trail-start
 * cache.  Called on run load — O(n) one-time cost replaces O(n) per draw.
 */
export function buildTransitionCacheFromFrames(frames: any[], robots: string[]): void {
  clearTransitionCache();
  for (const id of robots) {
    let prevSt: number | undefined;
    for (let i = 0; i < frames.length; i++) {
      const f = robotFrame(frames[i], id);
      if (!f) continue;
      if (prevSt === undefined) {
        _trailStartCache.set(id, i);  // first frame this robot appears
      } else if (f.st !== prevSt) {
        recordStateTransition(id, i, f.x, f.y, f.st);
      }
      prevSt = f.st;
    }
  }
}


/**
 * Draw the driven-path trail for one robot from frame 0 to frame `end`.
 *
 * Each path segment is coloured by the robot's active state at that frame.
 * Consecutive frames in the same state are batched into a single polyline,
 * so draw calls scale with state transitions, not total frame count.
 */
export function drawTrail(end: number, id: string): void {
  if (end < 1) return;

  state.cx.lineWidth = 2.5;

  function beginSeg(st: number, fx: number, fy: number): void {
    state.cx.stroke();
    state.cx.strokeStyle = hexA(ST[Math.min(st, ST.length - 1)].color, 0.55);
    state.cx.beginPath();
    state.cx.moveTo(fx, fy);
  }

  // Use cached start index — avoids O(n) scan for late-joining robots.
  let startIdx = _trailStartCache.get(id) ?? 0;
  // Robot hasn't appeared yet at this playback position — draw nothing.
  if (startIdx > end) return;
  let firstFrameRobot = robotFrame(state.SIM.frames[startIdx], id);
  if (!firstFrameRobot) {
    for (let i = startIdx + 1; i <= end; i++) {
      firstFrameRobot = robotFrame(state.SIM.frames[i], id);
      if (firstFrameRobot) { startIdx = i; _trailStartCache.set(id, i); break; }
    }
    if (!firstFrameRobot) return;
  }

  let curSt = firstFrameRobot.st;
  const [x0, y0] = w2c(firstFrameRobot.x, firstFrameRobot.y);
  state.cx.strokeStyle = hexA(ST[Math.min(curSt, ST.length - 1)].color, 0.55);
  state.cx.beginPath();
  state.cx.moveTo(x0, y0);

  for (let i = startIdx + TUNING.TRAIL_SAMPLE_EVERY; i <= end; i += TUNING.TRAIL_SAMPLE_EVERY) {
    const f = robotFrame(state.SIM.frames[i], id);
    if (!f) continue;
    const [px, py] = w2c(f.x, f.y);
    if (f.st !== curSt) {
      state.cx.lineTo(px, py);
      curSt = f.st;
      beginSeg(curSt, px, py);
    } else {
      state.cx.lineTo(px, py);
    }
  }

  const endFrameRobot = robotFrame(state.SIM.frames[end], id);
  if (!endFrameRobot) { state.cx.stroke(); return; }
  const [ex, ey] = w2c(endFrameRobot.x, endFrameRobot.y);
  state.cx.lineTo(ex, ey);
  state.cx.stroke();
}


/**
 * Draw small labelled circles at every position where this robot changed state.
 * Uses cached transition data — O(k) not O(n frames).
 */
export function drawStateTransitions(end: number, id: string): void {
  const transitions = _transitionCache.get(id);
  if (!transitions || transitions.length === 0) return;

  for (const { fi, x, y, st } of transitions) {
    if (fi > end) break;  // cache is insertion-ordered (ascending fi)

    const newCol   = ST[Math.min(st, ST.length - 1)].color;
    const [px, py] = w2c(x, y);

    state.cx.strokeStyle = '#050810';
    state.cx.lineWidth   = 2;
    state.cx.fillStyle   = hexA(newCol, 0.92);
    state.cx.beginPath();
    state.cx.arc(px, py, TUNING.STATE_MARKER_PX, 0, Math.PI * 2);
    state.cx.fill();
    state.cx.stroke();

    state.cx.fillStyle  = hexA(newCol, 0.85);
    state.cx.font       = '10px JetBrains Mono,monospace';
    state.cx.textAlign  = 'center';
    state.cx.fillText('\u2192' + SHORT[Math.min(st, SHORT.length - 1)], px, py - 10);
  }
}


function assessedGap(fr: any, followerId: string): number | null {
  const lrGap = fr.low_res?.per_robot?.[followerId]?.assessment?.gap?.bumper_gap_meters ?? null;
  if (lrGap != null) return lrGap;
  return fr.high_res?.per_robot?.[followerId]?.assessment?.gap?.bumper_gap_meters ?? null;
}


/**
 * Draw backend-assessed links between consecutive chain members.
 * Accepts one array per platoon component — links are only drawn within
 * a component, never across the boundary between two separate platoons.
 *
 * Colour encodes gap health relative to TARGET_GAP:
 *   < 70 %  → red    (too close)
 *   70–85 % → orange (slightly close)
 *   85–125% → green  (ideal)
 *   > 125%  → yellow (too far)
 */
export function drawPlatoonLinks(fr: any, components: string[][], vis: (id: string) => boolean): void {
  function gapHealthColor(gap: number): string {
    const ratio = gap / TARGET_GAP;
    if (ratio < TUNING.GAP_CLOSE)  return '#ff5252';
    if (ratio < TUNING.GAP_OK_LOW) return '#ff9100';
    if (ratio <= TUNING.GAP_OK_HI) return '#00e676';
    return '#ffd740';
  }

  components.forEach(component => {
    component.forEach((rid, idx) => {
      if (idx === 0 || !vis(rid)) return;
      const r = robotFrame(fr, rid);
      if (!r) return;
      const leaderId = component[idx - 1];
      const leader = leaderId ? robotFrame(fr, leaderId) : null;
      if (!leaderId || !leader || !vis(leaderId)) return;

      const gap = assessedGap(fr, rid);
      if (gap == null) return;
      const hCol = gapHealthColor(gap);

      const [x1, y1] = w2c(r.x,      r.y);
      const [x2, y2] = w2c(leader.x, leader.y);

      state.cx.strokeStyle = hexA(hCol, 0.55);
      state.cx.lineWidth   = 2;
      state.cx.setLineDash([7, 5]);
      state.cx.beginPath();
      state.cx.moveTo(x1, y1);
      state.cx.lineTo(x2, y2);
      state.cx.stroke();
      state.cx.setLineDash([]);

      state.cx.fillStyle  = hexA(hCol, 0.85);
      state.cx.font       = '13px JetBrains Mono,monospace';
      state.cx.textAlign  = 'center';
      state.cx.fillText(gap.toFixed(2) + ' m', (x1 + x2) / 2, (y1 + y2) / 2 - 12);
    });
  });
}


/** Draw the state colour legend in the bottom-left corner of the canvas. */
export function drawStateLegend(): void {
  if (!state.LAYERS.trail) return;

  const rowH    = 17;
  const swatchW = 16;
  const gap     = 6;
  const pad     = 8;
  const x       = 14;
  const totalH  = ST.length * rowH + pad * 2;
  const y0      = state.H - totalH - 28;

  state.cx.fillStyle = 'rgba(5,8,16,0.72)';
  state.cx.fillRect(x - pad, y0 - pad, 115, totalH);

  state.cx.font      = '11px JetBrains Mono,monospace';
  state.cx.textAlign = 'left';

  ST.forEach((s: any, i: number) => {
    const y = y0 + i * rowH;
    state.cx.strokeStyle = hexA(s.color, 0.80);
    state.cx.lineWidth   = 3;
    state.cx.beginPath();
    state.cx.moveTo(x, y + 5);
    state.cx.lineTo(x + swatchW, y + 5);
    state.cx.stroke();
    state.cx.fillStyle = hexA(s.color, 0.75);
    state.cx.fillText(s.label, x + swatchW + gap, y + 9);
  });
}
