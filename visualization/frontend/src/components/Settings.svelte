<script lang="ts">
  import { onMount } from 'svelte';
  import { toggleSfx, toggleMusic, setMusicVol } from '../canvas/audio';
  import { state } from '../canvas/state';
  import { updateRoadBuffer, initRoadBuffers } from '../canvas/render/drawRoad';
  import { updateAlignment, initAlignment } from '../canvas/render/alignment';
  import { rebuildPanel } from '../canvas/panel';
  import { shiftTransitionCache } from '../canvas/render/drawTrail';

  export let open = false;
  export let liveMode = true;
  export let liveReconnect: () => void;
  export let liveExit: () => void;

  let sfxOn = true;
  let musicOn = false;
  let musicVol = 45;

  let host = '';
  let port = 1883;
  let username = '';
  let password = '';
  let passwordTouched = false;
  let topic = 'vehicle/+/#';
  let liveHz = 20;
  let rollingBufferMaxFrames = 5000;
  let bufferMax = state.LIVE_BUFFER_MAX;
  let testing = false;
  let applying = false;
  let mqttDirty = false;
  let remoteConfigNotice = '';
  let testResult: { ok: boolean; latency_ms?: number; error?: string } | null = null;

  type MqttConfigPayload = {
    host: string;
    port: number;
    username?: string | null;
    topic: string;
    live_hz: number;
    rolling_buffer_max_frames?: number;
    connected?: boolean;
  };

  $: if (open) loadMqttConfig();

  onMount(() => {
    const handleConfig = (e: Event) => {
      syncIncomingConfig((e as CustomEvent<MqttConfigPayload>).detail);
    };
    window.addEventListener('tg:mqttconfig', handleConfig);
    return () => window.removeEventListener('tg:mqttconfig', handleConfig);
  });

  function handleSfx() {
    toggleSfx();
    sfxOn = !sfxOn;
  }

  function handleMusic() {
    toggleMusic();
    musicOn = !musicOn;
  }

  function markMqttDirty() {
    mqttDirty = true;
    remoteConfigNotice = '';
  }

  function applyLocalBufferMax(nextValue: number) {
    const safeMax = Number.isFinite(nextValue) && nextValue >= 60
      ? Math.round(nextValue)
      : state.LIVE_BUFFER_MAX;
    state.LIVE_BUFFER_MAX = safeMax;
    const excess = state.liveFrameBuffer.length - safeMax;
    if (excess > 0) {
      state.liveFrameBuffer.splice(0, excess);
      shiftTransitionCache(excess);
    }
    if (state.liveFrameBuffer.length === 0) {
      state.fi = 0;
      state.accumT = 0;
      return;
    }
    state.fi = Math.min(state.fi, state.liveFrameBuffer.length - 1);
    state.accumT = Math.min(state.accumT, state.liveFrameBuffer[state.fi]?.t ?? state.accumT);
    if (state.RUNS[state.LIVE_RUN]?.frames === state.liveFrameBuffer) {
      state.roadBuffer[state.LIVE_RUN] = {};
      state.curvatureScale[state.LIVE_RUN] = undefined;
      state.alignmentState[state.LIVE_RUN] = {};
      state.globalRoadMap[state.LIVE_RUN] = [];
      state._globalMapIdx[state.LIVE_RUN] = {};
      rebuildPanel();
      initRoadBuffers(state.LIVE_RUN);
      initAlignment(state.LIVE_RUN);
      state.liveFrameBuffer.forEach((frame, index) => {
        updateRoadBuffer(state.LIVE_RUN, frame);
        updateAlignment(state.LIVE_RUN, frame, index);
      });
    }
  }

  function applyConfigToForm(data: MqttConfigPayload) {
    host = data.host;
    port = data.port;
    username = data.username ?? '';
    password = '';
    topic = data.topic;
    liveHz = data.live_hz;
    rollingBufferMaxFrames = Number.isFinite(data.rolling_buffer_max_frames)
      ? Number(data.rolling_buffer_max_frames)
      : 5000;
    passwordTouched = false;
    mqttDirty = false;
    remoteConfigNotice = '';
  }

  function syncIncomingConfig(data: MqttConfigPayload) {
    if (!data) return;
    if (!open || !mqttDirty) {
      applyConfigToForm(data);
      return;
    }
    remoteConfigNotice = 'Settings were updated in another client. Save or reopen to reload.';
  }

  async function loadMqttConfig() {
    testResult = null;
    bufferMax = state.LIVE_BUFFER_MAX;
    try {
      const res = await fetch('/api/config/mqtt');
      if (res.ok) {
        const data: MqttConfigPayload = await res.json();
        syncIncomingConfig(data);
      }
    } catch (e) {
      console.warn('Could not fetch MQTT config:', e);
    }
  }

  async function testConnection() {
    const safePort = Number(port);
    if (!Number.isInteger(safePort) || safePort < 1 || safePort > 65535) {
      testResult = { ok: false, error: 'Port must be an integer between 1 and 65535' };
      return;
    }

    testing = true;
    testResult = null;
    try {
      const testBody: Record<string, unknown> = {
        host: host.trim(),
        port: safePort,
        username: username || null,
      };
      if (passwordTouched) {
        testBody.password = password || null;
      } else {
        testBody.use_stored_password = true;
      }
      const res = await fetch('/api/config/mqtt/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(testBody),
      });
      testResult = await res.json();
    } catch (e: any) {
      testResult = { ok: false, error: e.message ?? 'Request failed' };
    } finally {
      testing = false;
    }
  }

  async function applySettings() {
    const safePort = Number(port);
    const safeLiveHz = Number(liveHz);
    const safeRollingBufferMaxFrames = Number(rollingBufferMaxFrames);
    const safeBufferMax = Number(bufferMax);
    if (!Number.isInteger(safeBufferMax) || safeBufferMax < 60 || safeBufferMax > 12000) {
      testResult = { ok: false, error: 'Local view history must be between 60 and 12000 frames' };
      return;
    }
    if (!mqttDirty) {
      applyLocalBufferMax(safeBufferMax);
      open = false;
      return;
    }
    if (!host.trim()) {
      testResult = { ok: false, error: 'Host is required' };
      return;
    }
    if (!Number.isInteger(safePort) || safePort < 1 || safePort > 65535) {
      testResult = { ok: false, error: 'Port must be an integer between 1 and 65535' };
      return;
    }
    if (!topic.trim()) {
      testResult = { ok: false, error: 'Topic is required' };
      return;
    }
    if (!Number.isFinite(safeLiveHz) || safeLiveHz <= 0 || safeLiveHz > 100) {
      testResult = { ok: false, error: 'Sample rate must be between 1 and 100 Hz' };
      return;
    }
    if (!Number.isInteger(safeRollingBufferMaxFrames) || safeRollingBufferMaxFrames < 60) {
      testResult = { ok: false, error: 'Shared history must be at least 60 frames' };
      return;
    }
    applying = true;
    testResult = null;
    try {
      const patchBody: Record<string, unknown> = {
        host: host.trim(),
        port: safePort,
        username: username || null,
        topic: topic.trim(),
        live_hz: safeLiveHz,
        rolling_buffer_max_frames: safeRollingBufferMaxFrames,
      };
      if (passwordTouched) patchBody.password = password;

      const res = await fetch('/api/config/mqtt', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patchBody),
      });
      const data = await res.json();
      if (data.ok) {
        applyLocalBufferMax(safeBufferMax);
        mqttDirty = false;
        remoteConfigNotice = '';
        if (liveMode) liveReconnect();
        if (data.warning) {
          testResult = { ok: false, error: data.warning };
          // Leave drawer open so the warning is visible; user closes manually.
        } else {
          open = false;
        }
      } else {
        const msg = data.error
          ?? (Array.isArray(data.detail) ? data.detail[0]?.msg : null)
          ?? 'Apply failed';
        testResult = { ok: false, error: msg };
        if (liveMode) liveExit();
      }
    } catch (e: any) {
      testResult = { ok: false, error: e.message ?? 'Request failed' };
    } finally {
      applying = false;
    }
  }
