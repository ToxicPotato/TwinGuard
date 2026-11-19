import { useEffect, useState } from 'react';
import type { RecordingStatus, WsStatus } from '../../types';
import styles from './RecordingControl.module.css';

interface Props {
  recording: RecordingStatus;
  loading: boolean;
  syncing: boolean;
  saving: boolean;
  error: string | null;
  wsStatus: WsStatus;
  onStart: (name?: string) => Promise<void>;
  onStop: () => Promise<void>;
}

function formatClock(startedAt?: number): string {
  if (!startedAt) return '--';
  return new Date(startedAt * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function RecordingControl({ recording, loading, syncing, saving, error, wsStatus, onStart, onStop }: Props) {
  const [name, setName] = useState('');
  const startDisabled = loading || saving;
  const stopDisabled = loading || saving;

  useEffect(() => {
    if (!recording.active) setName('');
  }, [recording.active]);

  return (
    <section className={styles.wrap}>
      <div className={styles.header}>
        <div className={styles.sectionLabel}>SESSION RECORDING</div>
        <div className={styles.headerState}>
          {loading || syncing ? 'SYNCING' : wsStatus === 'connected' ? 'LIVE' : 'OFFLINE'}
        </div>
      </div>

      <div className={`${styles.statusRow} ${recording.active ? styles.active : styles.idle}`}>
        <span className={styles.statusDot} />
        <span className={styles.statusText}>{recording.active ? 'RECORDING' : 'IDLE'}</span>
      </div>

      <div className={styles.metaGrid}>
        <div className={styles.metaBlock}>
          <span className={styles.metaLabel}>Name</span>
          <span className={styles.metaValue}>
            {recording.active ? (recording.name?.trim() || 'Untitled capture') : 'Ready'}
          </span>
        </div>
        <div className={styles.metaBlock}>
          <span className={styles.metaLabel}>Started</span>
          <span className={styles.metaValue}>{recording.active ? formatClock(recording.started_at) : '--'}</span>
        </div>
      </div>

      {!recording.active && (
        <label className={styles.fieldLabel}>
          Capture name <span className={styles.optional}>optional</span>
          <input
            className={styles.fieldInput}
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="attack-session-01"
            maxLength={80}
            disabled={startDisabled}
          />
        </label>
      )}

      {recording.active && (
        <div className={styles.liveNote}>
          <span>{recording.run_id.slice(0, 8)}</span> · {recording.frame_count} frames
        </div>
      )}

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.actions}>
        {!recording.active ? (
          <button className={`${styles.actionBtn} ${styles.startBtn}`} onClick={() => void onStart(name)} disabled={startDisabled}>
            {loading ? 'SYNCING' : saving ? 'STARTING' : 'START REC'}
          </button>
        ) : (
          <button className={`${styles.actionBtn} ${styles.stopBtn}`} onClick={() => void onStop()} disabled={stopDisabled}>
            {loading ? 'SYNCING' : saving ? 'STOPPING' : 'STOP REC'}
          </button>
        )}
      </div>
    </section>
  );
}
