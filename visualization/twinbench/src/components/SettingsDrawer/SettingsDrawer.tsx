import { useState, useEffect, useCallback } from 'react';
import type { MqttConfig } from '../../types';
import { fetchMqttConfig, patchMqttConfig, testMqttConnection } from '../../api/client';
import styles from './SettingsDrawer.module.css';

interface Props {
  open: boolean;
  onClose: () => void;
  onReconnect: () => void;
}

type TestResult = { ok: boolean; latency_ms?: number; error?: string } | null;

export function SettingsDrawer({ open, onClose, onReconnect }: Props) {
  const [host, setHost] = useState('');
  const [port, setPort] = useState(1883);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [passwordTouched, setPasswordTouched] = useState(false);
  const [topic, setTopic] = useState('vehicle/+/#');
  const [liveHz, setLiveHz] = useState(20);
  const [rollingBufferMaxFrames, setRollingBufferMaxFrames] = useState(5000);

  const [mqttDirty, setMqttDirty] = useState(false);
  const [remoteNotice, setRemoteNotice] = useState('');
  const [testing, setTesting] = useState(false);
  const [applying, setApplying] = useState(false);
  const [testResult, setTestResult] = useState<TestResult>(null);

  const applyToForm = useCallback((data: MqttConfig) => {
    setHost(data.host);
    setPort(data.port);
    setUsername(data.username ?? '');
    setPassword('');
    setPasswordTouched(false);
    setTopic(data.topic);
    setLiveHz(data.live_hz);
    setRollingBufferMaxFrames(data.rolling_buffer_max_frames);
    setMqttDirty(false);
    setRemoteNotice('');
  }, []);

  // Sync incoming WS config broadcast (same event fired by useLiveSocket)
  useEffect(() => {
    const handler = (e: Event) => {
      const data = (e as CustomEvent<MqttConfig>).detail;
      if (!data) return;
      if (!open || !mqttDirty) {
        applyToForm(data);
      } else {
        setRemoteNotice('Settings were updated in another client. Save or reopen to reload.');
      }
    };
    window.addEventListener('tg:mqttconfig', handler);
    return () => window.removeEventListener('tg:mqttconfig', handler);
  }, [open, mqttDirty, applyToForm]);

  // Load on open
  useEffect(() => {
    if (!open) return;
    setTestResult(null);
    fetchMqttConfig()
      .then(applyToForm)
      .catch(() => {/* silent */});
  }, [open, applyToForm]);

  function markDirty() {
    setMqttDirty(true);
    setRemoteNotice('');
  }

  async function handleTest() {
    const safePort = Number(port);
    if (!Number.isInteger(safePort) || safePort < 1 || safePort > 65535) {
      setTestResult({ ok: false, error: 'Port must be 1–65535' });
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const body: Parameters<typeof testMqttConnection>[0] = {
        host: host.trim(),
        port: safePort,
        username: username || null,
      };
      if (passwordTouched) {
        body.password = password || null;
      } else {
        body.use_stored_password = true;
      }
      const result = await testMqttConnection(body);
      setTestResult(result);
    } catch (e: unknown) {
      setTestResult({ ok: false, error: e instanceof Error ? e.message : 'Request failed' });
    } finally {
      setTesting(false);
    }
  }

  async function handleApply(e: React.FormEvent) {
    e.preventDefault();
    const safePort = Number(port);
    const safeLiveHz = Number(liveHz);
    const safeRollingBuffer = Number(rollingBufferMaxFrames);

    if (!mqttDirty) { onClose(); return; }
    if (!host.trim()) { setTestResult({ ok: false, error: 'Host is required' }); return; }
    if (!Number.isInteger(safePort) || safePort < 1 || safePort > 65535) {
      setTestResult({ ok: false, error: 'Port must be 1–65535' }); return;
    }
    if (!topic.trim()) { setTestResult({ ok: false, error: 'Topic is required' }); return; }
    if (!Number.isFinite(safeLiveHz) || safeLiveHz <= 0 || safeLiveHz > 100) {
      setTestResult({ ok: false, error: 'Sample rate must be 1–100 Hz' }); return;
    }
    if (!Number.isInteger(safeRollingBuffer) || safeRollingBuffer < 60) {
      setTestResult({ ok: false, error: 'Shared history must be ≥ 60 frames' }); return;
    }

    setApplying(true);
    setTestResult(null);
    try {
      const patchBody: Parameters<typeof patchMqttConfig>[0] = {
        host: host.trim(),
        port: safePort,
        username: username || null,
        topic: topic.trim(),
        live_hz: safeLiveHz,
        rolling_buffer_max_frames: safeRollingBuffer,
      };
      if (passwordTouched) patchBody.password = password || null;

      const result = await patchMqttConfig(patchBody);
      if (result.ok) {
        setMqttDirty(false);
        setRemoteNotice('');
        onReconnect();
        if (result.warning) {
          setTestResult({ ok: false, error: result.warning });
          // Leave open so warning is visible
        } else {
          onClose();
        }
      } else {
        setTestResult({ ok: false, error: result.error ?? 'Apply failed' });
      }
    } catch (e: unknown) {
      setTestResult({ ok: false, error: e instanceof Error ? e.message : 'Request failed' });
    } finally {
      setApplying(false);
    }
  }

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div className={styles.backdrop} onClick={onClose} />

      {/* Drawer */}
      <div className={styles.drawer}>
        <div className={styles.drawerHdr}>
          <span className={styles.drawerTitle}>SETTINGS</span>
          <button className={styles.drawerClose} onClick={onClose} aria-label="Close settings">✕</button>
        </div>

        <form className={styles.drawerBody} onSubmit={(e) => { void handleApply(e); }}>

          {/* ── MQTT Broker ─────────────────────────────────────────────── */}
          <div className={styles.sectionHdr}>MQTT BROKER</div>

          {remoteNotice && (
            <div className={`${styles.resultBox} ${styles.resultErr}`}>{remoteNotice}</div>
          )}

          <label className={styles.fieldLabel}>
            Host
            <input
              className={styles.fieldInput}
              type="text"
              value={host}
              onChange={(e) => { setHost(e.target.value); markDirty(); }}
              placeholder="localhost"
              autoComplete="off"
            />
          </label>

          <label className={styles.fieldLabel}>
            Port
            <input
              className={styles.fieldInput}
              type="number"
              min={1}
              max={65535}
              value={port}
              onChange={(e) => { setPort(Number(e.target.value)); markDirty(); }}
            />
          </label>

          <label className={styles.fieldLabel}>
            Username <span className={styles.fieldOpt}>(optional)</span>
            <input
              className={styles.fieldInput}
              type="text"
              value={username}
              onChange={(e) => { setUsername(e.target.value); markDirty(); }}
              placeholder="—"
              autoComplete="off"
            />
          </label>

          <label className={styles.fieldLabel}>
            Password <span className={styles.fieldOpt}>(optional)</span>
            <input
              className={styles.fieldInput}
              type="password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setPasswordTouched(true); markDirty(); }}
              placeholder="—"
              autoComplete="new-password"
            />
          </label>

          <label className={styles.fieldLabel}>
            Topic
            <input
              className={styles.fieldInput}
              type="text"
              value={topic}
              onChange={(e) => { setTopic(e.target.value); markDirty(); }}
              placeholder="vehicle/+/#"
            />
          </label>

          <div className={styles.divider} />

          {/* ── Live stream ──────────────────────────────────────────────── */}
          <div className={styles.sectionHdr}>LIVE STREAM</div>

          <div className={styles.hint}>
            Shared history is kept on the backend for all clients.
          </div>

          <label className={styles.fieldLabel}>
            Sample rate <span className={styles.fieldOpt}>(Hz)</span>
            <input
              className={styles.fieldInput}
              type="number"
              min={1}
              max={100}
              step={1}
              value={liveHz}
              onChange={(e) => { setLiveHz(Number(e.target.value)); markDirty(); }}
            />
          </label>

          <label className={styles.fieldLabel}>
            Shared history <span className={styles.fieldOpt}>(backend · all clients)</span>
            <input
              className={styles.fieldInput}
              type="number"
              min={60}
              max={200000}
              step={60}
              value={rollingBufferMaxFrames}
              onChange={(e) => { setRollingBufferMaxFrames(Number(e.target.value)); markDirty(); }}
            />
          </label>

          {/* ── Test result / error ──────────────────────────────────────── */}
          {testResult && (
            <div className={`${styles.resultBox} ${testResult.ok ? styles.resultOk : styles.resultErr}`}>
              {testResult.ok
                ? `OK — ${testResult.latency_ms} ms`
                : testResult.error}
            </div>
          )}

          {/* ── Actions ──────────────────────────────────────────────────── */}
          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.actionBtn} ${styles.secondary}`}
              onClick={() => { void handleTest(); }}
              disabled={testing}
            >
              {testing ? '...' : 'TEST'}
            </button>
            <button
              type="submit"
              className={`${styles.actionBtn} ${styles.primary}`}
              disabled={applying}
            >
              {applying ? '...' : 'APPLY'}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
