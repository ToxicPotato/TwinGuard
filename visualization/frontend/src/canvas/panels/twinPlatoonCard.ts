import { state } from '../state';
import { PALETTE } from '../constants';
import { chainComponents, formatStructureStatus, robotLabel } from './shared';

function setTwinValue(id: string, value: string, cls = '') {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = value;
  element.className = `twin-platoon-value ${cls}`.trim();
}

function buildChainVisual(frame: any) {
  const components = chainComponents(frame);
  if (!components.length) return '';

  const perRobot: Record<string, any> = (frame.low_res && frame.low_res.per_robot) || {};

  return components.map((component, compIdx) => {
    const parts: string[] = [];
    component.forEach((robotId: string, index: number) => {
      const colorIndex = state.SIM.meta.robots.indexOf(robotId);
      const color = PALETTE[Math.max(0, colorIndex) % PALETTE.length];
      parts.push(`<span class="cv-node" style="color:${color}">&#x25CF; ${robotLabel(robotId, true)}</span>`);
      if (index < component.length - 1) {
        const followerId = component[index + 1];
        const gap = perRobot[followerId]?.assessment?.gap?.bumper_gap_meters ?? null;
        parts.push(`<span class="cv-gap"> -- ${gap != null ? gap.toFixed(1) + 'm' : '?'} -- </span>`);
      }
    });
    const sep = compIdx < components.length - 1 ? '<div class="cv-sep"></div>' : '';
    return `<div class="chain-visual">${parts.join('')}</div>${sep}`;
  }).join('');
}

