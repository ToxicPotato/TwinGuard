// ─────────────────────────────────────────────────────────────────────────────
// main.ts — Layer state, main draw function, animation loop,
//           robot visibility, and canvas initialisation.
// ─────────────────────────────────────────────────────────────────────────────

import { state } from './state';
import { PALETTE, robotFrame } from './constants';
import { initCamera, setDrawCallback, setUpdateUICallback } from './camera';
import { initScrubber, setDrawCallback as setPbDrawCallback, setUpdateUICallback as setPbUpdateUICallback, setSfxUICallback, setSfxScrubTickCallback } from './playback';
import { drawGrid, drawRobotRoad, initRoadBuffers } from './render/drawRoad';
import { drawGlobalCanvas } from './render/drawGlobal';
import { drawRobot, drawGhostRobot, drawVelocityVector } from './render/drawRobot';
import { drawSensorOverlay } from './render/drawSensors';
import { drawScenarioOverlayLocal, drawScenarioOverlaysGlobal } from './render/drawScenarios';
import { drawTrail, drawStateTransitions, drawPlatoonLinks, drawStateLegend } from './render/drawTrail';
import { initAlignment } from './render/alignment';
import {
  buildRunSelector, rebuildPanel, buildPanel, updateUI, clearPanels,
  setSfxTransitionCallback, setUpdateMusicReactiveCallback,
  setFocusRobotCallback, setToggleRobotVisCallback,
} from './panel';
import { buildTimeline } from './panels/timeline';
import { chainComponents, robotLabel } from './panels/shared';
import { sfxResume, sfxUI, sfxScrubTick, sfxTransition, updateMusicReactive } from './audio';
import {
  exitLiveMode,
  setLiveModeDrawCallback, setLiveModeUpdateUICallback,
} from './liveMode';


// ── Simulation data ───────────────────────────────────────────────────────────

/**
 * Called after a successful post-init upload.
 * Switches out of live mode, loads the new runs, and rebuilds all UI.
 */
export function activateRuns(runs: any) {
  state.RUNS = runs;
  // Exit live mode so the replay transport becomes active
  if (state.liveMode) exitLiveMode();

  const runCount = Object.keys(runs).length;

  if (runCount > 0) {
    // Rebuild run selector — sets state.SIM to the first run
    buildRunSelector();
    // Rebuild panel after loading runs (covers replay→replay where exitLiveMode is skipped)
    if (state.SIM) {
      state.fi = 0; state.accumT = 0; state.playing = false; state.lastTs = null;
      state.focusRobotId = null;
      state.cameraTarget = null;
      const pbPlay = document.getElementById('pbplay');
      if (pbPlay) { pbPlay.innerHTML = '&#x25B6;'; pbPlay.classList.remove('on'); }
      document.getElementById('btn-track')?.removeAttribute('disabled');
      const trackLbl = document.getElementById('track-target-lbl');
      if (trackLbl) trackLbl.textContent = 'ALL';
      rebuildPanel();
      initRoadBuffers(state.SIM.meta.sheet);
      initAlignment(state.SIM.meta.sheet);
      const totEl = document.getElementById('tl-tot');
      if (totEl) totEl.textContent = state.SIM.meta.duration.toFixed(3) + ' s';
    }
  } else {
    // Empty upload — tear down replay UI so no stale state persists under the overlay.
    state.SIM = null;
    state.focusRobotId = null;
    state.cameraTarget = null;
    document.getElementById('btn-track')?.removeAttribute('disabled');
    const _trkLblEU = document.getElementById('track-target-lbl');
    if (_trkLblEU) _trkLblEU.textContent = 'ALL';
    clearPanels();
    const sel = document.getElementById('run-sel');
    if (sel) sel.innerHTML = '';
    state.fi = 0; state.accumT = 0; state.playing = false; state.lastTs = null;
    const pbPlay  = document.getElementById('pbplay');
    if (pbPlay)  { pbPlay.innerHTML = '&#x25B6;'; pbPlay.classList.remove('on'); }
    const totEl2 = document.getElementById('tl-tot'); if (totEl2) totEl2.textContent = '— s';
    const curEl2 = document.getElementById('tl-cur'); if (curEl2) curEl2.textContent = '0.000 s';
    const fctEl2 = document.getElementById('fctr');   if (fctEl2) fctEl2.textContent = '0 / 0';
    document.getElementById('tl-fill')?.style.setProperty('width', '0%');
    document.getElementById('tl-thumb')?.style.setProperty('left', '0%');
    // Reset header twin pills to defaults so stale scores don't persist under the overlay.
    const _t = (id: string, v: string) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    _t('tw-low-score',  '--');  _t('tw-low-sub',    'components');
    _t('tw-high-score', '--');  _t('tw-high-sub',   'components');
    _t('tw-timing-val', '-- / --');
  }

  // Notify Svelte so it can show/hide the empty-replay overlay.
  window.dispatchEvent(new CustomEvent('tg:replaystate', { detail: { hasRuns: runCount > 0 } }));
}


