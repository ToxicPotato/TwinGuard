import { ST, TUNING } from '../constants';
import { state } from '../state';

type DetailLevel = 'full' | 'compact' | 'minimal';

// ── Per-robot element reference cache ────────────────────────────────────────
// Populated once in buildRobotCard() via card.querySelector (before the card
// is in the document).  Cleared by clearCardRefs() when clearPanels() tears
// down the DOM so stale detached-node references are never written to.
type CardRefs = Record<string, HTMLElement | null>;
const _cardRefs = new Map<string, CardRefs>();

export function clearCardRefs(): void {
  _cardRefs.clear();
}

function _refs(id: string): CardRefs {
  return _cardRefs.get(id) ?? {};
}

// ── Internal helpers that operate on cached element refs ─────────────────────

function _setText(el: HTMLElement | null | undefined, value: string): void {
  if (el) el.textContent = value;
}

function _setRowEl(el: HTMLElement | null | undefined, value: string, cls?: string): void {
  if (!el) return;
  el.textContent = value;
  el.className = 'rcard-row-value' + (cls ? ' ' + cls : '');
}

function _setGaugeEl(el: HTMLElement | null | undefined, value: number, maxValue: number): void {
  if (!el) return;
  const clamped = Math.max(-maxValue, Math.min(maxValue, value));
  const half = (Math.abs(clamped) / maxValue) * 50;
  if (clamped >= 0) {
    el.style.left = '50%';
    el.style.width = half + '%';
  } else {
    el.style.left = (50 - half) + '%';
    el.style.width = half + '%';
  }
}

function thresholdClass(value: number, warn: number, alert: number) {
  const absValue = Math.abs(value);
  return absValue > alert ? 'alert' : absValue > warn ? 'warn' : '';
}

// Kept for callers outside the hot-path (setCardDetailLevel does not need speed).
function setRowValue(id: string, value: string, cls?: string) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value;
  el.className = 'rcard-row-value' + (cls ? ' ' + cls : '');
}

function gaugeRow(id: string, label: string, color: string, tip: string, dimFill = false) {
  const fill = dimFill ? color + '88' : color;
  return `
    <div class="rcard-gauge-row" data-tip="${tip}">
      <span class="rcard-gauge-label">${label}</span>
      <div class="rcard-gauge-track"><div class="rcard-gauge-center"></div><div class="rcard-gauge-fill" id="${id}-g" style="background:${fill}"></div></div>
      <span class="rcard-gauge-value" id="${id}">-</span>
    </div>`;
}

export function setCardDetailLevel(cardId: string, level: DetailLevel) {
  state.cardDetailLevels[cardId] = level;
  const card = document.getElementById(cardId + '-card');
  if (!card) return;
  card.classList.remove('rcard--full', 'rcard--compact', 'rcard--minimal');
  card.classList.add(`rcard--${level}`);
  card.querySelectorAll<HTMLButtonElement>('.rcard-detail-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.level === level)
  );
}

