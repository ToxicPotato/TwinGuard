import { state } from '../state';
import { buildTwinPlatoonCard, updateTwinPlatoonCard } from './twinPlatoonCard';
import { buildTwinRobotCard, syncTwinRobotCardTab, updateTwinRobotCard } from './twinRobotTabs';
import { robotLabel } from './shared';

const twinRobotTabs: Record<string, 'lr' | 'hr'> = {};

export function buildTwinCardsPanel({
  container,
  robotIds,
  palette,
  focusedRobotId,
  onTabChange,
}: {
  container: HTMLElement;
  robotIds: string[];
  palette: string[];
  focusedRobotId: string | null;
  onTabChange: (id: string, tab: 'lr' | 'hr') => void;
}) {
  container.appendChild(buildTwinPlatoonCard(!!focusedRobotId));

  robotIds.forEach(id => {
    const paletteIndex = state.SIM ? state.SIM.meta.robots.indexOf(id) : -1;
    if (!twinRobotTabs[id]) twinRobotTabs[id] = 'lr';
    container.appendChild(buildTwinRobotCard({
      id,
      color: palette[(paletteIndex >= 0 ? paletteIndex : 0) % palette.length],
      label: robotLabel(id),
      activeTab: twinRobotTabs[id],
      onTabChange,
    }));
  });
}

export function updateTwinCardsPanel({ frame, robotIds }: { frame: any; robotIds: string[]; }) {
  const focusSummary = updateTwinPlatoonCard(frame);
  robotIds.forEach(id => updateTwinRobotCard(id, frame, twinRobotTabs[id] || 'lr'));
  return focusSummary;
}

export function setTwinRobotTab(id: string, tab: 'lr' | 'hr') {
  twinRobotTabs[id] = tab;
  syncTwinRobotCardTab(id, tab);
  if (state.SIM) updateTwinRobotCard(id, state.SIM.frames[state.fi], tab);
}
