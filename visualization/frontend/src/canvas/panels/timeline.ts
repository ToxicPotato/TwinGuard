import { state } from '../state';
import { ST, robotFrame, hexA } from '../constants';

type TimelineCanvas = HTMLCanvasElement & { _img?: ImageData };

export function buildTimeline(id: string) {
  const cv = document.getElementById(id + '-tl') as TimelineCanvas | null;
  if (!cv || !state.SIM) return;

  const width = (cv.parentElement && cv.parentElement.clientWidth) || cv.offsetWidth || 308;
  cv.width = width;
  const ctx = cv.getContext('2d');
  const frameCount = state.SIM.frames.length;
  if (!ctx || frameCount === 0) return;

  let previousState = robotFrame(state.SIM.frames[0], id)?.st ?? 0;
  let startFrame = 0;

  for (let index = 1; index <= frameCount; index++) {
    const nextState = index < frameCount ? (robotFrame(state.SIM.frames[index], id)?.st ?? previousState) : -1;
    if (nextState !== previousState) {
      const x1 = Math.floor((startFrame / frameCount) * width);
      const x2 = Math.ceil((index / frameCount) * width);
      ctx.fillStyle = hexA(ST[Math.min(previousState, ST.length - 1)].color, 0.70);
      ctx.fillRect(x1, 0, x2 - x1, 10);
      previousState = nextState;
      startFrame = index;
    }
  }

  cv._img = ctx.getImageData(0, 0, width, 10);
}

export function updateTimeline(id: string) {
  const cv = document.getElementById(id + '-tl') as TimelineCanvas | null;
  if (!cv || !cv._img || !state.SIM) return;

  const ctx = cv.getContext('2d');
  if (!ctx) return;

  ctx.putImageData(cv._img, 0, 0);

  const x = Math.round((state.fi / Math.max(1, state.SIM.frames.length - 1)) * cv.width);
  ctx.strokeStyle = 'rgba(255,255,255,0.90)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(x, 0);
  ctx.lineTo(x, 10);
  ctx.stroke();
}
