// ── Attack state ──────────────────────────────────────────────────────────────

export type AttackState = 'idle' | 'pending' | 'active';

export interface AttackStatusTrackResponse {
  status: AttackState;
  remaining_s?: number;
  fires_in_s?: number;
  follower?: string | null;
  target_robot?: string | null;
  speed_mps?: string | number | null;
  mode?: 'static' | 'ramp' | null;
  speed_start?: number | null;
  speed_end?: number | null;
}

export interface AttackStatusResponse {
  // False brake (top-level, backward compat)
  status: AttackState;
  remaining_s?: number;
  fires_in_s?: number;
  follower?: string | null;
  target_robot?: string | null;
  false_brake?: AttackStatusTrackResponse;
  // Velocity spoof sub-object
  velocity_spoof?: AttackStatusTrackResponse;
}

// Client-side history entry — built from status transitions, never persisted.
export interface HistoryEntry {
  id: string;
  timestamp: Date;
  type: 'false_brake' | 'velocity_spoof';
  follower: string | null;
  targetRobot: string | null;
  durationS: number;
  delayS: number;
  speedMps?: number;        // velocity_spoof static
  speedStart?: number;      // velocity_spoof ramp
  speedEnd?: number;        // velocity_spoof ramp
  vsMode?: 'static' | 'ramp';
  outcome: 'active' | 'completed' | 'cancelled';
}

// ── Live frame data ───────────────────────────────────────────────────────────

export interface RobotData {
  st: number;   // active_state: 0=AUTONOMOUS 1=CANDIDATE 2=ALIGNING 3=PLATOONING 4=RECOVERY
  x: number;
  y: number;
  v?: number;   // routed_signals/v_mps
  w?: number;   // heading (rad)
  d?: number;   // raw measured_distance from distance sensor
  dv?: boolean; // distance sensor valid flag
}

export interface RobotAssessment {
  gap?: {
    bumper_gap_meters?: number | null;
    source?: string | null;
  };
}

export interface LiveFrame {
  robots?: Record<string, RobotData>;
  low_res?: {
    platoon?: {
      assessment?: {
        components?: Array<{ order: string[] }>;
      };
    };
    per_robot?: Record<string, { assessment?: RobotAssessment }>;
  };
  scenario?: {
    per_robot?: Record<string, {
      velocity_spoof?: boolean;
      velocity_spoof_kind?: string | null;
    }>;
  };
}

// WebSocket envelope (what arrives over /ws/live after JSON.parse)
// { type: 'frame', data: LiveFrameEnvelope }
export interface LiveFrameEnvelope {
  session_id: string;
  frame_id: number;
  data: LiveFrame;
}

// Buffer snapshot from GET /api/live/buffer
export interface BufferSnapshot {
  session_id: string | null;
  started_at: number | null;
  last_frame_id: number;
  live_hz: number;
  robots: string[];
  frames: LiveFrameEnvelope[];
  connected: boolean;
}

// ── MQTT config ───────────────────────────────────────────────────────────────

export interface MqttConfig {
  host: string;
  port: number;
  username: string | null;
  topic: string;
  live_hz: number;
  rolling_buffer_max_frames: number;
  connected: boolean;
}

export interface ActiveRecording {
  active: true;
  run_id: string;
  name?: string | null;
  started_at: number;
  frame_count: number;
}

export interface InactiveRecording {
  active: false;
}

export type RecordingStatus = ActiveRecording | InactiveRecording;

// ── WebSocket status ──────────────────────────────────────────────────────────

export type WsStatus = 'connecting' | 'connected' | 'disconnected';

// Risk analysis

export type RiskLevel = 'low' | 'elevated' | 'high';
export type RiskStatusKind = 'missing' | 'empty' | 'ready';

export interface RiskStatusResponse {
  status: RiskStatusKind;
  message: string;
  run_count: number;
  usable_run_count: number;
}

export interface RiskSessionSummary {
  run_id: string;
  name: string;
  status: string;
  started_at?: number | null;
  ended_at?: number | null;
  duration_s?: number | null;
  frame_count: number;
  live_hz?: number | null;
  frames_bytes: number;
  has_frames: boolean;
  risk: RiskLevel;
  risk_score: number;
  error?: string | null;
}

export interface RiskTimelineBucket {
  start_frame: number;
  end_frame: number;
  frames: number;
  anomaly_frames: number;
}

export interface RiskRobotStats {
  frames: number;
  velocity_spoof_frames: number;
  first_velocity_spoof_t?: number | null;
  last_velocity_spoof_t?: number | null;
  velocity_spoof_kind_counts?: Record<string, number>;
  dominant_velocity_spoof_kind?: string | null;
  speed_min?: number | null;
  speed_max?: number | null;
  max_abs_lane_error?: number | null;
}

export interface RiskAnalysis {
  frame_count: number;
  parse_errors?: number;
  duration_s?: number | null;
  anomaly_frames?: number;
  anomaly_ratio?: number;
  max_gap_s?: number;
  robots: Record<string, RiskRobotStats>;
  timeline: RiskTimelineBucket[];
  findings: string[];
}