function buildSummaryRows(frame: any, twinKey: 'low_res' | 'high_res', focusedRobotId: string | null) {
  const twin = frame[twinKey];
  if (!twin) return '<div class="twin-brow"><span>no data</span></div>';

  const rows: string[] = [];
  const perRobot: Record<string, any> = twin.per_robot || {};

  if (focusedRobotId) {
    // Single-robot focused view
    const focusTemporal = perRobot[focusedRobotId]?.temporal ?? null;
    if (focusTemporal) {
      const span = focusTemporal.history_span_seconds;
      const samples = focusTemporal.samples_in_window;
      rows.push(`<div class="twin-brow"><span>temporal</span><span class="twin-bval">${focusTemporal.support_quality || '-'}${span != null ? ` (${span.toFixed(2)}s` : ''}${samples != null ? ` - ${samples} smp` : ''}${span != null ? ')' : ''}</span></div>`);
    }
    const relation = perRobot[focusedRobotId]?.trend?.relation ?? null;
    if (relation) {
      const parts = [];
      if (relation.gap_sample_count != null)  parts.push(`${relation.gap_sample_count} smp`);
      if (relation.leader_change_count != null) parts.push(`${relation.leader_change_count} chg`);
      if (relation.gap_rate_mps != null)       parts.push(`${Math.abs(relation.gap_rate_mps).toFixed(3)} gap/s`);
      rows.push(`<div class="twin-brow"><span>${robotLabel(focusedRobotId, true)}</span><span class="twin-bval">${parts.join(' - ') || 'no relation data'}</span></div>`);
    }
  } else {
    // Multi-platoon overview: temporal summary, then per-component robot rows
    if (Object.keys(perRobot).length > 0) {
      const supports = (Object.values(perRobot) as any[]).map(r => r.temporal || {});
      const goodCount    = supports.filter(s => s.support_quality === 'good').length;
      const limitedCount = supports.filter(s => s.support_quality === 'limited').length;
      rows.push(`<div class="twin-brow"><span>temporal</span><span class="twin-bval">${goodCount} good - ${limitedCount} limited</span></div>`);
    }

    const components = chainComponents(frame, twinKey);
    components.forEach((component, compIdx) => {
      if (components.length > 1) {
        rows.push(`<div class="twin-brow" style="opacity:.45;font-size:9px"><span>platoon ${compIdx + 1}</span></div>`);
      }
      component.forEach((robotId: string) => {
        const relation = perRobot[robotId]?.trend?.relation ?? null;
        if (!relation) return;
        const parts = [];
        if (relation.gap_sample_count != null)   parts.push(`${relation.gap_sample_count} smp`);
        if (relation.leader_change_count != null) parts.push(`${relation.leader_change_count} chg`);
        if (relation.gap_rate_mps != null)        parts.push(`${Math.abs(relation.gap_rate_mps).toFixed(3)} gap/s`);
        rows.push(`<div class="twin-brow"><span>${robotLabel(robotId, true)}</span><span class="twin-bval">${parts.join(' - ') || 'no relation data'}</span></div>`);
      });
    });
  }

  if (!rows.length) {
    rows.push('<div class="twin-brow"><span>no behavior data</span></div>');
  }

  return rows.join('');
}

export function buildTwinPlatoonCard(isFocused: boolean) {
  const card = document.createElement('section');
  card.className = 'twin-platoon-card';
  card.innerHTML = `
    <div class="twin-platoon-hdr">
      <span class="twin-platoon-title" id="tp-title">${isFocused ? 'Focused Analysis' : 'Platoon Overview'}</span>
      <span class="twin-platoon-title" id="tp-arch">${(state.SIM.meta.twin && state.SIM.meta.twin.architecture) || 'unknown'}</span>
    </div>
    <div class="twin-platoon-grid">
      <div class="twin-platoon-box">
        <div class="twin-platoon-key">Low-Res Twin</div>
        <div class="twin-platoon-value" id="tp-low-score">--</div>
        <div class="twin-platoon-sub" id="tp-low-sub">components</div>
      </div>
      <div class="twin-platoon-box">
        <div class="twin-platoon-key">High-Res Twin</div>
        <div class="twin-platoon-value" id="tp-high-score">--</div>
        <div class="twin-platoon-sub" id="tp-high-sub">components</div>
      </div>
    </div>
    <div id="tp-chain-vis"></div>
    <div class="twin-platoon-columns">
      <section class="twin-platoon-column">
        <div class="twin-platoon-column-title">Low-Res</div>
        <div class="twin-summary-list" id="tp-low-list"></div>
      </section>
      <section class="twin-platoon-column">
        <div class="twin-platoon-column-title">High-Res</div>
        <div class="twin-summary-list" id="tp-high-list"></div>
      </section>
    </div>
  `;
  return card;
}

export function updateTwinPlatoonCard(frame: any) {
  const isFocused = !!state.focusRobotId;
  const focusId = state.focusRobotId;
  const lowAssessment = frame.low_res && frame.low_res.platoon && frame.low_res.platoon.assessment;
  const highAssessment = frame.high_res && frame.high_res.platoon && frame.high_res.platoon.assessment;
  const focusLowAssessment = focusId && frame.low_res && frame.low_res.per_robot ? frame.low_res.per_robot[focusId]?.assessment : null;
  const focusHighAssessment = focusId && frame.high_res && frame.high_res.per_robot ? frame.high_res.per_robot[focusId]?.assessment : null;

  const lowStructureLabel = formatStructureStatus(lowAssessment ? lowAssessment.structure_status : '');
  const highStructureLabel = formatStructureStatus(highAssessment ? highAssessment.structure_status : '');
  const lowComponentCount = lowAssessment ? (lowAssessment.components || []).length : 0;
  const highComponentCount = highAssessment ? (highAssessment.components || []).length : 0;

  setTwinValue('tp-low-score', lowStructureLabel);
  setTwinValue('tp-high-score', highStructureLabel);

  const title = document.getElementById('tp-title');
  if (title) title.textContent = isFocused ? 'Focused Analysis' : 'Platoon Overview';

  const lowSubText = isFocused
    ? `${focusLowAssessment && focusLowAssessment.direct_leader_hypothesis_id ? robotLabel(focusLowAssessment.direct_leader_hypothesis_id) : 'LEAD'} - ${focusLowAssessment && focusLowAssessment.gap && focusLowAssessment.gap.bumper_gap_meters != null ? focusLowAssessment.gap.bumper_gap_meters.toFixed(2) + 'm' : 'n/a'}`
    : `${lowComponentCount} ${lowComponentCount === 1 ? 'component' : 'components'}`;
  const highSubText = isFocused
    ? `${focusHighAssessment && focusHighAssessment.gap && focusHighAssessment.gap.bumper_gap_meters != null ? focusHighAssessment.gap.bumper_gap_meters.toFixed(2) + 'm gap' : 'gap n/a'}`
    : `${highComponentCount} ${highComponentCount === 1 ? 'component' : 'components'}`;

  const lowSub = document.getElementById('tp-low-sub');
  if (lowSub) lowSub.textContent = lowSubText;

  const highSub = document.getElementById('tp-high-sub');
  if (highSub) highSub.textContent = highSubText;

  const chainContainer = document.getElementById('tp-chain-vis');
  if (chainContainer) chainContainer.innerHTML = buildChainVisual(frame);

  const lowList = document.getElementById('tp-low-list');
  if (lowList) lowList.innerHTML = buildSummaryRows(frame, 'low_res', focusId);

  const highList = document.getElementById('tp-high-list');
  if (highList) highList.innerHTML = buildSummaryRows(frame, 'high_res', focusId);

  return {
    lowScore: lowStructureLabel,
    highScore: highStructureLabel,
    lowSub: lowSubText,
    highSub: highSubText,
  };
}
