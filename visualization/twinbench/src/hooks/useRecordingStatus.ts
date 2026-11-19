import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchActiveRecording, startRecording, stopRecording } from '../api/client';
import type { RecordingStatus, RiskSessionAnalysis } from '../types';

interface UseRecordingStatusReturn {
  recording: RecordingStatus;
  loading: boolean;
  syncing: boolean;
  saving: boolean;
  error: string | null;
  start: (name?: string) => Promise<void>;
  stop: () => Promise<RiskSessionAnalysis | null>;
}

export function useRecordingStatus(): UseRecordingStatusReturn {
  const [recording, setRecording] = useState<RecordingStatus>({ active: false });
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const savingRef = useRef(false);
  const mutationVersionRef = useRef(0);

  const refresh = useCallback(async () => {
    const refreshVersion = mutationVersionRef.current;
    if (loading) {
      setLoading(true);
    } else {
      setSyncing(true);
    }
    try {
      const next = await fetchActiveRecording();
      if (savingRef.current || refreshVersion !== mutationVersionRef.current) return;
      setRecording(next);
      setError(null);
    } catch (err) {
      if (savingRef.current || refreshVersion !== mutationVersionRef.current) return;
      setError(err instanceof Error ? err.message : 'Unable to read recording state');
    } finally {
      if (refreshVersion === mutationVersionRef.current) {
        setLoading(false);
        setSyncing(false);
      }
    }
  }, [loading]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (saving) return;
    const timer = window.setInterval(() => {
      void refresh();
    }, recording.active ? 1000 : 2500);
    return () => window.clearInterval(timer);
  }, [recording.active, refresh, saving]);

  const start = useCallback(async (name = '') => {
    mutationVersionRef.current += 1;
    savingRef.current = true;
    setSaving(true);
    try {
      const started = await startRecording(name);
      setRecording({
        active: true,
        run_id: started.run_id,
        name: started.name,
        started_at: started.started_at,
        frame_count: 0,
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to start recording');
    } finally {
      savingRef.current = false;
      setLoading(false);
      setSyncing(false);
      setSaving(false);
    }
  }, []);

  const stop = useCallback(async () => {
    mutationVersionRef.current += 1;
    savingRef.current = true;
    setSaving(true);
    try {
      const result = await stopRecording();
      setRecording({ active: false });
      setError(null);
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to stop recording');
      return null;
    } finally {
      savingRef.current = false;
      setLoading(false);
      setSyncing(false);
      setSaving(false);
    }
  }, []);

  return { recording, loading, syncing, saving, error, start, stop };
}
