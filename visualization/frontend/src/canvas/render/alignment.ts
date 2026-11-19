// ─────────────────────────────────────────────────────────────────────────────
// alignment.ts — Simplified: all robots share one world frame.
//
// Local coordinates ARE world coordinates — no local-to-global transform is
// computed or applied.  All robots are assumed to live in the same coordinate
// system, so every robot gets an identity transform (tx=0, ty=0, theta=0).
//
// alignmentState[runName][robotId]:
//   { method:'bootstrap', tx:0, ty:0, theta:0, confidence:1.0, … }
//
// globalRoadMap[runName] is built by merging all robots' road buffers directly
// (no rotation/translation), using the same forward/backward extension logic
// as before so the map grows correctly as robots move.
// ─────────────────────────────────────────────────────────────────────────────

import { state } from '../state';
import { MIN_ROAD_DIST } from '../constants';


// ── Helpers ───────────────────────────────────────────────────────────────────

function _setState(
  runName: string, id: string, method: string,
  tx: number, ty: number, theta: number,
  confidence: number, anchor_frame: number, anchor_time: number, last_frame: number,
) {
  if (!state.alignmentState[runName]) state.alignmentState[runName] = {};
  state.alignmentState[runName][id] = { method, tx, ty, theta, confidence, anchor_frame, anchor_time, last_frame };
}

function initGlobalMap(runName: string): void {
  state.globalRoadMap[runName] = [];
  state._globalMapIdx[runName] = {};
}


// ── Global road map ───────────────────────────────────────────────────────────

/**
 * Merge new points from a robot's local road buffer into globalRoadMap.
 * Local coords ARE world coords — points are copied directly with no transform.
 * Supports both forward and backward extension of the map.
 * Safe to call every frame — idempotent when no new road points exist.
 */
export function addToGlobalMap(runName: string, robotId: string): void {
  const a = (state.alignmentState[runName] || {})[robotId];
  if (!a || a.method === 'none') return;

  const localBuf: { x: number; y: number; yaw: number }[] = (state.roadBuffer[runName] || {})[robotId] || [];
  if (localBuf.length === 0) return;

  if (!state._globalMapIdx[runName]) state._globalMapIdx[runName] = {};
  const gMap: { x: number; y: number; yaw: number }[] = state.globalRoadMap[runName] || (state.globalRoadMap[runName] = []);

  // Map is empty — add all points in order.
  if (gMap.length === 0) {
    for (const pt of localBuf) gMap.push({ x: pt.x, y: pt.y, yaw: pt.yaw });
    state._globalMapIdx[runName][robotId] = localBuf.length;
    return;
  }

  // ── Forward extension ─────────────────────────────────────────────────────
  const startIdx: number = state._globalMapIdx[runName][robotId] || 0;
  for (let i = startIdx; i < localBuf.length; i++) {
    const wp   = localBuf[i];
    const last = gMap[gMap.length - 1];
    const dx = wp.x - last.x, dy = wp.y - last.y;
    if (Math.hypot(dx, dy) < MIN_ROAD_DIST) continue;
    const fwdX = Math.cos(last.yaw), fwdY = Math.sin(last.yaw);
    if (dx * fwdX + dy * fwdY < 0) continue;
    gMap.push({ x: wp.x, y: wp.y, yaw: wp.yaw });
  }
  state._globalMapIdx[runName][robotId] = localBuf.length;

  // ── Backward extension ────────────────────────────────────────────────────
  const prepend: { x: number; y: number; yaw: number }[] = [];
  const first = gMap[0];
  const bwdX  = -Math.cos(first.yaw), bwdY = -Math.sin(first.yaw);
  for (let i = 0; i < localBuf.length; i++) {
    const wp = localBuf[i];
    const dx = wp.x - first.x, dy = wp.y - first.y;
    if (Math.hypot(dx, dy) < MIN_ROAD_DIST) continue;
    if (dx * bwdX + dy * bwdY <= 0) continue;
    prepend.push({ x: wp.x, y: wp.y, yaw: wp.yaw });
  }
  if (prepend.length > 0) {
    prepend.sort((a, b) => {
      const dA = (a.x - first.x) * bwdX + (a.y - first.y) * bwdY;
      const dB = (b.x - first.x) * bwdX + (b.y - first.y) * bwdY;
      return dB - dA;
    });
    const toAdd = [prepend[0]];
    for (let i = 1; i < prepend.length; i++) {
      const prev = toAdd[toAdd.length - 1];
      if (Math.hypot(prepend[i].x - prev.x, prepend[i].y - prev.y) >= MIN_ROAD_DIST) {
        toAdd.push(prepend[i]);
      }
    }
    gMap.unshift(...toAdd);
  }
}


// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Initialise alignment for a run (called once after initRoadBuffers).
 * All robots immediately get an identity transform — no matching needed.
 */
export function initAlignment(runName: string): void {
  state.alignmentState[runName] = {};
  initGlobalMap(runName);

  const robots: string[] = state.RUNS[runName].meta.robots;
  const f0 = state.RUNS[runName].frames[0];

  robots.forEach(id => {
    _setState(runName, id, 'bootstrap', 0, 0, 0, 1.0, 0, f0 ? f0.t : 0, 0);
    addToGlobalMap(runName, id);
  });
}


/**
 * Incorporate one new frame (streaming entry point).
 */
export function updateAlignment(runName: string, frame: any, frameIndex: number): void {
  if (!state.alignmentState[runName]) {
    state.alignmentState[runName] = {};
    initGlobalMap(runName);
  }
  // Ensure every known robot has an alignment entry — handles late joiners in live mode.
  const robots: string[] = state.RUNS[runName].meta.robots;
  robots.forEach(id => {
    if (!state.alignmentState[runName][id]) {
      _setState(runName, id, 'bootstrap', 0, 0, 0, 1.0, frameIndex, frame.t, frameIndex);
    }
  });
  robots.forEach(id => addToGlobalMap(runName, id));
}
