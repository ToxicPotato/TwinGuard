import type { LiveFrame } from '../../types';
import { robotLabel, STATE_COLORS, STATE_LABELS } from '../../utils/label';
import { spoofKindLabel } from '../../utils/scenario';
import styles from './RobotList.module.css';

interface AttackLink {
  targetRobot: string;
  follower: string;
  state: 'active' | 'pending';
}

interface Props {
  frame: LiveFrame | null;
  robotIds: string[];
  attacks: AttackLink[];
}

export function RobotList({ frame, robotIds, attacks }: Props) {
  if (robotIds.length === 0) {
    return (
      <div className={styles.wrap}>
        <div className={styles.sectionLabel}>ROBOTS</div>
        <div className={styles.empty}>WAITING FOR LIVE DATA</div>
      </div>
    );
  }

  const activeFollowers  = new Set(attacks.filter(a => a.state === 'active').map(a => a.follower));
  const pendingFollowers = new Set(attacks.filter(a => a.state === 'pending').map(a => a.follower));
  const spoofedSources   = new Set(attacks.map(a => a.targetRobot));

  return (
    <div className={styles.wrap}>
      <div className={styles.sectionLabel}>ROBOTS — {robotIds.length} ONLINE</div>
      <div className={styles.grid}>
        {robotIds.map((id) => {
          const robot = frame?.robots?.[id];
          const st = robot?.st ?? 0;
          const stColor = STATE_COLORS[Math.min(st, STATE_COLORS.length - 1)];
          const stLabel = STATE_LABELS[Math.min(st, STATE_LABELS.length - 1)];

          const isActiveFollower  = activeFollowers.has(id);
          const isPendingFollower = !isActiveFollower && pendingFollowers.has(id);
          const isSpoofSource     = spoofedSources.has(id);
          const velocitySpoof = frame?.scenario?.per_robot?.[id]?.velocity_spoof ?? false;
          const velocitySpoofKind = frame?.scenario?.per_robot?.[id]?.velocity_spoof_kind ?? null;
          const speed = robot?.v != null ? robot.v.toFixed(2) : '—';

          const cardClass = [
            styles.card,
            isActiveFollower  ? styles.attacked  : '',
            isPendingFollower ? styles.armed      : '',
            isSpoofSource     ? styles.spoofSrc   : '',
          ].filter(Boolean).join(' ');

          return (
            <div key={id} className={cardClass}>
              <div className={styles.cardTop}>
                <span className={styles.robotId}>{robotLabel(id, true)}</span>
                <span
                  className={styles.stateBadge}
                  style={{ color: stColor, borderColor: `${stColor}66` }}
                >
                  {stLabel}
                </span>
              </div>

              <div className={styles.cardRow}>
                <span className={styles.rowLabel}>SPEED</span>
                <span className={styles.rowValue}>{speed} m/s</span>
              </div>

              {isActiveFollower && (
                <div className={styles.attackTag}>UNDER ATTACK</div>
              )}
              {isPendingFollower && (
                <div className={styles.armedTag}>ARMED</div>
              )}
              {isSpoofSource && (
                <div className={styles.spoofTag}>SIG SPOOFED</div>
              )}
              {velocitySpoof && (
                <div className={styles.scenarioWarnTag}>
                  {velocitySpoofKind ? `VEL ${spoofKindLabel(velocitySpoofKind)}` : 'VEL SPOOF'}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

