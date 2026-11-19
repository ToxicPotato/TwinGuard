import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { fetchRecording, fetchRecordings, fetchRecordingsStatus } from '../../api/client';
import { useSystemRisk } from '../../hooks/useSystemRisk';
import type {
  ActiveRunState,
  EvidenceQuality,
  HistoricalContribution,
  LiveContribution,
  NistFindings,
  NistRiskLevel,
  NistRiskObject,
  RerunDecision,
  RiskAlert,
  RiskMatrix,
  RiskSessionAnalysis,
  RiskSessionSummary,
  RiskStatusResponse,
  RiskTimelineBucket,
  RunSummaryLink,
  SystemAssessment,
} from '../../types';
import styles from './RiskPanel.module.css';

interface Props {
  refreshKey?: number;
}

type View = 'overview' | 'recording';

// ── Top-level component ───────────────────────────────────────────────────────

export function RiskPanel({ refreshKey = 0 }: Props) {
  const [view, setView] = useState<View>('overview');
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const openRecording = (runId: string) => {
    setSelectedRunId(runId);
    setView('recording');
  };

  return (
    <div className={styles.panel}>
      {view === 'overview' ? (
        <SystemOverview refreshKey={refreshKey} onOpenRecording={openRecording} />
      ) : (
        <RecordingDetail
          initialRunId={selectedRunId}
          refreshKey={refreshKey}
          onBack={() => setView('overview')}
        />
      )}
    </div>
  );
}

// ── System overview ───────────────────────────────────────────────────────────

function SystemOverview({
  refreshKey,
  onOpenRecording,
}: {
  refreshKey: number;
  onOpenRecording: (runId: string) => void;
}) {
  const { assessment, loading, error, refresh } = useSystemRisk(2000, 12000, refreshKey);

  return (
    <>
      <header className={styles.header}>
        <div>
          <div className={styles.eyebrow}>Risk Assessment</div>
          <h2 className={styles.heading}>System Risk Overview</h2>
          <p className={styles.subheading}>
            Combined assessment from live sensor state and all recorded runs.
            Active threats override historical evidence.
          </p>
        </div>
        <button className={styles.refresh} onClick={() => void refresh()} disabled={loading}>
          {loading ? 'LOADING' : 'REFRESH'}
        </button>
      </header>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.overviewScroll}>
        {loading && !assessment ? (
          <div className={styles.overviewLoading}>Loading system assessment…</div>
        ) : assessment ? (
          <OverviewBody assessment={assessment} onOpenRecording={onOpenRecording} />
        ) : null}
      </div>
    </>
  );
}