// ── Local robot view ──────────────────────────────────────────────────────────

/**
 * Switch between global view (id = null) and per-robot local view.
 * Updates the tab bar button styles and resets camera-follow.
 *
 * @param {string|null} id  Robot ID, or null for the global ALL view.
 */
export function setFocusRobot(id) {
  state.focusRobotId = id;

  // Highlight the active tab; colour the robot tabs with their palette colour
  document.querySelectorAll('.tab-btn').forEach(btn => {
    const rid = btn.dataset.rid || '';
    const isActive = rid === (id || '');
    btn.classList.toggle('active', isActive);
    // Re-apply colour only to robot tabs (not the ALL tab)
    if (rid && state.SIM) {
      const idx = state.SIM.meta.robots.indexOf(rid);
      const col = idx >= 0 ? PALETTE[idx % PALETTE.length] : '';
      btn.style.borderColor = isActive ? col : '';
      btn.style.color       = isActive ? col : '';
    }
  });

  // Enable camera follow so it locks onto the selected robot immediately
  if (id) {
    state.cameraFollow = true;
    document.getElementById('btn-follow')?.classList.add('on');
  }

  // Reflect isolation mode in the TRACK button: show LOCAL while focused,
  // restore the actual target label when returning to global view.
  const trackBtn = document.getElementById('btn-track');
  const trackLbl = document.getElementById('track-target-lbl');
  if (trackBtn) trackBtn.toggleAttribute('disabled', !!id);
  if (trackLbl) trackLbl.textContent = id ? 'LOCAL' : trackTargetLabel();

  if (state.SIM) {
    rebuildPanel();
    if (state.liveMode) { draw(); updateUI(); }
  }
}


// ── Camera follow target ──────────────────────────────────────────────────────

/**
 * Cycle the global-view follow target through the available options:
 *   null (centroid) → 'leader' → rob1 → rob2 → ... → null
 *
 * No-ops when in isolation mode (focusRobotId is set), since local view
 * always follows the focused robot.
 */
export function cycleTrackTarget(): void {
  if (state.focusRobotId || !state.SIM) return;

  // All robots are offered as targets — the follow logic tracks hidden robots
  // too (hide is a rendering choice, not a camera choice). Excluding hidden
  // robots here would make per-robot tracking unavailable after any hide.
  const options: (string | null)[] = [null, 'leader', ...(state.SIM.meta.robots as string[])];
  const cur = options.indexOf(state.cameraTarget);
  state.cameraTarget = options[(cur + 1) % options.length] ?? null;

  // Ensure follow is on so the new target takes effect immediately
  state.cameraFollow = true;
  document.getElementById('btn-follow')?.classList.add('on');

  const lbl = document.getElementById('track-target-lbl');
  if (lbl) lbl.textContent = trackTargetLabel();
}

/** Human-readable label for the current cameraTarget value. */
export function trackTargetLabel(): string {
  if (!state.cameraTarget) return 'ALL';
  if (state.cameraTarget === 'leader') return 'LEAD';
  return robotLabel(state.cameraTarget, true);
}


// ── Layer visibility ──────────────────────────────────────────────────────────

