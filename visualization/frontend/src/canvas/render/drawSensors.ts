// ─────────────────────────────────────────────────────────────────────────────
// drawSensors.ts — Sensor overlay rendering.
//
// Drawn per robot when the SENSORS layer is active:
//   1. Lane camera FOV cone
//   2. Distance sensor beam with distance label
//   3. Leader-tracking reticle on the controller-advertised leader when tk=true
//   4. Sensor-estimated leader position diamond
// ─────────────────────────────────────────────────────────────────────────────

import { state } from '../state';
import { w2c } from '../camera';
import { robotFrame, hexA, ST, RL, FOV_RANGE, FOV_HALF, TUNING } from '../constants';

function advertisedLeaderId(r: any): string | null {
  return r && r.leader_input_id != null ? String(r.leader_input_id) : null;
}


/** Draw all sensor overlays for one robot. */
export function drawSensorOverlay(r: any, col: string, fr: any): void {
  drawLaneFOV(r, col);
  drawDistanceSensor(r);
  drawLeaderDetection(r, col, fr);
  drawSensorLeaderEstimate(r, col, fr);
}


/** Draw the lane camera field-of-view cone. */
export function drawLaneFOV(r: any, col: string): void {
  const [tx, ty] = w2c(r.x, r.y);
  const angL = r.w + FOV_HALF;
  const angR = r.w - FOV_HALF;
  const [fxL, fyL] = w2c(r.x + FOV_RANGE * Math.cos(angL), r.y + FOV_RANGE * Math.sin(angL));
  const [fxR, fyR] = w2c(r.x + FOV_RANGE * Math.cos(angR), r.y + FOV_RANGE * Math.sin(angR));

  state.cx.beginPath();
  state.cx.moveTo(tx, ty);
  state.cx.lineTo(fxL, fyL);
  state.cx.lineTo(fxR, fyR);
  state.cx.closePath();
  state.cx.fillStyle = hexA(col, 0.04);
  state.cx.fill();

  state.cx.strokeStyle = hexA(col, 0.18);
  state.cx.lineWidth   = 0.7;
  state.cx.setLineDash([4, 5]);
  state.cx.beginPath();
  state.cx.moveTo(tx, ty); state.cx.lineTo(fxL, fyL);
  state.cx.moveTo(tx, ty); state.cx.lineTo(fxR, fyR);
  state.cx.stroke();
  state.cx.setLineDash([]);
}


/**
 * Draw the distance sensor beam from the robot nose to the detected object.
 *
 * Visual encoding:
 *   - Solid line + bright dot  = controller path reports a leader lock (tk=true)
 *   - Dashed line + dim dot   = unknown contact
 *   - Very faint dashed       = sensor invalid (dv=false)
 */
export function drawDistanceSensor(r: any): void {
  const leaderLocked = !!r.tk;
  const stCol   = ST[Math.min(r.st, ST.length - 1)].color;
  const beamCol = r.dv ? (leaderLocked ? stCol : '#c8c8c8') : '#555';

  const noseOff = (RL / 2) * state.robotSizeM;
  const noseX = r.x + noseOff * Math.cos(r.w);
  const noseY = r.y + noseOff * Math.sin(r.w);
  const tipX  = r.x + (noseOff + r.d) * Math.cos(r.w);
  const tipY  = r.y + (noseOff + r.d) * Math.sin(r.w);
  const [nx, ny] = w2c(noseX, noseY);
  const [ex, ey] = w2c(tipX,  tipY);

  state.cx.strokeStyle = hexA(beamCol, r.dv ? 0.72 : 0.22);
  state.cx.lineWidth   = r.dv ? (leaderLocked ? 2 : 1.4) : 1;
  state.cx.setLineDash(r.dv && !leaderLocked ? [4, 4] : r.dv ? [] : [3, 5]);
  state.cx.beginPath();
  state.cx.moveTo(nx, ny);
  state.cx.lineTo(ex, ey);
  state.cx.stroke();
  state.cx.setLineDash([]);

  if (r.dv) {
    state.cx.fillStyle = hexA(beamCol, leaderLocked ? 1.0 : 0.65);
    state.cx.beginPath();
    state.cx.arc(ex, ey, leaderLocked ? 3.5 : 2.5, 0, Math.PI * 2);
    state.cx.fill();

    state.cx.fillStyle  = hexA(beamCol, leaderLocked ? 0.85 : 0.60);
    state.cx.font       = 'bold 12px JetBrains Mono,monospace';
    state.cx.textAlign  = 'center';
    const label = (leaderLocked ? '' : '? ') + r.d.toFixed(2) + ' m';
    state.cx.fillText(label, (nx + ex) / 2, (ny + ey) / 2 - 7);
  }
}