function OverviewBody({
  assessment,
  onOpenRecording,
}: {
  assessment: SystemAssessment;
  onOpenRecording: (runId: string) => void;
}) {
  const {
    overall_level, overall_score, live_contribution, historical_contribution,
    current_matrix, current_risk_objects,
    active_alerts, run_summaries, evidence_quality,
  } = assessment;

  return (
    <>
      {/* Top status strip */}
      <section className={styles.overviewStrip}>
        <OverallLevelCard level={overall_level} score={overall_score} />
        <LiveStatusCard contribution={live_contribution} />
        <HistoricalCard contribution={historical_contribution} />
        <EvidenceQualityCard quality={evidence_quality} />
      </section>

      {/* Evidence quality warning notes */}
      {evidence_quality.notes.length > 0 && (
        <div className={styles.qualityNotes}>
          {evidence_quality.notes.map((note) => (
            <div key={note} className={styles.qualityNote}>{note}</div>
          ))}
        </div>
      )}

      {/* Active live-threat banner */}
      {active_alerts.length > 0 && (
        <section className={styles.alertBannerSection}>
          {active_alerts.map((alert) => (
            <LiveAlertBanner key={alert.id} alert={alert} />
          ))}
        </section>
      )}

      {/* ── Current Risk Matrix ─────────────────────────────────────────────── */}
      <section className={styles.overviewBlock}>
        <div className={styles.overviewBlockTitle}>
          Current Risk Matrix
          <span className={`${styles.overviewBlockBadge} ${styles.badgeLive}`}>LIVE</span>
        </div>
        <p className={styles.overviewBlockHint}>
          Live threats always set the floor — an active attack immediately raises the level
          regardless of history. When no threat is active, the level is derived from completed
          runs scored by recency and severity: the most recent run weighs most, and clean
          recent runs lower the baseline over time.
        </p>
        <div className={styles.matrixWrap}>
          <AlignedRiskMatrixView matrix={current_matrix} objects={current_risk_objects} />
        </div>
        <div className={styles.matrixLegend}>
          {(['critical', 'high', 'moderate', 'low'] as NistRiskLevel[]).map((level) => (
            <span key={level} className={styles.matrixLegendItem}>
              <span className={`${styles.matrixLegendSwatch} ${styles[`cell_${level}`]}`} />
              {level} ({current_matrix.counts[level]})
            </span>
          ))}
        </div>
        <div className={styles.currentObjectList}>
          {[...current_risk_objects]
            .sort((a, b) => {
              const ord: Record<NistRiskLevel, number> = { low: 0, moderate: 1, high: 2, critical: 3 };
              return (ord[b.risk_level] ?? 0) - (ord[a.risk_level] ?? 0) || b.risk_score - a.risk_score;
            })
            .map((obj) => (
              <CurrentRiskObjectRow key={obj.id} obj={obj} />
            ))}
        </div>
      </section>

      {/* Run summaries */}
      <section className={styles.overviewBlock}>
        <div className={styles.overviewBlockTitle}>
          Recorded Runs
          <span className={styles.overviewBlockCount}>{run_summaries.length}</span>
        </div>
        {run_summaries.length === 0 ? (
          <div className={styles.overviewEmpty}>
            No recordings yet. Start a capture on the Attack tab to record a run.
          </div>
        ) : (
          <div className={styles.runList}>
            {run_summaries.map((run) => (
              <RunSummaryRow
                key={run.run_id}
                run={run}
                onOpen={() => onOpenRecording(run.run_id)}
              />
            ))}
          </div>
        )}
      </section>
    </>
  );
}

// ── Overview status cards ─────────────────────────────────────────────────────

// CSS modules return undefined for unknown keys at runtime despite TypeScript typing them as string.
// Use these explicit maps to avoid inserting the literal string "undefined" as a class name.
const LEVEL_CLASS: Record<NistRiskLevel, string> = {
  low: styles.level_low,
  moderate: styles.level_moderate,
  high: styles.level_high,
  critical: styles.level_critical,
};
const CARD_ACCENT_CLASS: Partial<Record<NistRiskLevel, string>> = {
  moderate: styles.overviewCard_moderate,
  high: styles.overviewCard_high,
  critical: styles.overviewCard_critical,
};

function OverallLevelCard({ level, score }: { level: NistRiskLevel; score: number }) {
  const labels: Record<NistRiskLevel, string> = {
    low: 'Low', moderate: 'Moderate', high: 'High', critical: 'Critical',
  };
  return (
    <div className={`${styles.overviewCard} ${CARD_ACCENT_CLASS[level] ?? ''}`}>
      <div className={styles.overviewCardLabel}>Overall System Risk</div>
      <div className={`${styles.overviewCardLevel} ${LEVEL_CLASS[level]}`}>
        {labels[level]}
      </div>
      <div className={styles.overviewCardSub}>Score {score}/25</div>
    </div>
  );
}

function LiveStatusCard({ contribution }: { contribution: LiveContribution }) {
  const connected = contribution.connected;
  const hasThreats = contribution.threats.length > 0;
  const run = contribution.active_run_state;
  const stateLabel = !connected ? 'Disconnected' : hasThreats ? contribution.level.toUpperCase() : 'No active threat';
  const stateClass = !connected ? styles.liveDisconnected : hasThreats ? LEVEL_CLASS[contribution.level] : styles.liveIdle;
  const subLine = !connected
    ? 'MQTT not connected'
    : hasThreats
      ? `${contribution.threats.length} active`
      : run
        ? `Recording · ${run.frame_count} frames${run.anomaly_frames > 0 ? ` · ${run.anomaly_frames} anomalies` : ''}`
        : 'Feed connected';
  return (
    <div className={`${styles.overviewCard} ${hasThreats ? (CARD_ACCENT_CLASS[contribution.level] ?? '') : ''}`}>
      <div className={styles.overviewCardLabel}>Live Sensor State</div>
      <div className={`${styles.overviewCardLevel} ${stateClass ?? ''}`}>{stateLabel}</div>
      <div className={styles.overviewCardSub}>{subLine}</div>
    </div>
  );
}

