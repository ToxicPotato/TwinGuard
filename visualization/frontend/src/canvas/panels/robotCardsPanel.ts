import { robotFrame } from '../constants';
import { state } from '../state';
import { buildRobotCard, setCardDetailLevel, updateRobotCard } from './robotCard';
import { buildTimeline } from './timeline';
import { robotLabel, chainComponents } from './shared';

type SortOrder = 'definition' | 'chain' | 'state' | 'id';

// ── State priority for the 'state' sort order ─────────────────────────────────
// Lower number = higher priority (appears nearer the top).
// PLATOONING (3) → ALIGNING (2) → CANDIDATE (1) → AUTONOMOUS (0) → RECOVERY (4)
const STATE_SORT_PRIORITY: Record<number, number> = { 3: 0, 2: 1, 1: 2, 0: 3, 4: 4 };

// Sorted robot ID list — shared between build and update so both iterate the same order.
let _sortedIds: string[] = [];

function computeSortedIds(ids: string[], order: SortOrder, frame: any): string[] {
  if (order === 'id') return ids.slice().sort();

  if (order === 'chain') {
    const chainFlat = frame ? chainComponents(frame).flat() : [];
    return [
      ...chainFlat.filter(id => ids.includes(id)),
      ...ids.filter(id => !chainFlat.includes(id)),
    ];
  }

  if (order === 'state') {
    return ids.slice().sort((a, b) => {
      const stA = frame ? (robotFrame(frame, a)?.st ?? 0) : 0;
      const stB = frame ? (robotFrame(frame, b)?.st ?? 0) : 0;
      const pA = STATE_SORT_PRIORITY[Math.min(stA, 4)] ?? 3;
      const pB = STATE_SORT_PRIORITY[Math.min(stB, 4)] ?? 3;
      if (pA !== pB) return pA - pB;
      return ids.indexOf(a) - ids.indexOf(b);  // preserve definition order as tiebreak
    });
  }

  return ids.slice();  // 'definition'
}

export function buildRobotCardsPanel({
  container,
  robotIds,
  palette,
  focusedRobotId,
  hiddenRobots,
  onToggleVisibility,
  onSortChange,
}: {
  container: HTMLElement;
  robotIds: string[];
  palette: string[];
  focusedRobotId: string | null;
  hiddenRobots: Set<string>;
  onToggleVisibility: (id: string) => void;
  onSortChange: () => void;
}) {
  // Panel header: label + global detail toggles + sort selector
  const header = document.createElement('div');
  header.className = 'rcards-panel-header';
  header.innerHTML = `
    <span class="rcards-panel-label">ROBOTS</span>
    <div class="rcards-global-detail-btns" title="Set detail level for all cards">
      <button class="rcards-global-detail-btn" data-level="full"    title="All full">F</button>
      <button class="rcards-global-detail-btn" data-level="compact" title="All compact">C</button>
      <button class="rcards-global-detail-btn" data-level="minimal" title="All minimal">M</button>
    </div>
    <select class="rcards-sort-select" title="Card sort order">
      <option value="definition">DEF</option>
      <option value="chain">CHAIN</option>
      <option value="state">STATE</option>
      <option value="id">ID</option>
    </select>
  `;
  container.appendChild(header);

  const sortSel = header.querySelector<HTMLSelectElement>('.rcards-sort-select')!;
  sortSel.value = state.cardSortOrder;
  sortSel.onchange = () => {
    state.cardSortOrder = sortSel.value as SortOrder;
    onSortChange();
  };

  header.querySelectorAll<HTMLButtonElement>('.rcards-global-detail-btn').forEach(btn => {
    btn.onclick = () => {
      const level = btn.dataset.level as 'full' | 'compact' | 'minimal';
      _sortedIds.forEach(id => setCardDetailLevel(id, level));
    };
  });

  // Compute and store sort order (no frame available at build time — use definition order
  // for chain/state on initial build; updateRobotCardsPanel will use frame-accurate order).
  const currentFrame = state.SIM ? state.SIM.frames[state.fi] : null;
  _sortedIds = computeSortedIds(robotIds, state.cardSortOrder, currentFrame);

  // Scroll wrapper — cards live here so the header stays pinned at top of the flex column.
  const scrollArea = document.createElement('div');
  scrollArea.className = 'rcards-scroll-area';
  container.appendChild(scrollArea);

  _sortedIds.forEach(id => {
    const paletteIndex = state.SIM ? state.SIM.meta.robots.indexOf(id) : -1;
    scrollArea.appendChild(buildRobotCard({
      id,
      color: palette[(paletteIndex >= 0 ? paletteIndex : 0) % palette.length],
      label: robotLabel(id),
      isFocused: focusedRobotId === id,
      isHidden: hiddenRobots.has(id),
      onToggleVisibility,
    }));
  });
}

export function buildRobotCardTimelines(robotIds: string[]) {
  robotIds.forEach(buildTimeline);
}

export function updateRobotCardsPanel({
  robotIds,
  frame,
  chainIndexMap,
  previousStates,
  isPlaying,
  isScrubbing,
  onTransition,
  updateTimeline,
}: {
  robotIds: string[];
  frame: any;
  chainIndexMap: Record<string, number>;
  previousStates: Record<string, number | undefined>;
  isPlaying: boolean;
  isScrubbing: boolean;
  onTransition: (id: string, nextState: number) => void;
  updateTimeline: (id: string) => void;
}) {
  // Recompute sort each frame so chain/state orders stay current.
  // For definition/id orders this is a no-op (stable output).
  const prevOrder = _sortedIds.join(',');
  _sortedIds = computeSortedIds(robotIds, state.cardSortOrder, frame);

  // Reorder DOM cards when the sort result changes. appendChild on an existing
  // child moves it to the end, so iterating in sorted order is sufficient.
  if (_sortedIds.join(',') !== prevOrder) {
    const scrollArea = document.querySelector<HTMLElement>('.rcards-scroll-area');
    if (scrollArea) {
      _sortedIds.forEach(id => {
        const card = document.getElementById(id + '-card');
        if (card) scrollArea.appendChild(card);
      });
    }
  }

  _sortedIds.forEach(id => {
    const robot = robotFrame(frame, id);
    if (!robot) return;

    const chainIndex = chainIndexMap[id] ?? 0;
    previousStates[id] = updateRobotCard({
      id,
      robot,
      chainIndex,
      previousState: previousStates[id],
      isPlaying,
      isScrubbing,
      onTransition,
      updateTimeline,
    });
  });
}
