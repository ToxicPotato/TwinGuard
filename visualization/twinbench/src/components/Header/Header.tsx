import type { AttackState, WsStatus } from '../../types';
import styles from './Header.module.css';

interface Props {
  wsStatus: WsStatus;
  attackState: AttackState;
  onSettingsOpen: () => void;
}

const WS_LABELS: Record<WsStatus, string> = {
  connecting: 'CONNECTING',
  connected: 'LIVE',
  disconnected: 'OFFLINE',
};

const ATTACK_LABELS: Record<AttackState, string> = {
  idle: 'STANDBY',
  pending: 'ARMED',
  active: 'ACTIVE',
};

export function Header({ wsStatus, attackState, onSettingsOpen }: Props) {
  return (
    <header className={styles.hdr}>
      <div className={styles.logo}>
        <img className={styles.logoIcon} src="/header-shield.svg" alt="" aria-hidden="true" />
        TWINGUARD
      </div>

      <span className={styles.pageBadge}>TWINBENCH</span>

      <div className={styles.spacer} />

      <div className={styles.indicators}>
        <div className={styles.wsBadge}>
          <span className={`${styles.wsDot} ${styles[wsStatus]}`} />
          WS · {WS_LABELS[wsStatus]}
        </div>

        <div className={`${styles.attackChip} ${styles[attackState]}`}>
          ATK · {ATTACK_LABELS[attackState]}
        </div>

        <button
          className={styles.settingsBtn}
          onClick={onSettingsOpen}
          aria-label="Open settings"
          title="Settings"
        >
          {/* Gear icon */}
          <svg viewBox="0 0 20 20" fill="none" width="14" height="14">
            <circle cx="10" cy="10" r="3" stroke="currentColor" strokeWidth="1.5" />
            <path
              d="M10 2v2M10 16v2M2 10h2M16 10h2M4.22 4.22l1.42 1.42M14.36 14.36l1.42 1.42M4.22 15.78l1.42-1.42M14.36 5.64l1.42-1.42"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
    </header>
  );
}
