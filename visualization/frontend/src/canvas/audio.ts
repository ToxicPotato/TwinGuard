// ─────────────────────────────────────────────────────────────────────────────
// audio.ts — Web Audio API sound engine.
//
// Two systems:
//   SFX     — short sine-tone chimes for state transitions and UI actions.
//   Music   — 6-voice sine/triangle ambient drone that reacts in real-time to
//             robot speed, lateral error, road curvature, and active state.
//
// No external audio files — everything is synthesised procedurally.
// ─────────────────────────────────────────────────────────────────────────────

import { state } from './state';
import { robotFrame, TARGET_GAP } from './constants';

// Single shared AudioContext.  Created lazily; null if Web Audio is unavailable.
const _ac: AudioContext | null = (() => {
  try {
    const AC = window.AudioContext ?? (window as any).webkitAudioContext;
    return AC ? new AC() : null;
  } catch { return null; }
})();

let _sfxOn = true;                // SFX enabled flag

let _lastScrubSnd  = 0;           // AudioContext time of last scrub tick sound
const _stTimer     = {};          // last sound time (ms) per robot — debounce
const ST_SND_GAP   = 2200;        // minimum ms between state sounds per robot


/** Resume the AudioContext after a user gesture (browser autoplay policy). */
export function sfxResume(): void {
  if (_ac && _ac.state === 'suspended') _ac.resume();
}


// ── Low-level synthesis primitives ───────────────────────────────────────────

/**
 * Play a short sine-tone with a soft attack and exponential decay.
 *
 * @param {number} freq    Frequency (Hz)
 * @param {number} dur     Total duration (s)
 * @param {number} vol     Peak gain (0–1)
 * @param {number} delay   Start delay from now (s)
 * @param {number} attack  Attack ramp duration (s)
 */
function _tone(freq, dur, vol = 0.10, delay = 0, attack = 0.08) {
  if (!_ac || !_sfxOn) return;

  const o = _ac.createOscillator();
  const g = _ac.createGain();
  o.connect(g);
  g.connect(_ac.destination);

  o.type            = 'sine';
  o.frequency.value = freq;

  const t0 = _ac.currentTime + delay;
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.linearRampToValueAtTime(vol, t0 + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + Math.max(attack + 0.05, dur));

  o.start(t0);
  o.stop(t0 + dur + 0.06);
}


/**
 * Play a very brief breath-noise pulse (low-pass filtered white noise).
 * Used for soft tactile feedback on play/pause and scrub ticks.
 *
 * @param {number} dur    Duration (s)
 * @param {number} vol    Gain (0–1)
 * @param {number} delay  Start delay (s)
 */
function _breath(dur = 0.04, vol = 0.018, delay = 0) {
  if (!_ac || !_sfxOn) return;

  const len = Math.ceil(_ac.sampleRate * dur);
  const buf = _ac.createBuffer(1, len, _ac.sampleRate);
  const d   = buf.getChannelData(0);
  // White noise with exponential fade-out
  for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.exp(-i / (len * 0.4));

  const src = _ac.createBufferSource();
  const lpf = _ac.createBiquadFilter();  // low-pass keeps it warm, not hissy
  const g   = _ac.createGain();
  lpf.type           = 'lowpass';
  lpf.frequency.value = 2200;
  src.buffer = buf;
  src.connect(lpf); lpf.connect(g); g.connect(_ac.destination);
  g.gain.value = vol;
  src.start(_ac.currentTime + delay);
}


// ── State transition sounds ───────────────────────────────────────────────────
// Musical intervals chosen to feel like meaningful status chimes.
// Each state has its own short melody (all sine tones, no harsh waveforms).

/**
 * Play the state-transition chime for a robot entering state `toSt`.
 * Rate-limited per robot to at most one chime per ST_SND_GAP ms.
 *
 * @param {string} id    Robot ID (for per-robot debounce)
 * @param {number} toSt  Target state (0–4)
 */
