// size-limit.js — the file size limit (Settings · Downloads): how big the
// file will be, whether it fits, and which formats do.
//
// The sizes come from the engine: POST /api/size before a run (three
// windows rendered as the export will be), the export's `sizes` after it.
// This file only compares them with the user's limit and draws the result,
// in the approved mockup's words (static/tmp/shimmer-size-limit-mockup.html).
// It never changes the format by itself and never cuts the song.

export const NAMES = {
    wav: 'WAV 24-bit', wav16: 'WAV 16-bit · 44.1 kHz', flac: 'FLAC 24-bit',
    flac16: 'FLAC 16-bit · 44.1 kHz', mp3: 'MP3 · 320 kbps', ogg: 'OGG Vorbis', m4a: 'M4A (AAC)',
};
// Lossless formats worth offering, in order: the same audio packed smaller,
// then the release copy as WAV, then as FLAC.
const LOSSLESS = ['flac', 'wav16', 'flac16'];
const RELEASE_COPIES = ['wav16', 'flac16'];
// Lossy formats are only ever offered, marked, when nothing lossless fits.
const LOSSY_OFFER = ['mp3'];

export const mb = (bytes) => `${(bytes / 1e6).toFixed(1)} MB`;
const about = (est) => (est.exact ? '' : 'about ') + mb(est.bytes);

function mmss(s) {
    const t = Math.max(0, Math.round(s || 0));
    return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`;
}
function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
}
function icon(name) {
    const s = el('span', 'ms', name);
    s.setAttribute('aria-hidden', 'true');
    return s;
}

/** Compare the engine's sizes with the limit. `actual` is the written
 *  file's size, once there is one. Null when the format is unknown. */
export function judge(sizes, current, limitMb, actual = null) {
    const cur = sizes && sizes[current];
    if (!cur) return null;
    const limit = limitMb * 1e6;
    const bytes = actual != null ? actual : cur.bytes;
    // Fits only if it fits at the top of its range.
    const fits = (actual != null ? actual : cur.high) <= limit;
    const ok = (k) => k !== current && sizes[k] && sizes[k].high <= limit;
    const fixes = fits ? [] : LOSSLESS.filter(ok);
    const none = !fits && !fixes.length;
    return {
        fits, limitMb, limit, current, bytes, sizes,
        exact: actual != null || !!cur.exact,
        over: Math.max(0, bytes - limit),
        fixes,
        checked: none ? RELEASE_COPIES.filter((k) => k !== current && sizes[k]) : [],
        lossy: none ? LOSSY_OFFER.filter(ok) : [],
    };
}

export function verdictTitle(j) {
    return j.fixes.length ? `Over your ${j.limitMb} MB limit` : `No lossless format fits ${j.limitMb} MB`;
}

function why(key, est, limit) {
    if (key === 'flac') return 'Fits. The same audio as your WAV, packed smaller.';
    if (key === 'wav16') return `Fits, with ${mb(limit - est.high)} to spare. The release copy stores ask for.`;
    if (key === 'flac16') return 'Fits. Lossless, about half the size of WAV. The size varies with the music.';
    return '';
}

function fixButton(key, est, limit, onPick, lossyNote = '') {
    const b = el('button', 'sl-fix' + (lossyNote ? ' lossy' : ''));
    b.type = 'button';
    const t = el('span', 't', `Use ${NAMES[key]}`);
    if (lossyNote) t.append(el('span', 'sl-tag lossy', 'LOSSY'));
    b.append(t, el('span', 'v', about(est)), el('span', 'd', lossyNote || why(key, est, limit)));
    b.addEventListener('click', () => onPick(key));
    return b;
}

function checkedList(j) {
    const box = el('div', 'sl-checked');
    for (const k of j.checked) {
        const row = el('div', 'sl-chk');
        row.append(el('span', null, NAMES[k]), el('span', 'v', about(j.sizes[k])), el('span', 'x', 'over'));
        box.append(row);
    }
    return box;
}

/** The size line under Format in Output. `j` from judge(), or null to hide. */
export function renderSizeLine(host, j, durationS, onPick) {
    if (!host) return;
    host.innerHTML = '';
    host.hidden = !j;
    if (!j) return;
    const size = (j.exact ? '' : 'about ') + mb(j.bytes);
    if (j.fits) {
        const v = el('div', 'sl-verdict ok');
        v.append(icon('check_circle'), `${size}, under your ${j.limitMb} MB limit`);
        host.append(v);
        return;
    }
    const v = el('div', 'sl-verdict over');
    v.append(icon('warning'), verdictTitle(j));
    const fig = `${NAMES[j.current]} · ${size} for ${mmss(durationS)}`;
    host.append(v, el('div', 'sl-fig', j.fixes.length ? `${fig} · ${mb(j.over)} over` : fig));
    if (j.fixes.length) {
        host.append(el('div', 'sl-label', 'Lossless formats that fit'));
        const box = el('div', 'sl-fixes');
        j.fixes.forEach((k) => box.append(fixButton(k, j.sizes[k], j.limit, onPick)));
        host.append(box);
        return;
    }
    if (j.checked.length) host.append(el('div', 'sl-label', 'Lossless formats'), checkedList(j));
    if (j.lossy.length) {
        host.append(el('div', 'sl-label', 'Only a lossy format fits'));
        const box = el('div', 'sl-fixes');
        j.lossy.forEach((k) => box.append(fixButton(k, j.sizes[k], j.limit, onPick,
            'Removes some detail to make the file small. Only if you choose it.')));
        host.append(box);
    }
    host.append(el('div', 'sl-never', 'Shimmer never cuts the song to make it fit.'));
}

/** The Download step's suggestions when the written file is over the limit.
 *  `kept` names the file that was written ("WAV"), which stays as it is. */
export function downloadBlock(j, onPick, kept) {
    const frag = document.createDocumentFragment();
    if (j.fixes.length) {
        frag.append(el('div', 'sl-label', 'Lossless formats that fit'));
        const grid = el('div', 'sl-dl-grid');
        j.fixes.forEach((k) => grid.append(fixButton(k, j.sizes[k], j.limit, onPick)));
        frag.append(grid);
        return frag;
    }
    if (j.checked.length) frag.append(el('div', 'sl-label', 'Lossless formats'), checkedList(j));
    if (j.lossy.length) {
        frag.append(el('div', 'sl-label', 'Only a lossy format fits'));
        j.lossy.forEach((k) => frag.append(fixButton(k, j.sizes[k], j.limit, onPick,
            `Removes some detail to make the file small. Your ${kept} stays as it is.`)));
    }
    frag.append(el('div', 'sl-never', 'Shimmer never cuts the song to make it fit.'));
    return frag;
}

/** "name · 47.8 MB, under your 50 MB limit" with the limit part in green. */
export function fitsSub(text, j) {
    const span = el('span', null, `${text} · ${mb(j.bytes)}, `);
    span.append(el('b', 'sl-ok', `under your ${j.limitMb} MB limit`));
    return span;
}

export { mmss };