function HistoricalCard({ contribution }: { contribution: HistoricalContribution }) {
  const level = contribution.level;
  const worst = contribution.worst_ever_level;
  const worstDiffers = worst !== level;
  const scorePct = Math.round(contribution.weighted_score * 100);
  return (
    <div className={styles.overviewCard}>
      <div className={styles.overviewCardLabel}>Historical Baseline</div>
      <div className={`${styles.overviewCardLevel} ${LEVEL_CLASS[level]}`}>
        {level.charAt(0).toUpperCase() + level.slice(1)}
      </div>
      <div className={styles.overviewCardSub}>
        {scorePct}% recency score · {contribution.run_count} run(s)
        {worstDiffers && (
          <span className={`${styles.worstEverBadge} ${LEVEL_CLASS[worst]}`}>
            {' '}· worst ever: {worst}
          </span>
        )}
      </div>
      <div className={styles.overviewCardWeightNote}>
        Recent runs weigh more than older ones
      </div>
    </div>
  );
}

function EvidenceQualityCard({ quality }: { quality: EvidenceQuality }) {
  const completenessNum = Math.round(quality.data_completeness * 100);
  const color = completenessNum >= 80 ? 'var(--green)' : completenessNum >= 50 ? '#e6b400' : 'var(--red)';
  return (
    <div className={styles.overviewCard}>
      <div className={styles.overviewCardLabel}>Evidence Quality</div>
      <div className={styles.overviewCardLevel} style={{ color }}>{completenessNum}%</div>
      <div className={styles.qualityBarWrap}>
        <div className={styles.qualityBarTrack}>
          <div className={styles.qualityBarFill} style={{ width: `${completenessNum}%`, background: color }} />
        </div>
      </div>
      <div className={styles.overviewCardSub}>
        {quality.runs_with_nist} analyzed · {quality.runs_without_nist} coarse
      </div>
    </div>
  );
}

// ── Current risk object row ───────────────────────────────────────────────────

const SIGNAL_LABELS: Record<string, string> = {
  velocity_spoof:      'Velocity Spoof',
  velocity_spoof_live: 'Velocity Spoof (Live)',
  false_brake:         'False Brake',
  false_brake_live:    'False Brake (Live)',
  historical_baseline: 'Historical Baseline',
  no_active_threat:    'No Active Threat',
  timing_gap:          'Timing Gap',
  recording_overflow:  'Recording Overflow',
};

function CurrentRiskObjectRow({ obj }: { obj: NistRiskObject }) {
  const label = SIGNAL_LABELS[obj.signal_type] ?? obj.signal_type;
  const subtype = obj.signal_subtype
    ? { 'tamper-service': 'attack control', 'detector+control': 'sensor + control',
        detector: 'sensor labels' }[obj.signal_subtype] ?? obj.signal_subtype
    : null;

  return (
    <div className={`${styles.currentObjectRow} ${styles[`alertCard_${obj.risk_level}`] ?? ''}`}>
      <span className={`${styles.levelBadge} ${styles[`badge_${obj.risk_level}`]}`}>
        {obj.risk_level.toUpperCase()}
      </span>
      <span className={styles.currentObjectLabel}>{label}</span>
      {subtype && <span className={styles.currentObjectSource}>via {subtype}</span>}
      <span className={styles.currentObjectLI}>
        L{obj.likelihood} × I{obj.impact} = {obj.risk_score}
      </span>
      <span className={styles.currentObjectSummary}>{obj.evidence_summary}</span>
    </div>
  );
}

// ── Alert components ──────────────────────────────────────────────────────────

const ATTACK_LABELS: Record<string, string> = {
  false_brake: 'False Brake',
  velocity_spoof: 'Velocity Spoof',
  timing_gap: 'Timing Gap',
  recording_overflow: 'Recording Overflow',
};

