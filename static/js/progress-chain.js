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
        pct: $('process-modal-pct'), error: $('process-modal-error'),
        close: $('process-modal-close'),
    };
    const st = { phases: [], nodes: new Map(), current: null, packet: null, wire: null, finished: false };

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

    function open({ title, phases, planned, stage, detail, outLabel } = {}) {
        if (!els.modal) return;
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
        if (els.stage) els.stage.textContent = 'Processing failed';
        if (els.detail) els.detail.textContent = '';
        if (els.error) { els.error.textContent = message || 'Unknown error'; els.error.hidden = false; }
        if (els.close) { els.close.hidden = false; els.close.focus(); }
    }

    function close() { if (els.modal) els.modal.hidden = true; }
    function closeSoon(ms = 900) { setTimeout(close, ms); }
    const isOpen = () => !!(els.modal && !els.modal.hidden);

    return { open, stage: setStage, progress, finish, fail, close, closeSoon, isOpen };
}

export const processModal = createProcessModal();
