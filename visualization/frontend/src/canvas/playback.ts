// ─────────────────────────────────────────────────────────────────────────────
// playback.ts — Playback state, transport controls (play/pause/rewind/speed),
//               click-to-seek, and draggable timeline scrubber.
// ─────────────────────────────────────────────────────────────────────────────

import { state } from './state';

// ── Draw / UI / SFX forward references ───────────────────────────────────────
let _draw: () => void = () => {};
let _updateUI: () => void = () => {};
let _sfxUI: (action: string) => void = () => {};
let _sfxScrubTick: () => void = () => {};

export function setDrawCallback(fn: () => void) { _draw = fn; }
export function setUpdateUICallback(fn: () => void) { _updateUI = fn; }
export function setSfxUICallback(fn: (action: string) => void) { _sfxUI = fn; }
export function setSfxScrubTickCallback(fn: () => void) { _sfxScrubTick = fn; }


/** Toggle play / pause. */
export function doPlay(): void {
  if (state.liveMode) return;
  state.playing = !state.playing;

  // Rewind to start if we were at the last frame
  if (state.playing && state.fi >= state.SIM.frames.length - 1) {
    state.fi = 0;
    state.accumT = 0;
  }

  state.lastTs = null;  // reset timing so the next tick starts fresh

  const pbPlay = document.getElementById('pbplay');
  if (pbPlay) {
    pbPlay.innerHTML = state.playing ? '&#x23F8;' : '&#x25B6;';
    pbPlay.classList.toggle('on', state.playing);
  }
  _sfxUI(state.playing ? 'play' : 'pause');
}


/** Jump to frame 0 and stop playback. */
export function doRewind(): void {
  if (state.liveMode) return;
  state.fi = 0; state.accumT = 0; state.playing = false; state.lastTs = null;
  const pbPlay = document.getElementById('pbplay');
  if (pbPlay) { pbPlay.innerHTML = '&#x25B6;'; pbPlay.classList.remove('on'); }
  _sfxUI('rewind');
}


/** Cycle through playback speeds (0.25× → 0.5× → 1× → 2× → 4× → …). */
export function doSpeed(): void {
  state.spdi = (state.spdi + 1) % state.SPEEDS.length;
  const pbSpd = document.getElementById('pbspd');
  if (pbSpd) pbSpd.textContent = state.SPDLBL[state.spdi];
}


/** Seek to a frame by clicking on the timeline track bar. */
export function doSeek(e: MouseEvent): void {
  if (state.liveMode) return;
  const track = document.getElementById('tl-track');
  if (!track) return;
  const r     = track.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  state.fi     = Math.floor(ratio * (state.SIM.frames.length - 1));
  state.accumT = state.SIM.frames[state.fi].t;
}


/**
 * Initialise the draggable timeline scrubber thumb.
 *
 * While scrubbing:
 *   - Smooth CSS transitions on thumb and fill are disabled for instant response.
 *   - sfxScrubTick() fires on each move event (rate-limited internally).
 *   - draw() and updateUI() are called immediately so the canvas stays in sync.
 */
export function initScrubber(): void {
  const track = document.getElementById('tl-track') as HTMLElement | null;
  const thumb = document.getElementById('tl-thumb') as HTMLElement | null;
  if (!track || !thumb) return;

  function scrubTo(clientX: number) {
    if (!state.SIM || !track) return;
    const r     = track.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
    state.fi     = Math.floor(ratio * (state.SIM.frames.length - 1));
    state.accumT = state.SIM.frames[state.fi].t;
    _sfxScrubTick();
    _draw();
    _updateUI();
  }

  track.addEventListener('mousedown', (e: MouseEvent) => {
    if (e.button !== 0) return;
    state._scrubbing = true;
    // Disable CSS transitions for instant visual feedback while dragging
    thumb.style.transition = 'none';
    const fill = document.getElementById('tl-fill');
    if (fill) fill.style.transition = 'none';
    scrubTo(e.clientX);
    e.stopPropagation();
  });

  window.addEventListener('mousemove', (e: MouseEvent) => {
    if (!state._scrubbing) return;
    scrubTo(e.clientX);
  });

  window.addEventListener('mouseup', () => {
    if (!state._scrubbing) return;
    state._scrubbing = false;
    // Re-enable smooth CSS transitions
    thumb.style.transition = '';
    const fill = document.getElementById('tl-fill');
    if (fill) fill.style.transition = '';
  });
}
