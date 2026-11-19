import { useState } from 'react';
import type { LiveFrame } from '../../types';
import type { FiredParams, UseAttackStatusReturn } from '../../hooks/useAttackStatus';
import { FalseBrakeForm } from '../FalseBrakeForm/FalseBrakeForm';
import { VelocitySpoofForm } from '../VelocitySpoofForm/VelocitySpoofForm';
import styles from './AttackPanel.module.css';

type Tab = 'false_brake' | 'velocity_spoof';

interface Props {
  frame: LiveFrame | null;
  attackStatus: UseAttackStatusReturn;
}

export function AttackPanel({ frame, attackStatus }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('false_brake');

  // If one attack goes active, auto-switch to its tab so the operator sees it
  const fbNonIdle = attackStatus.falseBrake.state !== 'idle';
  const vsNonIdle = attackStatus.velocitySpoof.state !== 'idle';

  const onFired = (params: FiredParams) => attackStatus.recordFired(params);
  const onStopped = (type: FiredParams['type']) => attackStatus.recordStopped(type);

  return (
    <div className={styles.wrap}>
      <div className={styles.tabBar}>
        <button
          className={`${styles.tab} ${activeTab === 'false_brake' ? styles.tabActive : ''} ${fbNonIdle ? styles.tabLive : ''}`}
          onClick={() => setActiveTab('false_brake')}
        >
          FALSE BRAKE
          {fbNonIdle && (
            <span className={`${styles.tabDot} ${attackStatus.falseBrake.state === 'active' ? styles.dotActive : styles.dotPending}`} />
          )}
        </button>
        <button
          className={`${styles.tab} ${activeTab === 'velocity_spoof' ? styles.tabActive : ''} ${vsNonIdle ? styles.tabLive : ''}`}
          onClick={() => setActiveTab('velocity_spoof')}
        >
          VELOCITY SPOOF
          {vsNonIdle && (
            <span className={`${styles.tabDot} ${attackStatus.velocitySpoof.state === 'active' ? styles.dotActive : styles.dotPending}`} />
          )}
        </button>
      </div>

      <div className={styles.body}>
        {activeTab === 'false_brake' ? (
          <FalseBrakeForm
            frame={frame}
            attackState={attackStatus.falseBrake.state}
            onFired={onFired}
            onStopped={onStopped}
          />
        ) : (
          <VelocitySpoofForm
            frame={frame}
            attackState={attackStatus.velocitySpoof.state}
            onFired={onFired}
            onStopped={onStopped}
          />
        )}
      </div>
    </div>
  );
}