/**
 * Toggle a layer on/off and update the corresponding button style.
 * Called by onclick handlers on the layer buttons in the footer.
 *
 * @param {string} key    Key in LAYERS, e.g. 'trail'
 * @param {string} btnId  ID of the button element, e.g. 'btn-trail'
 */
export function toggle(key, btnId) {
  state.LAYERS[key] = !state.LAYERS[key];
  document.getElementById(btnId).classList.toggle('on', state.LAYERS[key]);
  if (state.liveMode) draw();
}


// ── Robot visibility ──────────────────────────────────────────────────────────

/**
 * Toggle a robot's visibility on the canvas.
 * When hidden the robot is excluded from all draw calls and the follow-mode
 * centroid calculation.
 *
 * @param {string} id  Robot ID
 */
export function toggleRobotVis(id) {
  if (state.hiddenRobots.has(id)) {
    state.hiddenRobots.delete(id);
    document.getElementById(id + '-vis').classList.add('on');
  } else {
    state.hiddenRobots.add(id);
    document.getElementById(id + '-vis').classList.remove('on');
  }
  if (state.liveMode) draw();
}


// ── Main draw function ────────────────────────────────────────────────────────

/**
 * Render one frame of the visualisation.
 *
 * Two modes depending on focusRobotId:
 *
 * GLOBAL VIEW (focusRobotId === null)  — original multi-robot render:
 *   1. Background fill + metric grid
 *   2. Road per robot (progressive reveal, curvature heatmap)
 *   3. Ghost robots  (layer: ghost)
 *   4. Platoon links (layer: links)
 *   5. Sensor overlays per robot (layer: sensors)
 *   6. Trail + state-transition markers per robot (layer: trail)
 *   7. Velocity arrows + robot bodies (rear-to-front)
 *   8. State legend
 *
 * LOCAL VIEW (focusRobotId set)  — single-robot focused render:
 *   1. Background fill + metric grid
 *   2. Road in full (state-coloured past + curvature-ahead preview)
 *   3. Ghost ALWAYS drawn (reference pose)
 *   4. Trail + state-transition markers (layer: trail)
 *   5. Sensor overlays (layer: sensors)
 *   6. Velocity arrow + robot body
 *   7. State legend + local HUD overlay
 */
