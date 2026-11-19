import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchLiveAlerts, fetchSystemAssessment } from '../api/client';
import type { LiveAlertsSnapshot, NistRiskLevel, SystemAssessment } from '../types';

const LEVEL_ORDER: Record<string, number> = { low: 0, moderate: 1, high: 2, critical: 3 };

function maxLevel(a: NistRiskLevel, b: NistRiskLevel): NistRiskLevel {
  return (LEVEL_ORDER[a] ?? 0) >= (LEVEL_ORDER[b] ?? 0) ? a : b;
}

export function useSystemRisk(alertIntervalMs = 2000, fullIntervalMs = 12000, refreshKey = 0) {
  const [assessment, setAssessment] = useState<SystemAssessment | null>(null);
  const [alerts, setAlerts] = useState<LiveAlertsSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  const refreshFull = useCallback(async () => {
    try {
      const data = await fetchSystemAssessment();
      if (mountedRef.current) {
        setAssessment(data);
        setError(null);
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Unable to load system assessment');
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, []);

  const refreshAlerts = useCallback(async () => {
    try {
      const data = await fetchLiveAlerts();
      if (mountedRef.current) setAlerts(data);
    } catch {
      // Non-blocking; full assessment error is the primary signal.
    }
  }, []);

  // On refreshKey change, trigger both immediately.
  useEffect(() => {
    void refreshFull();
    void refreshAlerts();
  }, [refreshFull, refreshAlerts, refreshKey]);

  // Fast poll: live alerts only (no disk reads).
  useEffect(() => {
    mountedRef.current = true;
    const timer = setInterval(() => void refreshAlerts(), alertIntervalMs);
    return () => {
      mountedRef.current = false;
      clearInterval(timer);
    };
  }, [refreshAlerts, alertIntervalMs]);

  // Slow poll: full assessment with historical data.
  useEffect(() => {
    const timer = setInterval(() => void refreshFull(), fullIntervalMs);
    return () => clearInterval(timer);
  }, [refreshFull, fullIntervalMs]);

  // Merge: overlay live alerts snapshot on top of full assessment when fresher.
  const mergedAssessment = useMemo<SystemAssessment | null>(() => {
    if (!assessment) return null;
    if (!alerts || alerts.computed_at <= assessment.computed_at) return assessment;

    const liveLevel = alerts.overall_level;
    const histLevel = assessment.historical_contribution.level;
    return {
      ...assessment,
      active_alerts: alerts.active_alerts,
      overall_level: maxLevel(liveLevel, histLevel),
      live_contribution: {
        ...assessment.live_contribution,
        level: liveLevel,
        threats: alerts.active_alerts,
        active_run_state: alerts.live_run_state,
      },
    };
  }, [assessment, alerts]);

  return { assessment: mergedAssessment, loading, error, refresh: refreshFull };
}
