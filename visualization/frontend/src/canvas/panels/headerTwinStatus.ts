import { formatStructureStatus } from './shared';

export function updateHeaderTwinStatus(
  frame: any,
  focusSummary: { lowScore: string; highScore: string; lowSub: string; highSub: string; },
) {
  const lowAssessment = frame.low_res?.platoon?.assessment;
  const highAssessment = frame.high_res?.platoon?.assessment;

  const setEl = (id: string, value: string, cls?: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
    if (cls !== undefined) el.className = cls;
  };

  setEl('tw-low-score',  formatStructureStatus(lowAssessment?.structure_status),  'twin-v');
  setEl('tw-high-score', formatStructureStatus(highAssessment?.structure_status), 'twin-v');
  setEl('tw-low-sub',  focusSummary.lowSub);
  setEl('tw-high-sub', focusSummary.highSub);

  const timingValue = document.getElementById('tw-timing-val');
  if (!timingValue) return;

  if (frame.comparison?.timing_ms) {
    timingValue.textContent = `${frame.comparison.timing_ms.low_res.toFixed(2)} / ${frame.comparison.timing_ms.high_res.toFixed(2)}`;
  } else {
    timingValue.textContent = '-- / --';
  }
}