export function draw() {
  if (!state.W || !state.H || !state.SIM) return;

  // ── Clear ───────────────────────────────────────────────────────────────────
  state.cx.fillStyle = '#050810';
  state.cx.fillRect(0, 0, state.W, state.H);

  const fr = state.SIM.frames[state.fi];
  if (!fr) return;
  const components = chainComponents(fr);

  if (state.focusRobotId) {
    // ════════════════════════════════════════════════════════════════════════
    // LOCAL VIEW — show only the focused robot in its own coordinate frame
    // ════════════════════════════════════════════════════════════════════════
    const r   = robotFrame(fr, state.focusRobotId);
    if (!r) return;
    const idx = state.SIM.meta.robots.indexOf(state.focusRobotId);
    const col = PALETTE[idx % PALETTE.length];

    // Camera always follows the focused robot
    if (state.cameraFollow) {
      state.vx = r.x;
      state.vy = r.y;
    }

    drawGrid();

    // Road — state-coloured past + full ahead preview
    const buf = (state.roadBuffer[state.SIM.meta.sheet] || {})[state.focusRobotId];
    if (buf && buf.length >= 2) {
      drawRobotRoad(buf, r, col, state.focusRobotId);
    }

    // Ghost always shown in local view (not gated by LAYERS.ghost)
    drawGhostRobot(r, col);

    // Trail + state-transition markers
    if (state.LAYERS.trail) {
      drawTrail(state.fi, state.focusRobotId);
      drawStateTransitions(state.fi, state.focusRobotId);
    }

    if (state.LAYERS.sensors) {
      drawSensorOverlay(r, col, fr);
    }

    // Velocity arrow and robot body
    drawVelocityVector(r, col);
    drawRobot(r, col, robotLabel(state.focusRobotId));

    // Scenario overlays
    drawScenarioOverlayLocal(fr, state.focusRobotId, r);

    // State legend
    drawStateLegend();

  } else {
    // ════════════════════════════════════════════════════════════════════════
    // GLOBAL VIEW — all robots rendered; camera target driven by cameraTarget
    // ════════════════════════════════════════════════════════════════════════

    // Follow mode: track the selected target.
    if (state.cameraFollow) {
      const target = state.cameraTarget;
      if (target === 'leader') {
        // Two-path leader selection depending on whether the frame carries
        // a backend platoon assessment:
        //
        // ASSESSED: Use components[0][0] — the head of the first platoon in
        //   the backend's emission order (road-topology-aware). Visibility
        //   is a rendering choice and does not change who the lead robot is.
        //
        // FALLBACK (no assessment data): chainComponents() returns all
        //   meta.robots in one synthetic component so component[0] is just
        //   metadata insertion order — not road order. World X is the only
        //   available heuristic; scan all visible robots.
        const hasAssessment = Array.isArray(fr.low_res?.platoon?.assessment?.components)
          && (fr.low_res.platoon.assessment.components as any[]).length > 0;

        let leaderId: string | null = null;
        if (hasAssessment) {
          // Take the first component's head unconditionally — hiding is a
          // rendering choice and does not change who the lead robot is.
          // Consistent with explicit robot tracking which also ignores visibility.
          leaderId = components[0]?.[0] ?? null;
        } else {
          let bestX = -Infinity;
          (state.SIM.meta.robots as string[]).forEach((id: string) => {
            if (state.hiddenRobots.has(id)) return;
            const r = robotFrame(fr, id);
            if (r && r.x > bestX) { bestX = r.x; leaderId = id; }
          });
        }
        const lr = leaderId ? robotFrame(fr, leaderId) : null;
        if (lr) { state.vx = lr.x; state.vy = lr.y; }
      } else if (target) {
        // Track a specific robot regardless of its visibility.
        // Hide is a rendering choice; the user explicitly set this target.
        // To change the target, the user cycles TRACK.
        const tr = robotFrame(fr, target);
        if (tr) { state.vx = tr.x; state.vy = tr.y; }
      } else {
        // Default: centroid of all visible robots
        const visible = state.SIM.meta.robots.filter((id: string) => !state.hiddenRobots.has(id));
        if (visible.length > 0) {
          let sx = 0, sy = 0;
          visible.forEach((id: string) => {
            const r = robotFrame(fr, id);
            if (r) { sx += r.x; sy += r.y; }
          });
          state.vx = sx / visible.length;
          state.vy = sy / visible.length;
        }
      }
    }

    const vis = (id: string) => !state.hiddenRobots.has(id);

    drawGrid();
    drawGlobalCanvas(fr, vis);

    if (state.LAYERS.ghost) {
      state.SIM.meta.robots.forEach((id: string, i: number) => {
        if (!vis(id)) return;
        const rf = robotFrame(fr, id); if (!rf) return;
        drawGhostRobot(rf, PALETTE[i % PALETTE.length]);
      });
    }

    if (state.LAYERS.links) {
      drawPlatoonLinks(fr, components, vis);
    }

    if (state.LAYERS.sensors) {
      state.SIM.meta.robots.forEach((id: string, i: number) => {
        if (!vis(id)) return;
        const rf = robotFrame(fr, id); if (!rf) return;
        drawSensorOverlay(rf, PALETTE[i % PALETTE.length], fr);
      });
    }

    if (state.LAYERS.trail) {
      state.SIM.meta.robots.forEach((id: string) => {
        if (!vis(id)) return;
        drawTrail(state.fi, id);
        drawStateTransitions(state.fi, id);
      });
    }

    // Scenario overlays
    drawScenarioOverlaysGlobal(fr, state.SIM.meta.robots, vis);

    drawStateLegend();
  }
}


// ── Animation loop ────────────────────────────────────────────────────────────

/**
 * requestAnimationFrame loop.
 * When playing, advances fi based on wall-clock time × playback speed.
 * Always calls draw() and updateUI() so the canvas stays in sync while
 * scrubbing or paused.
 *
 * @param {DOMHighResTimeStamp} ts  Timestamp from requestAnimationFrame
 */
