import { useState, useEffect, useRef, useCallback } from 'react';
import type { LiveFrame, LiveFrameEnvelope, MqttConfig, WsStatus } from '../types';
import { fetchLiveBuffer } from '../api/client';

const BUFFER_LIMIT = 300;
const BOOTSTRAP_TIMEOUT_MS = 1500;

export interface UseLiveSocketReturn {
  latestFrame: LiveFrame | null;
  robotIds: string[];
  wsStatus: WsStatus;
  reconnect: () => void;
}

export function useLiveSocket(): UseLiveSocketReturn {
  const [latestFrame, setLatestFrame] = useState<LiveFrame | null>(null);
  const [robotIds, setRobotIds] = useState<string[]>([]);
  const [wsStatus, setWsStatus] = useState<WsStatus>('connecting');

  const wsRef = useRef<WebSocket | null>(null);
  const lastFrameIdRef = useRef(0);
  const sessionIdRef = useRef<string | null>(null);

  const connect = useCallback(() => {
    // Tear down any existing socket cleanly
    if (wsRef.current) {
      wsRef.current.onmessage = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    setWsStatus('connecting');
    setLatestFrame(null);
    setRobotIds([]);
    lastFrameIdRef.current = 0;
    sessionIdRef.current = null;

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/ws/live`);
    wsRef.current = ws;

    // Bootstrap: fetch buffer snapshot while the WS handshake completes.
    // Pending live envelopes are queued and flushed after snapshot is applied,
    // mirroring the pattern in liveMode.ts.
    let bootstrapping = true;
    const pending: LiveFrameEnvelope[] = [];
    const timeoutId = window.setTimeout(() => {
      if (!bootstrapping) return;
      bootstrapping = false;
      pending.forEach(processEnvelope);
      pending.length = 0;
    }, BOOTSTRAP_TIMEOUT_MS);

    fetchLiveBuffer(BUFFER_LIMIT)
      .then((snapshot) => {
        window.clearTimeout(timeoutId);
        if (!bootstrapping) return;
        bootstrapping = false;

        sessionIdRef.current = snapshot.session_id;

        if (snapshot.robots?.length) {
          setRobotIds(snapshot.robots);
        }

        if (Array.isArray(snapshot.frames) && snapshot.frames.length > 0) {
          const last = snapshot.frames[snapshot.frames.length - 1];
          if (last?.data) setLatestFrame(last.data);
          if (last?.frame_id != null) lastFrameIdRef.current = last.frame_id;
        }

        // Flush any envelopes that arrived while bootstrapping
        pending.forEach(processEnvelope);
        pending.length = 0;
      })
      .catch(() => {
        window.clearTimeout(timeoutId);
        bootstrapping = false;
        pending.forEach(processEnvelope);
        pending.length = 0;
      });

    function processEnvelope(envelope: LiveFrameEnvelope) {
      // Session fence: reset counters when the backend starts a new session
      if (
        envelope.session_id &&
        sessionIdRef.current &&
        envelope.session_id !== sessionIdRef.current
      ) {
        sessionIdRef.current = envelope.session_id;
        lastFrameIdRef.current = 0;
      }

      // Drop out-of-order or duplicate frames
      if (envelope.frame_id != null && envelope.frame_id <= lastFrameIdRef.current) return;
      if (envelope.frame_id != null) lastFrameIdRef.current = envelope.frame_id;

      if (!envelope.data) return;
      setLatestFrame(envelope.data);

      // Keep robotIds in sync as new robots appear mid-session
      const ids = Object.keys(envelope.data.robots ?? {});
      if (ids.length > 0) {
        setRobotIds((prev) => {
          const newIds = ids.filter((id) => !prev.includes(id));
          return newIds.length > 0 ? [...prev, ...newIds] : prev;
        });
      }
    }

    ws.onopen = () => setWsStatus('connected');
    ws.onerror = () => setWsStatus('disconnected');
    ws.onclose = () => setWsStatus('disconnected');

    ws.onmessage = (event: MessageEvent<string>) => {
      let msg: { type: string; data?: LiveFrameEnvelope | MqttConfig };
      try {
        msg = JSON.parse(event.data) as { type: string; data?: LiveFrameEnvelope | MqttConfig };
      } catch {
        return;
      }

      if (msg.type === 'meta') {
        return;
      }

      if (msg.type === 'config' && msg.data) {
        // Broadcast to any settings panels listening on this page
        window.dispatchEvent(new CustomEvent('tg:mqttconfig', { detail: msg.data }));
        return;
      }

      if (msg.type === 'frame' && msg.data) {
        if (bootstrapping) {
          pending.push(msg.data as LiveFrameEnvelope);
        } else {
          processEnvelope(msg.data as LiveFrameEnvelope);
        }
      }
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect]);

  return { latestFrame, robotIds, wsStatus, reconnect: connect };
}
