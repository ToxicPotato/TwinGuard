// liveMode.ts - WebSocket connection and live frame buffering.

import { state } from './state';
import { updateRoadBuffer, initRoadBuffers } from './render/drawRoad';
import { updateAlignment, initAlignment } from './render/alignment';
import { clearPanels, rebuildPanel } from './panel';
import {
  recordStateTransition,
  clearTransitionCache,
  shiftTransitionCache,
} from './render/drawTrail';
import { robotFrame, TRIM_BATCH_RATIO } from './constants';

let _draw = () => {};
export function setLiveModeDrawCallback(fn: () => void) { _draw = fn; }

let _updateUI = () => {};
export function setLiveModeUpdateUICallback(fn: () => void) { _updateUI = fn; }

type LiveFrameEnvelope = {
  session_id: string;
  frame_id: number;
  data: any;
};

type FrameProcessOptions = {
  render?: boolean;
};

// Last known state per robot — persists across single-frame gaps so a
// transiently absent robot that reappears in the same state does not produce
// a spurious transition marker.
const _liveLastKnownSt = new Map<string, number>();

let _bootstrappingSnapshot = false;
let _pendingLiveEnvelopes: LiveFrameEnvelope[] = [];
let _liveBootstrapRequestId = 0;
let _bootstrappingPreview = false;
let _bootstrapSessionFenceId: string | null = null;
const LIVE_BOOTSTRAP_TIMEOUT_MS = 1500;

function _resetTransportUi() {
  state.fi = 0;
  state.accumT = 0;
  state.playing = false;
  state.lastTs = null;
  const playBtn = document.getElementById('pbplay');
  if (playBtn) {
    playBtn.innerHTML = '&#x25B6;';
    playBtn.classList.remove('on');
  }
}

function _ensureLiveRun(robots: string[], liveHz: number) {
  state.RUNS[state.LIVE_RUN] = {
    frames: state.liveFrameBuffer,
    meta: {
      sheet: state.LIVE_RUN,
      robots,
      duration: Infinity,
      dt: 1.0 / liveHz,
      twin: {},
      comparison: {},
    },
  };

  state.roadBuffer[state.LIVE_RUN] = state.roadBuffer[state.LIVE_RUN] ?? {};
  state.SIM = state.RUNS[state.LIVE_RUN];
}

function _resetLiveSessionState(robots: string[] = [], liveHz = 20) {
  state.liveLastFrameId = 0;
  state._liveStartT = null;
  state.liveFrameBuffer.length = 0;
  clearTransitionCache();
  _liveLastKnownSt.clear();
  state.roadBuffer[state.LIVE_RUN] = {};
  state.curvatureScale[state.LIVE_RUN] = undefined;
  state.alignmentState[state.LIVE_RUN] = {};
  state.globalRoadMap[state.LIVE_RUN] = [];
  state._globalMapIdx[state.LIVE_RUN] = {};
  // Clear any stale per-session camera target so draw() does not keep trying
  // to follow a robot id or leader choice from the previous session.
  state.cameraTarget = null;
  state.focusRobotId = null;
  document.getElementById('btn-track')?.removeAttribute('disabled');
  const trkLbl = document.getElementById('track-target-lbl');
  if (trkLbl) trkLbl.textContent = 'ALL';
  _ensureLiveRun(robots, liveHz);
  clearPanels();
  rebuildPanel();
  initRoadBuffers(state.SIM.meta.sheet);
  initAlignment(state.SIM.meta.sheet);
}

export function enterLiveMode(wsUrl: string) {
  if (!state.RUNS) state.RUNS = {};

  if (state.liveSocket) {
    state.liveSocket.onmessage = null;
    state.liveSocket.onclose = null;
    state.liveSocket.onerror = null;
    state.liveSocket.close();
  }

  state.liveMode = true;
  state.liveSessionId = null;
  state.liveLastFrameId = 0;
  state._liveStartT = null;
  state.liveFrameBuffer.length = 0;
  state.focusRobotId = null;
  state.cameraTarget = null;
  document.getElementById('btn-track')?.removeAttribute('disabled');
  const trkLbl = document.getElementById('track-target-lbl');
  if (trkLbl) trkLbl.textContent = 'ALL';
  _setLiveBadge(true);
  _setConnStatus('connecting');

  state.liveSocket = new WebSocket(wsUrl);
  state.liveSocket.onopen = _onOpen;
  state.liveSocket.onmessage = _onMessage;
  state.liveSocket.onerror = _onError;
  state.liveSocket.onclose = _onClose;
}

