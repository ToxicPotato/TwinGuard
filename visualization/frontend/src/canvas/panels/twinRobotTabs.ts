import { chainTerminationLabel, trackingStatusLabel } from './shared';

function row(label: string, value: string, extraCls?: string, tip?: string) {
  const tipAttr = tip ? ` data-tip="${tip}"` : '';
  return `<div class="td-row"${tipAttr}><span>${label}</span><span class="td-val ${extraCls || ''}">${value}</span></div>`;
}

function formatNumber(value: number | null | undefined, decimals: number, suffix = '') {
  return value != null ? value.toFixed(decimals) + suffix : '-';
}

function twinBody(id: string, twinData: any) {
  if (!twinData) return '<div class="td-row" style="opacity:.4">no data</div>';

  const robot = (twinData.per_robot && twinData.per_robot[id]) || {};
  const assessment = robot.assessment || {};
  const trend = robot.trend || {};
  const temporal = robot.temporal || {};
  const motion = trend.motion || {};
  const relation = trend.relation || {};
  const arrow = (value: number | null | undefined) => value == null ? '-' : value < -0.02 ? 'v' : value > 0.02 ? '^' : '-';

  return [
    '<div class="td-section">Robot</div>',
    (() => {
      const gap = assessment.gap && assessment.gap.bumper_gap_meters != null ? assessment.gap.bumper_gap_meters : null;
      return row('gap', formatNumber(gap, 2, ' m'), '', 'Current frame-assessed bumper gap for this twin.');
    })(),
    row('role', assessment.role_hypothesis || '-', '', 'Current frame role hypothesis for this robot.'),
    row('direct leader', assessment.direct_leader_hypothesis_id || '-', '', 'Current direct leader hypothesis in this frame.'),
    row('front leader', assessment.front_leader_hypothesis_id || '-', '', 'Current front-most leader hypothesis in this frame.'),
    row('component', assessment.component_id || '-', '', 'Visible platoon component id for this robot in this frame.'),
    row('chain end', chainTerminationLabel(assessment.chain_termination_reason), '', 'Why the visible direct-leader chain stops for this robot in this frame.'),
    row('tracking', trackingStatusLabel(assessment.leader_tracking_status), '', 'Current-frame leader-tracking evidence status for this robot.'),
    `<div class="td-section">Behavior <span class="td-val">${temporal.support_quality || ''}</span><span style="opacity:.45;font-size:8px"> ${temporal.history_span_seconds != null ? temporal.history_span_seconds + 's' : ''}${temporal.samples_in_window != null ? ' · ' + temporal.samples_in_window + ' smp' : ''}</span></div>`,
    row('motion', motion.label || '-', '', 'Observed motion trend over the active history window.'),
    row('gap rate', relation.gap_rate_mps != null ? `${arrow(relation.gap_rate_mps)} ${Math.abs(relation.gap_rate_mps).toFixed(3)} m/s` : '-', '', 'Rate of gap change to the current direct leader over same-leader samples.'),
    row('gap samples', relation.gap_sample_count != null ? String(relation.gap_sample_count) : '-', '', 'Number of same-leader gap samples used to compute the gap rate.'),
    row('leader changes', relation.leader_change_count != null ? String(relation.leader_change_count) : '-', '', 'Number of non-null direct-leader changes observed in the active history window.'),
    row('frames assessed', relation.frames_assessed != null ? String(relation.frames_assessed) : '-', '', 'Number of observed entries considered for relation analysis in the active history window.'),
  ].join('');
}

export function buildTwinRobotCard({
  id,
  color,
  label,
  activeTab,
  onTabChange,
}: {
  id: string;
  color: string;
  label: string;
  activeTab: 'lr' | 'hr';
  onTabChange: (id: string, tab: 'lr' | 'hr') => void;
}) {
  const card = document.createElement('section');
  card.className = 'twin-robot-card';
  card.innerHTML = `
    <div class="twin-robot-hdr" style="color:${color}">&#x25CF; ${label}</div>
    <div class="card-tab-bar" id="${id}-card-tabbar">
      <button class="card-tab-btn${activeTab === 'lr' ? ' active' : ''}" data-tab="lr">Low-Res</button>
      <button class="card-tab-btn${activeTab === 'hr' ? ' active' : ''}" data-tab="hr">High-Res</button>
    </div>
    <div class="twin-tab-body" id="${id}-twin-body"></div>
  `;

  card.querySelectorAll('.card-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => onTabChange(id, (btn.getAttribute('data-tab') as 'lr' | 'hr')));
  });

  return card;
}

export function updateTwinRobotCard(id: string, frame: any, activeTab: 'lr' | 'hr') {
  const body = document.getElementById(id + '-twin-body');
  if (!body) return;
  body.innerHTML = activeTab === 'hr'
    ? twinBody(id, frame.high_res)
    : twinBody(id, frame.low_res);
}

export function syncTwinRobotCardTab(id: string, activeTab: 'lr' | 'hr') {
  const bar = document.getElementById(id + '-card-tabbar');
  if (!bar) return;
  bar.querySelectorAll('.card-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-tab') === activeTab);
  });
}