export function sfxTransition(id: string, toSt: number): void {
  if (!_ac || !_sfxOn) return;
  const now = Date.now();
  if (_stTimer[id] && now - _stTimer[id] < ST_SND_GAP) return;
  _stTimer[id] = now;
  sfxResume();
  _duckMusic(0.6);

  if (toSt === 0) {
    // AUTONOMOUS — gentle descending fifth (A4 → E4): soft exhale
    _tone(440,    1.0, 0.07, 0.00, 0.10);
    _tone(329.63, 1.2, 0.05, 0.25, 0.12);
  } else if (toSt === 1) {
    // CANDIDATE — single soft ping on D5, with faint echo: radar sweep
    _tone(587.33, 1.8, 0.07, 0.00, 0.06);
    _tone(587.33, 1.4, 0.03, 0.50, 0.08);
  } else if (toSt === 2) {
    // ALIGNING — rising minor third A4 → C5: focused, preparing
    _tone(440,    0.9, 0.07, 0.00, 0.09);
    _tone(523.25, 1.1, 0.07, 0.30, 0.09);
  } else if (toSt === 3) {
    // PLATOONING — slow A-minor arpeggio: arrival, resolution
    _tone(220,    2.0, 0.07, 0.00, 0.12);
    _tone(329.63, 2.0, 0.06, 0.28, 0.12);
    _tone(440,    2.2, 0.06, 0.55, 0.14);
    _tone(659.25, 1.8, 0.04, 0.85, 0.16);
  } else if (toSt === 4) {
    // RECOVERY — descending A4 → G4 → E4: gentle concern
    _tone(440,    1.2, 0.07, 0.00, 0.10);
    _tone(392,    1.2, 0.06, 0.40, 0.10);
    _tone(329.63, 1.4, 0.05, 0.80, 0.12);
  }
}


/**
 * Play a UI feedback sound for play, pause, or rewind actions.
 * @param {string} type  'play' | 'pause' | 'rewind'
 */
export function sfxUI(type: string): void {
  if (!_ac || !_sfxOn) return;
  sfxResume();
  _duckMusic(0.25);
  if (type === 'play')   { _breath(0.05, 0.015); _tone(523.25, 0.5, 0.05, 0.01, 0.06); }
  if (type === 'pause')  { _tone(440,    0.5, 0.04, 0.00, 0.06); }
  if (type === 'rewind') { _tone(329.63, 0.4, 0.04, 0.00, 0.06); _tone(220, 0.5, 0.03, 0.18, 0.08); }
}


/**
 * Play a very soft tick during timeline scrubbing.
 * Rate-limited to maximum one tick per 50 ms to avoid audio spam.
 */
export function sfxScrubTick(): void {
  if (!_ac || !_sfxOn) return;
  const now = _ac.currentTime;
  if (now - _lastScrubSnd < 0.05) return;
  _lastScrubSnd = now;
  _breath(0.03, 0.010);
}


/** Toggle SFX on/off. Button state is managed reactively by Settings.svelte. */
export function toggleSfx() {
  _sfxOn = !_sfxOn;
}


// ── Ambient music engine ──────────────────────────────────────────────────────

let _music    = null;    // active ambient track object, or null
let _musicVol = 0.45;    // current music volume (0–1)


/** Fade out and stop the ambient music. */
function _stopMusic() {
  if (!_music) return;
  const m = _music;
  _music   = null;
  m.gain.gain.linearRampToValueAtTime(0.0001, _ac.currentTime + 1.0);
  setTimeout(() => m.stop(), 1100);
}


/**
 * Temporarily duck (lower) the music volume, then fade back up.
 * Called when SFX tones fire so they are audible over the drone.
 *
 * @param {number} dur  Duration before the volume returns (s)
 */
function _duckMusic(dur = 0.5) {
  if (!_music) return;
  const g   = _music.gain.gain;
  const now = _ac.currentTime;
  g.cancelScheduledValues(now);
  g.setTargetAtTime(_musicVol * 0.25, now, 0.04);        // quick duck
  g.setTargetAtTime(_musicVol, now + dur, 0.15);          // slow recovery
}


