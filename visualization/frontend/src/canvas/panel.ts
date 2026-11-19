import { state } from './state';
import { PALETTE } from './constants';
import { initRoadBuffers } from './render/drawRoad';
import { initAlignment } from './render/alignment';
import { buildRobotCardsPanel, buildRobotCardTimelines, updateRobotCardsPanel } from './panels/robotCardsPanel';
import { clearCardRefs } from './panels/robotCard';
import { updateHeaderTwinStatus } from './panels/headerTwinStatus';
import { buildTwinCardsPanel, setTwinRobotTab, updateTwinCardsPanel } from './panels/twinCardsPanel';
import { updateTimeline } from './panels/timeline';
import { chainComponents, robotLabel } from './panels/shared';
import { buildArenaLegend } from './panels/arenaLegend';
import { buildTransitionCacheFromFrames, getTransitionCacheGeneration } from './render/drawTrail';

const previousStates: Record<string, number | undefined> = {};

// Guard for the replay transition cache — rebuilt only when the run changes
// or after a live-mode session clears it.  Avoids the O(frames × robots) scan
// on every rebuildPanel() call triggered by focus changes or sort changes.
let _transitionCacheBuiltForSim: any = null;
let _transitionCacheBuiltAtGen  = -1;

// Cache for stable layout elements that are never rebuilt by rebuildPanel().
// Queried lazily on first access so they're safe to cache across sessions.
const _elCache: Record<string, HTMLElement | null> = {};
function _el(id: string): HTMLElement | null {
  if (!(id in _elCache)) _elCache[id] = document.getElementById(id);
  return _elCache[id];
}

let onStateTransition = (_id: string, _toSt: number) => {};
export function setSfxTransitionCallback(fn: (id: string, toSt: number) => void) { onStateTransition = fn; }

let updateMusicReactive = (_frame: any) => {};
export function setUpdateMusicReactiveCallback(fn: (frame: any) => void) { updateMusicReactive = fn; }

let setFocusRobot = (_id: string | null) => {};
export function setFocusRobotCallback(fn: (id: string | null) => void) { setFocusRobot = fn; }

let toggleRobotVisibility = (_id: string) => {};
export function setToggleRobotVisCallback(fn: (id: string) => void) { toggleRobotVisibility = fn; }

export function buildRunSelector() {
  const select = document.getElementById('run-sel');
  if (!select) return;

  select.innerHTML = '';
  Object.keys(state.RUNS).forEach(name => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  });

  select.onchange = () => {
    state.SIM = state.RUNS[select.value];
    state.fi = 0;
    state.accumT = 0;
    state.playing = false;
    state.lastTs = null;
    state.focusRobotId = null;
    state.cameraTarget = null;
    document.getElementById('btn-track')?.removeAttribute('disabled');
    const trackLbl = document.getElementById('track-target-lbl');
    if (trackLbl) trackLbl.textContent = 'ALL';

    const playButton = document.getElementById('pbplay');
    if (playButton) {
      playButton.innerHTML = '&#x25B6;';
      playButton.classList.remove('on');
    }

    const totalLabel = document.getElementById('tl-tot');
    if (totalLabel && state.SIM) totalLabel.textContent = state.SIM.meta.duration.toFixed(3) + ' s';

    rebuildPanel();
    initRoadBuffers(state.SIM.meta.sheet);
    initAlignment(state.SIM.meta.sheet);
  };

  const firstKey = Object.keys(state.RUNS)[0];
  state.SIM = firstKey ? state.RUNS[firstKey] : null;
  if (firstKey) select.value = firstKey;
}

function panelRobotIds() {
  // Return the original array — callers only read it (computeSortedIds makes
  // its own copy before sorting, updateRobotCardsPanel/updateTwinCardsPanel only forEach).
  return state.focusRobotId ? [state.focusRobotId] : (state.SIM ? state.SIM.meta.robots : []);
}

export function clearPanels() {
  const robotCardsPanel = document.getElementById('robot-cards-panel');
  const twinCardsPanel = document.getElementById('twin-cards-panel');
  const arenaLegend = document.getElementById('arena-legend');
  const tabBar = document.getElementById('tab-bar');

  if (robotCardsPanel) robotCardsPanel.innerHTML = '';
  if (twinCardsPanel) twinCardsPanel.innerHTML = '';
  if (arenaLegend) arenaLegend.innerHTML = '';
  if (tabBar) tabBar.innerHTML = '';

  // Invalidate robot card element ref cache — elements are now detached.
  clearCardRefs();
}

export function rebuildPanel() {
  clearPanels();
  buildPanel();
  requestAnimationFrame(() => buildRobotCardTimelines(panelRobotIds()));
}


