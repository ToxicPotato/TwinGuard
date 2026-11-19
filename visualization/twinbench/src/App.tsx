import { useState } from 'react';
import { useLiveSocket } from './hooks/useLiveSocket';
import { useAttackStatus } from './hooks/useAttackStatus';
import { Header } from './components/Header/Header';
import { PlatoonDiagram } from './components/PlatoonDiagram/PlatoonDiagram';
import { RobotList } from './components/RobotList/RobotList';
import { AttackStatus } from './components/AttackStatus/AttackStatus';
import { AttackPanel } from './components/AttackPanel/AttackPanel';
import { AttackHistory } from './components/AttackHistory/AttackHistory';
import { SettingsDrawer } from './components/SettingsDrawer/SettingsDrawer';
import { RiskPanel } from './components/RiskPanel/RiskPanel';
import { RecordingControl } from './components/RecordingControl/RecordingControl';
import styles from './App.module.css';
import { useRecordingStatus } from './hooks/useRecordingStatus';

type Tab = 'attack' | 'risk';

export function App() {
  const { latestFrame, robotIds, wsStatus, reconnect } = useLiveSocket();
  const attackStatus = useAttackStatus();
  const recordingStatus = useRecordingStatus();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>('attack');
  const [riskRefreshKey, setRiskRefreshKey] = useState(0);

  const anyAttackState =
    attackStatus.falseBrake.state === 'active' || attackStatus.velocitySpoof.state === 'active' ? 'active' :
    attackStatus.falseBrake.state === 'pending' || attackStatus.velocitySpoof.state === 'pending' ? 'pending' :
    'idle';

  // Each active/pending attack is a (targetRobot → follower) link on the communication channel.
  // targetRobot is the leader whose signal is being spoofed — it is NOT being attacked.
  // follower is the robot receiving false data and responding to it.
  const attacks: Array<{ targetRobot: string; follower: string; state: 'active' | 'pending' }> = [];
  for (const track of [attackStatus.falseBrake, attackStatus.velocitySpoof]) {
    if ((track.state === 'active' || track.state === 'pending') && track.targetRobot && track.follower) {
      attacks.push({ targetRobot: track.targetRobot, follower: track.follower, state: track.state });
    }
  }

  return (
    <div className={styles.shell}>
      <Header wsStatus={wsStatus} attackState={anyAttackState} onSettingsOpen={() => setSettingsOpen(true)} />

      <nav className={styles.tabNav}>
        <button
          className={`${styles.tabBtn} ${activeTab === 'attack' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('attack')}
        >
          Attack
        </button>
        <button
          className={`${styles.tabBtn} ${activeTab === 'risk' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('risk')}
        >
          Risk
        </button>
      </nav>

      {activeTab === 'attack' ? (
        <div className={styles.attackView}>
          <div className={styles.attackLeft}>
            <PlatoonDiagram
              frame={latestFrame}
              robotIds={robotIds}
              attacks={attacks}
            />
            <main className={styles.main}>
              <div className={styles.left}>
                <RobotList
                  frame={latestFrame}
                  robotIds={robotIds}
                  attacks={attacks}
                />
              </div>
              <div className={styles.attackForms}>
                <AttackPanel
                  frame={latestFrame}
                  attackStatus={attackStatus}
                />
              </div>
            </main>
          </div>
          <aside className={styles.attackRail}>
            <div className={styles.attackSide}>
              <RecordingControl
                recording={recordingStatus.recording}
                loading={recordingStatus.loading}
                syncing={recordingStatus.syncing}
                saving={recordingStatus.saving}
                error={recordingStatus.error}
                wsStatus={wsStatus}
                onStart={recordingStatus.start}
                onStop={async () => {
                  const result = await recordingStatus.stop();
                  if (result) {
                    setRiskRefreshKey((current) => current + 1);
                  }
                }}
              />
              <AttackStatus attackStatus={attackStatus} />
              <AttackHistory history={attackStatus.history} />
            </div>
          </aside>
        </div>
      ) : (
        <div className={styles.riskView}>
          <RiskPanel refreshKey={riskRefreshKey} />
        </div>
      )}

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onReconnect={reconnect}
      />
    </div>
  );
}
