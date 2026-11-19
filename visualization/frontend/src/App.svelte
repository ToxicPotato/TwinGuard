<script lang="ts">
  import TwinCanvas from './components/TwinCanvas.svelte';
  import { activateRuns } from './canvas/main';

  let uploading = false;
  let uploadError = '';
  let uploadMsg = '';
  let uploadStage: 'uploading' | 'processing' | 'loading' = 'uploading';

  async function handleUpload(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    uploading = true;
    uploadStage = 'uploading';
    uploadError = '';
    uploadMsg = '';

    const form = new FormData();
    form.append('file', file);

    try {
      // 1. POST file — returns immediately with job_id
      const res = await fetch('/api/datasets/upload', { method: 'POST', body: form });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg);
      }
      const { job_id } = await res.json();

      // 2. Poll until pipeline is done
      uploadStage = 'processing';
      const startMs = Date.now();
      while (true) {
        await new Promise(r => setTimeout(r, 2000));
        uploadMsg = `${Math.round((Date.now() - startMs) / 1000)} s`;

        const statusRes = await fetch(`/api/datasets/upload/status/${job_id}`);
        if (!statusRes.ok) throw new Error('Status check failed');
        const status = await statusRes.json();

        if (status.status === 'done') {
          uploadStage = 'loading';
          uploadMsg = '';
          await _loadRuns();
          break;
        } else if (status.status === 'error') {
          throw new Error(status.error ?? 'Pipeline failed');
        }
      }
    } catch (err: any) {
      uploadError = err.message ?? 'Upload failed';
    } finally {
      uploading = false;
      uploadMsg = '';
      input.value = '';
    }
  }

  async function _loadRuns() {
    const metaRes = await fetch('/api/datasets');
    if (!metaRes.ok) throw new Error('Failed to fetch run list');
    const runMeta: Record<string, any> = await metaRes.json();

    const runs: Record<string, any> = {};
    await Promise.all(
      Object.keys(runMeta).map(async (runId) => {
        const framesRes = await fetch(`/api/datasets/${encodeURIComponent(runId)}/frames`);
        if (framesRes.ok) {
          runs[runId] = { frames: await framesRes.json(), meta: runMeta[runId] };
        }
      })
    );

    // Switch to replay and rebuild all UI in one call
    activateRuns(runs);
  }

  function triggerUpload() {
    document.getElementById('xlsx-input')?.click();
  }
</script>

<TwinCanvas
  onUploadClick={triggerUpload}
  {uploading}
  {uploadStage}
  {uploadError}
  {uploadMsg}
/>

<!-- Hidden file input -->
<input id="xlsx-input" type="file" accept=".xlsx" on:change={handleUpload} />

<style>
  #xlsx-input {
    display: none;
  }
</style>