function loop(ts: DOMHighResTimeStamp) {
  if (state.liveMode) {
    if (state.SIM && state.liveFrameBuffer.length > 0) {
      // draw() and updateUI() both run every tick so camera interactions,
      // local buffer edits (applyLocalBufferMax), and WS frames all reflect
      // immediately without waiting for the next incoming message.
      draw();
      updateUI();
    }
    requestAnimationFrame(loop);
    return;
  }

  if (state.playing && state.SIM) {
    if (state.lastTs === null) state.lastTs = ts;
    const dt = (ts - state.lastTs) / 1000;   // wall-clock delta in seconds
    state.lastTs = ts;
    state.accumT += dt * state.SPEEDS[state.spdi];   // advance simulation time at selected speed

    // Find the first frame whose timestamp is >= the accumulated sim time
    const idx = state.SIM.frames.findIndex(f => f.t >= state.accumT);

    if (idx < 0 || idx >= state.SIM.frames.length - 1) {
      // Reached the end of the run — stop playback
      state.fi      = state.SIM.frames.length - 1;
      state.playing = false;
      document.getElementById('pbplay').innerHTML = '&#x25B6;';
      document.getElementById('pbplay').classList.remove('on');
    } else {
      state.fi = idx;
    }
  } else {
    state.lastTs = null;
  }

  if (state.SIM) { draw(); updateUI(); }

  requestAnimationFrame(loop);
}


// ── Initialisation ────────────────────────────────────────────────────────────

/**
 * Initialise the canvas visualiser.
 *
 * Called by the Svelte component after mounting.
 *
 * @param {HTMLCanvasElement} canvasEl  The <canvas id="arena"> element
 */
export function init(canvasEl: HTMLCanvasElement) {
  // ── Wire all cross-module callbacks ────────────────────────────────────────

  // camera → draw/updateUI
  setDrawCallback(draw);
  setUpdateUICallback(updateUI);

  // playback → draw/updateUI/sfx
  setPbDrawCallback(draw);
  setPbUpdateUICallback(updateUI);
  setSfxUICallback(sfxUI);
  setSfxScrubTickCallback(sfxScrubTick);

  // panel → sfx, focusRobot, toggleRobotVis
  setSfxTransitionCallback(sfxTransition);
  setUpdateMusicReactiveCallback(updateMusicReactive);
  setFocusRobotCallback(setFocusRobot);
  setToggleRobotVisCallback(toggleRobotVis);

  // liveMode → draw/updateUI
  setLiveModeDrawCallback(draw);
  setLiveModeUpdateUICallback(updateUI);

  // ── Canvas & controls setup ────────────────────────────────────────────────
  initCamera();
  initScrubber();

  // Register audio resume on first user gesture (browser autoplay policy)
  document.addEventListener('click',   sfxResume, { once: true });
  document.addEventListener('keydown', sfxResume, { once: true });

  // ── Load RUNS data if already available ───────────────────────────────────
  if (state.RUNS && Object.keys(state.RUNS).length > 0) {
    buildRunSelector();
    buildPanel();

    if (state.SIM) {
      initRoadBuffers(state.SIM.meta.sheet);
      initAlignment(state.SIM.meta.sheet);
      document.getElementById('tl-tot').textContent = state.SIM.meta.duration.toFixed(3) + ' s';
      state.SIM.meta.robots.forEach(buildTimeline);
    }
  }

  // Seed hasReplayRuns in TwinCanvas from the actual RUNS state at mount time.
  // The tg:replaystate listener is registered in onMount before init() is called,
  // so this event arrives correctly even in the preloaded-data case.
  // No key filtering needed: at init() time the WS connection has not been made yet,
  // so state.RUNS["live"] can only exist if it is a legitimate preloaded replay run.
  window.dispatchEvent(new CustomEvent('tg:replaystate', {
    detail: { hasRuns: Object.keys(state.RUNS).length > 0 },
  }));

  // ── Start the animation loop ───────────────────────────────────────────────
  requestAnimationFrame(loop);
}
