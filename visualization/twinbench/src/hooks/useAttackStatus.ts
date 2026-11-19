import { useState, useEffect, useRef, useCallback } from 'react';
import type { AttackState, AttackStatusTrackResponse, HistoryEntry } from '../types';
import { fetchAttackStatus } from '../api/client';

export interface FiredParams {
  type: 'false_brake' | 'velocity_spoof';
  follower: string | null;
  targetRobot: string | null;
  durationS: number;
  delayS: number;
  vsMode?: 'static' | 'ramp';
  speedMps?: number;
  speedStart?: number;
  speedEnd?: number;
}

export interface AttackTrack {
  state: AttackState;
  displayRemainingS: number;
  displayFiresInS: number;
  follower: string | null;
  targetRobot: string | null;
  speedMps: number | null;        // velocity_spoof current (interpolated for ramp)
  vsMode: 'static' | 'ramp' | null;
  speedStart: number | null;      // ramp only
  speedEnd: number | null;        // ramp only
}

export interface UseAttackStatusReturn {
  falseBrake: AttackTrack;
  velocitySpoof: AttackTrack;
  follower: string | null;
  targetRobot: string | null;
  targetRobots: string[];
  activeTargetRobots: string[];
  pendingTargetRobots: string[];
  history: HistoryEntry[];
  recordFired: (params: FiredParams) => void;
  recordStopped: (type: FiredParams['type']) => void;
}

const HISTORY_CAP = 100;