/**
 * Draw a targeting reticle on the controller-advertised leader when
 * this follower has a confirmed lock (tk=true).
 */
export function drawLeaderDetection(r: any, col: string, fr: any): void {
  if (!r.tk) return;
  const leaderId = advertisedLeaderId(r);
  const leader   = robotFrame(fr, leaderId);
  if (!leader) return;
  const [lx, ly] = w2c(leader.x, leader.y);
  const R        = TUNING.RETICLE_RADIUS_PX;

  state.cx.strokeStyle = hexA(col, 0.65);
  state.cx.lineWidth   = 1.2;
  state.cx.beginPath();
  state.cx.arc(lx, ly, R, 0, Math.PI * 2);
  state.cx.stroke();

  [0, Math.PI / 2, Math.PI, 3 * Math.PI / 2].forEach(a => {
    const ix = lx + (R - 4) * Math.cos(a), iy = ly + (R - 4) * Math.sin(a);
    const ox = lx + (R + 5) * Math.cos(a), oy = ly + (R + 5) * Math.sin(a);
    state.cx.beginPath();
    state.cx.moveTo(ix, iy);
    state.cx.lineTo(ox, oy);
    state.cx.stroke();
  });

  state.cx.fillStyle = hexA(col, 0.45);
  state.cx.beginPath();
  state.cx.arc(lx, ly, 2.5, 0, Math.PI * 2);
  state.cx.fill();

  state.cx.fillStyle  = hexA(col, 0.7);
  state.cx.font       = '11px JetBrains Mono,monospace';
  state.cx.textAlign  = 'center';
  state.cx.fillText('TRACKED', lx, ly - R - 5);
}


/**
 * Draw a diamond marker at the sensor-estimated leader position, plus a
 * dashed error line to the actual leader.
 */
export function drawSensorLeaderEstimate(r: any, col: string, fr: any): void {
  if (!r.dv) return;
  const leaderId = advertisedLeaderId(r);
  const leader   = robotFrame(fr, leaderId);
  if (!leader) return;

  const predX = r.x + r.d * Math.cos(r.w);
  const predY = r.y + r.d * Math.sin(r.w);
  const [px, py] = w2c(predX, predY);

  const D = 5;
  state.cx.save();
  state.cx.translate(px, py);
  state.cx.rotate(Math.PI / 4);
  state.cx.strokeStyle = hexA(col, 0.70);
  state.cx.lineWidth   = 1.2;
  state.cx.fillStyle   = hexA(col, 0.15);
  state.cx.fillRect(-D, -D, D * 2, D * 2);
  state.cx.strokeRect(-D, -D, D * 2, D * 2);
  state.cx.restore();

  const [lx, ly] = w2c(leader.x, leader.y);
  state.cx.strokeStyle = hexA(col, 0.28);
  state.cx.lineWidth   = 0.8;
  state.cx.setLineDash([2, 4]);
  state.cx.beginPath();
  state.cx.moveTo(px, py);
  state.cx.lineTo(lx, ly);
  state.cx.stroke();
  state.cx.setLineDash([]);
}