</script>

{#if open}
  <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
  <div class="backdrop" on:click={() => (open = false)}></div>

  <div class="drawer">
    <div class="drawer-hdr">
      <span class="drawer-title">SETTINGS</span>
      <button class="drawer-close" on:click={() => (open = false)}>x</button>
    </div>

    <form class="drawer-body" on:submit|preventDefault={applySettings}>
      <div class="section-hdr">AUDIO</div>
      <div class="audio-row">
        <button type="button" class="abtn" class:on={sfxOn} on:click={handleSfx}
                data-tip="Toggle state-transition sounds">SFX</button>
        <button type="button" class="abtn" class:on={musicOn} on:click={handleMusic}
                data-tip="Toggle ambient music - reacts to speed, steering and errors">MUS</button>
        <input
          type="range"
          class="vol-slider"
          min="0" max="100"
          bind:value={musicVol}
          on:input={() => setMusicVol(musicVol)}
          data-tip="Music volume"
        />
      </div>

      <div class="divider"></div>

      <div class="section-hdr">MQTT BROKER</div>

      {#if remoteConfigNotice}
        <div class="test-result err">{remoteConfigNotice}</div>
      {/if}

      <label class="field-label">Host
        <input class="field-input" type="text" bind:value={host} placeholder="localhost" on:input={markMqttDirty} />
      </label>
      <label class="field-label">Port
        <input class="field-input" type="number" bind:value={port} min="1" max="65535" on:input={markMqttDirty} />
      </label>
      <label class="field-label">
        Username <span class="field-opt">(optional)</span>
        <input class="field-input" type="text" bind:value={username} placeholder="-" autocomplete="off" on:input={markMqttDirty} />
      </label>
      <label class="field-label">
        Password <span class="field-opt">(optional)</span>
        <input
          class="field-input"
          type="password"
          bind:value={password}
          placeholder="-"
          autocomplete="new-password"
          on:input={() => { passwordTouched = true; markMqttDirty(); }}
        />
      </label>
      <label class="field-label">Topic
        <input class="field-input" type="text" bind:value={topic} placeholder="vehicle/+/#" on:input={markMqttDirty} />
      </label>

      <div class="divider"></div>

      <div class="section-hdr">LIVE STREAM</div>

      <div class="test-result">
        Shared history is kept on the backend for all clients. Local view history only affects this browser.
      </div>

      <label class="field-label">Sample rate <span class="field-opt">(Hz)</span>
        <input class="field-input" type="number" bind:value={liveHz} min="1" max="100" step="1" on:input={markMqttDirty} />
      </label>
      <label class="field-label">Shared history <span class="field-opt">(backend, used by all clients)</span>
        <input class="field-input" type="number" bind:value={rollingBufferMaxFrames} min="60" max="200000" step="60" on:input={markMqttDirty} />
      </label>
      <label class="field-label">Local view history <span class="field-opt">(this browser only, ~{Math.round(bufferMax / liveHz)} s)</span>
        <input class="field-input" type="number" bind:value={bufferMax} min="60" max="12000" step="60" />
      </label>

      {#if testResult}
        <div class="test-result" class:ok={testResult.ok} class:err={!testResult.ok}>
          {#if testResult.ok}
            OK {testResult.latency_ms} ms
          {:else}
            {testResult.error}
          {/if}
        </div>
      {/if}

      <div class="actions">
        <button type="button" class="action-btn secondary" on:click={testConnection} disabled={testing}>
          {testing ? '...' : 'TEST'}
        </button>
        <button type="submit" class="action-btn primary" disabled={applying}>
          {applying ? '...' : 'APPLY'}
        </button>
      </div>
    </form>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed; inset: 0; z-index: 100;
    background: rgba(0, 0, 0, 0.3);
  }

  .drawer {
    position: fixed;
    top: 68px; right: 0; bottom: 0;
    width: 270px;
    z-index: 101;
    background: var(--pan);
    border-left: 1px solid var(--bdr2);
    display: flex; flex-direction: column;
    box-shadow: -4px 0 24px rgba(0, 0, 0, 0.5);
  }

  .drawer-hdr {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid var(--bdr);
    background: var(--pan2);
    flex-shrink: 0;
  }

  .drawer-title {
    font-family: var(--fui); font-size: 12px; font-weight: 700;
    letter-spacing: 3px; text-transform: uppercase; color: var(--txhi);
  }

  .drawer-close {
    width: 22px; height: 22px;
    background: none; border: 1px solid var(--bdr); border-radius: 3px;
    color: var(--txlo); cursor: pointer; font-size: 11px;
    display: flex; align-items: center; justify-content: center;
    transition: all 0.12s;
  }
  .drawer-close:hover { border-color: var(--red); color: var(--red); }

  .drawer-body {
    flex: 1; overflow-y: auto;
    padding: 16px;
    display: flex; flex-direction: column; gap: 12px;
  }

  .section-hdr {
    font-family: var(--fmono); font-size: 9px; letter-spacing: 2.5px;
    text-transform: uppercase; color: var(--txlo);
    padding-bottom: 4px;
  }

  .divider {
    height: 1px; background: var(--bdr); margin: 4px 0;
  }

  .audio-row {
    display: flex; align-items: center; gap: 6px;
  }

  :global(.abtn) {
    height: 26px; padding: 0 9px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--bdr);
    border-radius: 4px;
    color: var(--txlo);
    cursor: pointer;
    font-family: var(--fmono);
    font-size: 9px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    white-space: nowrap;
    transition: all 0.15s;
  }
  :global(.abtn:hover) { border-color: rgba(255, 255, 255, 0.25); color: var(--tx); }
  :global(.abtn.on) { border-color: var(--s0); color: var(--s0); background: rgba(0, 229, 255, 0.07); }

  .vol-slider {
    -webkit-appearance: none;
    flex: 1; height: 3px;
    background: var(--bdr);
    border-radius: 2px;
    outline: none;
    cursor: pointer;
  }
  .vol-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 11px; height: 11px;
    border-radius: 50%;
    background: var(--s0);
    cursor: pointer;
  }

  .field-label {
    display: flex; flex-direction: column; gap: 4px;
    font-family: var(--fmono); font-size: 9px; letter-spacing: 1.5px;
    text-transform: uppercase; color: var(--txlo);
  }

  .field-opt {
    text-transform: none; letter-spacing: 0; opacity: 0.6; font-size: 9px;
  }

  .field-input {
    height: 30px; padding: 0 10px;
    background: var(--pan2);
    border: 1px solid var(--bdr2);
    border-radius: 4px;
    color: var(--txhi);
    font-family: var(--fmono); font-size: 11px;
    outline: none;
    transition: border-color 0.12s;
  }
  .field-input:focus { border-color: var(--s0); }
  .field-input::placeholder { color: var(--txlo); opacity: 0.6; }

  .test-result {
    padding: 7px 10px; border-radius: 4px;
    font-family: var(--fmono); font-size: 10px; letter-spacing: 1px;
  }
  .test-result.ok  { background: rgba(0, 255, 136, 0.08); border: 1px solid rgba(0, 255, 136, 0.25); color: var(--green); }
  .test-result.err { background: rgba(255, 48, 96, 0.08);  border: 1px solid rgba(255, 48, 96, 0.25);  color: var(--red); }

  .actions {
    display: flex; gap: 8px; margin-top: 4px;
  }

  .action-btn {
    flex: 1; height: 30px;
    border-radius: 4px; cursor: pointer;
    font-family: var(--fmono); font-size: 10px; letter-spacing: 2px;
    text-transform: uppercase; transition: all 0.15s;
  }
  .action-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .action-btn.secondary {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--bdr2); color: var(--tx);
  }
  .action-btn.secondary:hover:not(:disabled) { border-color: var(--s0); color: var(--s0); }

  .action-btn.primary {
    background: rgba(0, 229, 255, 0.1);
    border: 1px solid var(--s0); color: var(--s0);
  }
  .action-btn.primary:hover:not(:disabled) { background: rgba(0, 229, 255, 0.18); }
</style>