export function useAttackStatus(): UseAttackStatusReturn {
  const [fbState, setFbState] = useState<AttackState>('idle');
  const [fbDisplayRemaining, setFbDisplayRemaining] = useState(0);
  const [fbDisplayFiresIn, setFbDisplayFiresIn] = useState(0);
  const [fbFollower, setFbFollower] = useState<string | null>(null);
  const [fbTargetRobot, setFbTargetRobot] = useState<string | null>(null);

  const [vsState, setVsState] = useState<AttackState>('idle');
  const [vsDisplayRemaining, setVsDisplayRemaining] = useState(0);
  const [vsDisplayFiresIn, setVsDisplayFiresIn] = useState(0);
  const [vsFollower, setVsFollower] = useState<string | null>(null);
  const [vsTargetRobot, setVsTargetRobot] = useState<string | null>(null);
  const [vsSpeedMps, setVsSpeedMps] = useState<number | null>(null);
  const [vsMode, setVsMode] = useState<'static' | 'ramp' | null>(null);
  const [vsSpeedStart, setVsSpeedStart] = useState<number | null>(null);
  const [vsSpeedEnd, setVsSpeedEnd] = useState<number | null>(null);

  const [follower, setFollower] = useState<string | null>(null);
  const [targetRobot, setTargetRobot] = useState<string | null>(null);
  const [targetRobots, setTargetRobots] = useState<string[]>([]);
  const [activeTargetRobots, setActiveTargetRobots] = useState<string[]>([]);
  const [pendingTargetRobots, setPendingTargetRobots] = useState<string[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);

  // Interpolation refs
  const fbPollRemainingRef = useRef(0);
  const fbPollFiresInRef = useRef(0);
  const vsPollRemainingRef = useRef(0);
  const vsPollFiresInRef = useRef(0);
  const pollTimeRef = useRef(performance.now());

  // History tracking refs — one per attack type
  const fbPrevStateRef = useRef<AttackState>('idle');
  const fbActiveEntryIdRef = useRef<string | null>(null);
  const vsPrevStateRef = useRef<AttackState>('idle');
  const vsActiveEntryIdRef = useRef<string | null>(null);
  const fbPendingParamsRef = useRef<FiredParams | null>(null);
  const vsPendingParamsRef = useRef<FiredParams | null>(null);
  const fbStopRequestedRef = useRef(false);
  const vsStopRequestedRef = useRef(false);

  const recordFired = useCallback((params: FiredParams) => {
    if (params.type === 'false_brake') {
      fbPendingParamsRef.current = params;
      return;
    }
    vsPendingParamsRef.current = params;
  }, []);

  const getSharedIdentity = useCallback(
    (
      falseBrake: AttackStatusTrackResponse,
      velocitySpoof: AttackStatusTrackResponse | undefined,
      key: 'follower' | 'target_robot',
    ): string | null => {
      const values = [falseBrake[key] ?? null, velocitySpoof?.[key] ?? null].filter(
        (value): value is string => Boolean(value),
      );
      const uniqueValues = new Set(values);
      if (uniqueValues.size !== 1) {
        return null;
      }
      return values[0] ?? null;
    },
    [],
  );

  const recordStopped = useCallback((type: FiredParams['type']) => {
    if (type === 'false_brake') {
      fbStopRequestedRef.current = true;
      return;
    }
    vsStopRequestedRef.current = true;
  }, []);

  const poll = useCallback(async () => {
    try {
      const data = await fetchAttackStatus();
      const now = performance.now();

      // False brake
      const fb = data.false_brake ?? data;
      const newFbState = fb.status;
      const prevFbState = fbPrevStateRef.current;
      fbPollRemainingRef.current = fb.remaining_s ?? 0;
      fbPollFiresInRef.current = fb.fires_in_s ?? 0;
      setFbState(newFbState);
      setFbFollower(fb.follower ?? null);
      setFbTargetRobot(fb.target_robot ?? null);

      // Velocity spoof
      const vs = data.velocity_spoof;
      const newVsState = vs?.status ?? 'idle';
      const prevVsState = vsPrevStateRef.current;
      vsPollRemainingRef.current = vs?.remaining_s ?? 0;
      vsPollFiresInRef.current = vs?.fires_in_s ?? 0;
      const rawSpeed = vs?.speed_mps;
      setVsState(newVsState);
      setVsFollower(vs?.follower ?? null);
      setVsTargetRobot(vs?.target_robot ?? null);
      setVsSpeedMps(rawSpeed != null ? Number(rawSpeed) : null);
      setVsMode((vs?.mode as 'static' | 'ramp' | null | undefined) ?? null);
      setVsSpeedStart(vs?.speed_start ?? null);
      setVsSpeedEnd(vs?.speed_end ?? null);

      pollTimeRef.current = now;
      const currentTargetRobots = Array.from(new Set(
        [fb.target_robot ?? null, vs?.target_robot ?? null].filter(
          (value): value is string => Boolean(value),
        ),
      ));
      const currentActiveTargetRobots = Array.from(new Set(
        [
          newFbState === 'active' ? fb.target_robot ?? null : null,
          newVsState === 'active' ? vs?.target_robot ?? null : null,
        ].filter((value): value is string => Boolean(value)),
      ));
      const currentPendingTargetRobots = Array.from(new Set(
        [
          newFbState === 'pending' ? fb.target_robot ?? null : null,
          newVsState === 'pending' ? vs?.target_robot ?? null : null,
        ]
          .filter((value): value is string => Boolean(value))
          .filter((value) => !currentActiveTargetRobots.includes(value)),
      ));
      setFollower(getSharedIdentity(fb, vs, 'follower'));
      setTargetRobot(currentTargetRobots[0] ?? null);
      setTargetRobots(currentTargetRobots);
      setActiveTargetRobots(currentActiveTargetRobots);
      setPendingTargetRobots(currentPendingTargetRobots);

      const fbWasStopped = fbStopRequestedRef.current;
      const vsWasStopped = vsStopRequestedRef.current;

      // History transitions — false brake
      if (prevFbState === 'idle' && (newFbState === 'pending' || newFbState === 'active')) {
        const id = crypto.randomUUID();
        fbActiveEntryIdRef.current = id;
        const params = fbPendingParamsRef.current;
        setHistory((prev) => {
          const entry: HistoryEntry = {
            id,
            timestamp: new Date(),
            type: 'false_brake',
            follower: fb.follower ?? params?.follower ?? null,
            targetRobot: fb.target_robot ?? params?.targetRobot ?? null,
            durationS: params?.durationS ?? 0,
            delayS: params?.delayS ?? 0,
            outcome: 'active',
          };
          if (params) fbPendingParamsRef.current = null;
          const next = [entry, ...prev];
          return next.length > HISTORY_CAP ? next.slice(0, HISTORY_CAP) : next;
        });
      } else if (prevFbState !== 'idle' && newFbState === 'idle') {
        const id = fbActiveEntryIdRef.current;
        if (id) {
          const outcome = fbWasStopped ? 'cancelled' as const : 'completed' as const;
          setHistory((prev) => prev.map((e) => e.id === id ? { ...e, outcome } : e));
          fbActiveEntryIdRef.current = null;
        }
      }
      fbPrevStateRef.current = newFbState;
      if (newFbState === 'idle') {
        fbStopRequestedRef.current = false;
      }

      // History transitions — velocity spoof
      if (prevVsState === 'idle' && (newVsState === 'pending' || newVsState === 'active')) {
        const id = crypto.randomUUID();
        vsActiveEntryIdRef.current = id;
        const params = vsPendingParamsRef.current;
        setHistory((prev) => {
          const entry: HistoryEntry = {
            id,
            timestamp: new Date(),
            type: 'velocity_spoof',
            follower: vs?.follower ?? params?.follower ?? null,
            targetRobot: vs?.target_robot ?? params?.targetRobot ?? null,
            durationS: params?.durationS ?? 0,
            delayS: params?.delayS ?? 0,
            vsMode: params?.vsMode,
            speedMps: params?.speedMps ?? (rawSpeed != null ? Number(rawSpeed) : undefined),
            speedStart: params?.speedStart,
            speedEnd: params?.speedEnd,
            outcome: 'active',
          };
          if (params) vsPendingParamsRef.current = null;
          const next = [entry, ...prev];
          return next.length > HISTORY_CAP ? next.slice(0, HISTORY_CAP) : next;
        });
      } else if (prevVsState !== 'idle' && newVsState === 'idle') {
        const id = vsActiveEntryIdRef.current;
        if (id) {
          const outcome = vsWasStopped ? 'cancelled' as const : 'completed' as const;
          setHistory((prev) => prev.map((e) => e.id === id ? { ...e, outcome } : e));
          vsActiveEntryIdRef.current = null;
        }
      }
      vsPrevStateRef.current = newVsState;
      if (newVsState === 'idle') {
        vsStopRequestedRef.current = false;
      }

    } catch {
      // Preserve the last known state across transient polling failures.
    }
  }, []);

  useEffect(() => {
    void poll();
    const pollInterval = setInterval(() => { void poll(); }, 1000);
    const displayInterval = setInterval(() => {
      const elapsed = (performance.now() - pollTimeRef.current) / 1000;
      setFbDisplayRemaining(Math.max(0, fbPollRemainingRef.current - elapsed));
      setFbDisplayFiresIn(Math.max(0, fbPollFiresInRef.current - elapsed));
      setVsDisplayRemaining(Math.max(0, vsPollRemainingRef.current - elapsed));
      setVsDisplayFiresIn(Math.max(0, vsPollFiresInRef.current - elapsed));
    }, 100);

    return () => {
      clearInterval(pollInterval);
      clearInterval(displayInterval);
    };
  }, [poll]);

  return {
    falseBrake: {
      state: fbState,
      displayRemainingS: fbDisplayRemaining,
      displayFiresInS: fbDisplayFiresIn,
      follower: fbFollower,
      targetRobot: fbTargetRobot,
      speedMps: null,
      vsMode: null,
      speedStart: null,
      speedEnd: null,
    },
    velocitySpoof: {
      state: vsState,
      displayRemainingS: vsDisplayRemaining,
      displayFiresInS: vsDisplayFiresIn,
      follower: vsFollower,
      targetRobot: vsTargetRobot,
      speedMps: vsSpeedMps,
      vsMode,
      speedStart: vsSpeedStart,
      speedEnd: vsSpeedEnd,
    },
    follower,
    targetRobot,
    targetRobots,
    activeTargetRobots,
    pendingTargetRobots,
    history,
    recordFired,
    recordStopped,
  };
}
