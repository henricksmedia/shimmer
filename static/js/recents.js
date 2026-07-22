// recents.js — clickable Recent sessions with real file restore.
//
// Browsers never expose a dropped file's path, so a plain "path in
// localStorage" is impossible.  Chromium's File System Access API is the
// sanctioned mechanism: FileSystemFileHandles are structured-cloneable,
// so we persist them in IndexedDB and reopen the file later after a
// one-click permission re-grant (which requires a user gesture — the
// click on the recent item itself).
//
// Capture points:
//  - window drop (capture phase): grab the handle via
//    DataTransferItem.getAsFileSystemHandle() without disturbing
//    single.js's own drop handling.
//  - "Choose file…": intercepted in capture phase to use
//    showOpenFilePicker() (which yields a handle), falling back to the
//    native <input> when the API is missing or the user cancels.
// Files that arrive without a handle still get a recents row — they just
// say "re-drop the file to restore" instead of being clickable.

const DB_NAME = 'shimmer-ui';
const STORE = 'recents';
const MAX_RECENTS = 6;

function openDb() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open(DB_NAME, 1);
        req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'key' });
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

function tx(db, mode, fn) {
    return new Promise((resolve, reject) => {
        const t = db.transaction(STORE, mode);
        const out = fn(t.objectStore(STORE));
        t.oncomplete = () => resolve(out?.result !== undefined ? out.result : out);
        t.onerror = () => reject(t.error);
    });
}

async function saveRecent(file, handle = null) {
    try {
        const db = await openDb();
        const key = `${file.name}|${file.size}`;
        const rec = { key, name: file.name, size: file.size, ts: Date.now() };
        if (handle) rec.handle = handle;   // FileSystemFileHandle is cloneable
        else {
            // Keep an existing handle if we already have one for this file.
            const prev = await new Promise((res) => {
                const t = db.transaction(STORE, 'readonly');
                const q = t.objectStore(STORE).get(key);
                q.onsuccess = () => res(q.result);
                q.onerror = () => res(null);
            });
            if (prev?.handle) rec.handle = prev.handle;
        }
        await tx(db, 'readwrite', (s) => s.put(rec));
        // Trim to the newest MAX_RECENTS.
        const all = await listRecents();
        for (const extra of all.slice(MAX_RECENTS)) {
            await tx(db, 'readwrite', (s) => s.delete(extra.key));
        }
        renderRecents();
    } catch (_) { /* IndexedDB unavailable — recents just stay empty */ }
}

async function listRecents() {
    const db = await openDb();
    const rows = await new Promise((resolve, reject) => {
        const t = db.transaction(STORE, 'readonly');
        const q = t.objectStore(STORE).getAll();
        q.onsuccess = () => resolve(q.result || []);
        q.onerror = () => reject(q.error);
    });
    return rows.sort((a, b) => b.ts - a.ts);
}

function adoptFile(file) {
    const input = document.getElementById('file-input');
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
}

async function restore(rec, rowEl) {
    const errEl = rowEl.querySelector('.r-err');
    errEl.textContent = '';
    if (!rec.handle) {
        errEl.textContent = 'no saved handle — re-drop the file';
        return;
    }
    try {
        let perm = await rec.handle.queryPermission({ mode: 'read' });
        if (perm !== 'granted') perm = await rec.handle.requestPermission({ mode: 'read' });
        if (perm !== 'granted') { errEl.textContent = 'permission declined'; return; }
        const file = await rec.handle.getFile();
        adoptFile(file);
    } catch (e) {
        errEl.textContent = 'couldn’t reopen (moved or deleted?) — re-drop the file';
    }
}

export async function renderRecents() {
    const card = document.getElementById('recents-card');
    const list = document.getElementById('recents-list');
    if (!card || !list) return;
    let rows = [];
    try { rows = (await listRecents()).slice(0, MAX_RECENTS); } catch (_) { return; }
    if (!rows.length) { card.hidden = true; return; }
    list.innerHTML = rows.map((r, i) => `
        <button type="button" class="recent-item" data-i="${i}" title="${r.handle ? 'Click to reload this file' : 'Re-drop the file to load it again'}">
            <span class="r-note">♪</span>
            <span class="r-name">${escapeHtml(r.name)}</span>
            <span class="r-err"></span>
            <span class="r-hint">${(r.size / 1e6).toFixed(1)} MB · ${r.handle ? 'click to reload' : 're-drop to restore'}</span>
        </button>`).join('');
    list.querySelectorAll('.recent-item').forEach((btn) =>
        btn.addEventListener('click', () => restore(rows[+btn.dataset.i], btn)));
    card.hidden = false;
}

export function initRecents() {
    // 1. Record every adoption (with or without a handle).
    const input = document.getElementById('file-input');
    input?.addEventListener('change', () => {
        const f = input.files && input.files[0];
        if (f) saveRecent(f);
    });

    // 2. Drops: capture the file handle alongside single.js's own handling.
    window.addEventListener('drop', (e) => {
        const item = e.dataTransfer?.items?.[0];
        if (!item || item.kind !== 'file' || !item.getAsFileSystemHandle) return;
        const file = item.getAsFile();
        item.getAsFileSystemHandle().then((h) => {
            if (h?.kind === 'file' && file) saveRecent(file, h);
        }).catch(() => {});
    }, true);

    // 3. "Choose file…": prefer showOpenFilePicker so we get a handle.
    const pickBtn = document.getElementById('pick-file-btn');
    if (pickBtn && window.showOpenFilePicker) {
        pickBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();   // keep single.js from also opening <input>
            try {
                const [handle] = await window.showOpenFilePicker({
                    types: [{
                        description: 'Audio',
                        accept: { 'audio/*': ['.wav', '.mp3', '.flac', '.ogg', '.m4a'] },
                    }],
                });
                const file = await handle.getFile();
                await saveRecent(file, handle);
                adoptFile(file);
            } catch (err) {
                if (err?.name === 'AbortError') return;      // user cancelled
                document.getElementById('file-input')?.click();  // fallback
            }
        }, true);
    }

    renderRecents();
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}