export function exitLiveMode() {
  state.liveMode = false;
  if (state.liveSocket) { state.liveSocket.close(); state.liveSocket = null; }

  _liveBootstrapRequestId += 1;
  _bootstrappingSnapshot = false;
  _bootstrappingPreview = false;
  _bootstrapSessionFenceId = null;
  _pendingLiveEnvelopes = [];
  _setLiveBadge(false);
  state.liveSessionId = null;
  state.liveLastFrameId = 0;
  state._liveStartT = null;
  state.focusRobotId = null;
  state.cameraTarget = null;
  document.getElementById('btn-track')?.removeAttribute('disabled');
  const trkLbl = document.getElementById('track-target-lbl');
  if (trkLbl) trkLbl.textContent = 'ALL';

  const isWebSocketRun = state.RUNS[state.LIVE_RUN]?.frames === state.liveFrameBuffer;
  if (isWebSocketRun) delete state.RUNS[state.LIVE_RUN];
  state.liveFrameBuffer.length = 0;

  clearPanels();

  const sel = document.getElementById('run-sel') as HTMLSelectElement | null;
  sel?.querySelector(`option[value="${state.LIVE_RUN}"][data-live-ws]`)?.remove();

  const replayKeys = Object.keys(state.RUNS);
  const restore =
    (sel && sel.value !== state.LIVE_RUN && state.RUNS[sel.value])
      ? sel.value
      : replayKeys[0];

  state.SIM = restore ? state.RUNS[restore] : null;
  if (restore && sel) sel.value = restore;

  _resetTransportUi();
  const totEl = document.getElementById('tl-tot');
  const curEl = document.getElementById('tl-cur');
  const fctEl = document.getElementById('fctr');
  const htEl = document.getElementById('htime');

  if (state.SIM) {
    rebuildPanel();
    initRoadBuffers(state.SIM.meta.sheet);
    initAlignment(state.SIM.meta.sheet);
    if (totEl) totEl.textContent = state.SIM.meta.duration.toFixed(3) + ' s';
    _draw();
    _updateUI();
  } else {
    if (totEl) totEl.textContent = '- s';
    if (curEl) curEl.textContent = '0.000 s';
    if (fctEl) fctEl.textContent = '0 / 0';
    if (htEl) htEl.textContent = '0.000 s';
    document.getElementById('tl-fill')?.style.setProperty('width', '0%');
    document.getElementById('tl-thumb')?.style.setProperty('left', '0%');
  }

  window.dispatchEvent(new CustomEvent('tg:replaystate', {
    detail: { hasRuns: replayKeys.length > 0 },
  }));
}

function _onOpen() {
  console.log('[live] connected');
  _setConnStatus('connected');
}

function _onError(e: Event) {
  console.warn('[live] WebSocket error', e);
  _setConnStatus('disconnected');
}

function _onClose() {
  console.log('[live] disconnected');
  _setConnStatus('disconnected');
  if (state.liveMode) exitLiveMode();
}

function _onMessage(event: MessageEvent<string>) {
  let msg: any;
  try { msg = JSON.parse(event.data); } catch { return; }

  if (msg.type === 'meta') { _handleMeta(msg); return; }
  if (msg.type === 'config') { _handleConfig(msg.data); return; }
  if (msg.type === 'frame') { _handleFrameEnvelope(msg.data); }
}