/** Toggle ambient music on/off. Requires a user gesture (browser policy).
 *  Button state is managed reactively by Settings.svelte. */
export function toggleMusic(): void {
  if (!_ac) return;
  _ac.resume();  // must be called in response to a user gesture
  if (_music) {
    _stopMusic();
  } else {
    _music = _startAmbient();
  }
}


/** Set the music volume from the slider input (0–100 → 0–1). */
export function setMusicVol(v: number): void {
  _musicVol = v / 100;
  if (_music) _music.gain.gain.setTargetAtTime(_musicVol, _ac.currentTime, 0.1);
}


// ── Reactive music parameters ─────────────────────────────────────────────────

/**
 * Return the dominant active state across all robots in the current frame.
 * Priority: RECOVERY > ALIGNING > PLATOONING > CANDIDATE > AUTONOMOUS.
 * This drives the chord voicing of the ambient drone.
 *
 * @param {object} fr  Full frame data for the current timestep
 * @returns {number}   State index 0–4
 */
function _dominantSt(fr) {
  if (!state.SIM) return 0;
  const sts = state.SIM.meta.robots
    .map(id => robotFrame(fr, id))
    .filter(r => r)
    .map(r => r.st);
  if (sts.includes(4)) return 4;
  if (sts.includes(2)) return 2;
  if (sts.includes(3)) return 3;
  if (sts.includes(1)) return 1;
  return 0;
}


/**
 * Called every animation frame to update the reactive music parameters.
 * Aggregates five continuous signals from the live robot data and passes
 * them to the active ambient track.
 *
 * Parameters (all normalised 0–1):
 *   speedN  — average forward speed    → LFO shimmer depth
 *   errN    — average lateral error    → voice detuning (dissonance)
 *   curvN   — average road curvature   → bass/treble gain balance
 *   turnN   — average wheel differential → steering intensity
 *   gapN    — platoon gap vs TARGET_GAP → harmonic tension
 *
 * @param {object} fr  Full frame data for the current timestep
 */
export function updateMusicReactive(fr: any): void {
  if (!_music || !_ac || !state.SIM) return;

  const robots = state.SIM.meta.robots;
  const n      = robots.length;
  let sumV = 0, sumLE = 0, sumCurv = 0, sumTurn = 0;
  const gapMap = fr.low_res && fr.low_res.per_robot
    ? Object.fromEntries(
        Object.entries(fr.low_res.per_robot)
          .map(([id, output]) => [
            id,
            output && output.assessment && output.assessment.gap
              ? output.assessment.gap.bumper_gap_meters
              : null,
          ])
      )
    : {};

  robots.forEach(id => {
    const r  = robotFrame(fr, id);
    if (!r) return;
    sumV    += r.v;
    sumLE   += Math.abs(r.le);
    sumCurv += Math.abs(r.rc || 0);            // routed curvature
    sumTurn += Math.abs(r.wl - r.wr);          // wheel differential = steering intensity
  });

  const gapValues = Object.values(gapMap).filter(gap => typeof gap === 'number');
  const meanGap = gapValues.length > 0
    ? gapValues.reduce((sum, gap) => sum + gap, 0) / gapValues.length
    : TARGET_GAP;

  const speedN = Math.min(1, (sumV    / n) / 6.0);   // 6 m/s = max expected speed
  const errN   = Math.min(1, (sumLE   / n) / 0.35);  // 0.35 m = large lateral error
  const curvN  = Math.min(1, (sumCurv / n) / 0.12);  // 0.12 rad/m = very tight curve
  const turnN  = Math.min(1, (sumTurn / n) / 3.5);   // 3.5 rad/s diff = hard turn
  const gapN   = Math.min(1, meanGap / TARGET_GAP);
  const dom    = _dominantSt(fr);
  const now    = _ac.currentTime;

  if (_music.setParams) _music.setParams({ speedN, errN, curvN, turnN, gapN, dom, now });
}


// ── Ambient drone (6 voices) ──────────────────────────────────────────────────

