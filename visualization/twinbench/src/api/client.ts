import type {
  RecordingStatus,
  AttackStatusResponse,
  BufferSnapshot,
  LiveAlertsSnapshot,
  MqttConfig,
  RiskSessionAnalysis,
  RiskSessionSummary,
  RiskStatusResponse,
  SystemAssessment,
} from '../types';

const BASE = '/api';

// ── Attack ────────────────────────────────────────────────────────────────────

export async function fetchAttackStatus(): Promise<AttackStatusResponse> {
  const res = await fetch(`${BASE}/attack/status`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<AttackStatusResponse>;
}

export async function fireFalseBrake(body: {
  duration_s: number;
  delay_s: number;
  follower_robot: string | null;
  target_robot: string | null;
}): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${BASE}/attack/false_brake`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json() as Promise<{ ok: boolean; error?: string }>;
}


export async function stopFalseBrake(): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${BASE}/attack/false_brake/stop`, { method: 'POST' });
  return res.json() as Promise<{ ok: boolean; error?: string }>;
}

export async function stopVelocitySpoof(): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${BASE}/attack/velocity_spoof/stop`, { method: 'POST' });
  return res.json() as Promise<{ ok: boolean; error?: string }>;
}

export async function fireVelocitySpoof(body: {
  mode: 'static' | 'ramp';
  speed_mps?: number | null;
  speed_start?: number | null;
  speed_end?: number | null;
  duration_s: number;
  delay_s: number;
  follower_robot: string | null;
  target_robot: string | null;
}): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`${BASE}/attack/velocity_spoof`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json() as Promise<{ ok: boolean; error?: string }>;
}

// ── Live ──────────────────────────────────────────────────────────────────────

export async function fetchLiveBuffer(limit?: number): Promise<BufferSnapshot> {
  const url =
    limit != null ? `${BASE}/live/buffer?limit=${limit}` : `${BASE}/live/buffer`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<BufferSnapshot>;
}

export async function fetchActiveRecording(): Promise<RecordingStatus> {
  const res = await fetch(`${BASE}/live/capture/active`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<RecordingStatus>;
}

export async function startRecording(name = ''): Promise<{ run_id: string; name: string; started_at: number }> {
  const res = await fetch(`${BASE}/live/capture/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const data = await res.json() as { detail?: string; run_id?: string; name?: string; started_at?: number };
  if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
  return {
    run_id: data.run_id ?? '',
    name: data.name ?? '',
    started_at: data.started_at ?? 0,
  };
}

export async function stopRecording(): Promise<RiskSessionAnalysis> {
  const res = await fetch(`${BASE}/live/capture/stop`, { method: 'POST' });
  const data = await res.json() as RiskSessionAnalysis & { detail?: string };
  if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
  return data;
}

// ── Config ────────────────────────────────────────────────────────────────────

export async function fetchMqttConfig(): Promise<MqttConfig> {
  const res = await fetch(`${BASE}/config/mqtt`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<MqttConfig>;
}

export async function patchMqttConfig(body: {
  host?: string;
  port?: number;
  username?: string | null;
  password?: string | null;
  topic?: string;
  live_hz?: number;
  rolling_buffer_max_frames?: number;
}): Promise<{ ok: boolean; warning?: string; error?: string }> {
  const res = await fetch(`${BASE}/config/mqtt`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json() as Promise<{ ok: boolean; warning?: string; error?: string }>;
}

export async function testMqttConnection(body: {
  host: string;
  port: number;
  username?: string | null;
  password?: string | null;
  use_stored_password?: boolean;
}): Promise<{ ok: boolean; latency_ms?: number; error?: string }> {
  const res = await fetch(`${BASE}/config/mqtt/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json() as Promise<{ ok: boolean; latency_ms?: number; error?: string }>;
}

// Recordings

export async function fetchRecordingsStatus(): Promise<RiskStatusResponse> {
  const res = await fetch(`${BASE}/recordings/status`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<RiskStatusResponse>;
}

export async function fetchRecordings(): Promise<{ runs: RiskSessionSummary[] }> {
  const res = await fetch(`${BASE}/recordings`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<{ runs: RiskSessionSummary[] }>;
}

export async function fetchRecording(runId: string): Promise<RiskSessionAnalysis> {
  const res = await fetch(`${BASE}/recordings/${encodeURIComponent(runId)}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<RiskSessionAnalysis>;
}

// ── System risk ───────────────────────────────────────────────────────────────

export async function fetchSystemAssessment(): Promise<SystemAssessment> {
  const res = await fetch(`${BASE}/risk/system`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<SystemAssessment>;
}

export async function fetchLiveAlerts(): Promise<LiveAlertsSnapshot> {
  const res = await fetch(`${BASE}/risk/alerts`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<LiveAlertsSnapshot>;
}