export function buildRobotCard({
  id,
  color,
  label,
  isFocused,
  isHidden,
  onToggleVisibility,
}: {
  id: string;
  color: string;
  label: string;
  isFocused: boolean;
  isHidden: boolean;
  onToggleVisibility: (id: string) => void;
}) {
  const card = document.createElement('section');
  card.id = id + '-card';
  card.className = 'rcard' + (isFocused ? ' focused' : '');
  card.innerHTML = `
    <div class="rcard-header">
      <span class="rcard-header-dot" style="background:${color};box-shadow:0 0 7px ${color}88"></span>
      <span class="rcard-header-id" style="color:${color}">${label}</span>
      <span class="rcard-chain-pos" id="${id}-pos">#-</span>
      <span class="state-badge state-badge--st0" id="${id}-st">AUTONOMOUS</span>
      <div class="rcard-detail-btns">
        <button class="rcard-detail-btn" data-level="full"    title="Full detail">F</button>
        <button class="rcard-detail-btn" data-level="compact" title="Compact">C</button>
        <button class="rcard-detail-btn" data-level="minimal" title="Minimal">M</button>
      </div>
      <button class="rcard-vis-btn${isHidden ? '' : ' on'}" id="${id}-vis" title="Toggle visibility">&#x25A0;</button>
    </div>
    <div class="rcard-minimal-row" id="${id}-min-row">
      <div class="rcard-minimal-cell"><span class="rcard-minimal-lbl">X</span><span class="rcard-minimal-val" id="${id}-min-x">-</span></div>
      <div class="rcard-minimal-cell"><span class="rcard-minimal-lbl">Y</span><span class="rcard-minimal-val" id="${id}-min-y">-</span></div>
      <div class="rcard-minimal-cell"><span class="rcard-minimal-lbl">V</span><span class="rcard-minimal-val" id="${id}-min-v">-</span></div>
    </div>
    <canvas class="rcard-timeline" id="${id}-tl" height="10"
            data-tip="State history for this run\nColours match the state legend\nClick to seek to that frame"
            data-detail-group="timeline"
            style="display:block;width:100%;cursor:pointer"></canvas>

    <div class="rcard-section-label" data-detail-group="pose">Estimated State</div>
    <div class="rcard-rows" data-cols="2" data-detail-group="pose">
      <div class="rcard-row"><span class="rcard-row-name">X</span><span class="rcard-row-value" id="${id}-x">-</span></div>
      <div class="rcard-row"><span class="rcard-row-name">Yaw</span><span class="rcard-row-value" id="${id}-yaw">-</span></div>
      <div class="rcard-row"><span class="rcard-row-name">Y</span><span class="rcard-row-value" id="${id}-y">-</span></div>
      <div class="rcard-row"><span class="rcard-row-name">V</span><span class="rcard-row-value" id="${id}-v">-</span></div>
    </div>

    <div class="rcard-section-label" data-detail-group="errors">Controller Inputs</div>
    <div class="rcard-gauges" data-detail-group="errors">
      ${gaugeRow(id + '-le', 'le', color, 'Lateral error routed to controller (le, m)\\nnegative = left, positive = right')}
      ${gaugeRow(id + '-he', 'he', color, 'Heading error routed to controller (he, rad)\\nnegative = left, positive = right')}
      ${gaugeRow(id + '-rc', 'rc', color, 'Curvature routed to controller (rc, rad/m)', true)}
      ${gaugeRow(id + '-vv', 'vv', color, 'Velocity routed to controller (vv, m/s)', true)}
    </div>

    <div class="rcard-section-label" data-detail-group="raw-lane">Raw Lane Sensor</div>
    <div class="rcard-gauges" data-detail-group="raw-lane">
      ${gaugeRow(id + '-lc',      'lc',      color, 'Raw lane curvature from own lane sensor (lc, rad/m)',             true)}
      ${gaugeRow(id + '-lane-le', 'lane le', color, 'Raw lane lateral error from lane sensor (lane_le, m)')}
      ${gaugeRow(id + '-lane-he', 'lane he', color, 'Raw lane heading error from lane sensor (lane_he, rad)')}
    </div>

    <div class="rcard-section-label" data-detail-group="raw-leader">Raw Leader Camera</div>
    <div class="rcard-gauges" data-detail-group="raw-leader">
      ${gaugeRow(id + '-le-raw', 'le raw', color, 'Raw camera lateral error to visible leader (le_raw, m)')}
      ${gaugeRow(id + '-he-raw', 'he raw', color, 'Raw camera heading error to visible leader (he_raw, rad)')}
    </div>

    <div class="rcard-section-label" data-detail-group="demand">Steering Demand</div>
    <div class="rcard-rows" data-cols="2" data-detail-group="demand">
      <div class="rcard-row" data-tip="Curvature command output from controller (sc, rad/m)">
        <span class="rcard-row-name">k cmd</span><span class="rcard-row-value" id="${id}-sc">-</span>
      </div>
      <div class="rcard-row" data-tip="Speed command output from controller (sd_v, m/s)">
        <span class="rcard-row-name">v cmd</span><span class="rcard-row-value" id="${id}-sdv">-</span>
      </div>
    </div>

    <div class="rcard-section-label" data-detail-group="motors">Motors</div>
    <div class="rcard-gauges" data-detail-group="motors">
      ${gaugeRow(id + '-wl', 'L whl', color, 'Left wheel speed command (rad/s)')}
      ${gaugeRow(id + '-wr', 'R whl', color, 'Right wheel speed command (rad/s)')}
    </div>

    <div class="rcard-section-label" data-detail-group="sensors">Sensors</div>
    <div class="rcard-rows" data-detail-group="sensors">
      <div class="rcard-row" data-tip="Raw distance sensor reading reported by this robot (d), bumper-to-bumper in metres.">
        <span class="rcard-row-name">raw distance</span><span class="rcard-row-value" id="${id}-d">-</span>
      </div>
      <div class="rcard-row" data-tip="Raw distance-valid flag reported by this robot (dv).">
        <span class="rcard-row-name">dist valid</span><span class="rcard-row-value" id="${id}-dv">-</span>
      </div>
      <div class="rcard-row" data-tip="Raw camera tracking flag reported by this robot (tk).">
        <span class="rcard-row-name">cam lock</span><span class="rcard-row-value" id="${id}-tk">-</span>
      </div>
    </div>

    <div id="${id}-leader-sec" data-detail-group="leader">
      <div class="rcard-section-label">Advertised Leader</div>
      <div class="rcard-rows">
        <div class="rcard-row" data-tip="Leader ID advertised to this robot through its controller input path (leader_input.id).">
          <span class="rcard-row-name">leader id</span><span class="rcard-row-value" id="${id}-linid">-</span>
        </div>
        <div class="rcard-row" data-tip="Leader velocity advertised to this robot through its controller input path (leader_input.v_mps).">
          <span class="rcard-row-name">leader v</span><span class="rcard-row-value" id="${id}-linv">-</span>
        </div>
        <div class="rcard-row" data-tip="Leader state advertised to this robot through its controller input path (leader_input.active_state).">
          <span class="rcard-row-name">leader st</span><span class="rcard-row-value" id="${id}-linst">-</span>
        </div>
      </div>
    </div>
  `;

  const visButton = card.querySelector<HTMLButtonElement>('.rcard-vis-btn');
  if (visButton) visButton.onclick = () => onToggleVisibility(id);

  card.querySelectorAll<HTMLButtonElement>('.rcard-detail-btn').forEach(btn => {
    btn.onclick = () => setCardDetailLevel(id, btn.dataset.level as DetailLevel);
  });

  // Apply stored or default detail level without triggering a DOM getElementById — card is not in
  // the document yet, so we set the class directly rather than going through setCardDetailLevel.
  const level: DetailLevel = (state.cardDetailLevels[id] as DetailLevel) ?? 'compact';
  state.cardDetailLevels[id] = level;
  card.classList.add(`rcard--${level}`);
  card.querySelectorAll<HTMLButtonElement>('.rcard-detail-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.level === level)
  );

  // Cache all element references while the card is still in-memory (not yet
  // attached to the document).  Build a plain Map via querySelectorAll('[id]')
  // so element lookup is an exact string match — no CSS selector parsing, safe
  // for robot IDs that contain selector metacharacters (colons, dots, etc.).
  const _idMap = new Map<string, HTMLElement>();
  card.querySelectorAll<HTMLElement>('[id]').forEach(el => _idMap.set(el.id, el));
  const q = (suffix: string) => _idMap.get(id + '-' + suffix) ?? null;
  _cardRefs.set(id, {
    pos: q('pos'), st: q('st'),
    'min-x': q('min-x'), 'min-y': q('min-y'), 'min-v': q('min-v'),
    x: q('x'), y: q('y'), yaw: q('yaw'), v: q('v'),
    le: q('le'), he: q('he'),
    'le-g': q('le-g'), 'he-g': q('he-g'), 'rc-g': q('rc-g'), 'vv-g': q('vv-g'),
    'wl-g': q('wl-g'), 'wr-g': q('wr-g'),
    wl: q('wl'), wr: q('wr'), rc: q('rc'), vv: q('vv'),
    sc: q('sc'), sdv: q('sdv'),
    d: q('d'), dv: q('dv'), tk: q('tk'),
    'lc-g': q('lc-g'), 'lane-le-g': q('lane-le-g'), 'lane-he-g': q('lane-he-g'),
    lc: q('lc'), 'lane-le': q('lane-le'), 'lane-he': q('lane-he'),
    'le-raw-g': q('le-raw-g'), 'he-raw-g': q('he-raw-g'),
    'le-raw': q('le-raw'), 'he-raw': q('he-raw'),
    'leader-sec': q('leader-sec'), linid: q('linid'), linv: q('linv'), linst: q('linst'),
  });

  return card;
}

