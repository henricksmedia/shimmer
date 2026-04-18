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
