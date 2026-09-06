// progress-chain.js — The processing window: a chain drawn live.
//
// One modal (#process-modal in index.html) shared by every long job on
// the page: Clean & Master, stem separation, the remix render. The caller
// hands it a list of phases; audio comes in on the left as a small
// waveform packet, each phase lights in its own colour as the server
// reports it, the active one pulses, phases not in this run are dashed,
// and the packet leaves through Out when the job finishes.
//
//   processModal.open({ title, phases, planned, stage, detail, outLabel })
//   processModal.stage(key, label, detail)   a server stage event
//   processModal.progress(frac, fallback)    the bar; `fallback(frac)` names
//                                            the stage when no stage events
//                                            have arrived (older server)
//   processModal.finish()                    every planned phase done
//   processModal.fail(message)               keep it open with a Close
//   processModal.close() / closeSoon(ms)
//   processModal.offerDownload({ title, sub, primary, secondary })
//                                            the Download step at the end
//                                            of a run: the chain stays
//                                            finished, the progress lines
//                                            give way to the file's name
//                                            and the buttons; `primary` /
//                                            `secondary` are { label,
//                                            onClick } and each takes the
//                                            window down after its action
//
// Between two runs that belong together (a two-pass plan), the window
// stays up so the gap never reads as the end:
//
//   processModal.hold({ title, stage, detail, phases, planned, outLabel })
//                                            keep the window up after a
//                                            finish: cancels a pending
//                                            closeSoon and shows the stage
//                                            as done over a busy bar; with
//                                            `phases` it draws that chain
//                                            as finished first
//   processModal.detail(text)                the line under the stage
//   processModal.countdown({ seconds, kicker, title, sub, stopLabel,
//                            phases, planned, outLabel, modalTitle })
//                                            a big 3-2-1 in front of the
//                                            next run's chain; resolves
//                                            true at zero and false on
//                                            Stop here or Escape
//
// `phases` is [[key, label, color], ...] (the Signal Chain's PHASES shape);
// `planned` is a Set of keys that will run (others draw as skipped).

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
}