/**
 * Start a 6-voice ambient drone and return a control object.
 *
 * Voices: 55, 110, 164.81, 196, 246.94, 440 Hz
 * Waveforms alternate sine/triangle for slight timbral variation.
 * Each voice has its own LFO for slow pitch shimmer.
 *
 * Chord voicings change per dominant state (slow 3 s glide):
 *   0 AUTONOMOUS  → Am9      (tense, open)
 *   1 CANDIDATE   → Am7      (seeking)
 *   2 ALIGNING    → Asus4    (suspended, tense)
 *   3 PLATOONING  → C major  (resolved, bright)
 *   4 RECOVERY    → Am low   (heavy, concerned)
 *
 * @returns {{ gain, setParams, stop }}
 */
function _startAmbient() {
  const gain = _ac.createGain();
  gain.gain.value = _musicVol;
  gain.connect(_ac.destination);

  // [frequency, waveform, detune_cents, base_gain]
  const VOICES = [
    [55,     'sine',     -3, 0.32],
    [110,    'sine',      5, 0.28],
    [164.81, 'sine',     -5, 0.22],
    [196,    'triangle',  4, 0.16],
    [246.94, 'triangle', -4, 0.11],
    [440,    'triangle',  7, 0.07],
  ];

  const oscs = [], lfos = [], lfoGains = [], voiceGains = [], baseDet = [];

  VOICES.forEach(([f, tp, det, gv], i) => {
    const o  = _ac.createOscillator();
    const g  = _ac.createGain();
    const lfo = _ac.createOscillator();
    const lg  = _ac.createGain();

    o.type            = tp;
    o.frequency.value = f;
    o.detune.value    = det;

    // LFO for slow pitch shimmer — rate increases slightly per voice
    lfo.frequency.value = 0.03 + i * 0.012;
    lg.gain.value       = f * 0.005;   // shimmer depth scales with base frequency
    lfo.connect(lg);
    lg.connect(o.frequency);

    o.connect(g);
    g.connect(gain);
    g.gain.value = gv;

    o.start(); lfo.start();
    oscs.push(o); lfos.push(lfo); lfoGains.push(lg);
    voiceGains.push(g); baseDet.push(det);
  });

  // Chord frequency sets — one per state
  const CHORD = [
    [55,    110,    164.81, 196,    246.94, 440   ],  // 0 AUT  — Am9
    [55,    110,    155.56, 196,    233.08, 440   ],  // 1 CAN  — Am7
    [55,    110,    164.81, 207.65, 261.63, 440   ],  // 2 ALN  — Asus4
    [65.41, 130.81, 196,    261.63, 329.63, 523.25],  // 3 PLT  — C major
    [41.20, 82.41,  110,    164.81, 196,    329.63],  // 4 RCV  — Am low
  ];

  let lastDom = -1;

  return {
    gain,
    setParams({ speedN, errN, curvN, dom, now }) {
      // Chord change on dominant state change — slow 3 s frequency glide
      if (dom !== lastDom) {
        lastDom = dom;
        CHORD[dom].forEach((f, i) =>
          oscs[i].frequency.setTargetAtTime(f, now, 3.0)
        );
      }

      // Speed → LFO shimmer depth (faster = more movement in the pad)
      lfoGains.forEach((lg, i) =>
        lg.gain.setTargetAtTime(VOICES[i][0] * (0.004 + speedN * 0.022), now, 0.5)
      );

      // Lateral error → voice detuning (off-lane = slight dissonance)
      oscs.forEach((o, i) => {
        const sign = i % 2 === 0 ? 1 : -1;
        o.detune.setTargetAtTime(baseDet[i] + sign * errN * 32, now, 0.4);
      });

      // Curvature → shift gain toward lower voices (curve = heavier, more grounded)
      voiceGains.forEach((g, i) => {
        const base  = VOICES[i][3];
        const shift = curvN * (i < 3 ? 0.06 : -0.04);
        g.gain.setTargetAtTime(Math.max(0.01, base + shift), now, 0.6);
      });
    },
    stop() {
      [...oscs, ...lfos].forEach(n => { try { n.stop(); } catch (e) {} });
    },
  };
}
