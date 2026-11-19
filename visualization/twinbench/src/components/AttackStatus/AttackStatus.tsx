import type { UseAttackStatusReturn } from '../../hooks/useAttackStatus';
import { robotLabel } from '../../utils/label';
import styles from './AttackStatus.module.css';

interface Props {
  attackStatus: UseAttackStatusReturn;
}

export function AttackStatus({ attackStatus }: Props) {
  const { falseBrake: fb, velocitySpoof: vs } = attackStatus;
  const bothIdle = fb.state === 'idle' && vs.state === 'idle';

  return (
    <div className={styles.wrap}>
      <div className={styles.sectionLabel}>ATTACK STATUS</div>

      {bothIdle && <div className={styles.idle}>NO ACTIVE ATTACK</div>}

      {fb.state === 'pending' && (
        <div className={`${styles.statusBlock} ${styles.pending}`}>
          <div className={styles.statusType}>◆ FALSE BRAKE — ARMED</div>
          <div className={styles.statusCountdown}>{fb.displayFiresInS.toFixed(1)}s</div>
          <div className={styles.statusMeta}>
            fires in · target <span>{fb.follower ? robotLabel(fb.follower) : '?'}</span>
          </div>
        </div>
      )}

      {fb.state === 'active' && (
        <div className={`${styles.statusBlock} ${styles.active}`}>
          <div className={styles.statusType}>◆ FALSE BRAKE — ACTIVE</div>
          <div className={styles.statusCountdown}>{fb.displayRemainingS.toFixed(1)}s</div>
          <div className={styles.statusMeta}>
            remaining · target <span>{fb.follower ? robotLabel(fb.follower) : '?'}</span>
          </div>
        </div>
      )}

      {vs.state === 'pending' && (
        <div className={`${styles.statusBlock} ${styles.pendingVs}`}>
          <div className={styles.statusType}>◆ VELOCITY SPOOF — ARMED</div>
          <div className={styles.statusCountdown}>{vs.displayFiresInS.toFixed(1)}s</div>
          <div className={styles.statusMeta}>
            fires in
            {vs.vsMode === 'ramp' && vs.speedStart != null && vs.speedEnd != null
              ? <> · ramp <span>{vs.speedStart.toFixed(2)}</span> → <span>{vs.speedEnd.toFixed(2)} m/s</span></>
              : vs.speedMps != null && <> · <span>{vs.speedMps.toFixed(2)} m/s</span></>
            }
          </div>
        </div>
      )}

      {vs.state === 'active' && (
        <div className={`${styles.statusBlock} ${styles.activeVs}`}>
          <div className={styles.statusType}>◆ VELOCITY SPOOF — ACTIVE</div>
          <div className={styles.statusCountdown}>{vs.displayRemainingS.toFixed(1)}s</div>
          <div className={styles.statusMeta}>
            remaining
            {vs.vsMode === 'ramp' && vs.speedStart != null && vs.speedEnd != null
              ? <> · ramp <span>{vs.speedStart.toFixed(2)}</span> → <span>{vs.speedEnd.toFixed(2)}</span> · now <span>{vs.speedMps?.toFixed(2)} m/s</span></>
              : vs.speedMps != null && <> · forced <span>{vs.speedMps.toFixed(2)} m/s</span></>
            }
          </div>
        </div>
      )}
    </div>
  );
}