export function updateRobotCard({
  id,
  robot,
  chainIndex,
  previousState,
  isPlaying,
  isScrubbing,
  onTransition,
  updateTimeline,
}: {
  id: string;
  robot: any;
  chainIndex: number;
  previousState: number | undefined;
  isPlaying: boolean;
  isScrubbing: boolean;
  onTransition: (id: string, nextState: number) => void;
  updateTimeline: (id: string) => void;
}) {
  if (isPlaying && !isScrubbing && previousState !== undefined && robot.st !== previousState) {
    onTransition(id, robot.st);
  }

  const r = _refs(id);

  _setText(r.pos, chainIndex > 0 ? '#' + chainIndex : '#-');

  _setRowEl(r.x,   robot.x != null ? robot.x.toFixed(3)               + ' m'   : '-');
  _setRowEl(r.y,   robot.y != null ? robot.y.toFixed(3)               + ' m'   : '-');
  _setRowEl(r.yaw, robot.w != null ? (robot.w * 57.2958).toFixed(2)   + ' deg' : '-');
  _setRowEl(r.v,   robot.v != null ? robot.v.toFixed(3)               + ' m/s' : '-');

  _setText(r['min-x'], robot.x != null ? robot.x.toFixed(1) : '-');
  _setText(r['min-y'], robot.y != null ? robot.y.toFixed(1) : '-');
  _setText(r['min-v'], robot.v != null ? robot.v.toFixed(2) : '-');

  const leEl = r.le;
  if (leEl) {
    if (robot.le != null) {
      const dir = robot.le < -0.001 ? '< ' : robot.le > 0.001 ? '> ' : '';
      leEl.textContent = dir + Math.abs(robot.le).toFixed(4) + ' m';
      leEl.className = 'rcard-gauge-value ' + thresholdClass(robot.le, TUNING.WARN_LE, TUNING.ALERT_LE);
    } else {
      leEl.textContent = '-';
      leEl.className = 'rcard-gauge-value';
    }
  }
  const heEl = r.he;
  if (heEl) {
    if (robot.he != null) {
      const dir = robot.he < -0.001 ? '< ' : robot.he > 0.001 ? '> ' : '';
      heEl.textContent = dir + (Math.abs(robot.he) * 57.2958).toFixed(3) + ' deg';
      heEl.className = 'rcard-gauge-value ' + thresholdClass(robot.he, TUNING.WARN_HE, TUNING.ALERT_HE);
    } else {
      heEl.textContent = '-';
      heEl.className = 'rcard-gauge-value';
    }
  }

  _setGaugeEl(r['le-g'], robot.le,       TUNING.GAUGE_MAX_LE);
  _setGaugeEl(r['he-g'], robot.he,       TUNING.GAUGE_MAX_HE);
  _setGaugeEl(r['rc-g'], robot.rc ?? 0,  TUNING.GAUGE_MAX_RC);
  _setGaugeEl(r['vv-g'], robot.vv ?? 0,  TUNING.GAUGE_MAX_VV);
  _setGaugeEl(r['wl-g'], robot.wl,       TUNING.GAUGE_MAX_WH);
  _setGaugeEl(r['wr-g'], robot.wr,       TUNING.GAUGE_MAX_WH);

  _setText(r.wl, robot.wl != null ? robot.wl.toFixed(2) : '-');
  _setText(r.wr, robot.wr != null ? robot.wr.toFixed(2) : '-');
  _setText(r.rc, robot.rc != null && !isNaN(robot.rc) ? robot.rc.toFixed(4) : '-');
  _setText(r.vv, robot.vv != null ? robot.vv.toFixed(3) + ' m/s' : '-');
  _setText(r.sc,  robot.sc  != null ? robot.sc.toFixed(4)          : '-');
  _setText(r.sdv, robot.sd_v != null ? robot.sd_v.toFixed(3) + ' m/s' : '-');

  const dEl = r.d;
  if (dEl) {
    dEl.textContent = robot.d != null ? robot.d.toFixed(2) + ' m' : '-';
    dEl.className = 'rcard-row-value';
    dEl.style.opacity = robot.dv ? '' : '0.4';
  }
  const dvEl = r.dv;
  if (dvEl) {
    dvEl.textContent = robot.dv ? 'YES' : 'NO';
    dvEl.className = 'rcard-row-value' + (robot.dv ? ' good' : '');
    dvEl.style.opacity = robot.dv ? '' : '0.5';
  }
  const tkEl = r.tk;
  if (tkEl) {
    tkEl.textContent = robot.tk ? 'YES' : 'NO';
    tkEl.className = 'rcard-row-value' + (robot.tk ? ' good' : '');
    tkEl.style.opacity = robot.tk ? '' : '0.45';
  }

  _setGaugeEl(r['lc-g'],      robot.lc      ?? 0, TUNING.GAUGE_MAX_LC);
  _setGaugeEl(r['lane-le-g'], robot.lane_le ?? 0, TUNING.GAUGE_MAX_LE);
  _setGaugeEl(r['lane-he-g'], robot.lane_he ?? 0, TUNING.GAUGE_MAX_HE);
  _setText(r.lc, robot.lc != null ? robot.lc.toFixed(4) : '-');

  const laneLeEl = r['lane-le'];
  if (laneLeEl) {
    if (robot.lane_le != null) {
      const dir = robot.lane_le < -0.001 ? '< ' : robot.lane_le > 0.001 ? '> ' : '';
      laneLeEl.textContent = dir + Math.abs(robot.lane_le).toFixed(4) + ' m';
    } else { laneLeEl.textContent = '-'; }
  }
  const laneHeEl = r['lane-he'];
  if (laneHeEl) {
    if (robot.lane_he != null) {
      const dir = robot.lane_he < -0.001 ? '< ' : robot.lane_he > 0.001 ? '> ' : '';
      laneHeEl.textContent = dir + (Math.abs(robot.lane_he) * 57.2958).toFixed(3) + ' deg';
    } else { laneHeEl.textContent = '-'; }
  }

  _setGaugeEl(r['le-raw-g'], robot.le_raw ?? 0, TUNING.GAUGE_MAX_RAW);
  _setGaugeEl(r['he-raw-g'], robot.he_raw ?? 0, TUNING.GAUGE_MAX_RAW);

  const leRawEl = r['le-raw'];
  if (leRawEl) {
    if (robot.le_raw != null) {
      const dir = robot.le_raw < -0.001 ? '< ' : robot.le_raw > 0.001 ? '> ' : '';
      leRawEl.textContent = dir + Math.abs(robot.le_raw).toFixed(4) + ' m';
    } else { leRawEl.textContent = '-'; }
  }
  const heRawEl = r['he-raw'];
  if (heRawEl) {
    if (robot.he_raw != null) {
      const dir = robot.he_raw < -0.001 ? '< ' : robot.he_raw > 0.001 ? '> ' : '';
      heRawEl.textContent = dir + (Math.abs(robot.he_raw) * 57.2958).toFixed(3) + ' deg';
    } else { heRawEl.textContent = '-'; }
  }

  const leaderSec = r['leader-sec'];
  if (leaderSec) leaderSec.style.display = robot.leader_input_id != null ? '' : 'none';

  const leaderIdEl = r.linid;
  if (leaderIdEl) {
    leaderIdEl.textContent = robot.leader_input_id != null ? String(robot.leader_input_id) : '-';
    leaderIdEl.className = 'rcard-row-value';
  }
  const leaderVelEl = r.linv;
  if (leaderVelEl) {
    leaderVelEl.textContent = robot.leader_input_v != null ? robot.leader_input_v.toFixed(3) + ' m/s' : '-';
    leaderVelEl.className = 'rcard-row-value';
  }
  const leaderStateEl = r.linst;
  if (leaderStateEl) {
    const leaderState = robot.leader_input_state;
    if (leaderState != null && leaderState >= 0 && leaderState < ST.length) {
      leaderStateEl.innerHTML = `<span class="state-badge state-badge--st${leaderState}">${ST[leaderState].label}</span>`;
      leaderStateEl.className = '';
    } else {
      leaderStateEl.textContent = '-';
      leaderStateEl.className = 'rcard-row-value';
    }
  }

  const stateIndex = Math.min(robot.st, ST.length - 1);
  const badge = r.st;
  if (badge) {
    badge.textContent = ST[stateIndex].label;
    badge.className = 'state-badge state-badge--st' + stateIndex;
  }

  updateTimeline(id);
  return robot.st;
}
