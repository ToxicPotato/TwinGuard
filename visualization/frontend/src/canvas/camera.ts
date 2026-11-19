// ─────────────────────────────────────────────────────────────────────────────
// camera.ts — Canvas setup, world↔canvas coordinate transform,
//             pan drag, scroll-to-zoom, follow mode, robot size control.
// ─────────────────────────────────────────────────────────────────────────────

import { state } from './state';
import { TUNING } from './constants';
import { sfxResume } from './audio';

// ── Draw / UI forward references ──────────────────────────────────────────────
let _draw: () => void = () => {};
let _updateUI: () => void = () => {};

export function setDrawCallback(fn: () => void) { _draw = fn; }
export function setUpdateUICallback(fn: () => void) { _updateUI = fn; }


/**
 * Resize the canvas to fill its parent element, applying HiDPI scaling.
 * Must be called on startup and whenever the window is resized.
 */
export function resizeCvs(): void {
  const dpr  = window.devicePixelRatio || 1;
  const rect = (state.cvs as HTMLCanvasElement).parentElement!.getBoundingClientRect();
  (state.cvs as HTMLCanvasElement).width  = rect.width  * dpr;
  (state.cvs as HTMLCanvasElement).height = rect.height * dpr;
  state.W = rect.width;
  state.H = rect.height;
  (state.cx as CanvasRenderingContext2D).setTransform(dpr, 0, 0, dpr, 0, 0);
}


/**
 * Convert a world-space position (metres) to canvas pixel coordinates.
 *
 * World frame: X right, Y up.
 * Canvas frame: X right, Y down — so we negate the Y component.
 */
export function w2c(wx: number, wy: number): [number, number] {
  return [
    state.W / 2 + (wx - state.vx) * state.scale,
    state.H / 2 - (wy - state.vy) * state.scale,
  ];
}


/**
 * Zoom the viewport by factor f, keeping the viewport centre fixed.
 * Scale is clamped to [SCALE_MIN, SCALE_MAX] px/m.
 */
export function doZoom(f: number): void {
  state.scale = Math.max(TUNING.SCALE_MIN, Math.min(TUNING.SCALE_MAX, state.scale * f));
  const cnfo = document.getElementById('cnfo');
  if (cnfo) cnfo.textContent = 'SCALE: ' + state.scale.toFixed(0) + ' px/m';
}


/** Toggle camera-follow mode on/off. */
export function toggleFollow(): void {
  state.cameraFollow = !state.cameraFollow;
  document.getElementById('btn-follow')?.classList.toggle('on', state.cameraFollow);
}


/**
 * Adjust the robot render size multiplier.
 * Clamped to [0.3×, 12×] so robots stay visible at any zoom.
 */
export function resizeRobot(f: number): void {
  state.robotSizeM = Math.max(0.3, Math.min(12.0, state.robotSizeM * f));
  const lbl = document.getElementById('robot-size-lbl');
  if (lbl) lbl.textContent = state.robotSizeM.toFixed(1) + 'x';
}


/**
 * Initialise the canvas element and 2D context from the DOM, resize to fill
 * the parent, and register mouse/wheel interaction handlers.
 *   - Left-drag: pan the viewport (disables follow mode)
 *   - Scroll wheel: zoom centred on the cursor position
 */
export function initCamera(): void {
  state.cvs = document.getElementById('arena') as HTMLCanvasElement;
  state.cx  = (state.cvs as HTMLCanvasElement).getContext('2d')!;

  resizeCvs();

  window.addEventListener('resize', () => { resizeCvs(); _draw(); });

  // ── Pan drag ────────────────────────────────────────────────────────────────
  (state.cvs as HTMLCanvasElement).addEventListener('mousedown', (e: MouseEvent) => {
    if (e.button !== 0 || state._scrubbing) return;
    state._drag = { x: e.clientX, y: e.clientY, vx0: state.vx, vy0: state.vy };
    (state.cvs as HTMLCanvasElement).style.cursor = 'grabbing';
  });

  window.addEventListener('mousemove', (e: MouseEvent) => {
    if (!state._drag) return;
    // Convert pixel drag delta to world-space offset
    const dx = (e.clientX - state._drag.x) / state.scale;
    const dy = (e.clientY - state._drag.y) / state.scale;
    state.vx = state._drag.vx0 - dx;
    state.vy = state._drag.vy0 + dy;   // +dy because canvas Y is flipped
    // Dragging implies the user wants free pan — disable follow mode
    if (state.cameraFollow) {
      state.cameraFollow = false;
      document.getElementById('btn-follow')?.classList.remove('on');
    }
  });

  window.addEventListener('mouseup', () => {
    state._drag = null;
    (state.cvs as HTMLCanvasElement).style.cursor = 'grab';
  });

  (state.cvs as HTMLCanvasElement).style.cursor = 'grab';

  // ── Scroll-to-zoom (keeps the world point under the cursor fixed) ────────────
  (state.cvs as HTMLCanvasElement).addEventListener('wheel', (e: WheelEvent) => {
    e.preventDefault();
    sfxResume();

    const rect = (state.cvs as HTMLCanvasElement).getBoundingClientRect();
    const mx   = e.clientX - rect.left;
    const my   = e.clientY - rect.top;

    // World coordinates under the cursor BEFORE zooming
    const wx = state.vx + (mx - state.W / 2) / state.scale;
    const wy = state.vy - (my - state.H / 2) / state.scale;

    // doZoom handles clamping and the cnfo label
    doZoom(e.deltaY < 0 ? 1.12 : 1 / 1.12);

    // Adjust viewport centre so the same world point stays under the cursor
    state.vx = wx - (mx - state.W / 2) / state.scale;
    state.vy = wy + (my - state.H / 2) / state.scale;

    if (state.SIM) { _draw(); _updateUI(); }
  }, { passive: false });
}