const DETECTION_SOURCE_LABELS: Record<string, string> = {
  'tamper-service': 'attack control',
  'detector': 'sensor labels',
  'detector+control': 'sensor + control',
};

function LiveAlertBanner({ alert }: { alert: RiskAlert }) {
  const isActive = alert.status === 'active';
  const label = ATTACK_LABELS[alert.attack_type] ?? alert.attack_type;
  const robots = alert.affected_robots.join(', ') || 'unknown robot(s)';
  const sourceLabel = DETECTION_SOURCE_LABELS[alert.detection_source] ?? alert.detection_source;
  return (
    <div className={`${styles.liveAlertBanner} ${isActive ? styles.liveAlertBanner_active : styles.liveAlertBanner_pending}`}>
      <div className={styles.liveAlertLeft}>
        <span className={`${styles.levelBadge} ${styles[`badge_${alert.level}`]}`}>
          {isActive ? 'LIVE ACTIVE' : 'PENDING'}
        </span>
        <span className={styles.liveAlertTitle}>{label} detected</span>
        <span className={styles.liveAlertSource}>via {sourceLabel}</span>
      </div>
      <div className={styles.liveAlertMeta}>
        {robots && <span>Affected: {robots}</span>}
        {alert.attack_type !== 'false_brake' && alert.attack_type !== 'velocity_spoof' && alert.details.remaining_s != null && (
          <span>Remaining: {String(alert.details.remaining_s)}s</span>
        )}
        {alert.details.fires_in_s != null && (
          <span>Fires in: {String(alert.details.fires_in_s)}s</span>
        )}
        {alert.details.frame_count != null && (
          <span>{String(alert.details.frame_count)} frame(s) in window</span>
        )}
      </div>
    </div>
  );
}

// ── Run summary list ──────────────────────────────────────────────────────────

// CSS dot class uses the existing .low/.moderate/.high/.critical names
const DOT_CLASS: Record<NistRiskLevel, string> = {
  low: styles.low,
  moderate: styles.moderate,
  high: styles.high,
  critical: styles.critical,
};

function RunSummaryRow({ run, onOpen }: { run: RunSummaryLink; onOpen: () => void }) {
  const started = formatDate(run.started_at);
  const dur = run.duration_s != null ? `${run.duration_s.toFixed(1)}s` : '–';
  return (
    <div className={styles.runRow}>
      <span className={`${styles.riskDot} ${DOT_CLASS[run.nist_level]}`} />
      <span className={styles.runRowName}>{run.name || shortId(run.run_id)}</span>
      <span className={styles.runRowMeta}>{started}</span>
      <span className={styles.runRowMeta}>{dur}</span>
      <span className={styles.runRowMeta}>{run.frame_count} frames</span>
      <span className={`${styles.runRowLevel} ${LEVEL_CLASS[run.nist_level]}`}>
        {run.nist_level}
        {!run.has_nist && <span className={styles.runRowCoarseFlag}> (coarse)</span>}
      </span>
      <span className={styles.runRowFindings}>
        {run.finding_count > 0 ? `${run.finding_count} finding(s)` : 'no findings'}
      </span>
      <button className={styles.runRowDrilldown} onClick={onOpen}>
        Inspect →
      </button>
    </div>
  );
}

// ── Recording detail (existing per-run inspector) ─────────────────────────────