function createProcessModal() {
    const $ = (id) => document.getElementById(id);
    const els = {
        modal: $('process-modal'), title: $('process-modal-title'),
        chain: $('process-modal-chain'), stage: $('process-modal-stage'),
        detail: $('process-modal-detail'), fill: $('process-modal-fill'),
        track: $('process-modal-track'),
        pct: $('process-modal-pct'), error: $('process-modal-error'),
        close: $('process-modal-close'),
        // The count between passes.
        countdown: $('process-modal-countdown'), cdKicker: $('process-modal-cd-kicker'),
        cdNum: $('process-modal-cd-num'), cdDigit: $('process-modal-cd-digit'),
        cdTitle: $('process-modal-cd-title'), cdSub: $('process-modal-cd-sub'),
        cdStop: $('process-modal-cd-stop'),
        // The Download step at the end.
        download: $('process-modal-download'), dlTitle: $('process-modal-dl-title'),
        dlSub: $('process-modal-dl-sub'), dlPrimary: $('process-modal-dl-primary'),
        dlSecondary: $('process-modal-dl-secondary'), dlClose: $('process-modal-dl-close'),
    };
    const st = {
        phases: [], nodes: new Map(), current: null, packet: null, wire: null, finished: false,
        closeTimer: null,     // a pending closeSoon
        abortCountdown: null, // ends a running countdown as "stopped"
        dlCleanup: null,      // unwires the Download step's buttons and Escape
    };

    if (els.close) els.close.addEventListener('click', () => close());
    window.addEventListener('resize', () => {
        if (!els.modal || els.modal.hidden || !st.nodes.size) return;
        syncDensity();
        movePacket(st.finished ? 'out' : (st.current || 'in'));
    });

    // Eleven or thirteen stages in one row: when a slot gets narrower than
    // the longest label, alternate the labels over two lines.
    const DENSE_SLOT_PX = 78;
    function syncDensity() {
        if (!els.chain) return;
        const slots = st.phases.length + 2;
        const width = els.chain.getBoundingClientRect().width;
        els.chain.classList.toggle('dense', width > 0 && width / slots < DENSE_SLOT_PX);
    }

    function build(phases, planned, outLabel) {
        if (!els.chain) return;
        els.chain.innerHTML = '';
        els.chain.classList.remove('finished');
        st.phases = phases;
        st.nodes.clear();
        st.current = null;
        st.finished = false;
        const wire = el('div', 'pm-wire');
        const lit = el('div', 'pm-wire-lit');
        wire.appendChild(lit);
        st.wire = lit;
        els.chain.appendChild(wire);
        const row = el('div', 'pm-nodes');
        const port = (cls, label) => {
            const p = el('div', `pm-port ${cls}`);
            p.append(el('span', 'pm-port-glyph'), el('span', 'pm-label', label));
            return p;
        };
        row.appendChild(port('in', 'In'));
        phases.forEach(([key, label, color]) => {
            const isPlanned = !planned || planned.has(key);
            const node = el('div', `pm-node ${isPlanned ? 'pending' : 'skipped'}`);
            node.style.setProperty('--phase', color);
            node.dataset.key = key;
            node.append(el('span', 'pm-dot'), el('span', 'pm-label', label));
            node.title = isPlanned ? label : `${label}: not in this run`;
            row.appendChild(node);
            st.nodes.set(key, node);
        });
        row.appendChild(port('out', outLabel || 'Out'));
        els.chain.appendChild(row);
        const packet = el('div', 'pm-packet');
        packet.append(el('i'), el('i'), el('i'));
        els.chain.appendChild(packet);
        st.packet = packet;
        requestAnimationFrame(() => { syncDensity(); movePacket('in'); });
    }

    function centerPct(target) {
        if (!els.chain) return 0;
        const rect = els.chain.getBoundingClientRect();
        if (rect.width <= 0) return 0;
        let node = null;
        if (target === 'in') node = els.chain.querySelector('.pm-port.in .pm-port-glyph');
        else if (target === 'out') node = els.chain.querySelector('.pm-port.out .pm-port-glyph');
        else { const n = st.nodes.get(target); node = n ? n.querySelector('.pm-dot') : null; }
        if (!node) return 0;
        const r = node.getBoundingClientRect();
        return ((r.left + r.width / 2) - rect.left) / rect.width * 100;
    }

    function movePacket(target) {
        if (!st.packet) return;
        const to = centerPct(target);
        const from = centerPct('in');
        st.packet.style.setProperty('--x0', `${from}%`);
        st.packet.style.setProperty('--x1', `${to}%`);
        if (st.wire) {
            st.wire.style.left = `${from}%`;
            st.wire.style.width = `${Math.max(0, to - from)}%`;
        }
        // Restart the travel so the packet always sets off from In.
        st.packet.style.animation = 'none';
        void st.packet.offsetWidth;
        st.packet.style.animation = '';
        st.packet.classList.toggle('arrived', target === 'out');
    }

    // ── Shared housekeeping ─────────────────────────────────────────
    function cancelClose() {
        if (st.closeTimer) { clearTimeout(st.closeTimer); st.closeTimer = null; }
    }
    function abortCountdown() {
        if (st.abortCountdown) st.abortCountdown();
    }
    // The progress lines (stage, detail, bar, percent) and the countdown
    // panel take turns in the same slot under the chain.
    function showLines(on) {
        [els.stage, els.detail, els.track, els.pct].forEach((e) => { if (e) e.hidden = !on; });
        if (els.countdown && on) els.countdown.hidden = true;
        if (on) hideDownload();
    }
    function hideDownload() {
        if (st.dlCleanup) { st.dlCleanup(); st.dlCleanup = null; }
        if (els.download) els.download.hidden = true;
    }
    // Undo what hold() did to the stage line and the bar.
    function clearHold() {
        if (els.stage) els.stage.classList.remove('pm-done');
        if (els.track) els.track.classList.remove('busy');
    }

    function open({ title, phases, planned, stage, detail, outLabel } = {}) {
        if (!els.modal) return;
        cancelClose();
        abortCountdown();
        clearHold();
        showLines(true);
        if (els.title && title) els.title.textContent = title;
        if (els.error) { els.error.hidden = true; els.error.textContent = ''; }
        if (els.close) els.close.hidden = true;
        if (els.fill) els.fill.style.width = '0%';
        if (els.pct) els.pct.textContent = '0%';
        if (els.stage) els.stage.textContent = stage || 'Preparing…';
        if (els.detail) els.detail.textContent = detail || '';
        els.modal.hidden = false;
        build(phases || [], planned || null, outLabel);
    }

    function setStage(key, label, detail) {
        if (label && els.stage) els.stage.textContent = label;
        if (els.detail) els.detail.textContent = detail || '';
        if (!key || !st.nodes.size) return;
        const order = st.phases.map(([k]) => k);
        const idx = order.indexOf(key);
        if (idx < 0) return;
        order.forEach((k, i) => {
            const node = st.nodes.get(k);
            if (!node || node.classList.contains('skipped')) return;
            node.classList.remove('pending', 'active', 'done');
            node.classList.add(i < idx ? 'done' : i === idx ? 'active' : 'pending');
        });
        st.current = key;
        movePacket(key);
    }

    function finish() {
        st.nodes.forEach((node) => {
            if (node.classList.contains('skipped')) return;
            node.classList.remove('pending', 'active');
            node.classList.add('done');
        });
        st.finished = true;
        if (els.chain) els.chain.classList.add('finished');
        movePacket('out');
    }

    function progress(frac, fallback) {
        const pct = Math.max(0, Math.min(100, Math.round(frac * 100)));
        if (els.fill) els.fill.style.width = `${pct}%`;
        if (els.pct) els.pct.textContent = `${pct}%`;
        if (!st.current && fallback && frac > 0.05 && frac < 1 && els.stage) {
            const text = fallback(frac);
            if (text) els.stage.textContent = text;
        }
        if (frac >= 1) finish();
    }

    function fail(message) {
        cancelClose();
        abortCountdown();
        clearHold();
        showLines(true);
        if (els.stage) els.stage.textContent = 'Processing failed';
        if (els.detail) els.detail.textContent = '';
        if (els.error) { els.error.textContent = message || 'Unknown error'; els.error.hidden = false; }
        if (els.close) { els.close.hidden = false; els.close.focus(); }
    }

    function close() {
        cancelClose();
        abortCountdown();
        hideDownload();
        if (els.modal) els.modal.hidden = true;
    }

    // ── The end of the run: the Download step ────────────────────────
    // The chain stays drawn as finished (packet at Out) and the progress
    // lines give way to the file's name, where it went, and the buttons.
    // Download / Show in folder / Download a copy each run their action
    // and take the window down; Close and Escape just close it.
    function offerDownload({ title, sub, primary, secondary } = {}) {
        if (!els.modal || !els.download) return;
        cancelClose();
        abortCountdown();
        clearHold();
        hideDownload();
        if (els.error) { els.error.hidden = true; els.error.textContent = ''; }
        if (els.close) els.close.hidden = true;
        els.modal.hidden = false;
        if (!st.finished && st.nodes.size) finish();
        showLines(false);
        if (els.dlTitle) els.dlTitle.textContent = title || 'Your file is ready';
        if (els.dlSub) els.dlSub.textContent = sub || '';
        const wire = (btn, spec) => {
            if (!btn) return null;
            if (!spec) { btn.hidden = true; return null; }
            btn.hidden = false;
            btn.textContent = spec.label || 'Download';
            const h = () => {
                try { if (spec.onClick) spec.onClick(); } finally { close(); }
            };
            btn.addEventListener('click', h);
            return () => btn.removeEventListener('click', h);
        };
        const offs = [wire(els.dlPrimary, primary), wire(els.dlSecondary, secondary)];
        const onClose = () => close();
        const onKey = (e) => {
            if (e.key !== 'Escape') return;
            e.preventDefault();
            close();
        };
        if (els.dlClose) els.dlClose.addEventListener('click', onClose);
        document.addEventListener('keydown', onKey);
        st.dlCleanup = () => {
            offs.forEach((off) => { if (off) off(); });
            if (els.dlClose) els.dlClose.removeEventListener('click', onClose);
            document.removeEventListener('keydown', onKey);
        };
        els.download.hidden = false;
        const focusTarget = (els.dlPrimary && !els.dlPrimary.hidden) ? els.dlPrimary : els.dlClose;
        if (focusTarget) { try { focusTarget.focus({ preventScroll: true }); } catch (_) { /* no focus */ } }
    }
    function closeSoon(ms = 900) {
        cancelClose();
        st.closeTimer = setTimeout(() => { st.closeTimer = null; close(); }, ms);
    }
    const isOpen = () => !!(els.modal && !els.modal.hidden);

    // ── Between the passes ───────────────────────────────────────────
    // Keep the window up after a finish. The stage reads as done (green,
    // ticked) and the bar sweeps while the caller loads the next pass.
    // A closed window opens again; with `phases` the chain is drawn as
    // finished first, so "Pass 1 done" has the pass-1 chain above it.
    function hold({ title, stage, detail, phases, planned, outLabel } = {}) {
        if (!els.modal) return;
        cancelClose();
        abortCountdown();
        if (els.title && title) els.title.textContent = title;
        if (els.error) { els.error.hidden = true; els.error.textContent = ''; }
        if (els.close) els.close.hidden = true;
        els.modal.hidden = false;
        if (phases) { build(phases, planned || null, outLabel); finish(); }
        showLines(true);
        if (els.stage) { els.stage.textContent = stage || 'Done'; els.stage.classList.add('pm-done'); }
        if (els.detail) els.detail.textContent = detail || '';
        // The busy sweep sizes and moves the fill itself.
        if (els.fill) els.fill.style.width = '';
        if (els.track) els.track.classList.add('busy');
        if (els.pct) els.pct.hidden = true;
    }

    function setDetail(text) {
        if (els.detail) els.detail.textContent = text || '';
    }

    // The big count. With `phases` the chain is rebuilt first, pending, so
    // the next run sits loaded above the digits. Each second the digit
    // punches in and the ring drains; at zero the ring fills green, the
    // digit says Go for a beat, and the promise resolves true. Stop here
    // and Escape resolve false and put the progress lines back; the
    // caller decides whether to close the window.
    function countdown({ seconds = 3, kicker, title, sub, stopLabel,
                         phases, planned, outLabel, modalTitle } = {}) {
        return new Promise((resolve) => {
            if (!els.modal || !els.countdown || !els.cdDigit) { resolve(true); return; }
            cancelClose();
            abortCountdown();
            clearHold();
            if (els.title && modalTitle) els.title.textContent = modalTitle;
            if (els.error) { els.error.hidden = true; els.error.textContent = ''; }
            if (els.close) els.close.hidden = true;
            els.modal.hidden = false;
            if (phases) build(phases, planned || null, outLabel);
            hideDownload();
            showLines(false);

            const n = Math.max(1, Math.round(seconds));
            let left = n;
            let timer = null;
            let settled = false;
            if (els.cdKicker) els.cdKicker.textContent = kicker || '';
            if (els.cdTitle) els.cdTitle.textContent = title || '';
            if (els.cdSub) els.cdSub.textContent = sub || `starts in ${n} second${n === 1 ? '' : 's'}`;
            if (els.cdStop) { els.cdStop.textContent = stopLabel || 'Stop here'; els.cdStop.hidden = false; }
            els.countdown.classList.remove('go', 'counting');
            els.countdown.style.setProperty('--cd-total', `${n}s`);
            els.countdown.hidden = false;

            const showDigit = (text) => {
                els.cdDigit.textContent = text;
                if (!els.cdNum) return;
                // Restart the punch-in for every digit.
                els.cdNum.classList.remove('pop');
                void els.cdNum.offsetWidth;
                els.cdNum.classList.add('pop');
            };
            const settle = (go) => {
                if (settled) return;
                settled = true;
                if (timer) clearTimeout(timer);
                timer = null;
                if (els.cdStop) els.cdStop.removeEventListener('click', onStop);
                document.removeEventListener('keydown', onKey);
                els.countdown.classList.remove('counting', 'go');
                els.countdown.hidden = true;
                showLines(true);
                st.abortCountdown = null;
                resolve(go);
            };
            const onStop = () => settle(false);
            const onKey = (e) => {
                if (e.key !== 'Escape') return;
                e.preventDefault();
                settle(false);
            };
            const tick = () => {
                if (settled) return;
                if (left > 0) {
                    showDigit(String(left));
                    left -= 1;
                    timer = setTimeout(tick, 1000);
                    return;
                }
                // Zero: a short Go beat, then the caller opens the run.
                els.countdown.classList.add('go');
                if (els.cdStop) els.cdStop.hidden = true;
                if (els.cdSub) els.cdSub.textContent = 'Starting…';
                showDigit('Go');
                timer = setTimeout(() => settle(true), 420);
            };

            st.abortCountdown = () => settle(false);
            if (els.cdStop) els.cdStop.addEventListener('click', onStop);
            document.addEventListener('keydown', onKey);
            // Focus lives in the dialog while it counts: Stop here is the
            // only control, so Enter or Space stops, Escape stops too.
            if (els.cdStop) { try { els.cdStop.focus({ preventScroll: true }); } catch (_) { /* no focus */ } }
            // Start the ring's drain on the next frame, after the panel is
            // laid out: an animation set on a just-unhidden element can
            // skip its first frames.
            requestAnimationFrame(() => { if (!settled) els.countdown.classList.add('counting'); });
            tick();
        });
    }

    return { open, stage: setStage, progress, finish, fail, close, closeSoon, isOpen,
             hold, detail: setDetail, countdown, offerDownload };
}

export const processModal = createProcessModal();
