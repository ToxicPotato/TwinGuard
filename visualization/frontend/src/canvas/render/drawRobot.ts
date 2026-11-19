// ─────────────────────────────────────────────────────────────────────────────
// drawRobot.ts — Robot body, ghost (reference pose) and velocity arrow.
// ─────────────────────────────────────────────────────────────────────────────

import { state } from '../state';
import { w2c } from '../camera';
import { hexA, rrect, ST, RL, RW, VEL_SCALE } from '../constants';


/**
 * Draw the solid robot body at its estimated position.
 *
 * Rendering layers (inside-out):
 *   1. State glow ring  — coloured by active state, slightly larger than body
 *   2. Robot body       — rounded rectangle coloured by robot palette index
 *   3. Direction arrow  — small forward-pointing arrow on the nose
 *   4. Label            — display label above the robot
 */
export function drawRobot(r: any, col: string, label: string): void {
  const [px, py] = w2c(r.x, r.y);
  const yaw = -r.w;
  const lp  = RL * state.robotSizeM * state.scale;
  const wp  = RW * state.robotSizeM * state.scale;
  const stCol = ST[Math.min(r.st, ST.length - 1)].color;

  state.cx.save();
  state.cx.translate(px, py);
  state.cx.rotate(yaw);

  // State glow ring
  state.cx.shadowColor = stCol;
  state.cx.shadowBlur  = 20;
  state.cx.fillStyle   = hexA(stCol, 0.08);
  state.cx.strokeStyle = hexA(stCol, 0.45);
  state.cx.lineWidth   = 1;
  rrect(state.cx, -lp / 2 - 3, -wp / 2 - 3, lp + 6, wp + 6, 5);
  state.cx.fill();
  state.cx.stroke();

  // Robot body
  state.cx.shadowColor = col;
  state.cx.shadowBlur  = 10;
  state.cx.fillStyle   = hexA(col, 0.22);
  state.cx.strokeStyle = col;
  state.cx.lineWidth   = 2;
  rrect(state.cx, -lp / 2, -wp / 2, lp, wp, 3);
  state.cx.fill();
  state.cx.stroke();

  // Forward-pointing direction arrow on the nose
  state.cx.fillStyle  = col;
  state.cx.shadowBlur = 6;
  state.cx.beginPath();
  state.cx.moveTo(lp / 2 - 3, -3);
  state.cx.lineTo(lp / 2 + 8,  0);
  state.cx.lineTo(lp / 2 - 3,  3);
  state.cx.closePath();
  state.cx.fill();

  state.cx.shadowBlur = 0;
  state.cx.restore();

  // Label above the robot (outside rotated block)
  state.cx.fillStyle  = col;
  state.cx.font       = 'bold 13px JetBrains Mono,monospace';
  state.cx.textAlign  = 'center';
  state.cx.fillText(label, px, py - wp / 2 - 7);
}


/**
 * Draw a ghost (dashed outline) at the reference pose — where the controller
 * wants the robot to be.  Shows tracking error when estimated and reference
 * poses diverge.
 */
export function drawGhostRobot(r: any, col: string): void {
  const [gx, gy] = w2c(r.rx, r.ry);
  const [sx, sy] = w2c(r.x,  r.y);
  const lp = RL * state.robotSizeM * state.scale;
  const wp = RW * state.robotSizeM * state.scale;

  state.cx.save();
  state.cx.translate(gx, gy);
  state.cx.rotate(-r.ryaw);
  state.cx.strokeStyle = hexA(col, 0.28);
  state.cx.lineWidth   = 1.2;
  state.cx.setLineDash([4, 4]);
  rrect(state.cx, -lp / 2, -wp / 2, lp, wp, 3);
  state.cx.stroke();
  state.cx.setLineDash([]);

  state.cx.strokeStyle = hexA(col, 0.22);
  state.cx.lineWidth   = 1;
  state.cx.beginPath();
  state.cx.moveTo(lp / 2, 0);
  state.cx.lineTo(lp / 2 + 5, 0);
  state.cx.stroke();
  state.cx.restore();

  state.cx.fillStyle  = hexA(col, 0.40);
  state.cx.font       = '11px JetBrains Mono,monospace';
  state.cx.textAlign  = 'center';
  state.cx.fillText('REF', gx, gy - wp / 2 - 5);

  const errPx = Math.hypot(sx - gx, sy - gy);
  if (errPx >= 0.5) {
    state.cx.strokeStyle = 'rgba(255,255,255,0.30)';
    state.cx.lineWidth   = 1;
    state.cx.setLineDash([3, 4]);
    state.cx.beginPath();
    state.cx.moveTo(gx, gy);
    state.cx.lineTo(sx, sy);
    state.cx.stroke();
    state.cx.setLineDash([]);

    const errM = Math.hypot(r.x - r.rx, r.y - r.ry);
    state.cx.fillStyle  = 'rgba(255,255,255,0.55)';
    state.cx.font       = '11px JetBrains Mono,monospace';
    state.cx.textAlign  = 'center';
    state.cx.fillText(errM.toFixed(4) + ' m', (gx + sx) / 2 + 8, (gy + sy) / 2);
  }
}


/**
 * Draw a velocity vector arrow from the robot nose along its heading.
 * Not drawn when speed < 0.05 m/s.
 */
export function drawVelocityVector(r: any, col: string): void {
  if (r.v < 0.05) return;

  const bodyFront = RL / 2 * state.robotSizeM;
  const arrowLen  = r.v * VEL_SCALE;
  const tailX = r.x + bodyFront * Math.cos(r.w);
  const tailY = r.y + bodyFront * Math.sin(r.w);
  const tipX  = r.x + (bodyFront + arrowLen) * Math.cos(r.w);
  const tipY  = r.y + (bodyFront + arrowLen) * Math.sin(r.w);

  const [tx, ty] = w2c(tailX, tailY);
  const [hx, hy] = w2c(tipX,  tipY);

  state.cx.strokeStyle = hexA(col, 0.75);
  state.cx.lineWidth   = 2;
  state.cx.beginPath();
  state.cx.moveTo(tx, ty);
  state.cx.lineTo(hx, hy);
  state.cx.stroke();

  const ang  = Math.atan2(hy - ty, hx - tx);
  const aLen = 8;
  state.cx.fillStyle = hexA(col, 0.85);
  state.cx.beginPath();
  state.cx.moveTo(hx, hy);
  state.cx.lineTo(hx - aLen * Math.cos(ang - 0.38), hy - aLen * Math.sin(ang - 0.38));
  state.cx.lineTo(hx - aLen * Math.cos(ang + 0.38), hy - aLen * Math.sin(ang + 0.38));
  state.cx.closePath();
  state.cx.fill();
}