function RecordingDetail({
  initialRunId,
  refreshKey,
  onBack,
}: {
  initialRunId: string | null;
  refreshKey: number;
  onBack: () => void;
}) {
  const [status, setStatus] = useState<RiskStatusResponse | null>(null);
  const [sessions, setSessions] = useState<RiskSessionSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(initialRunId);
  const [analysis, setAnalysis] = useState<RiskSessionAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statusResult, runsResult] = await Promise.all([
        fetchRecordingsStatus(),
        fetchRecordings(),
      ]);
      setStatus(statusResult);
      setSessions(runsResult.runs);
      setSelectedId((current) => {
        if (current && runsResult.runs.some((run) => run.run_id === current)) {
          return current;
        }
        return runsResult.runs.find((run) => run.has_frames)?.run_id
          ?? runsResult.runs[0]?.run_id
          ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load recordings');
      setStatus(null);
      setSessions([]);
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions, refreshKey]);

  useEffect(() => {
    if (!selectedId) {
      setAnalysis(null);
      return;
    }
    let cancelled = false;
    setAnalysisLoading(true);
    setError(null);
    fetchRecording(selectedId)
      .then((result) => {
        if (!cancelled) setAnalysis(result);
      })
      .catch((err) => {
        if (!cancelled) {
          setAnalysis(null);
          setError(err instanceof Error ? err.message : 'Unable to analyse selected run');
        }
      })
      .finally(() => {
        if (!cancelled) setAnalysisLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedId]);

  const selectedSession = useMemo(
    () => sessions.find((session) => session.run_id === selectedId) ?? null,
    [selectedId, sessions],
  );

  return (
    <>
      <header className={styles.header}>
        <div>
          <button className={styles.backBtn} onClick={onBack}>← System Overview</button>
          <div className={styles.eyebrow}>Risk Analysis</div>
          <h2 className={styles.heading}>Recording Inspector</h2>
          <p className={styles.subheading}>
            Select a recording to inspect risk findings, the velocity-spoof timeline, and rerun decisions.
          </p>
        </div>
        <button className={styles.refresh} onClick={() => void loadSessions()} disabled={loading}>
          {loading ? 'SCANNING' : 'REFRESH'}
        </button>
      </header>

      {error && <div className={styles.error}>{error}</div>}

      <section className={styles.statusBar}>
        <StatusCard label="Status" value={status?.status.toUpperCase() ?? 'LOADING'} />
        <StatusCard label="Valid Runs" value={String(status?.usable_run_count ?? sessions.length)} />
        <StatusCard label="Shown" value={String(sessions.length)} />
        <StatusCard label="Message" value={status?.message ?? 'Reading live recordings'} wide />
      </section>

      <div className={styles.content}>
        <aside className={styles.sessions}>
          <div className={styles.sectionTitle}>Recorded Runs</div>
          {sessions.length === 0 && !loading ? (
            <div className={styles.empty}>No persisted live recordings yet.</div>
          ) : (
            sessions.map((session) => (
              <button
                key={session.run_id}
                className={`${styles.sessionBtn} ${session.run_id === selectedId ? styles.sessionActive : ''}`}
                onClick={() => setSelectedId(session.run_id)}
              >
                <span className={`${styles.riskDot} ${styles[session.risk]}`} />
                <span className={styles.sessionMain}>
                  <span className={styles.runId}>{session.name || shortId(session.run_id)}</span>
                  <span className={styles.sessionMeta}>{formatDate(session.started_at)}</span>
                </span>
                <span className={styles.sessionScore}>{session.risk_score}</span>
              </button>
            ))
          )}
        </aside>

        <main className={styles.detail}>
          {!selectedSession ? (
            <div className={styles.placeholder}>Select a recording to inspect risk signals.</div>
          ) : (
            <>
              {analysisLoading ? (
                <div className={styles.placeholder}>Analysing selected recording…</div>
              ) : analysis ? (
                <>
                  {analysis.nist_findings && (
                    <NistFindingsSection
                      findings={analysis.nist_findings}
                      runLabel={selectedSession.name || shortId(selectedSession.run_id)}
                    />
                  )}

                  {analysis.analysis && (
                    <>
                      <section className={styles.block}>
                        <div className={styles.sectionTitle}>Timeline</div>
                        <Timeline buckets={analysis.analysis.timeline ?? []} />
                        <div className={styles.legend}>
                          <span><span className={`${styles.legendDot} ${styles.frames}`} />Frames</span>
                          <span><span className={`${styles.legendDot} ${styles.anomalies}`} />Velocity spoof</span>
                        </div>
                      </section>

                      <section className={styles.block}>
                        <div className={styles.sectionTitle}>Findings</div>
                        <ul className={styles.findings}>
                          {(analysis.analysis.findings ?? []).map((finding) => (
                            <li key={finding}>{finding}</li>
                          ))}
                        </ul>
                      </section>
                    </>
                  )}
                </>
              ) : (
                <div className={styles.placeholder}>No analysis is available for this recording.</div>
              )}
            </>
          )}
        </main>
      </div>
    </>
  );
}

// ── Risk findings section (per-run detail) ────────────────────────────────────

function NistFindingsSection({ findings, runLabel }: { findings: NistFindings; runLabel: string }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const { risk_objects, matrix, nist_summary } = findings;
  const sortedObjects = risk_objects.slice().sort((a, b) => b.risk_score - a.risk_score);

  return (
    <>
      <DecisionPanel decision={findings.rerun_decision} />

      <section className={styles.block}>
        <div className={styles.sectionTitle}>Risk Matrix — {runLabel}</div>
        <div className={styles.matrixWrap}>
          <AlignedRiskMatrixView matrix={matrix} objects={risk_objects} />
        </div>
        <div className={styles.matrixLegend}>
          {(['critical', 'high', 'moderate', 'low'] as NistRiskLevel[]).map((level) => (
            <span key={level} className={styles.matrixLegendItem}>
              <span className={`${styles.matrixLegendSwatch} ${styles[`cell_${level}`]}`} />
              {level} ({nist_summary.level_counts[level]})
            </span>
          ))}
        </div>
      </section>

      <section className={styles.block}>
        <div className={styles.sectionTitleRow}>
          <span className={styles.sectionTitle}>Risk Findings ({risk_objects.length})</span>
          <span className={styles.nistMeta}>
            Evidence quality: {pct(nist_summary.session_completeness)} · Confidence: {pct(nist_summary.avg_confidence)}
          </span>
        </div>
        {risk_objects.length === 0 ? (
          <div className={styles.empty}>No risk finding was generated for this session.</div>
        ) : (
          sortedObjects.map((obj) => (
            <NistFindingCard
              key={obj.id}
              obj={obj}
              expanded={expanded.has(obj.id)}
              onToggle={() => toggle(obj.id)}
            />
          ))
        )}
      </section>
    </>
  );
}

// ── Decision panel ────────────────────────────────────────────────────────────

function DecisionPanel({ decision }: { decision: RerunDecision }) {
  return (
    <section className={`${styles.decisionPanel} ${styles[`decision_${decision.severity}`]}`}>
      <div className={styles.decisionTop}>
        <div>
          <div className={styles.sectionTitle}>Rerun Decision</div>
          <div className={styles.decisionLabel}>{decision.label}</div>
        </div>
        <span className={styles.decisionState}>
          {decision.next_run_allowed ? 'Next run allowed' : 'Next run blocked'}
        </span>
      </div>
      <p className={styles.decisionReason}>{decision.reason}</p>
      {decision.required_actions.length > 0 && (
        <div className={styles.decisionActions}>
          <div className={styles.sectionTitle}>Required Before Next Run</div>
          <ol>
            {decision.required_actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}

// ── Risk matrix heatmap ───────────────────────────────────────────────────────

function AlignedRiskMatrixView({ matrix, objects }: { matrix: RiskMatrix; objects: NistRiskObject[] }) {
  const byId = useMemo(() => {
    const map = new Map<string, NistRiskObject>();
    objects.forEach((o) => map.set(o.id, o));
    return map;
  }, [objects]);

  // Identify the IDs of highest-severity objects so their cells get a dominant ring.
  const dominantIds = useMemo(() => {
    if (objects.length === 0) return new Set<string>();
    const ord: Record<NistRiskLevel, number> = { low: 0, moderate: 1, high: 2, critical: 3 };
    const top = objects.reduce((max, obj) => Math.max(max, ord[obj.risk_level] ?? 0), 0);
    if (top === 0) return new Set<string>(); // all low — no highlight
    return new Set(objects.filter((obj) => (ord[obj.risk_level] ?? 0) === top).map((o) => o.id));
  }, [objects]);

  const rows = [4, 3, 2, 1, 0];
  const cols = [0, 1, 2, 3, 4];

  return (
    <div className={styles.matrixContainer}>
      <div className={styles.matrixChart}>
        <div className={styles.matrixYTitle}>Likelihood</div>
        {rows.map((li, rowIndex) => (
          <div
            key={`likelihood-${li}`}
            className={styles.matrixYAxisLabel}
            style={{ gridRow: rowIndex + 1 } as CSSProperties}
          >
            <strong>{li + 1}</strong>
            <span>{matrix.likelihood_labels[li]}</span>
          </div>
        ))}

        {rows.map((li, rowIndex) =>
          cols.map((ii, colIndex) => {
            const ids = matrix.grid[li]?.[ii] ?? [];
            const count = ids.length;
            const likelihoodScore = li + 1;
            const impactScore = ii + 1;
            const cellLevel = ids.reduce<NistRiskLevel | null>((best, id) => {
              const obj = byId.get(id);
              if (!obj) return best;
              const order: Record<NistRiskLevel, number> = { low: 0, moderate: 1, high: 2, critical: 3 };
              if (!best || order[obj.risk_level] > order[best]) return obj.risk_level;
              return best;
            }, null) ?? riskLevelForScores(likelihoodScore, impactScore);
            const signals = ids.map((id) => byId.get(id)?.signal_type ?? id).join(', ');
            const title = count > 0
              ? `Likelihood ${likelihoodScore} (${matrix.likelihood_labels[li]}), impact ${impactScore} (${matrix.impact_labels[ii]}): ${count} finding(s) — ${signals}`
              : `Likelihood ${likelihoodScore} (${matrix.likelihood_labels[li]}), impact ${impactScore} (${matrix.impact_labels[ii]}): no findings`;

            const isDominant = count > 0 && ids.some((id) => dominantIds.has(id));
            return (
              <div
                key={`${li}-${ii}`}
                className={`${styles.matrixCell} ${styles[`cell_${cellLevel}`]} ${count > 0 ? styles.matrixCellFilled : ''} ${isDominant ? styles.matrixCellDominant : ''}`}
                style={{ gridColumn: colIndex + 3, gridRow: rowIndex + 1 } as CSSProperties}
                title={title}
                aria-label={title}
              >
                {count > 0 && <span className={styles.matrixCellCount}>{count === 1 ? '!' : `!${count}`}</span>}
              </div>
            );
          }),
        )}

        {cols.map((ii, colIndex) => (
          <div
            key={`impact-${ii}`}
            className={styles.matrixXAxisLabel}
            style={{ gridColumn: colIndex + 3 } as CSSProperties}
          >
            <strong>{ii + 1}</strong>
            <span>{matrix.impact_labels[ii]}</span>
          </div>
        ))}
        <div className={styles.matrixXTitle}>Impact</div>
      </div>
    </div>
  );
}

function riskLevelForScores(likelihoodScore: number, impactScore: number): NistRiskLevel {
  const score = likelihoodScore * impactScore;
  if (score >= 17) return 'critical';
  if (score >= 10) return 'high';
  if (score >= 5) return 'moderate';
  return 'low';
}

// ── Risk finding card ─────────────────────────────────────────────────────────

function riskSignalLabel(obj: NistRiskObject): string {
  const base = SIGNAL_LABELS[obj.signal_type] ?? obj.signal_type;
  return obj.signal_subtype ? `${base} (${obj.signal_subtype})` : base;
}

function NistFindingCard({
  obj,
  expanded,
  onToggle,
}: {
  obj: NistRiskObject;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className={`${styles.findingCard} ${styles[`card_${obj.risk_level}`]}`}>
      <button className={styles.findingHeader} onClick={onToggle}>
        <span className={styles.findingHeaderMain}>
          <span className={`${styles.levelBadge} ${styles[`badge_${obj.risk_level}`]}`}>
            {obj.risk_level.toUpperCase()}
          </span>
          <span className={styles.findingTitle}>{riskSignalLabel(obj)}</span>
        </span>
        <span className={styles.findingChevron}>{expanded ? 'Hide details' : 'Show details'}</span>
      </button>

      <div className={styles.findingSummary}>
        <p>{obj.evidence_summary}</p>
        <div className={styles.findingPills}>
          <span>Likelihood {obj.likelihood}/5</span>
          <span>Impact {obj.impact}/5</span>
          <span>Risk score {obj.risk_score}/25</span>
          <span>Confidence {pct(obj.confidence)}</span>
        </div>
      </div>

      {expanded && (
        <div className={styles.findingDetail}>
          <div className={styles.detailSection}>
            <div className={styles.detailLabel}>Run details</div>
            <table className={styles.detailTable}>
              <tbody>
                <tr><td>Source</td><td>{obj.source_type}</td></tr>
                <tr><td>Session</td><td>{obj.run_id}</td></tr>
                {obj.timestamp_range && (
                  <tr>
                    <td>Time Range</td>
                    <td>{obj.timestamp_range[0].toFixed(2)} s – {obj.timestamp_range[1].toFixed(2)} s</td>
                  </tr>
                )}
                {obj.affected_robots.length > 0 && (
                  <tr><td>Affected Robots</td><td>{obj.affected_robots.join(', ')}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function StatusCard({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={`${styles.statusCard} ${wide ? styles.statusWide : ''}`}>
      <div className={styles.cardLabel}>{label}</div>
      <div className={styles.cardValue}>{value}</div>
    </div>
  );
}

function Timeline({ buckets }: { buckets: RiskTimelineBucket[] }) {
  const maxAnomalyFrames = Math.max(1, ...buckets.map((bucket) => bucket.anomaly_frames));
  if (buckets.length === 0) {
    return <div className={styles.empty}>No timeline buckets were produced for this recording.</div>;
  }
  const midTick = Math.ceil(maxAnomalyFrames / 2);
  const xTicks = timelineXTicks(buckets);

  return (
    <div className={styles.chartShell}>
      <div className={styles.yAxisName}>Velocity-spoof frames</div>
      <div className={styles.chartGrid}>
        <div className={styles.yTicks} aria-hidden="true">
          <span>{maxAnomalyFrames}</span>
          <span>{midTick}</span>
          <span>0</span>
        </div>
        <div className={styles.timeline} style={{ '--bucket-count': buckets.length } as CSSProperties}>
          {buckets.map((bucket) => {
            const hasAnomaly = bucket.anomaly_frames > 0;
            const height = hasAnomaly
              ? Math.max(6, Math.round((bucket.anomaly_frames / maxAnomalyFrames) * 100))
              : 0;
            return (
              <div
                key={bucket.start_frame}
                className={`${styles.bucket} ${hasAnomaly ? styles.bucketAnomaly : ''}`}
                style={{ height: `${height}%` } as CSSProperties}
                title={`Frames ${bucket.start_frame}-${bucket.end_frame}: ${bucket.anomaly_frames} velocity-spoof frame(s)`}
              />
            );
          })}
        </div>
      </div>
      <div className={styles.xTicks} aria-hidden="true">
        {xTicks.map((tick) => (
          <span key={tick.position} style={{ left: `${tick.position}%` }}>{tick.label}</span>
        ))}
      </div>
      <div className={styles.xAxisName}>Frame range, 20 frames per column</div>
    </div>
  );
}

// ── Formatters ────────────────────────────────────────────────────────────────

function shortId(runId: string): string {
  return runId.length > 12 ? `${runId.slice(0, 8)}…` : runId;
}

function formatDate(value?: number | null): string {
  if (typeof value !== 'number') return 'unknown start';
  const millis = value > 1_000_000_000_000 ? value : value * 1000;
  return new Intl.DateTimeFormat(undefined, {
    month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(millis));
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function timelineXTicks(buckets: RiskTimelineBucket[]): Array<{ label: string; position: number }> {
  if (buckets.length === 1) {
    const only = buckets[0];
    return [{ label: `${only.start_frame}-${only.end_frame}`, position: 0 }];
  }
  const indices = Array.from(new Set([
    0,
    Math.floor((buckets.length - 1) / 2),
    buckets.length - 1,
  ]));
  return indices.map((index) => {
    const bucket = buckets[index];
    const position = buckets.length === 1 ? 0 : (index / (buckets.length - 1)) * 100;
    return { label: `${bucket.start_frame}-${bucket.end_frame}`, position };
  });
}
