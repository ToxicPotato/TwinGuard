import { useState } from 'react';
import type { AttackState, LiveFrame } from '../../types';
import type { FiredParams } from '../../hooks/useAttackStatus';
import { assessedChainComponents, leaderOf, robotLabel } from '../../utils/label';
import { fireVelocitySpoof, stopVelocitySpoof } from '../../api/client';
import styles from './VelocitySpoofForm.module.css';

interface Props {
  frame: LiveFrame | null;
  attackState: AttackState;
  onFired: (params: FiredParams) => void;
  onStopped: (type: FiredParams['type']) => void;
}

type VsMode = 'static' | 'ramp';
type RampSubMode = 'absolute' | 'delta';

function RampPreview({ from, to, duration }: { from: number; to: number; duration: number }) {
  const W = 280; const H = 48; const PAD_X = 36; const PAD_Y = 8;
  const minV = Math.min(from, to, 0);
  const maxV = Math.max(from, to, 0.01);
  const range = maxV - minV || 0.01;
  const toY = (v: number) => PAD_Y + (H - PAD_Y * 2) * (1 - (v - minV) / range);
  const x0 = PAD_X; const x1 = W - PAD_X;
  const y0 = toY(from); const y1 = toY(to);
  const baseline = toY(0);
  const isUp = to > from;
  const color = isUp ? '#00ff88' : '#00e5ff';
  const clampedBaseline = Math.min(Math.max(baseline, PAD_Y), H - PAD_Y);

  return (
    <svg className={styles.rampPreview} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id="ramp-grad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={color} stopOpacity="0.15" />
          <stop offset="100%" stopColor={color} stopOpacity="0.05" />
        </linearGradient>
      </defs>
      <line x1={x0} y1={clampedBaseline} x2={x1} y2={clampedBaseline} stroke="var(--bdr2)" strokeWidth="1" strokeDasharray="2 3" />
      <polygon
        points={`${x0},${clampedBaseline} ${x0},${y0} ${x1},${y1} ${x1},${clampedBaseline}`}
        fill="url(#ramp-grad)"
      />
      <line x1={x0} y1={y0} x2={x1} y2={y1} stroke={color} strokeWidth="1.5" />
      <circle cx={x0} cy={y0} r={3} fill={color} />
      <circle cx={x1} cy={y1} r={3} fill={color} />
      <text x={x0} y={y0 - 4} textAnchor="middle" fill={color} fontSize="8" fontFamily="var(--fmono)">{from.toFixed(1)}</text>
      <text x={x1} y={y1 - 4} textAnchor="middle" fill={color} fontSize="8" fontFamily="var(--fmono)">{to.toFixed(1)}</text>
      <text x={W / 2} y={H - 1} textAnchor="middle" fill="#5e7f9e" fontSize="7" fontFamily="var(--fmono)">{duration}s</text>
    </svg>
  );
}

function StaticPreview({ speed, duration }: { speed: number; duration: number }) {
  const W = 280; const H = 48; const PAD_X = 36; const PAD_Y = 8;
  const color = speed < 0 ? '#ff9100' : '#00e5ff';
  const lineY = speed >= 0
    ? PAD_Y + (H - PAD_Y * 2) * 0.35
    : PAD_Y + (H - PAD_Y * 2) * 0.65;

  return (
    <svg className={styles.rampPreview} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id="flat-grad" x1="0" y1={speed >= 0 ? '0' : '1'} x2="0" y2={speed >= 0 ? '1' : '0'}>
          <stop offset="0%" stopColor={color} stopOpacity="0.12" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <line x1={PAD_X} y1={H / 2} x2={W - PAD_X} y2={H / 2} stroke="var(--bdr2)" strokeWidth="1" strokeDasharray="2 3" />
      <rect x={PAD_X} y={Math.min(lineY, H / 2)} width={W - PAD_X * 2} height={Math.abs(lineY - H / 2)} fill="url(#flat-grad)" />
      <line x1={PAD_X} y1={lineY} x2={W - PAD_X} y2={lineY} stroke={color} strokeWidth="1.5" strokeDasharray="4 2" />
      <text x={W / 2} y={lineY - 4} textAnchor="middle" fill={color} fontSize="8" fontFamily="var(--fmono)">{speed.toFixed(2)} m/s</text>
      <text x={W / 2} y={H - 1} textAnchor="middle" fill="#5e7f9e" fontSize="7" fontFamily="var(--fmono)">{duration}s</text>
    </svg>
  );
}

