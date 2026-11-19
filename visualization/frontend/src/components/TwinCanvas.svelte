<script lang="ts">
  import { onMount } from 'svelte';
  import { init, toggle, cycleTrackTarget } from '../canvas/main';
  import { doPlay, doRewind, doSpeed, doSeek } from '../canvas/playback';
  import { doZoom, toggleFollow, resizeRobot } from '../canvas/camera';
  import { startLive, liveReconnect, exitLiveMode } from '../canvas/liveMode';
  import Header from './Header.svelte';
  import Settings from './Settings.svelte';

  export let onUploadClick: () => void = () => {};
  export let uploading = false;
  export let uploadStage: 'uploading' | 'processing' | 'loading' = 'uploading';
  export let uploadError = '';
  export let uploadMsg = '';

  let canvasEl: HTMLCanvasElement;
  let liveMode = true;
  let connStatus: 'connecting' | 'connected' | 'disconnected' = 'connecting';
  let settingsOpen = false;
  let hasReplayRuns = false;
  let recordingActive = false;
  let recordingLoading = true;
  let recordingBusy = false;
  let recordingLabel = 'Idle';
  let recordingError = '';

  type RecordingStatus =
    | { active: false }
    | { active: true; run_id: string; name?: string | null; started_at: number; frame_count: number };

  onMount(() => {
    window.addEventListener('tg:modechange',  (e: Event) => { liveMode      = (e as CustomEvent).detail.liveMode; });
    window.addEventListener('tg:connstatus',  (e: Event) => { connStatus    = (e as CustomEvent).detail.status; });
    window.addEventListener('tg:replaystate', (e: Event) => { hasReplayRuns = (e as CustomEvent).detail.hasRuns; });

    init(canvasEl);
    startLive();

    let disposed = false;
    const syncRecording = async () => {
      try {
        const res = await fetch('/api/live/capture/active');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: RecordingStatus = await res.json();
        if (disposed) return;
        recordingActive = data.active;
        recordingLabel = data.active ? (data.name?.trim() || 'Live capture') : 'Idle';
        recordingError = '';
      } catch (err) {
        if (disposed) return;
        recordingError = err instanceof Error ? err.message : 'Could not read recording state';
      } finally {
        if (!disposed) recordingLoading = false;
      }
    };

    void syncRecording();
    const refreshTimer = window.setInterval(() => {
      if (liveMode && !recordingBusy) void syncRecording();
    }, 2000);

    return () => {
      disposed = true;
      window.clearInterval(refreshTimer);
    };
  });

  function switchToLive()   { if (!liveMode) startLive(); }
  function switchToReplay() { if (liveMode)  exitLiveMode(); }

  function openTwinbench() {
    const url = new URL(window.location.href);
    url.pathname = '/';
    url.search = '';
    url.hash = '';
    url.port = '5174';
    window.location.href = url.toString();
  }

  function toggleRobotCardsPanel() {
    document.getElementById('robot-cards-panel')?.classList.toggle('visible');
  }

  async function toggleRecording() {
    if (recordingBusy) return;
    recordingBusy = true;
    recordingError = '';
    const stopping = recordingActive;
    try {
      const url = stopping ? '/api/live/capture/stop' : '/api/live/capture/start';
      const res = await fetch(url, {
        method: 'POST',
        headers: stopping ? undefined : { 'Content-Type': 'application/json' },
        body: stopping ? undefined : JSON.stringify({ name: '' }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail ?? `HTTP ${res.status}`);
      recordingActive = !stopping;
      recordingLabel = stopping ? 'Idle' : (data?.name?.trim?.() || 'Live capture');
    } catch (err) {
      recordingError = err instanceof Error ? err.message : 'Recording request failed';
    } finally {
      recordingBusy = false;
    }
  }
</script>

<div id="tt"></div>

<Header
  {liveMode}
  {connStatus}
  {hasReplayRuns}
  {onUploadClick}
  {uploading}
  {uploadError}
  {uploadMsg}
  onSettingsClick={() => (settingsOpen = true)}
  onTwinbenchClick={openTwinbench}
  onSwitchToLive={switchToLive}
  onSwitchToReplay={switchToReplay}
  {recordingActive}
  {recordingLoading}
  {recordingBusy}
  {recordingLabel}
  {recordingError}
  onToggleRecording={toggleRecording}
/>

<Settings bind:open={settingsOpen} {liveMode} {liveReconnect} liveExit={exitLiveMode} />

<div class="main">
  <div class="robot-cards-panel" id="robot-cards-panel"></div>

  <div class="arena-wrap">
    <canvas id="arena" bind:this={canvasEl}></canvas>

    {#if !liveMode && !uploading && !hasReplayRuns}
      <div class="arena-overlay empty-state">
        <div class="empty-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
        </div>
        <div class="empty-title">NO REPLAY DATA</div>
        {#if uploadError}
          <div class="empty-err">{uploadError}</div>
        {:else}
          <div class="empty-sub">Upload an .xlsx run file to begin</div>
        {/if}
        <button class="empty-cta" type="button" on:click={onUploadClick}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          UPLOAD FILE
        </button>
      </div>
    {/if}

    {#if uploading && !liveMode}
      <div class="arena-overlay upload-progress">
        <div class="up-stage-dots">
          <span class:active={uploadStage === 'uploading'}>●</span>
          <span class:active={uploadStage === 'processing'}>●</span>
          <span class:active={uploadStage === 'loading'}>●</span>
        </div>
        <div class="up-spinner"></div>
        <div class="up-stage-label">
          {#if uploadStage === 'uploading'}UPLOADING FILE
          {:else if uploadStage === 'processing'}RUNNING PIPELINE
          {:else}LOADING FRAMES{/if}
        </div>
        {#if uploadStage === 'processing' && uploadMsg}
          <div class="up-elapsed">{uploadMsg} elapsed</div>
        {/if}
      </div>
    {/if}

    <div class="tab-bar" id="tab-bar"></div>
    <div class="scanlines"></div>
    <div class="arena-legend" id="arena-legend"></div>

    <button class="follow-btn on" id="btn-follow"
            on:click={toggleFollow}
            data-tip="Camera follow mode&#10;Click to toggle free pan (drag canvas)">FOLLOW</button>
    <button class="track-btn" id="btn-track"
            on:click={cycleTrackTarget}
            data-tip="Camera track target&#10;Cycles: ALL to LEADER to each robot">TRACK: <span id="track-target-lbl">ALL</span></button>

    <div class="zoom-btns">
      <button class="zbtn" on:click={() => doZoom(1.25)} data-tip="Zoom in">+</button>
      <button class="zbtn" on:click={() => doZoom(0.8)}  data-tip="Zoom out">&#x2212;</button>
    </div>

    <div class="zoom-btns" style="right:52px">
      <button class="zbtn" on:click={() => resizeRobot(1.3)}  data-tip="Increase robot render size">R+</button>
      <span id="robot-size-lbl" style="text-align:center;font-size:9px;color:var(--txlo);letter-spacing:0;line-height:1">1.0x</span>
      <button class="zbtn" on:click={() => resizeRobot(0.77)} data-tip="Decrease robot render size">R&#x2212;</button>
    </div>

    <div class="cnfo" id="cnfo">SCALE: â€” px/m</div>
  </div>

  <div class="twin-cards-panel" id="twin-cards-panel"></div>
</div>

<button class="panel-toggle" id="btn-robot-cards-panel"
        on:click={toggleRobotCardsPanel}
        data-tip="Toggle robot cards panel">DATA</button>

<footer class="ctrl">
  <div class="pbtns">
    <button class="pbtn" on:click={doRewind} data-tip="Rewind to start">&#x23EE;</button>
    <button class="pbtn" id="pbplay" on:click={doPlay} data-tip="Play / Pause">&#x25B6;</button>
    <button class="pbtn spd" id="pbspd" on:click={doSpeed} data-tip="Cycle playback speed">1&#x00D7;</button>
  </div>

  <div class="tl-wrap">
    <div class="tl-lbls">
      <span id="tl-cur">0.000 s</span>
      <span id="tl-tot">â€” s</span>
    </div>
    <div
      class="tl-track"
      id="tl-track"
      role="slider"
      tabindex="0"
      aria-label="Timeline seek bar"
      aria-valuemin="0"
      aria-valuemax="100"
      aria-valuenow="0"
      on:click={(e) => doSeek(e)}
      on:keydown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); doSeek(e as unknown as MouseEvent); }
      }}
      data-tip="Click to seek&#10;Drag thumb to scrub"
    >
      <div class="tl-fill"  id="tl-fill"  style="width:0%"></div>
      <div class="tl-thumb" id="tl-thumb" style="left:0%"></div>
    </div>
  </div>

  <div class="fc" id="fctr">0 / 0</div>

  <div class="layers">
    <button class="layer-btn on" id="btn-trail"
            on:click={() => toggle('trail','btn-trail')}
            data-tip="Toggle: permanent state-coloured&#10;path history trail">TRAIL</button>
    <button class="layer-btn on" id="btn-sensors"
            on:click={() => toggle('sensors','btn-sensors')}
            data-tip="Toggle: FOV cone, distance beam&#10;and leader diamond marker">SENSORS</button>
    <button class="layer-btn on" id="btn-links"
            on:click={() => toggle('links','btn-links')}
            data-tip="Toggle: backend-assessed platoon links&#10;between consecutive chain members">LINKS</button>
    <button class="layer-btn" id="btn-ghost"
            on:click={() => toggle('ghost','btn-ghost')}
            data-tip="Toggle: ghost robot showing&#10;controller reference setpoint">GHOST</button>
  </div>
</footer>
