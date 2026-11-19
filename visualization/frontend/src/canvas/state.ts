// state.ts — single shared mutable state object imported by all canvas modules
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const state: Record<string, any> = {

  // ── Simulation data ────────────────────────────────────────────────────────
  // RUNS is populated by activateRuns() in main.ts; SIM is the currently selected run.
  RUNS: {},
  SIM:  null,

  // ── Local robot view (from main.js) ────────────────────────────────────────
  // null = global view; string = per-robot local view
  focusRobotId: null,

  // ── Layer visibility (from main.js) ────────────────────────────────────────
  LAYERS: {
    trail:   true,
    sensors: true,
    links:   true,
    ghost:   false,
  },

  // ── Robot visibility (from main.js) ────────────────────────────────────────
  hiddenRobots: new Set(),

  // ── Canvas element and 2D context (from camera.js) ─────────────────────────
  // Set during initCamera(); null until then.
  cvs: null,
  cx:  null,

  // ── Canvas logical size in CSS pixels (from camera.js) ─────────────────────
  W: 0,
  H: 0,

  // ── View state (from camera.js) ────────────────────────────────────────────
  scale:        50,    // pixels per metre
  vx:           0,     // world X at the centre of the viewport
  vy:           0,     // world Y at the centre of the viewport
  cameraFollow: true,  // true = camera tracks robot centroid each frame
  // cameraTarget: what to track in global view when cameraFollow is true.
  //   null         → centroid of all visible robots
  //   'leader'     → frontmost robot in the chain
  //   <robot id>   → specific robot (no isolation — all robots still rendered)
  cameraTarget: null as string | null,
  _drag:        null,  // { x, y, vx0, vy0 } while a mouse drag is in progress

  // ── Robot render size multiplier (from camera.js) ──────────────────────────
  // Default 5× base size makes the ~0.1 m JetBot visible at typical zoom levels.
  robotSizeM: 5.0,

  // ── Playback state (from playback.js) ──────────────────────────────────────
  fi:       0,      // current frame index into SIM.frames
  playing:  false,  // true while the animation loop is advancing frames
  spdi:     2,      // index into SPEEDS array (default = 1×)
  lastTs:   null,   // last requestAnimationFrame timestamp (ms), null when paused
  accumT:   0,      // accumulated simulation time (s) — drives frame selection

  SPEEDS: [0.25, 0.5, 1, 2, 4],
  SPDLBL: ['1/4\u00d7', '1/2\u00d7', '1\u00d7', '2\u00d7', '4\u00d7'],

  // true while the user is dragging the timeline scrubber thumb
  _scrubbing: false,

  // ── Road buffers (from drawRoad.ts) ────────────────────────────────────────
  // roadBuffer[runName][robotId] = [{ x, y, yaw }, ...]
  roadBuffer: {},
  // curvatureScale[runName] — 95th-percentile |Δyaw/ds| across all robots in the run
  curvatureScale: {},

  // ── Alignment state (from render/alignment.ts) ─────────────────────────────
  // alignmentState[runName][robotId] = { method, tx, ty, theta, confidence, … }
  alignmentState: {},
  // globalRoadMap[runName] = merged road point array
  globalRoadMap: {},
  // _globalMapIdx[runName][robotId] = next localBuf index to process in addToGlobalMap
  _globalMapIdx: {},

  // ── Robot cards panel UI state ─────────────────────────────────────────────
  // cardSortOrder: order in which robot cards are rendered in the left panel.
  //   'definition' — arrival order from meta.robots (default)
  //   'chain'      — front-to-back platoon chain order from current frame
  //   'state'      — PLATOONING first, then ALIGNING, CANDIDATE, AUTONOMOUS, RECOVERY
  //   'id'         — lexicographic robot ID sort
  cardSortOrder: 'definition' as 'definition' | 'chain' | 'state' | 'id',

  // cardDetailLevels: per-robot detail density map.
  //   'full'    — all sections including raw sensor fields
  //   'compact' — header + timeline + estimated state + controller errors + sensors (default)
  //   'minimal' — header only with inline X, Y, V summary
  cardDetailLevels: {} as Record<string, 'full' | 'compact' | 'minimal'>,

  // ── Live mode (from liveMode.ts) ────────────────────────────────────────────
  liveMode:        false,
  liveSocket:      null,
  liveSessionId:   null,
  liveLastFrameId: 0,
  _liveStartT:     null,   // monotonic time of first live frame
  LIVE_BUFFER_MAX: 1200,   // ~60 s at 20 Hz — writable, updated from Settings
  liveFrameBuffer: [],
  // Excel sheet names cannot contain [ or ] (xlsx spec + openpyxl enforces this),
  // so '[live]' is structurally unreachable from any uploaded workbook.
  LIVE_RUN:        '[live]',
};