export function VelocitySpoofForm({ frame, attackState, onFired, onStopped }: Props) {
  const [vsMode, setVsMode] = useState<VsMode>('static');
  const [rampSubMode, setRampSubMode] = useState<RampSubMode>('absolute');
  const [targetFollower, setTargetFollower] = useState('');
  const [speedMps, setSpeedMps] = useState(0.5);
  const [speedStart, setSpeedStart] = useState(2.0);
  const [speedEnd, setSpeedEnd] = useState(0.0);
  const [speedDelta, setSpeedDelta] = useState(-2.0);
  const [duration, setDuration] = useState(10);
  const [delay, setDelay] = useState(0);
  const [allowReverse, setAllowReverse] = useState(false);
  const [firing, setFiring] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState('');

  const components = assessedChainComponents(frame);
  const followers = components.flatMap((c) => (c.length > 1 ? c.slice(1) : []));

  const idle = attackState === 'idle';
  const busy = firing || stopping;
  const canFire = !busy && idle && followers.length > 0;
  const canStop = !busy && !idle;

  const selectedFollower = targetFollower || followers[0] || '';
  const leader = leaderOf(selectedFollower, frame);
  const leaderSpeed = leader != null ? (frame?.robots?.[leader]?.v ?? null) : null;

  const speedMin = allowReverse ? undefined : 0;
  const previewStart = rampSubMode === 'delta' && leaderSpeed != null ? leaderSpeed : speedStart;
  const previewEnd = rampSubMode === 'delta' && leaderSpeed != null ? leaderSpeed + speedDelta : speedEnd;

  function validate(): string | null {
    const d = Number(duration);
    if (!Number.isFinite(d) || d <= 0 || d > 120) return 'Duration must be 1-120 s';
    const dl = Number(delay);
    if (!Number.isFinite(dl) || dl < 0 || dl > 300) return 'Delay must be 0-300 s';

    if (vsMode === 'static') {
      const s = Number(speedMps);
      if (!Number.isFinite(s)) return 'Speed must be a number';
      if (!allowReverse && s < 0) return 'Enable "allow reverse" to use negative speeds';
      if (Math.abs(s) > 20) return 'Speed magnitude must be <= 20 m/s';
    } else if (rampSubMode === 'absolute') {
      const s = Number(speedStart);
      const e = Number(speedEnd);
      if (!Number.isFinite(s) || !Number.isFinite(e)) return 'Start and end speeds must be numbers';
      if (!allowReverse && (s < 0 || e < 0)) return 'Enable "allow reverse" to use negative speeds';
      if (Math.abs(s) > 20 || Math.abs(e) > 20) return 'Speed magnitudes must be <= 20 m/s';
    } else {
      const delta = Number(speedDelta);
      if (!Number.isFinite(delta)) return 'Delta must be a number';
      if (Math.abs(delta) > 20) return 'Delta magnitude must be <= 20 m/s';
      if (leaderSpeed == null) return 'No live speed data for leader - cannot use delta mode';
      const endSpeed = leaderSpeed + delta;
      if (!allowReverse && endSpeed < 0) return `Computed end speed (${endSpeed.toFixed(2)} m/s) is negative - enable "allow reverse" or adjust delta`;
    }
    return null;
  }

  async function handleFire() {
    const err = validate();
    if (err) { setError(err); return; }
    if (components.length === 0) { setError('Platoon order unavailable'); return; }
    if (!leader) { setError('Cannot resolve leader for selected follower'); return; }

    let resolvedStart: number | null = null;
    let resolvedEnd: number | null = null;
    let resolvedSpeed: number | null = null;

    if (vsMode === 'static') {
      resolvedSpeed = Number(speedMps);
    } else if (rampSubMode === 'absolute') {
      resolvedStart = Number(speedStart);
      resolvedEnd = Number(speedEnd);
    } else {
      resolvedStart = leaderSpeed!;
      resolvedEnd = leaderSpeed! + Number(speedDelta);
    }

    setFiring(true);
    setError('');
    try {
      const result = await fireVelocitySpoof({
        mode: vsMode,
        speed_mps: vsMode === 'static' ? resolvedSpeed : null,
        speed_start: vsMode === 'ramp' ? resolvedStart : null,
        speed_end: vsMode === 'ramp' ? resolvedEnd : null,
        duration_s: Number(duration),
        delay_s: Number(delay),
        follower_robot: selectedFollower,
        target_robot: leader,
      });
      if (!result.ok) {
        setError(result.error ?? 'Attack request failed');
      } else {
        onFired({
          type: 'velocity_spoof',
          follower: selectedFollower,
          targetRobot: leader,
          durationS: Number(duration),
          delayS: Number(delay),
          vsMode,
          speedMps: vsMode === 'static' ? resolvedSpeed ?? undefined : undefined,
          speedStart: vsMode === 'ramp' ? (resolvedStart ?? undefined) : undefined,
          speedEnd: vsMode === 'ramp' ? (resolvedEnd ?? undefined) : undefined,
        });
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
      const result = await stopVelocitySpoof();
      if (!result.ok) {
        setError(result.error ?? 'Stop failed');
      } else {
        onStopped('velocity_spoof');
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed');
    } finally {
      setStopping(false);
    }
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.modeToggle}>
        <button
          className={`${styles.modeBtn} ${vsMode === 'static' ? styles.active : ''}`}
          onClick={() => setVsMode('static')}
          disabled={!idle}
        >FIXED</button>
        <button
          className={`${styles.modeBtn} ${vsMode === 'ramp' ? styles.active : ''}`}
          onClick={() => setVsMode('ramp')}
          disabled={!idle}
        >RAMP</button>
      </div>

      <div className={styles.fields}>
        <label className={styles.fieldLabel}>
          Deceive follower
          <select
            className={`${styles.fieldInput} ${styles.fieldSelect}`}
            value={selectedFollower}
            onChange={(e) => setTargetFollower(e.target.value)}
            disabled={!idle}
          >
            {followers.length === 0 ? (
              <option value="">- no followers in platoon -</option>
            ) : (
              followers.map((r) => (
                <option key={r} value={r}>{robotLabel(r)}</option>
              ))
            )}
          </select>
        </label>

        {leader && (
          <div className={styles.hint}>
            injects into <span>{robotLabel(selectedFollower, true)}</span>'s leader feed -
            tampers <span>{robotLabel(leader, true)}</span>
            {leaderSpeed != null && (
              <> - now <span>{leaderSpeed.toFixed(2)} m/s</span></>
            )}
          </div>
        )}

        {vsMode === 'static' ? (
          <label className={styles.fieldLabel}>
            Force velocity
            <span className={styles.fieldOpt}>(m/s{allowReverse ? ' - negative = reverse' : ' - 0 = stopped'})</span>
            <input
              className={styles.fieldInput}
              type="number"
              min={speedMin}
              max={20}
              step={0.1}
              value={speedMps}
              onChange={(e) => setSpeedMps(Number(e.target.value))}
              disabled={!idle}
            />
          </label>
        ) : (
          <>
            <div className={styles.subToggle}>
              <button
                className={`${styles.subBtn} ${rampSubMode === 'absolute' ? styles.active : ''}`}
                onClick={() => setRampSubMode('absolute')}
                disabled={!idle}
              >ABSOLUTE</button>
              <button
                className={`${styles.subBtn} ${rampSubMode === 'delta' ? styles.active : ''}`}
                onClick={() => setRampSubMode('delta')}
                disabled={!idle}
              >DELTA</button>
            </div>

            {rampSubMode === 'absolute' ? (
              <div className={styles.rampRow}>
                <label className={styles.fieldLabel}>
                  From (m/s)
                  <input
                    className={styles.fieldInput}
                    type="number"
                    min={speedMin}
                    max={20}
                    step={0.1}
                    value={speedStart}
                    onChange={(e) => setSpeedStart(Number(e.target.value))}
                    disabled={!idle}
                  />
                </label>
                <span className={styles.rampArrow}>-&gt;</span>
                <label className={styles.fieldLabel}>
                  To (m/s)
                  <input
                    className={styles.fieldInput}
                    type="number"
                    min={speedMin}
                    max={20}
                    step={0.1}
                    value={speedEnd}
                    onChange={(e) => setSpeedEnd(Number(e.target.value))}
                    disabled={!idle}
                  />
                </label>
              </div>
            ) : (
              <div className={styles.deltaBlock}>
                <label className={styles.fieldLabel}>
                  Speed change (Delta m/s)
                  <span className={styles.fieldOpt}>(positive = faster - negative = slower)</span>
                  <input
                    className={styles.fieldInput}
                    type="number"
                    step={0.5}
                    value={speedDelta}
                    onChange={(e) => setSpeedDelta(Number(e.target.value))}
                    disabled={!idle}
                  />
                </label>
                {leaderSpeed != null ? (
                  <>
                    <div className={styles.deltaHint}>
                      <span className={styles.deltaFrom}>{leaderSpeed.toFixed(2)}</span>
                      <span className={styles.deltaArrow}>-&gt;</span>
                      <span className={`${styles.deltaTo} ${(leaderSpeed + speedDelta) < 0 ? styles.deltaWarn : ''}`}>
                        {(leaderSpeed + speedDelta).toFixed(2)} m/s
                      </span>
                      <span className={styles.deltaMeta}>
                        {delay > 0 ? 'at arm time' : 'at fire time'}
                      </span>
                    </div>
                    {delay > 0 && (
                      <div className={styles.deltaStaleWarn}>
                        Speed sampled now, not at fire time. Leader may change speed during the {delay}s delay.
                      </div>
                    )}
                  </>
                ) : (
                  <div className={styles.deltaNoData}>no live leader speed - cannot use delta mode</div>
                )}
              </div>
            )}
          </>
        )}

        {vsMode === 'static' ? (
          <StaticPreview speed={speedMps} duration={duration} />
        ) : (
          <RampPreview from={previewStart} to={previewEnd} duration={duration} />
        )}

        <label className={styles.reverseToggle}>
          <input
            type="checkbox"
            checked={allowReverse}
            onChange={(e) => setAllowReverse(e.target.checked)}
            disabled={!idle}
          />
          <span>Allow reverse (negative m/s)</span>
        </label>

        <label className={styles.fieldLabel}>
          Duration
          <span className={styles.fieldOpt}>(seconds, 1-120)</span>
          <input
            className={styles.fieldInput}
            type="number"
            min={1}
            max={120}
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
          <button
            className={`${styles.btn} ${styles.btnFire}`}
            onClick={() => { void handleFire(); }}
            disabled={!canFire}
          >
            {firing ? '...' : 'FIRE'}
          </button>
          <button
            className={`${styles.btn} ${styles.btnStop}`}
            onClick={() => { void handleStop(); }}
            disabled={!canStop}
          >
            {stopping ? '...' : 'STOP'}
          </button>
        </div>
      </div>
    </div>
  );
}
