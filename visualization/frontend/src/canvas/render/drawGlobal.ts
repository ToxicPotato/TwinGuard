// drawGlobal.ts — Global canvas: all robots drawn in world coordinates.
//
// All robots share one world coordinate frame (identity alignment).
// Roads and robot bodies are rendered for every visible robot.

import { state } from '../state';
import { robotFrame, hexA, PALETTE } from '../constants';
import { w2c } from '../camera';
import { drawRobotRoad } from './drawRoad';
import { drawRobot, drawVelocityVector } from './drawRobot';
import { robotLabel } from '../panels/shared';


export function drawGlobalCanvas(fr: any, vis: (id: string) => boolean): void {
  const runName  = state.SIM.meta.sheet as string;
  const runBuf   = state.roadBuffer[runName] || {};
  const runAlign = state.alignmentState[runName] || {};

  // Roads — one per visible robot
  (state.SIM.meta.robots as string[]).forEach((id, idx) => {
    if (!vis(id) || !runAlign[id]) return;
    const buf = runBuf[id];
    if (!buf || buf.length < 2) return;
    const r = robotFrame(fr, id);
    if (!r) return;
    drawRobotRoad(buf, r, PALETTE[idx % PALETTE.length], id);
  });

  // Robot bodies — sorted rear-to-front so leaders render on top.
  // Build palette index map once so the render loop avoids O(n) indexOf per robot.
  const robotList = state.SIM.meta.robots as string[];
  const paletteIdx = new Map(robotList.map((id, i) => [id, i]));

  const sorted = robotList.slice().sort((idA, idB) => {
    const rA = robotFrame(fr, idA);
    const rB = robotFrame(fr, idB);
    if (!rA || !rB) return 0;
    return rB.x - rA.x;
  });

  sorted.forEach((id: string) => {
    if (!vis(id) || !runAlign[id]) return;
    const r = robotFrame(fr, id);
    if (!r) return;
    const col = PALETTE[(paletteIdx.get(id) ?? 0) % PALETTE.length];

    drawVelocityVector(r, col);
    drawRobot(r, col, robotLabel(id));
  });
}
