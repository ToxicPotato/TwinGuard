import type { HistoryEntry } from '../../types';
import { robotLabel } from '../../utils/label';
import styles from './AttackHistory.module.css';

interface Props {
  history: HistoryEntry[];
}

function formatTime(date: Date): string {
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  const ss = String(date.getSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

const OUTCOME_LABELS: Record<HistoryEntry['outcome'], string> = {
  active: 'ACTIVE',
  completed: 'DONE',
  cancelled: 'STOPPED',
};

const TYPE_LABELS: Record<HistoryEntry['type'], string> = {
  false_brake: 'FALSE BRAKE',
  velocity_spoof: 'VEL SPOOF',
};

export function AttackHistory({ history }: Props) {
  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <div className={styles.sectionLabel}>ATTACK LOG</div>
        <div className={styles.count}>{history.length} entries</div>
      </div>

      <div className={styles.list}>
        {history.length === 0 ? (
          <div className={styles.empty}>no attacks fired this session</div>
        ) : (
          history.map((entry) => (
            <div key={entry.id} className={styles.entry}>
              <span className={styles.entryTime}>{formatTime(entry.timestamp)}</span>

              <div className={styles.entryBody}>
                <span className={styles.entryType}>{TYPE_LABELS[entry.type]}</span>
                <span className={styles.entryMeta}>
                  {entry.follower ? robotLabel(entry.follower, true) : '?'}
                  {' '}→{' '}
                  {entry.targetRobot ? robotLabel(entry.targetRobot, true) : '?'}
                  {' · '}
                  {entry.durationS}s
                  {entry.type === 'velocity_spoof' && (
                    entry.vsMode === 'ramp' && entry.speedStart != null && entry.speedEnd != null
                      ? ` · ${entry.speedStart.toFixed(2)}→${entry.speedEnd.toFixed(2)} m/s`
                      : entry.speedMps != null
                        ? ` · ${entry.speedMps.toFixed(2)} m/s`
                        : ''
                  )}
                  {entry.delayS > 0 ? ` +${entry.delayS}s` : ''}
                </span>
              </div>

              <span className={`${styles.outcomeBadge} ${styles[entry.outcome]}`}>
                {OUTCOME_LABELS[entry.outcome]}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