function _handleMeta(msg: any) {
  const robots = msg.robots || [];
  const liveHz = msg.live_hz ?? 20.0;
  const incomingSessionId = msg.session_id ?? null;
  const sessionChanged = incomingSessionId !== state.liveSessionId;

  if (_bootstrappingSnapshot && incomingSessionId) {
    _bootstrapSessionFenceId = incomingSessionId;
  }

  _setConnStatus(msg.connected === false ? 'disconnected' : 'connected');

  if (sessionChanged) {
    state.liveSessionId = incomingSessionId;
    _resetLiveSessionState(robots, liveHz);
  } else {
    if (!state.RUNS) state.RUNS = {};
    _ensureLiveRun(robots, liveHz);
  }

  const sel = document.getElementById('run-sel') as HTMLSelectElement | null;
  if (sel && !sel.querySelector(`option[value="${state.LIVE_RUN}"][data-live-ws]`)) {
    const opt = document.createElement('option');
    opt.value = state.LIVE_RUN;
    opt.textContent = 'LIVE';
    opt.dataset.liveWs = 'true';
    sel.appendChild(opt);
  }
  if (sel) sel.value = state.LIVE_RUN;

  if (sessionChanged || state.liveFrameBuffer.length === 0) {
    _resetTransportUi();
  }
  if (!sessionChanged) {
    rebuildPanel();
    initRoadBuffers(state.SIM.meta.sheet);
    initAlignment(state.SIM.meta.sheet);
  }
  const totEl = document.getElementById('tl-tot');
  if (totEl) totEl.textContent = state.LIVE_BUFFER_MAX + ' fr max';
  _draw();
  _updateUI();
}

function _handleConfig(config: any) {
  if (!config) return;
  window.dispatchEvent(new CustomEvent('tg:mqttconfig', { detail: config }));
}

function _renderLiveUi(frame: any) {
  const htEl = document.getElementById('htime');
  if (htEl) {
    const elapsed = frame && state._liveStartT !== null ? frame.t - state._liveStartT : 0;
    htEl.textContent = elapsed.toFixed(3) + ' s';
  }
  // draw() / updateUI() are called every RAF tick by the loop in main.ts;
  // no explicit trigger needed here.
}

function _appendLiveFrame(frame: any, options: FrameProcessOptions = {}) {
  if (!frame || !state.RUNS[state.LIVE_RUN]) return;
  const render = options.render ?? true;

  if (state.liveFrameBuffer.length === 0) {
    state._liveStartT = frame.t;
  }

  const knownRobots = state.RUNS[state.LIVE_RUN].meta.robots;
  Object.keys(frame.robots || {}).forEach((rid) => {
    if (!knownRobots.includes(rid)) {
      knownRobots.push(rid);
      if (render) rebuildPanel();
    }
  });

  state.liveFrameBuffer.push(frame);
  if (state.liveFrameBuffer.length > state.LIVE_BUFFER_MAX) {
    const trimCount = Math.max(1, Math.floor(state.LIVE_BUFFER_MAX * TRIM_BATCH_RATIO));
    state.liveFrameBuffer.splice(0, trimCount);
    // Keep transition and trail-start caches aligned after buffer shift.
    shiftTransitionCache(trimCount);
  }

  // Record any state transitions in this frame (O(robots), not O(frames)).
  // _liveLastKnownSt tracks each robot's last seen state across frame gaps so
  // a transiently absent robot that reappears in the same state does not
  // produce a spurious marker.
  const fi = state.liveFrameBuffer.length - 1;
  for (const rid of knownRobots) {
    const cur = robotFrame(frame, rid);
    if (!cur) continue;
    const lastSt = _liveLastKnownSt.get(rid);
    if (lastSt !== undefined && cur.st !== lastSt) {
      recordStateTransition(rid, fi, cur.x, cur.y, cur.st);
    }
    _liveLastKnownSt.set(rid, cur.st);
  }

  updateRoadBuffer(state.LIVE_RUN, frame);
  updateAlignment(state.LIVE_RUN, frame, state.liveFrameBuffer.length - 1);

  state.fi = state.liveFrameBuffer.length - 1;

  if (render) _renderLiveUi(frame);
}

function _processFrameEnvelope(envelope: LiveFrameEnvelope, options: FrameProcessOptions = {}) {
  if (!envelope?.data) return;

  if (envelope.session_id && state.liveSessionId && envelope.session_id !== state.liveSessionId) {
    state.liveSessionId = envelope.session_id;
    _resetLiveSessionState(
      Object.keys(envelope.data?.robots || {}),
      state.RUNS[state.LIVE_RUN]?.meta?.dt ? 1 / state.RUNS[state.LIVE_RUN].meta.dt : 20,
    );
  }
  if (envelope.session_id && !state.liveSessionId) {
    state.liveSessionId = envelope.session_id;
  }
  if (envelope.frame_id <= (state.liveLastFrameId ?? 0)) {
    return;
  }

  state.liveLastFrameId = envelope.frame_id;
  _appendLiveFrame(envelope.data, options);
}

