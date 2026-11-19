import { useState } from 'react';
import type { AttackState, LiveFrame } from '../../types';
import type { FiredParams } from '../../hooks/useAttackStatus';
import { assessedChainComponents, leaderOf, robotLabel } from '../../utils/label';
import { fireFalseBrake, stopFalseBrake } from '../../api/client';
import styles from './FalseBrakeForm.module.css';

interface Props {
  frame: LiveFrame | null;
  attackState: AttackState;
  onFired: (params: FiredParams) => void;
  onStopped: (type: FiredParams['type']) => void;
}

export function FalseBrakeForm({ frame, attackState, onFired, onStopped }: Props) {
  const [targetFollower, setTargetFollower] = useState('');
  const [duration, setDuration] = useState(5);
  const [delay, setDelay] = useState(0);
  const [firing, setFiring] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState('');

  const components = assessedChainComponents(frame);
  const followers = components.flatMap((c) => (c.length > 1 ? c.slice(1) : []));

  const idle = attackState === 'idle';
  const busy = firing || stopping;
  const canFire = !busy && idle && followers.length > 0;
  const canStop = !busy && !idle;

  async function handleFire() {
    const safeDuration = Number(duration);
    const safeDelay = Number(delay);

    if (!Number.isFinite(safeDuration) || safeDuration <= 0 || safeDuration > 60) {
      setError('Duration must be 1-60 s');
      return;
    }
    if (!Number.isFinite(safeDelay) || safeDelay < 0 || safeDelay > 300) {
      setError('Delay must be 0-300 s');
      return;
    }
    if (components.length === 0) {
      setError('Platoon order unavailable');
      return;
    }

    const follower = targetFollower || followers[0] || '';
    const leader = leaderOf(follower, frame);
    if (!leader) {
      setError('Cannot resolve leader for selected follower');
      return;
    }

    setFiring(true);
    setError('');
    try {
      const result = await fireFalseBrake({
        duration_s: safeDuration,
        delay_s: safeDelay,
        follower_robot: follower,
        target_robot: leader,
      });
      if (!result.ok) {
        setError(result.error ?? 'Attack request failed');
      } else {
        onFired({ type: 'false_brake', follower, targetRobot: leader, durationS: safeDuration, delayS: safeDelay });
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed');
    } finally {
      setFiring(false);
    }
  }

  async function handleStop() {
    setStopping(true);
    setError('');
    try {
      const result = await stopFalseBrake();
      if (!result.ok) {
        setError(result.error ?? 'Stop failed');
      } else {
        onStopped('false_brake');
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed');
    } finally {
      setStopping(false);
    }
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.fields}>
        <label className={styles.fieldLabel}>
          Deceive follower
          <select
            className={`${styles.fieldInput} ${styles.fieldSelect}`}
            value={targetFollower || followers[0] || ''}
            onChange={(e) => setTargetFollower(e.target.value)}
            disabled={!idle}
          >
            {followers.length === 0 ? (
              <option value="">- no followers in platoon -</option>
            ) : (
              followers.map((r) => (
                <option key={r} value={r}>
                  {robotLabel(r)}
                </option>
              ))
            )}
          </select>
        </label>

        <label className={styles.fieldLabel}>
          Duration
          <span className={styles.fieldOpt}>(seconds, 1-60)</span>
          <input
            className={styles.fieldInput}
            type="number"
            min={1}
            max={60}
            step={1}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            disabled={!idle}
          />
        </label>

        <label className={styles.fieldLabel}>
          Start after
          <span className={styles.fieldOpt}>(seconds, 0 = immediate)</span>
          <input
            className={styles.fieldInput}
            type="number"
            min={0}
            max={300}
            step={1}
            value={delay}
            onChange={(e) => setDelay(Number(e.target.value))}
            disabled={!idle}
          />
        </label>

        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.actions}>
          <button className={`${styles.btn} ${styles.btnFire}`} onClick={() => { void handleFire(); }} disabled={!canFire}>
            {firing ? '...' : 'FIRE'}
          </button>
          <button className={`${styles.btn} ${styles.btnStop}`} onClick={() => { void handleStop(); }} disabled={!canStop}>
            {stopping ? '...' : 'STOP'}
          </button>
        </div>
      </div>
    </div>
  );
}