export function buildTabBar() {
  const bar = document.getElementById('tab-bar');
  if (!bar || !state.SIM) return;

  const allButton = document.createElement('button');
  allButton.className = 'tab-btn' + (state.focusRobotId === null ? ' active' : '');
  allButton.dataset.rid = '';
  allButton.textContent = 'ALL';
  allButton.onclick = () => setFocusRobot(null);
  bar.appendChild(allButton);

  state.SIM.meta.robots.forEach((id, index) => {
    const color = PALETTE[index % PALETTE.length];
    const isActive = state.focusRobotId === id;
    const button = document.createElement('button');
    button.className = 'tab-btn' + (isActive ? ' active' : '');
    button.dataset.rid = id;
    button.textContent = robotLabel(id);
    button.style.borderColor = isActive ? color : '';
    button.style.color = isActive ? color : '';
    button.onclick = () => setFocusRobot(id);
    bar.appendChild(button);
  });
}

export function buildPanel() {
  if (!state.SIM) return;

  // Build state-transition cache once per run load so drawStateTransitions()
  // is O(k) per draw instead of O(n frames). Live mode populates it incrementally.
  // Skip the rebuild when the same SIM is still current and the cache hasn't
  // been invalidated — avoids the O(frames × robots) scan on every
  // rebuildPanel() call triggered by focus changes or sort changes.
  if (!state.liveMode) {
    const gen = getTransitionCacheGeneration();
    if (state.SIM !== _transitionCacheBuiltForSim || gen !== _transitionCacheBuiltAtGen) {
      buildTransitionCacheFromFrames(state.SIM.frames, state.SIM.meta.robots);
      _transitionCacheBuiltForSim = state.SIM;
      _transitionCacheBuiltAtGen  = getTransitionCacheGeneration();
    }
  }

  const robotCardsPanel = document.getElementById('robot-cards-panel');
  const twinCardsPanel = document.getElementById('twin-cards-panel');
  if (!robotCardsPanel || !twinCardsPanel) return;

  const robotIds = panelRobotIds();
  buildArenaLegend();

  buildRobotCardsPanel({
    container: robotCardsPanel,
    robotIds,
    palette: PALETTE,
    focusedRobotId: state.focusRobotId,
    hiddenRobots: state.hiddenRobots,
    onToggleVisibility: toggleRobotVisibility,
    onSortChange: rebuildPanel,
  });

  buildTwinCardsPanel({
    container: twinCardsPanel,
    robotIds,
    palette: PALETTE,
    focusedRobotId: state.focusRobotId,
    onTabChange: setTwinRobotTab,
  });

  buildTabBar();
}

export function updateUI() {
  if (!state.SIM) return;

  const frame = state.SIM.frames[state.fi];
  if (!frame) {
    if (state.liveMode) {
      _el('tl-fill')?.style.setProperty('width', '0%');
      _el('tl-thumb')?.style.setProperty('left', '0%');
      const elCur0  = _el('tl-cur');  if (elCur0)  elCur0.textContent  = '0 frames';
      const elFctr0 = _el('fctr');    if (elFctr0) elFctr0.textContent = 'FRAME 0';
      const elHt0   = _el('htime');   if (elHt0)   elHt0.textContent   = '0.000 s';
    }
    return;
  }

  const elFill  = _el('tl-fill');
  const elThumb = _el('tl-thumb');
  const elCur   = _el('tl-cur');
  const elFctr  = _el('fctr');
  const elHtime = _el('htime');

  if (state.liveMode) {
    const percent = state.SIM.frames.length > 0
      ? Math.min(100, (state.SIM.frames.length / state.LIVE_BUFFER_MAX) * 100)
      : 0;
    if (elFill)  elFill.style.width  = percent + '%';
    if (elThumb) elThumb.style.left  = percent + '%';
    if (elCur)   elCur.textContent   = state.SIM.frames.length + ' frames';
    if (elFctr)  elFctr.textContent  = 'FRAME ' + state.SIM.frames.length;
  } else {
    const progress = state.SIM.frames.length > 1 ? state.fi / (state.SIM.frames.length - 1) : 0;
    if (elHtime) elHtime.textContent = frame.t.toFixed(3) + ' s';
    if (elFill)  elFill.style.width  = (progress * 100) + '%';
    if (elThumb) elThumb.style.left  = (progress * 100) + '%';
    if (elCur)   elCur.textContent   = frame.t.toFixed(3) + ' s';
    if (elFctr)  elFctr.textContent  = 'FRAME ' + (state.fi + 1) + ' / ' + state.SIM.frames.length;
  }

  const robotIds = panelRobotIds();

  // Build a component-local chain index so each robot shows its position
  // within its own platoon (1-based), not a flat cross-platoon index.
  const chainIndexMap: Record<string, number> = {};
  chainComponents(frame).forEach(component => {
    component.forEach((id, idx) => { chainIndexMap[id] = idx + 1; });
  });

  const focusSummary = updateTwinCardsPanel({ frame, robotIds });
  updateHeaderTwinStatus(frame, focusSummary);

  updateRobotCardsPanel({
    robotIds,
    frame,
    chainIndexMap,
    previousStates,
    isPlaying: state.playing,
    isScrubbing: state._scrubbing,
    onTransition: onStateTransition,
    updateTimeline,
  });

  updateMusicReactive(frame);
}
