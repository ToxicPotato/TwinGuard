<script lang="ts">
  export let liveMode: boolean;
  export let connStatus: 'connecting' | 'connected' | 'disconnected';
  export let hasReplayRuns: boolean;
  export let onUploadClick: () => void;
  export let uploading: boolean;
  export let uploadError: string;
  export let uploadMsg: string;
  export let onSettingsClick: () => void;
  export let onTwinbenchClick: () => void;
  export let onSwitchToLive: () => void;
  export let onSwitchToReplay: () => void;
  export let recordingActive = false;
  export let recordingLoading = true;
  export let recordingBusy = false;
  export let recordingLabel = 'Idle';
  export let recordingError = '';
  export let onToggleRecording: () => void;
</script>

<header class="hdr">
  <div class="logo">
    <img class="logo-icon" src="/header-shield.svg" alt="" aria-hidden="true" />
    TwinGuard
  </div>

  <div class="hdr-sep"></div>

  <div class="mode-tabs">
    <button
      class="mode-tab"
      class:active={liveMode}
      on:click={onSwitchToLive}
      data-tip="Switch to live MQTT stream">
      LIVE
    </button>
    <button
      class="mode-tab"
      class:active={!liveMode}
      on:click={onSwitchToReplay}
      data-tip="Switch to file replay">
      REPLAY
    </button>
  </div>

  <div class="hdr-center">
    {#if liveMode}
      <span class="conn-badge conn-{connStatus}">
        {#if connStatus === 'connected'}CONNECTED
        {:else if connStatus === 'connecting'}CONNECTING
        {:else}DISCONNECTED{/if}
      </span>
    {/if}

    <span
      class="hdr-time"
      id="htime"
      style:display={liveMode || hasReplayRuns ? 'inline' : 'none'}
    >0.000 s</span>

    {#if !liveMode && !hasReplayRuns}
      <span class="hdr-hint">Upload a file or switch to LIVE</span>
    {/if}
  </div>

  <div class="hdr-sep"></div>

  <div class="hdr-right">
    <div class="twin-pill" data-tip="Low-resolution twin&#10;Current platoon structure assessment">
      <span class="twin-k">Low-Res Twin</span>
      <span class="twin-v" id="tw-low-score">--</span>
      <span class="twin-sub" id="tw-low-sub">components</span>
    </div>
    <div class="twin-pill" data-tip="High-resolution twin&#10;Current platoon structure assessment">
      <span class="twin-k">High-Res Twin</span>
      <span class="twin-v" id="tw-high-score">--</span>
      <span class="twin-sub" id="tw-high-sub">components</span>
    </div>
    <div class="twin-pill" data-tip="Twin pipeline compute time per frame (ms)&#10;Low-Res vs High-Res thesis RQ3 cost comparison">
      <span class="twin-k">Timing ms</span>
      <span class="twin-v" id="tw-timing-val">-- / --</span>
      <span class="twin-sub" id="tw-timing-sub">lr / hr</span>
    </div>

    <div class="hdr-pills-sep"></div>

    <select
      id="run-sel"
      class="run-sel"
      style:display={!liveMode && hasReplayRuns ? 'block' : 'none'}
    ></select>

    {#if !liveMode && hasReplayRuns}
      <button
        class="hdr-abtn"
        on:click={onUploadClick}
        disabled={uploading}
        data-tip="Upload another .xlsx run file">
        {#if uploading}
          <span class="hdr-spinner"></span>
          {#if uploadMsg}<span class="hdr-upload-msg">{uploadMsg}</span>{/if}
        {:else}
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          ADD FILE
        {/if}
      </button>
      {#if !uploading && uploadError}
        <span class="hdr-err">{uploadError}</span>
      {/if}
    {/if}

    {#if liveMode}
      <div
        class="record-pill"
        class:active={recordingActive}
        data-tip={recordingActive ? 'Backend capture is active' : 'Backend capture is idle'}>
        <span class="record-dot"></span>
        <span class="record-text">{recordingActive ? 'REC' : 'IDLE'}</span>
        <span class="record-sub">{recordingLabel}</span>
      </div>
      <button
        class="hdr-abtn record-btn"
        on:click={onToggleRecording}
        disabled={recordingLoading || recordingBusy}
        data-tip={recordingActive ? 'Stop current live capture' : 'Start a backend live capture'}>
        {#if recordingBusy}
          <span class="hdr-spinner"></span>
        {/if}
        {#if recordingLoading}
          SYNCING
        {:else}
          {recordingActive ? 'STOP REC' : 'START REC'}
        {/if}
      </button>
      <button
        class="icon-btn bench-btn"
        on:click={onTwinbenchClick}
        data-tip="Open TwinBench operator console">LAB</button>
    {/if}
    <button class="icon-btn" on:click={onSettingsClick} data-tip="Settings">⚙</button>
  </div>
</header>

{#if liveMode && recordingError}
  <div class="record-error">{recordingError}</div>
{/if}

<style>
  :global(.hdr-abtn) {
    display: flex; align-items: center; gap: 6px;
    padding: 5px 12px;
    background: rgba(10, 14, 26, 0.7);
    border: 1px solid rgba(0, 200, 255, 0.3);
    border-radius: 6px;
    color: #b8d4e8;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px; letter-spacing: 1.5px;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s, color 0.15s;
    white-space: nowrap;
  }
  :global(.hdr-abtn:hover:not(:disabled)) {
    border-color: rgba(0, 200, 255, 0.65);
    background: rgba(0, 200, 255, 0.07);
    color: #daeef8;
  }
  :global(.hdr-abtn:disabled) { opacity: 0.4; cursor: not-allowed; }

  :global(.hdr-err) {
    color: #ff4d6d;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    max-width: 180px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  :global(.hdr-upload-msg) {
    color: #b8d4e8;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px; letter-spacing: 0.5px;
    white-space: nowrap;
  }
  :global(.hdr-spinner) {
    width: 11px; height: 11px;
    border: 1.5px solid rgba(0, 200, 255, 0.3);
    border-top-color: #00c8ff;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    display: inline-block;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  :global(.bench-btn) {
    font-size: 9px !important;
    letter-spacing: 1.5px !important;
  }
  :global(.bench-btn:hover) {
    border-color: var(--s0) !important;
    color: var(--s0) !important;
    background: rgba(0, 229, 255, 0.08) !important;
  }
  :global(.record-btn) {
    border-color: rgba(255, 48, 96, 0.24);
  }
  :global(.record-btn:hover:not(:disabled)) {
    border-color: rgba(255, 48, 96, 0.55);
    color: #ffd3dc;
    background: rgba(255, 48, 96, 0.08);
  }
  .record-pill {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    flex-shrink: 0;
    padding: 6px 12px;
    border: 1px solid var(--bdr);
    border-radius: 8px;
    background: linear-gradient(180deg, rgba(10,17,32,.95), rgba(13,22,40,.75));
  }
  .record-pill.active {
    border-color: rgba(255, 48, 96, 0.36);
    background: linear-gradient(180deg, rgba(44,12,22,.95), rgba(28,10,16,.85));
  }
  .record-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--txlo);
    flex-shrink: 0;
  }
  .record-pill.active .record-dot {
    background: var(--red);
    box-shadow: 0 0 10px rgba(255, 48, 96, 0.5);
    animation: pulse-red 0.8s infinite;
  }
  .record-text {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    letter-spacing: 1.8px;
    color: var(--txhi);
    white-space: nowrap;
  }
  .record-sub {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: var(--txlo);
    white-space: nowrap;
    max-width: 110px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .record-error {
    position: fixed;
    top: 76px;
    right: 24px;
    z-index: 25;
    max-width: 320px;
    padding: 8px 10px;
    border: 1px solid rgba(255, 48, 96, 0.28);
    border-radius: 6px;
    background: rgba(34, 7, 13, 0.94);
    color: #ff9bb2;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    line-height: 1.35;
  }
</style>
