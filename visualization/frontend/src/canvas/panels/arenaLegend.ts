import { state } from '../state';
import { PALETTE } from '../constants';
import { robotLabel } from './shared';

export function buildArenaLegend() {
  const legend = document.getElementById('arena-legend');
  if (!legend || !state.SIM) return;

  state.SIM.meta.robots.forEach((id: string, index: number) => {
    const color = PALETTE[index % PALETTE.length];
    const item = document.createElement('div');
    item.className = 'ali';
    item.innerHTML = `<div class="alc" style="background:${color}"></div>${robotLabel(id)}`;
    legend.appendChild(item);
  });
}
