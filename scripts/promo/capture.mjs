// capture.mjs — screenshots of Shimmer for the README and the promo kit.
//
// Drives a headless Edge (or Chrome) over the DevTools protocol against a
// running Shimmer, so every shot is the real app: it uploads a song, turns
// on the Shimmer and Sibilance cards, plays the Removed track, runs a full
// Clean & Master with tags filled in, and photographs each step.
//
//   node scripts/promo/capture.mjs --song "C:/music/song.wav" [options]
//
//   --song     the song to load (required)
//   --out      where to write (default: promo-assets); shots go in <out>/screens
//   --port     the port Shimmer is on (default: 7860)
//   --mode     full (default) or cards, the cards close-up in a taller window
//   --browser  path to Edge or Chrome, if it is somewhere unusual
//
// Run the full mode first, then the cards mode: the card is taller than a
// normal window, so its close-up needs its own pass. docs/PROMO-ASSETS.md.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function arg(name, fallback = null) {
    const i = process.argv.indexOf(`--${name}`);
    return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const SONG = arg('song');
if (!SONG) {
    console.error('Say which song to load: --song "C:/music/song.wav"');
    process.exit(2);
}
const OUT = join(arg('out', 'promo-assets'), 'screens');
const PORT_APP = arg('port', '7860');
const MODE = arg('mode', 'full');
const WINDOW = MODE === 'cards' ? '1600,2400' : '1600,1000';
const APP = `http://127.0.0.1:${PORT_APP}/`;
// Its own debugging port and browser profile per run, so two runs (say the
// full pass and the cards pass, or two songs) never talk to each other's
// browser.
const PORT_CDP = Number(arg('cdp-port', 0)) || 9400 + Math.floor(Math.random() * 500);
const PROFILE = join(tmpdir(), `shimmer-promo-browser-${PORT_CDP}`);
const BROWSER = [
    arg('browser'),
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
].filter(Boolean).find((p) => existsSync(p));
if (!BROWSER) {
    console.error('No Edge or Chrome found. Pass one with --browser.');
    process.exit(2);
}

mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

// On Windows a headless window can stop drawing: the GPU process stalls, or
// the browser decides the window is covered. These flags keep it painting.
const browser = spawn(BROWSER, [
    '--headless=new', `--remote-debugging-port=${PORT_CDP}`, `--user-data-dir=${PROFILE}`,
    '--no-first-run', '--no-default-browser-check', `--window-size=${WINDOW}`,
    '--force-device-scale-factor=1.5', '--disable-gpu',
    '--disable-features=CalculateNativeWinOcclusion',
    '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding',
    '--disable-background-timer-throttling',
    '--autoplay-policy=no-user-gesture-required', '--hide-scrollbars', 'about:blank',
], { stdio: 'ignore' });

async function pageSocketUrl() {
    for (let i = 0; i < 60; i++) {
        try {
            const list = await (await fetch(`http://127.0.0.1:${PORT_CDP}/json/list`)).json();
            const page = list.find((t) => t.type === 'page');
            if (page) return page.webSocketDebuggerUrl;
        } catch { /* not up yet */ }
        await sleep(300);
    }
    throw new Error('the browser did not start');
}

const ws = new WebSocket(await pageSocketUrl());
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let nextId = 0;
const pending = new Map();
const waiters = [];
ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
        const { res, rej } = pending.get(m.id);
        pending.delete(m.id);
        if (m.error) rej(new Error(m.error.message)); else res(m.result);
    } else if (m.method) {
        for (const w of waiters.slice()) {
            if (w.method === m.method) { waiters.splice(waiters.indexOf(w), 1); w.res(m.params); }
        }
    }
});
// Every call gives up after 45 s, so a stuck page fails instead of hanging.
const send = (method, params = {}) => new Promise((res, rej) => {
    const id = ++nextId;
    const timer = setTimeout(() => {
        pending.delete(id);
        rej(new Error(`${method} did not answer in 45 s`));
    }, 45000);
    pending.set(id, { res: (v) => { clearTimeout(timer); res(v); },
                      rej: (e) => { clearTimeout(timer); rej(e); } });
    ws.send(JSON.stringify({ id, method, params }));
});
const once = (method) => new Promise((res) => waiters.push({ method, res }));
async function js(expression) {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) {
        throw new Error(`${r.exceptionDetails.text} ${r.exceptionDetails.exception?.description || ''}`);
    }
    return r.result.value;
}
async function waitFor(expression, ms, label) {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
        try { if (await js(expression)) return; } catch { /* page busy */ }
        await sleep(500);
    }
    throw new Error(`timed out waiting for ${label}`);
}
async function shot(name, selector = null, pad = 14) {
    const params = { format: 'png' };
    if (selector) {
        const r = await js(`(() => {
            const e = document.querySelector(${JSON.stringify(selector)});
            if (!e) return null;
            e.scrollIntoView({ block: 'center' });
            const b = e.getBoundingClientRect();
            return { x: b.left + window.scrollX, y: b.top + window.scrollY, w: b.width, h: b.height };
        })()`);
        if (!r) throw new Error(`no element ${selector}`);
        await sleep(500);
        params.captureBeyondViewport = true;
        params.clip = { x: Math.max(0, r.x - pad), y: Math.max(0, r.y - pad),
                        width: r.w + 2 * pad, height: r.h + 2 * pad, scale: 1 };
    }
    const { data } = await send('Page.captureScreenshot', params);
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'));
    log('saved', name);
}
const status = () => js(`document.getElementById('preview-status').textContent`);