function _handleFrameEnvelope(envelope: LiveFrameEnvelope) {
  if (_bootstrappingSnapshot) {
    if (!_bootstrapSessionFenceId && envelope?.session_id) {
      _bootstrapSessionFenceId = envelope.session_id;
    }
    _pendingLiveEnvelopes.push(envelope);
    if (_bootstrappingPreview) {
      _processFrameEnvelope(envelope);
    }
    return;
  }
  _processFrameEnvelope(envelope);
}

function _applySnapshot(snapshot: any) {
  const snapshotSessionId = snapshot.session_id ?? null;
  const robots = snapshot.robots || [];
  const liveHz = snapshot.live_hz ?? 20.0;
  if (_bootstrapSessionFenceId && snapshotSessionId && snapshotSessionId !== _bootstrapSessionFenceId) {
    return;
  }
  const sessionChanged = snapshotSessionId !== state.liveSessionId;
  const shouldResetForSnapshot = sessionChanged || _bootstrappingPreview;

  if (shouldResetForSnapshot) {
    _resetLiveSessionState(robots, liveHz);
  } else {
    _ensureLiveRun(robots, liveHz);
  }
  state.liveSessionId = snapshotSessionId;

  const frames = Array.isArray(snapshot.frames) ? snapshot.frames : [];
  for (const envelope of frames) {
    _processFrameEnvelope(envelope, { render: false });
  }
  if (frames.length > 0) {
    rebuildPanel();
    _renderLiveUi(frames[frames.length - 1]?.data);
  }
}

function _flushPendingLiveEnvelopes() {
  const pending = _pendingLiveEnvelopes;
  _pendingLiveEnvelopes = [];
  const acceptedSessionId = state.liveSessionId;
  for (const envelope of pending) {
    if (acceptedSessionId && envelope.session_id && envelope.session_id !== acceptedSessionId) {
      continue;
    }
    _processFrameEnvelope(envelope);
  }
}

export async function startLive() {
  const bootstrapRequestId = ++_liveBootstrapRequestId;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${proto}//${location.host}/ws/live`;
  enterLiveMode(wsUrl);
  _bootstrappingSnapshot = true;
  _bootstrappingPreview = false;
  _bootstrapSessionFenceId = null;
  _pendingLiveEnvelopes = [];
  const timeoutId = window.setTimeout(() => {
    if (bootstrapRequestId !== _liveBootstrapRequestId || !_bootstrappingSnapshot || !state.liveMode) return;
    _bootstrappingPreview = true;
    for (const envelope of _pendingLiveEnvelopes) {
      _processFrameEnvelope(envelope);
    }
  }, LIVE_BOOTSTRAP_TIMEOUT_MS);

  try {
    const res = await fetch(`/api/live/buffer?limit=${encodeURIComponent(String(state.LIVE_BUFFER_MAX))}`);
    if (bootstrapRequestId !== _liveBootstrapRequestId || !res.ok || !state.liveMode) return;
    const snapshot = await res.json();
    if (bootstrapRequestId !== _liveBootstrapRequestId || !state.liveMode) return;
    _applySnapshot(snapshot);
  } catch (e) {
    if (bootstrapRequestId === _liveBootstrapRequestId) {
      console.warn('[live] bootstrap failed', e);
    }
  } finally {
    window.clearTimeout(timeoutId);
    if (bootstrapRequestId !== _liveBootstrapRequestId) return;
    _bootstrappingSnapshot = false;
    _bootstrappingPreview = false;
    _bootstrapSessionFenceId = null;
    if (state.liveMode) {
      _flushPendingLiveEnvelopes();
    } else {
      _pendingLiveEnvelopes = [];
    }
  }
}

function _setLiveBadge(active: boolean) {
  document.body.classList.toggle('live-mode', active);
  window.dispatchEvent(new CustomEvent('tg:modechange', { detail: { liveMode: active } }));
}

function _setConnStatus(status: 'connecting' | 'connected' | 'disconnected') {
  window.dispatchEvent(new CustomEvent('tg:connstatus', { detail: { status } }));
}

export function liveReconnect() {
  if (state.liveSocket) {
    state.liveSocket.onmessage = null;
    state.liveSocket.onclose = null;
    state.liveSocket.onerror = null;
  }
  void startLive();
}
