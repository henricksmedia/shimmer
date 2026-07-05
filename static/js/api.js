// api.js — Thin wrappers around the FastAPI endpoints.
// Keeps all URL and response-shape knowledge in one place.

export async function fetchPresets() {
    const res = await fetch('/api/presets');
    if (!res.ok) throw new Error('Failed to load presets');
    return res.json();
}

export async function fetchSettings() {
    const res = await fetch('/api/settings');
    if (!res.ok) return {};
    return res.json();
}

export async function saveSettings(payload) {
    await fetch('/api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
    });
}

export async function submitProcess(file, paramsBody, outputFormat, preserveVolume) {
    const form = new FormData();
    form.append('file', file);
    form.append('params', JSON.stringify(paramsBody));
    form.append('output_format', outputFormat);
    form.append('preserve_volume', preserveVolume ? 'true' : 'false');
    const res = await fetch('/api/process', {method: 'POST', body: form});
    if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Process failed (${res.status})`);
    }
    return res.json();  // { job_id }
}

export async function fetchMetrics(jobId) {
    const res = await fetch(`/api/metrics/${jobId}`);
    if (res.status === 202) return null;
    if (!res.ok) throw new Error('Metrics fetch failed');
    return res.json();
}

export function resultUrl(jobId, kind) {
    return `/api/result/${jobId}?kind=${encodeURIComponent(kind)}`;
}

// ─── Live preview ────────────────────────────────────────────────────
// One-time upload returns a session_id; subsequent /api/preview calls
// re-render small WAV slices in-place as the user moves sliders.

export async function uploadFile(file) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/api/upload', {method: 'POST', body: form});
    if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Upload failed (${res.status})`);
    }
    return res.json();  // { session_id, sample_rate, channels, duration_s, name }
}

export async function dropSession(sessionId) {
    if (!sessionId) return;
    try {
        await fetch(`/api/upload/${sessionId}`, {method: 'DELETE'});
    } catch (_) { /* best-effort */ }
}

export async function renderPreview(payload, {signal} = {}) {
    // Single binary response carrying everything one render needs:
    //   [u32 json_len][json meta][u32 wav_len][processed wav][removed wav]
    const res = await fetch('/api/preview', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
        signal,
    });
    if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Preview failed (${res.status})`);
    }
    const buf = await res.arrayBuffer();
    const view = new DataView(buf);
    const jsonLen = view.getUint32(0, true);
    const meta = JSON.parse(
        new TextDecoder().decode(new Uint8Array(buf, 4, jsonLen)));
    let off = 4 + jsonLen;
    const wavLen = view.getUint32(off, true);
    off += 4;
    const processed = buf.slice(off, off + wavLen);
    const removed = buf.slice(off + wavLen);
    // meta: { duration_s, sample_rate, render_ms, start_s, end_s,
    //         lufs_original, lufs_processed }
    return {meta, processed, removed};
}

export async function suggestPreset(file) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/api/suggest', {method: 'POST', body: form});
    if (!res.ok) {
        const text = await res.text();
        throw new Error(text || 'Auto-detect failed');
    }
    return res.json();
}

export async function browseFolder({initialDir, title} = {}) {
    const res = await fetch('/api/browse-folder', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            initial_dir: initialDir || '',
            title: title || 'Select folder',
        }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.path || null;
}

// ─── Server-Sent Events helper ────────────────────────────────────────
// Returns an EventSource-like iterator but also handles JSON-parsing.

export function openSSE(url, {onMessage, onError, onDone} = {}) {
    const src = new EventSource(url);
    src.onmessage = (ev) => {
        try {
            const data = JSON.parse(ev.data);
            if (onMessage) onMessage(data);
            if (data.done || data.type === 'end') {
                src.close();
                if (onDone) onDone(data);
            }
        } catch (e) {
            if (onError) onError(e);
        }
    };
    src.onerror = (ev) => {
        if (onError) onError(ev);
        src.close();
    };
    return src;
}

export function postBatchStream(payload, {onMessage, onError, onDone} = {}) {
    // FastAPI StreamingResponse is a POST with a streaming body; we use
    // fetch + a ReadableStream reader since EventSource only supports GET.
    const ctrl = new AbortController();
    (async () => {
        try {
            const res = await fetch('/api/batch', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
                signal: ctrl.signal,
            });
            if (!res.ok) {
                const text = await res.text();
                throw new Error(text || `Batch failed (${res.status})`);
            }
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buf = '';
            while (true) {
                const {value, done} = await reader.read();
                if (done) break;
                buf += decoder.decode(value, {stream: true});
                let idx;
                while ((idx = buf.indexOf('\n\n')) !== -1) {
                    const chunk = buf.slice(0, idx);
                    buf = buf.slice(idx + 2);
                    const line = chunk.split('\n').find(l => l.startsWith('data: '));
                    if (!line) continue;
                    const json = line.slice(6).trim();
                    if (!json) continue;
                    try {
                        const data = JSON.parse(json);
                        if (onMessage) onMessage(data);
                        if (data.type === 'end' && onDone) onDone(data);
                    } catch (e) {
                        if (onError) onError(e);
                    }
                }
            }
        } catch (e) {
            if (onError) onError(e);
        }
    })();
    return () => ctrl.abort();
}