try {
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Page.setDownloadBehavior', { behavior: 'deny' }).catch(() => {});
    // Keep the tab drawing: a hidden tab can stop producing frames, and then
    // a screenshot waits forever.
    await send('Page.bringToFront').catch(() => {});
    await send('Emulation.setFocusEmulationEnabled', { enabled: true }).catch(() => {});
    const loaded = once('Page.loadEventFired');
    await send('Page.navigate', { url: APP });
    await loaded;
    await sleep(2500);
    // A fresh browser profile makes the app open its Quick start help over
    // everything, which would cover every shot. Mark it seen, reload, and
    // press Escape in case anything else is open.
    await js(`(() => { try { localStorage.setItem('shimmer.quickstart-seen', '1'); } catch (e) {} return true; })()`);
    const reloaded = once('Page.loadEventFired');
    await send('Page.reload', {});
    await reloaded;
    await sleep(2500);
    await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape',
                                          windowsVirtualKeyCode: 27 }).catch(() => {});
    await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape',
                                          windowsVirtualKeyCode: 27 }).catch(() => {});
    await sleep(500);
    // Fail fast if screenshots do not work at all.
    await shot('check-page-loaded');

    // Upload the song through the real file input.
    const { root } = await send('DOM.getDocument', { depth: -1 });
    const { nodeId } = await send('DOM.querySelector', { nodeId: root.nodeId, selector: '#file-input' });
    await send('DOM.setFileInputFiles', { nodeId, files: [SONG] });
    log('uploading', SONG);
    await waitFor(`!/Drop a file/.test(document.getElementById('preview-status').textContent)`,
                  180000, 'the upload');
    await sleep(4000);

    // Turn on the cards the demo shows.
    const turnedOn = await js(`(() => {
        const want = ['Shimmer', 'Sibilance'];
        const tiles = [...document.querySelectorAll('.hear-tile')];
        const out = [];
        for (const w of want) {
            const t = tiles.find((b) => (b.querySelector('.t') || {}).textContent?.trim() === w);
            if (t && !t.classList.contains('on')) { t.click(); out.push(w); }
        }
        return out;
    })()`);
    log('cards on:', turnedOn.join(', '));
    await sleep(800);

    flow: {
    if (MODE === 'cards') {
        await sleep(2500);
        await shot('cards', '#hear-card');
        log('done');
        break flow;
    }

    // Live preview on: the Shimmer card reads the whole song once first.
    await js(`(() => { const t = document.getElementById('preview-toggle');
        if (!t.checked) { t.checked = true; t.dispatchEvent(new Event('change', { bubbles: true })); }
        return true; })()`);
    log('live preview on; waiting for the first read and the preview');
    let tookFirstRead = false;
    const t0 = Date.now();
    for (;;) {
        if (Date.now() - t0 > 400000) throw new Error('timed out waiting for the preview');
        const s = await status();
        if (!tookFirstRead && /reading the whole song once, ([4-9]\d)%/.test(s)) {
            await shot('first-read-progress');
            tookFirstRead = true;
        }
        if (/rendered in/.test(s)) break;
        await sleep(700);
    }
    await sleep(1500);

    const pick = async (track) => {
        await js(`(document.querySelector('[data-track="${track}"]').click(), true)`);
        await sleep(1500);
    };
    await pick('original');
    await shot('master-original');
    await pick('processed');
    await shot('master-processed');
    await pick('removed');
    await shot('master-removed');

    // Tags, so the release check can say the file is ready to upload.
    const title = SONG.split(/[\\/]/).pop().replace(/\.[^.]+$/, '');
    await js(`(() => {
        const set = (id, v) => { const e = document.getElementById(id); if (!e) return;
            e.value = v; e.dispatchEvent(new Event('input', { bubbles: true }));
            e.dispatchEvent(new Event('change', { bubbles: true })); };
        const on = document.getElementById('tags-enabled');
        if (on && !on.checked) { on.checked = true; on.dispatchEvent(new Event('change', { bubbles: true })); }
        set('tag-title', ${JSON.stringify(title)});
        set('tag-album', ${JSON.stringify(title)});
        return true;
    })()`);
    await sleep(800);

    // A full Clean & Master, for the progress window and the release check.
    await js(`(document.getElementById('process-btn').click(), true)`);
    log('Clean & Master started');
    let tookExport = false;
    const t1 = Date.now();
    for (;;) {
        if (Date.now() - t1 > 600000) throw new Error('timed out waiting for the export');
        const st = await js(`(() => {
            const dl = document.getElementById('process-modal-download');
            const d = document.getElementById('process-modal-detail');
            const e = document.getElementById('process-modal-error');
            return { dl: !!dl && !dl.hidden && dl.offsetParent !== null,
                     detail: d ? d.textContent : '', err: e && !e.hidden ? e.textContent.trim() : '' };
        })()`);
        if (!tookExport && /reading the whole song once, ([4-9]\d)%/.test(st.detail)) {
            await shot('export-progress');
            tookExport = true;
        }
        if (st.err) throw new Error(`export failed: ${st.err}`);
        if (st.dl) break;
        await sleep(1000);
    }
    await sleep(1500);
    await shot('export-done');
    await js(`((document.getElementById('process-modal-dl-close') || { click() {} }).click(), true)`);
    await sleep(2000);
    await shot('release-check', '#release-card');
    await shot('master-after-run');

    await js(`(document.querySelector('[data-tab="chain"]').click(), true)`);
    await sleep(3000);
    await shot('signal-chain');
    log('done');
    }
} catch (e) {
    console.error('FAILED:', e.message);
    try { await shot('failure-state'); } catch { /* nothing more to save */ }
    process.exitCode = 1;
} finally {
    try { ws.close(); } catch { /* closing */ }
    browser.kill();
}