export interface RiskSessionAnalysis extends RiskSessionSummary {
  analysis: RiskAnalysis;
  nist_findings?: NistFindings | null;
}

// ── NIST risk engine types ────────────────────────────────────────────────────

export interface CsfMapping {
  function: string;       // Govern | Identify | Protect | Detect | Respond | Recover
  category: string;       // e.g. DE.CM
  subcategory: string;    // e.g. DE.CM-01
  rationale: string;
}

export interface IncidentAction {
  phase: string;   // Preparation | Detection and Analysis | Containment Eradication and Recovery | Post-Incident Activity
  action: string;
  rationale: string;
}

export type NistRiskLevel = 'low' | 'moderate' | 'high' | 'critical';

export interface NistRiskObject {
  id: string;
  source_type: string;              // live_recording | replay
  run_id: string;
  frame_range: [number, number] | null;
  timestamp_range: [number, number] | null;
  affected_robots: string[];
  signal_type: string;              // velocity_spoof | timing_gap | recording_overflow
  signal_subtype?: string | null;
  observed_signal_subtypes?: string[];
  evidence_summary: string;
  likelihood: number;               // 1–5
  impact: number;                   // 1–5
  risk_score: number;               // likelihood × impact
  risk_level: NistRiskLevel;
  assumptions: string[];
  confidence: number;               // 0.0–1.0
  completeness: number;             // 0.0–1.0
  csf_mappings: CsfMapping[];
  incident_actions: IncidentAction[];
}

export interface RiskMatrix {
  grid: string[][][];               // [likelihood_idx 0-4][impact_idx 0-4] = [risk_object_ids]
  impact_labels: string[];
  likelihood_labels: string[];
  counts: Record<NistRiskLevel, number>;
  total: number;
}

export interface NistSummary {
  total_findings: number;
  level_counts: Record<NistRiskLevel, number>;
  avg_confidence: number;
  session_completeness: number;
  nist_methods: string[];
}

export type RerunDecisionKind =
  | 'safe_to_rerun'
  | 'review_before_rerun'
  | 'investigate_before_rerun'
  | 'do_not_rerun_until_contained';

export interface RerunDecision {
  decision: RerunDecisionKind;
  label: string;
  severity: NistRiskLevel;
  next_run_allowed: boolean;
  reason: string;
  required_actions: string[];
}

export interface NistFindings {
  risk_objects: NistRiskObject[];
  matrix: RiskMatrix;
  completeness: number;
  worst_risk_level: NistRiskLevel;
  rerun_decision: RerunDecision;
  nist_summary: NistSummary;
}

// ── System-wide risk assessment ───────────────────────────────────────────────

export type AlertSource = 'live' | 'historical';
export type AlertStatus = 'active' | 'pending' | 'historical';

export interface RiskAlert {
  id: string;
  source: AlertSource;
  is_live: boolean;
  run_id: string | null;
  run_label: string | null;
  attack_type: string;
  detection_source: string;
  affected_robots: string[];
  status: AlertStatus;
  level: NistRiskLevel;
  first_seen_at: number | null;
  last_seen_at: number | null;
  details: Record<string, unknown>;
}

export interface RunSummaryLink {
  run_id: string;
  name: string;
  status: string;
  started_at: number | null;
  ended_at: number | null;
  duration_s: number | null;
  frame_count: number;
  nist_level: NistRiskLevel;
  coarse_score: number;
  has_nist: boolean;
  finding_count: number;
}

export interface ActiveRunState {
  run_id: string;
  name: string;
  started_at: number;
  frame_count: number;
  anomaly_frames: number;
  anomaly_ratio: number;
  robots_with_spoofing: string[];
}

export interface LiveContribution {
  level: NistRiskLevel;
  score: number;
  connected: boolean;
  threats: RiskAlert[];
  active_run_state: ActiveRunState | null;
}

export interface HistoricalContribution {
  level: NistRiskLevel;
  weighted_score: number;
  run_count: number;
  worst_run_id: string | null;
  worst_ever_level: NistRiskLevel;
  total_findings: number;
  level_counts: Record<NistRiskLevel, number>;
}

export interface LiveAlertsSnapshot {
  overall_level: NistRiskLevel;
  active_alerts: RiskAlert[];
  live_run_state: ActiveRunState | null;
  computed_at: number;
}

export interface EvidenceQuality {
  data_completeness: number;
  runs_with_nist: number;
  runs_without_nist: number;
  live_connected: boolean;
  notes: string[];
}

export interface SystemAssessment {
  overall_level: NistRiskLevel;
  overall_score: number;
  live_contribution: LiveContribution;
  historical_contribution: HistoricalContribution;
  current_matrix: RiskMatrix;
  current_risk_objects: NistRiskObject[];
  active_alerts: RiskAlert[];
  run_summaries: RunSummaryLink[];
  evidence_quality: EvidenceQuality;
  computed_at: number;
}

