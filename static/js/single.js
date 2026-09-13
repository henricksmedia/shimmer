// single.js — Orchestrates the Single-File tab.

import { renderControls, CONTROL_SPEC as ADV_SPEC, GROUPS as ADV_GROUPS } from './controls.js';
import { initPresetSelect, presetToSliderValues, runAutoDetect } from './preset.js';
import {
    submitProcess, openSSE, fetchMetrics, resultUrl, fetchTonePlan, fetchToneFamilies,
    uploadFile, dropSession, renderPreview, browseFolder, revealPath,
} from './api.js';
import { makeSettingsSaver, loadSettings } from './settings.js';
import { openHelp } from './help.js';
import { createUnifiedPlayer, fmtTime } from './visualizer.js';
import { initEqPanel } from './eq.js';
import { PHASES as CHAIN_PHASES } from './chain.js';
import { processModal } from './progress-chain.js';
import { initTrim } from './trim.js';
import { initReport } from './report.js';
import { initFaultPicker } from './fault-picker.js';


const PREVIEW_DEBOUNCE_MS = 250;
const PREVIEW_CACHE_MAX = 20;


export async function initSingleTab() {
    const $ = (id) => document.getElementById(id);

    const dropzone     = $('dropzone');
    const fileInput    = $('file-input');
    const pickBtn      = $('pick-file-btn');
    const selectedFile = $('selected-file');
    const presetSelect = $('preset-select');
    const presetDesc   = $('preset-desc');
    const autoBtn      = $('analyze-btn');
    const masterEnabled = $('master-enabled');
    const masterTarget  = $('master-target');
    const masterIntensity = $('master-intensity');
    const masterTilt = $('master-tilt');
    const masteringReadout = $('mastering-readout');
    const preserveVolCard = $('preserve-vol-card');
    const abLoudnessMatch = $('ab-loudness-match');
    const stepUpload = $('step-upload');
    const stepAnalyze = $('step-analyze');
    const stepProcess = $('step-process');
    const slidersHost  = $('sliders-host');
    const preserveVol  = $('preserve-vol');
    const trimSilence  = $('trim-silence');
    const rememberSettings = $('remember-settings');
    const outputFormat = $('output-format');
    // Settings tab, Downloads: automatic download and the download
    // location (the browser, or a folder the server writes into). Read
    // through downloadPrefs() / activeSaveFolder().
    const dlAuto        = $('dl-auto');
    const dlLocBrowser  = $('dl-location-browser');
    const dlLocFolder   = $('dl-location-folder');
    const dlState       = $('dl-state');
    const saveFolder    = $('save-folder');
    const saveFolderRow = $('save-folder-row');
    const browseSaveBtn = $('browse-save-btn');
    const processBtn   = $('process-btn');
    const progressEl   = $('progress');
    const strengthEl   = $('preset-strength');
    const strengthValEl = $('preset-strength-value');

    const audioOrig = $('audio-original');
    const audioProc = $('audio-processed');
    const audioDiff = $('audio-diff');
    const metricsBox = $('metrics-box');
    // Renders the stat readout. Accepts a string, an array of strings (one
    // unlabeled row), or an array of {label, chips} groups (one labeled
    // row each; empty groups are skipped). Empty input hides the box.
    function setMetrics(items) {
        metricsBox.innerHTML = '';
        const list = items == null ? [] : (Array.isArray(items) ? items : [String(items)]);
        const isGrouped = list.length > 0 &&
            list.every(g => g && typeof g === 'object' && Array.isArray(g.chips));
        const groups = isGrouped ? list : [{ label: '', chips: list }];
        let count = 0;
        for (const g of groups) {
            const chips = g.chips.map(s => String(s).trim()).filter(s => s.length > 0);
            if (!chips.length) continue;
            const row = document.createElement('div');
            row.className = 'metric-row';
            if (g.label) {
                const lab = document.createElement('span');
                lab.className = 'metric-row-label';
                lab.textContent = g.label;
                row.appendChild(lab);
            }
            for (const text of chips) {
                const chip = document.createElement('span');
                chip.className = 'metric-chip';
                if (/^Error\b/i.test(text)) chip.classList.add('err');
                chip.textContent = text;
                chip.title = text;
                row.appendChild(chip);
            }
            metricsBox.appendChild(row);
            count += chips.length;
        }
        metricsBox.hidden = count === 0;
    }
    // The Release check card (shimmer/release.py grades, this draws): a
    // verdict pill, one line per check, then how loud it plays on each
    // service. Hidden when a run was not mastered.
    const releaseCard = $('release-card');
    const releaseVerdict = $('release-verdict');
    const releaseList = $('release-list');
    const releasePlatforms = $('release-platforms');
    function releaseVerdictText(rel) {
        if (rel.status === 'pass') return '✓ Ready to upload';
        if (rel.status === 'fail') return `✕ Not ready · ${rel.failed} problem${rel.failed === 1 ? '' : 's'}`;
        return `⚠ ${rel.warned} thing${rel.warned === 1 ? '' : 's'} to look at`;
    }
    function renderReleaseCard(rel) {
        if (!releaseCard) return;
        if (!rel || !Array.isArray(rel.checks) || !rel.checks.length) {
            releaseCard.hidden = true;
            return;
        }
        releaseVerdict.textContent = releaseVerdictText(rel);
        releaseVerdict.className = `rc-verdict ${rel.status}`;
        releaseList.innerHTML = '';
        const glyph = { pass: '✓', warn: '!', fail: '✕', info: 'i' };
        for (const c of rel.checks) {
            const li = mkEl('li', `rc-row ${c.status}`);
            // Value and advice flow together in one column, so the advice
            // wraps under the value instead of into a sliver.
            const text = mkEl('span', 'rc-text');
            text.append(mkEl('span', 'rc-value', c.value || ''));
            if (c.detail) text.append(mkEl('span', 'rc-detail', c.detail));
            li.append(mkEl('span', 'rc-icon', glyph[c.status] || '·'),
                      mkEl('span', 'rc-label', c.label),
                      text);
            releaseList.appendChild(li);
        }
        releasePlatforms.innerHTML = '';
        const plats = Array.isArray(rel.platforms) ? rel.platforms : [];
        releasePlatforms.hidden = plats.length === 0;
        if (plats.length) {
            releasePlatforms.appendChild(mkEl('span', 'rc-plat-label', 'How loud it plays'));
            for (const p of plats) {
                const chip = mkEl('span', 'rc-chip', `${p.name}: ${p.note}`);
                chip.title = `${p.name} normalises to ${p.target_lufs} LUFS`;
                releasePlatforms.appendChild(chip);
            }
        }
        releaseCard.hidden = false;
    }
    const autoDetectResults = $('auto-detect-results');
    // Step 2 in the dock: runs Analyze and jumps to the Analysis card,
    // then shows the verdict as a green status. Same for the card header.
    const analyzeDockBtn = $('analyze-dock-btn');
    const analysisCard = $('analysis-card');
    const analysisStatus = $('analysis-status');
    function setAnalyzeDock(state, text = '') {
        if (!analyzeDockBtn) return;
        analyzeDockBtn.classList.toggle('busy', state === 'busy');
        analyzeDockBtn.classList.toggle('done', state === 'done');
        const label = analyzeDockBtn.querySelector('.adb-text');
        const step = analyzeDockBtn.querySelector('.adb-step');
        if (label) label.textContent = state === 'busy' ? 'Analyzing…'
            : state === 'done' ? 'View analysis' : 'Analyze';
        if (step) step.textContent = state === 'done' ? '✓' : '2';
        analyzeDockBtn.title = state === 'done'
            ? 'Analysis is done. Opens the results in the workspace.'
            : 'Listens to your track and picks the best cleanup preset. Jumps to the Analysis card.';
        if (analysisStatus) {
            analysisStatus.hidden = state !== 'done';
            analysisStatus.textContent = state === 'done' ? `Ready · ${text}` : '';
        }
        if (analysisExpandBtn) analysisExpandBtn.hidden = state !== 'done';
        syncSheetStatus();
    }
    // The file in the workspace. Declared here, ahead of every helper
    // that reads it: settings restore fires a preset change during
    // startup, and that path (pushSettings -> syncDockStatus) used to
    // hit "Cannot access 'currentFile' before initialization".
    let currentFile = null;
    // What stage 3 will do, from the live controls (never a stale copy):
    // preset, strength, and master target or cleaning only.
    const dockStatus = $('dock-status');
    function syncDockStatus() {
        if (!dockStatus) return;
        if (!currentFile) { dockStatus.hidden = true; return; }
        const preset = labelOf(presetSelect.value) || presetSelect.value || '';
        const pct = Math.round(currentStrength() * 100);
        let tail = 'cleaning only';
        if (masterEnabled.checked) {
            const opt = masterTarget.options[masterTarget.selectedIndex];
            const t = opt ? opt.text : '';
            const short = t.includes(')') ? t.slice(0, t.indexOf(')') + 1) : t;
            tail = `master to ${short}`;
        }
        dockStatus.textContent = `${preset} · ${pct}% · ${tail}`;
        dockStatus.hidden = false;
    }

    function jumpToAnalysis() {
        if (!analysisCard) return;
        analysisCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        analysisCard.classList.remove('flash');
        void analysisCard.offsetWidth;   // restart the animation
        analysisCard.classList.add('flash');
    }
    if (analyzeDockBtn) {
        analyzeDockBtn.addEventListener('click', () => {
            if (analyzeDockBtn.classList.contains('done')) {
                openAnalysisSheet();
                return;
            }
            jumpToAnalysis();
            if (!analyzeDockBtn.classList.contains('busy')) autoBtn.click();
        });
    }

    // ── Analysis workspace: the results slide up over the page ───────
    // The result nodes are moved into the sheet while it is open and
    // moved back into the card on close, so there is one copy and a
    // re-run of Analyze while the sheet is open renders into the sheet.
    const analysisSheet = $('analysis-sheet');
    const analysisSheetBody = $('analysis-sheet-body');
    const analysisSheetStatus = $('analysis-sheet-status');
    const analysisSheetClose = $('analysis-sheet-close');
    const analysisSheetLoop = $('analysis-sheet-loop');
    const analysisHome = $('analysis-home');
    const analysisExpandBtn = $('analysis-expand-btn');
    const tagsEnabled = $('tags-enabled');
    const tagTitle = $('tag-title');
    const tagTitleHint = $('tag-title-hint');
    const tagFields = {
        artist: $('tag-artist'), album_artist: $('tag-album-artist'), album: $('tag-album'),
        genre: $('tag-genre'), year: $('tag-year'), track: $('tag-track'),
        copyright: $('tag-copyright'), isrc: $('tag-isrc'),
    };
    const tagsKeep = $('tags-keep');
    const tagsNotes = $('tags-notes');
    const repairListHost = $('repair-list');
    let sheetCloseTimer = null;

    function placeAnalysisSheet() {
        if (!analysisSheet) return;
        const bridge = document.querySelector('.bridge');
        const rail = document.querySelector('.rail');
        const bottom = bridge ? bridge.getBoundingClientRect().height : 0;
        const left = rail ? rail.getBoundingClientRect().width : 0;
        analysisSheet.style.bottom = `${bottom}px`;
        analysisSheet.style.left = `${left}px`;
        analysisSheet.style.maxHeight = `calc(100dvh - ${bottom + 52}px)`;
    }
    function syncSheetStatus() {
        if (!analysisSheetStatus || !analysisStatus) return;
        analysisSheetStatus.hidden = analysisStatus.hidden;
        analysisSheetStatus.textContent = analysisStatus.textContent;
    }
    function openAnalysisSheet() {
        if (!analysisSheet || !analysisSheetBody) return;
        if (sheetCloseTimer) { clearTimeout(sheetCloseTimer); sheetCloseTimer = null; }
        placeAnalysisSheet();
        analysisSheetBody.append(autoDetectResults, repairListHost);
        syncSheetStatus();
        analysisSheet.hidden = false;
        requestAnimationFrame(() => analysisSheet.classList.add('open'));
        if (analysisSheetClose) analysisSheetClose.focus();
    }
    function closeAnalysisSheet(immediate = false) {
        if (!analysisSheet || analysisSheet.hidden) return;
        analysisSheet.classList.remove('open');
        const finish = () => {
            sheetCloseTimer = null;
            analysisSheet.hidden = true;
            if (analysisHome) analysisHome.after(autoDetectResults, repairListHost);
        };
        if (immediate) finish();
        else sheetCloseTimer = setTimeout(finish, 240);
    }
    if (analysisSheetClose) analysisSheetClose.addEventListener('click', () => closeAnalysisSheet());
    if (analysisExpandBtn) analysisExpandBtn.addEventListener('click', openAnalysisSheet);
    if (analysisSheetLoop) {
        analysisSheetLoop.addEventListener('click', () => {
            // Same as the auto anchor: Live on, loop parked on the worst
            // stretch the analysis found.
            previewState.anchorMode = 'auto';
            if (!previewState.active) {
                previewToggle.checked = true;
                applyPreviewToggle(true);
            } else {
                doPreviewRender();
            }
        });
    }
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && analysisSheet && !analysisSheet.hidden) closeAnalysisSheet();
    });
    window.addEventListener('resize', () => {
        if (analysisSheet && !analysisSheet.hidden) placeAnalysisSheet();
    });
    const downloadLink = $('download-link');
    const doneBanner = $('done-banner');
    const doneChips = $('done-chips');

    // ── Advanced controls drawer ─────────────────────────────────────
    const advOpenBtn  = $('advanced-open-btn');
    const advDrawer   = $('advanced-drawer');
    const advBackdrop = $('advanced-drawer-backdrop');
    const advCloseBtn = $('advanced-close');

    const advContext = $('adv-context');
    const advLive = $('adv-live');
    const advResetAll = $('adv-reset-all');
    const advFocus = $('adv-focus');
    let advLastFocus = null;

    function openAdvancedDrawer() {
        advDrawer.hidden = false;
        advBackdrop.hidden = false;
        syncAdvancedBaseline();
        syncAdvancedHeader();
        renderAdvFocus(null);
        advLastFocus = document.activeElement;
        const first = advDrawer.querySelector('input[type="range"]');
        if (first) first.focus({ preventScroll: true });
    }
    function closeAdvancedDrawer() {
        advDrawer.hidden = true;
        advBackdrop.hidden = true;
        if (advLastFocus && advLastFocus.focus) advLastFocus.focus({ preventScroll: true });
    }
    advOpenBtn.addEventListener('click', openAdvancedDrawer);
    advCloseBtn.addEventListener('click', closeAdvancedDrawer);
    advBackdrop.addEventListener('click', closeAdvancedDrawer);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !advDrawer.hidden) closeAdvancedDrawer();
    });
    if (advResetAll) {
        advResetAll.addEventListener('click', () => {
            if (controls.resetAll()) { pushSettings(); schedulePreviewRender(); }
            syncAdvancedHeader();
        });
    }

    // The preset's values at the current strength: the tick under every
    // slider, and what "changed" is measured against.
    function syncAdvancedBaseline() {
        const preset = byName.get(presetSelect.value);
        if (!preset) return;
        controls.setBaseline(presetToSliderValues(preset, currentStrength()));
    }
    function syncAdvancedHeader() {
        // Only while the pane is open: it is refreshed on open, and the
        // page's own init sets sliders long before the labels exist.
        if (!advContext || !advDrawer || advDrawer.hidden) return;
        const changed = controls.getChanged();
        const preset = labelOf(presetSelect.value);
        const pct = Math.round(currentStrength() * 100);
        advContext.textContent = changed.length
            ? `${preset} · ${pct}% · ${changed.length} control${changed.length === 1 ? '' : 's'} overridden for this run`
            : `${preset} · ${pct}% · preset values. Move a slider to override it for this run.`;
        if (advResetAll) advResetAll.hidden = changed.length === 0;
        if (advLive) {
            const live = !!(previewState && previewState.active);
            advLive.textContent = live ? 'Live · you hear each change in about a second'
                : 'Live loop is off · turn it on under the player to hear changes as you move';
            advLive.classList.toggle('on', live);
        }
    }

    // Focus panel: the control under the pointer or keyboard, its meaning,
    // where it sits on the chain, and the preset value against the current one.
    function renderAdvFocus(spec, state) {
        if (!advFocus) return;
        advFocus.innerHTML = '';
        const chain = mkEl('div', 'af-chain');
        const phase = spec ? (ADV_GROUPS.find((g) => g.key === spec.group) || {}).phase : null;
        CHAIN_PHASES.forEach(([key, label, color]) => {
            const dot = mkEl('span', `af-dot${phase === key ? ' on' : ''}`);
            dot.style.setProperty('--phase', color);
            dot.title = label;
            chain.appendChild(dot);
        });
        if (!spec) {
            const changed = controls.getChanged();
            advFocus.appendChild(mkEl('div', 'af-kicker', changed.length ? 'Overridden for this run' : 'How to read this pane'));
            if (changed.length) {
                const list = mkEl('div', 'af-changed');
                changed.forEach((c) => {
                    const row = mkEl('div', 'af-changed-row');
                    row.append(mkEl('span', 'af-changed-label', c.label),
                               mkEl('span', 'af-changed-vals', `${c.baselineText} → ${c.valueText}`));
                    list.appendChild(row);
                });
                advFocus.appendChild(list);
                advFocus.appendChild(mkEl('div', 'af-note', 'Double-click a slider to put it back on the preset. Reset all is at the top.'));
            } else {
                advFocus.appendChild(mkEl('div', 'af-title', 'Hover or tab to a control'));
                advFocus.appendChild(mkEl('div', 'af-short',
                    'This panel explains it: what it does, when to move it, and where it sits in the chain. ' +
                    'The tick under each slider is the preset\u2019s value at the current strength. ' +
                    'Double-click a slider to go back to it. Shift + arrow keys move ten steps.'));
            }
            advFocus.appendChild(mkEl('div', 'af-chain-label', 'The chain'));
            advFocus.appendChild(chain);
            return;
        }
        const g = ADV_GROUPS.find((x) => x.key === spec.group) || { title: spec.group };
        advFocus.appendChild(mkEl('div', 'af-kicker', `${g.title} · ${spec.module || ''}`));
        advFocus.appendChild(mkEl('div', 'af-title', spec.label));
        if (spec.gloss) advFocus.appendChild(mkEl('div', 'af-gloss', spec.gloss));
        if (spec.help && spec.help.short) advFocus.appendChild(mkEl('div', 'af-short', spec.help.short));
        if (spec.help) {
            const list = mkEl('div', 'af-list');
            const up = mkEl('div', 'af-item');
            up.append(mkEl('b', null, 'Move it right when'), mkEl('span', null, spec.help.when_up || ''));
            const dn = mkEl('div', 'af-item');
            dn.append(mkEl('b', null, 'Move it left when'), mkEl('span', null, spec.help.when_down || ''));
            list.append(up, dn);
            advFocus.appendChild(list);
            if (spec.help.typical) advFocus.appendChild(mkEl('div', 'af-typical', `Typical ${spec.help.typical}`));
        }
        if (state) {
            const vals = mkEl('div', 'af-values');
            vals.append(mkEl('span', 'af-val', `Now ${state.valueText}`));
            if (state.baselineText != null) {
                vals.append(mkEl('span', `af-val base${state.changed ? '' : ' same'}`,
                    state.changed ? `Preset ${state.baselineText}` : 'On the preset value'));
            }
            advFocus.appendChild(vals);
        }
        advFocus.appendChild(mkEl('div', 'af-chain-label', 'Where it acts on the chain'));
        advFocus.appendChild(chain);
    }

    // ── Preset description: collapsed to 2 lines, click to expand ────
    presetDesc.addEventListener('click', () => {
        presetDesc.classList.toggle('expanded');
    });
    document.addEventListener('click', (e) => {
        if (!presetDesc.contains(e.target)) {
            presetDesc.classList.remove('expanded');
        }
    });

    const previewToggle  = $('preview-toggle');
    const previewControls = $('preview-controls');
    const previewWindow  = $('preview-window');
    const previewHereBtn = $('preview-here-btn');
    const previewStatus  = $('preview-status');
    const previewExplainer = $('preview-explainer');
    const previewToggleRow = $('preview-toggle-row');

    // One-time discoverability nudge: the first time the user edits a
    // setting with Live off, point them at the toggle. Persisted so it
    // never fires again on any later visit.
    const NUDGE_KEY = 'shimmer.previewNudgeSeen';
    let previewNudged = false;  // this session, avoid repeat pulses
    const nudgeSeen = () => {
        try { return !!localStorage.getItem(NUDGE_KEY); } catch (_) { return false; }
    };
    const markNudgeSeen = () => {
        try { localStorage.setItem(NUDGE_KEY, '1'); } catch (_) {}
    };
    const DEFAULT_EXPLAINER =
        'Turn on Live to loop the worst section and hear edits instantly.';

    // Explainer shows only while Live is off; when Live is on the status
    // pill (rendering / live / error) carries the state instead.
    function showPreviewExplainer(text, nudge) {
        if (!previewExplainer) return;
        previewExplainer.textContent = text;
        previewExplainer.classList.toggle('nudge', !!nudge);
        previewExplainer.hidden = false;
    }
    function syncPreviewExplainer() {
        if (!previewExplainer) return;
        if (previewState.active) {
            previewExplainer.hidden = true;          // status pill owns the row
        } else if (!previewExplainer.classList.contains('nudge')) {
            showPreviewExplainer(DEFAULT_EXPLAINER, false);
        } else {
            previewExplainer.hidden = false;         // keep the active nudge
        }
    }

    function maybePreviewNudge() {
        if (!currentFile || previewNudged || nudgeSeen()) return;
        previewNudged = true;
        markNudgeSeen();
        showPreviewExplainer('Hear that change instantly — turn on Live ↑', true);
        if (previewToggleRow) {
            previewToggleRow.classList.remove('nudge-pulse');
            void previewToggleRow.offsetWidth;       // restart the animation
            previewToggleRow.classList.add('nudge-pulse');
        }
    }

    let lastAnalysis = null;
    // Tone step (suggested EQ): the last plan, what it put into the EQ,
    // the family list from the server and the user's choices.
    let lastTonePlan = null;
    let toneAppliedBands = [];
    let toneApplied = false;
    const toneStrip = $('tone-strip');
    const stateEls = {
        eq: $('state-eq'), master: $('state-master'), output: $('state-output'), tags: $('state-tags'),
    };
    let toneFamilies = [];
    const toneState = { family: 'neutral', auto: true, amount: 1.0 };
    fetchToneFamilies().then((f) => { toneFamilies = f; });
    let lastFollowUp = null; // Analyze's second-pass suggestion, if any
    // Static-repair plan for the current file: the generator's fixed
    // tonal lines the server found, each with an `on` flag the user can
    // untick. Sent with every preview / process request; null = let the
    // server scan and decide.
    let lastRepair = null;
    let lastEdges = null;    // head/tail scan from the last upload
    let lastMasteringReport = null;
    // Match deltas (processed LUFS minus original LUFS). Preview uses
    // per-render slice loudness; full uses whole-file metrics. `null`
    // means "no data yet for this state".
    let fullMatchDb = null;
    let previewMatchDb = null;
    // Analyze timeline (intensity bins over the whole file), kept so the
    // preview window can auto-anchor on the artifact-hot region.
    let lastTimeline = null;
    let player = null;

    const saveSettings = makeSettingsSaver();

    // ── Preview state ────────────────────────────────────────────────
    // Held across the entire single-tab lifetime; reset on file change.
    const previewState = {
        sessionId: null,
        durationS: 0,
        active: false,
        anchorS: 0,        // start of the loop window in source time
        anchorMode: 'auto',  // 'auto' = artifact-hot region; 'manual' = playhead
        windowS: 20,
        renderInflight: null,  // AbortController for the in-flight render
        renderPending: false,
        debounceTimer: null,
        originalBlobUrl: null,
        savedTime: 0,
    };

    // Decoded render cache keyed by (window + params). Hits skip the
    // network and swap buffers instantly.
    const previewCache = new Map();  // key -> {processedBuf, removedBuf, meta}

    function currentStrength() {
        const v = parseFloat(strengthEl.value);
        return Number.isFinite(v) ? v : 1.0;
    }

    function renderStrengthBadge() {
        const v = currentStrength();
        strengthValEl.textContent = `${Math.round(v * 100)}%`;
    }
    renderStrengthBadge();

    // "What do you hear?": its picks go to the engine as fixes/auto. The
    // cards that live in Mastering (Loudness, Lack of air) set its controls.
    const picker = await initFaultPicker({
        onChange: () => { pushSettings(); schedulePreviewRender(); },
        onMasterCard: (key, on) => {
            if (!on && key === 'loudness') return;
            if (on && !masterEnabled.checked) {
                masterEnabled.checked = true;
                masterEnabled.dispatchEvent(new Event('change'));
            }
            if (key === 'loudness') {
                masterTarget.value = 'cd';
                masterTarget.dispatchEvent(new Event('change'));
            } else if (key === 'air') {
                masterTilt.value = on ? 'bright' : 'neutral';
                masterTilt.dispatchEvent(new Event('change'));
            }
        },
    });

    const {byName, defaultName} = await initPresetSelect(presetSelect, {
        descEl: presetDesc,
        onChange: (preset) => {
            controls.setValues(presetToSliderValues(preset, currentStrength()));
            controls.setBaseline(presetToSliderValues(preset, currentStrength()));
            pushSettings();
            schedulePreviewRender();
        },
    });

    const controls = renderControls(
        slidersHost,
        () => { pushSettings(); schedulePreviewRender(); },
        (specKey) => openHelp('controls', specKey),
        {
            onFocus: (spec, state) => renderAdvFocus(spec, state),
            onDirty: () => syncAdvancedHeader(),
        },
    );

    const eqPanel = initEqPanel($('eq-card'), {
        onChange: () => { pushSettings(); schedulePreviewRender(); },
        getSpectrum: () => (lastAnalysis && lastAnalysis.spectrum) || null,
        getCutoffHz: () => (lastAnalysis && Number(lastAnalysis.cutoff_hz)) || 0,
    });

    // Top & tail. Detection is reported here, never applied on its own —
    // the trim only reaches the export because the user armed it.
    const trimPanel = initTrim({});
    // Report stage: the "What changed" spectrum card (report.js draws,
    // shimmer/report.py measures).
    const report = initReport({
        card: $('spectrum-card'),
        canvas: $('spectrum-compare'),
        headline: $('spectrum-headline'),
        readout: $('spectrum-readout'),
    });

    // Transport scrubber (bridge): follows the playhead and shows the Live
    // loop window; click or drag to seek. Declared before the player so
    // its first time update can reach these elements.
    const seekEl = $('player-seek');
    const seekTrack = seekEl ? seekEl.querySelector('.tp-seek-track') : null;
    const seekFill = $('player-seek-fill');
    const seekThumb = $('player-seek-thumb');
    const seekLoop = $('player-seek-loop');
    const tpCur = $('tp-cur');
    const tpTotal = $('tp-total');
    function updateSeek(t, d, loop) {
        if (tpCur) tpCur.textContent = fmtTime(t);
        if (tpTotal) tpTotal.textContent = fmtTime(d);
        if (!seekEl) return;
        const frac = d > 0 ? Math.max(0, Math.min(1, t / d)) : 0;
        seekFill.style.width = `${frac * 100}%`;
        seekThumb.style.left = `${frac * 100}%`;
        seekEl.setAttribute('aria-valuenow', String(Math.round(frac * 100)));
        seekEl.setAttribute('aria-valuetext', `${fmtTime(t)} of ${fmtTime(d)}`);
        if (loop && d > 0) {
            seekLoop.hidden = false;
            seekLoop.style.left = `${(loop.start / d) * 100}%`;
            seekLoop.style.width = `${Math.max(0.5, ((loop.end - loop.start) / d) * 100)}%`;
        } else {
            seekLoop.hidden = true;
        }
    }

    player = createUnifiedPlayer({
        onTimeUpdate: updateSeek,
        els: { original: audioOrig, processed: audioProc, removed: audioDiff },
        canvas: $('player-canvas'),
        playBtn: $('player-play'),
        timeLabel: $('player-time'),
        tabsHost: $('track-tabs'),
        modeWaveBtn: $('viz-mode-wave'),
        modeOverlayBtn: $('viz-mode-overlay'),
        modeSpecBtn: $('viz-mode-spec'),
        spectrumCanvas: $('spectrum-live'),
        metersHost: $('player-meters'),
        lufsFillEl: $('viz-lufs-fill'),
        lufsTargetEl: $('viz-lufs-target'),
        getShimmerBand: () => {
            const v = controls.getValues();
            return { lo: v.start_hz || 5100, hi: v.end_hz || 7200 };
        },
    });
    player.attachKeyboard();

    // Transport buttons and scrubber.
    const SKIP_S = 5;
    const btnStart = $('player-start'), btnBack = $('player-back'), btnFwd = $('player-fwd');
    if (btnStart) btnStart.addEventListener('click', () => player.toStart());
    if (btnBack) btnBack.addEventListener('click', () => player.skip(-SKIP_S));
    if (btnFwd) btnFwd.addEventListener('click', () => player.skip(SKIP_S));
    if (seekEl && seekTrack) {
        let seeking = false;
        const seekAt = (clientX) => {
            const rect = seekTrack.getBoundingClientRect();
            if (rect.width <= 0) return;
            const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
            const d = player.duration;
            if (d > 0) player.seek(frac * d);
        };
        seekEl.addEventListener('pointerdown', (e) => {
            seeking = true;
            try { seekEl.setPointerCapture(e.pointerId); } catch (_) {}
            seekAt(e.clientX);
            e.preventDefault();
        });
        seekEl.addEventListener('pointermove', (e) => { if (seeking) seekAt(e.clientX); });
        const stop = (e) => { if (seeking) { seeking = false; if (e && e.clientX != null) seekAt(e.clientX); } };
        seekEl.addEventListener('pointerup', stop);
        seekEl.addEventListener('pointercancel', () => { seeking = false; });
    }

    const abMatchNote = $('ab-match-note');

    function applyLoudnessMatch() {
        // Delta = processed LUFS minus original LUFS, from the state we
        // are actually auditioning: per-render slice loudness while the
        // preview loop is live, whole-file metrics after a full run.
        const d = previewState.active ? previewMatchDb : fullMatchDb;
        // Clamp the match attenuation. A short preview slice can report a
        // LUFS delta far larger than the whole track's — e.g. when Analyze
        // re-anchors the loop onto an atypically quiet or loud region — which
        // would drop the monitored track to a fraction of its level ("volume
        // way down after applying a match"). Loudness differences that matter
        // for A/B sit within a few dB; past ~6 dB the slice estimate is
        // unreliable and a near-silent track defeats the point of matching.
        // Cap so playback is never attenuated by more than half.
        const MATCH_MAX_DB = 6;
        const raw = d == null ? 0 : d;
        const dd = Math.max(-MATCH_MAX_DB, Math.min(MATCH_MAX_DB, raw));
        // Say what the match is doing. A silent 6 dB cut on the Processed
        // monitor reads as "processed got quieter and won't come back".
        if (abMatchNote) {
            let txt = '';
            if (abLoudnessMatch.checked) {
                if (d == null) {
                    txt = '(waiting for render)';
                } else if (Math.abs(dd) >= 0.1) {
                    const side = dd > 0 ? 'Processed' : 'Original';
                    txt = `${side} −${Math.abs(dd).toFixed(1)} dB`;
                    if (Math.abs(raw) > MATCH_MAX_DB + 1e-6) txt += ' (capped)';
                }
            }
            abMatchNote.textContent = txt;
            abMatchNote.title = txt
                ? 'Monitoring gain only — the louder side is turned down so ' +
                  'you compare sound, not level. Never applied to your export.'
                : '';
        }
        // Attenuate whichever side is louder so the comparison is fair.
        // Removed is an audition track and stays out of the match.
        player.setLoudnessMatch(abLoudnessMatch.checked, {
            original:  dd < 0 ? dd : 0,
            processed: dd > 0 ? -dd : 0,
            removed:   0,
        });
    }

    // Defaults first; restore only when the user opted in last time.
    controls.setValues(presetToSliderValues(
        byName.get(defaultName), currentStrength()));
    controls.setBaseline(presetToSliderValues(
        byName.get(defaultName), currentStrength()));

    const saved = await loadSettings();
    const shouldRestore = !!(saved && saved.remember_settings);
    if (rememberSettings) rememberSettings.checked = shouldRestore;
    if (shouldRestore) {
        if (typeof saved.preset_strength === 'number') {
            strengthEl.value = String(saved.preset_strength);
            renderStrengthBadge();
        }
        if (saved.preset && byName.has(saved.preset)) {
            presetSelect.value = saved.preset;
            presetSelect.dispatchEvent(new Event('change'));
        }
        if (saved.sliders) controls.setValues(saved.sliders);
        if (typeof saved.preserve_volume === 'boolean') {
            preserveVol.checked = saved.preserve_volume;
        }
        if (typeof saved.trim_silence === 'boolean') {
            trimSilence.checked = saved.trim_silence;
        }
        if (saved.output_format) outputFormat.value = saved.output_format;
        if (typeof saved.ab_loudness_match === 'boolean') {
            abLoudnessMatch.checked = saved.ab_loudness_match;
        }
        if (saved.eq) eqPanel.setPayload(saved.eq);
        if (saved.mastering) {
            if (typeof saved.mastering.enabled === 'boolean') {
                masterEnabled.checked = saved.mastering.enabled;
            }
            if (saved.mastering.target) masterTarget.value = saved.mastering.target;
            if (saved.mastering.intensity) masterIntensity.value = saved.mastering.intensity;
            if (saved.mastering.tilt) masterTilt.value = saved.mastering.tilt;
        }
    }

    // Identity and preferences come back regardless of "remember
    // settings": the artist name and the Tone family are not run state.
    if (saved && saved.tags) restoreTagsDefaults(saved.tags);
    // The Download preferences (Settings tab) are preferences too, so
    // they come back with the tags: a folder set once stays set.
    if (saved && saved.downloads && typeof saved.downloads === 'object') {
        const d = saved.downloads;
        if (dlAuto) dlAuto.checked = !!d.auto;
        if (saveFolder && typeof d.folder === 'string') saveFolder.value = d.folder;
        const useFolder = d.location === 'folder' && !!(saveFolder && saveFolder.value.trim());
        if (dlLocFolder) dlLocFolder.checked = useFolder;
        if (dlLocBrowser) dlLocBrowser.checked = !useFolder;
        syncDownloadControls();
    }
    if (saved && saved.tone) {
        if (typeof saved.tone.family === 'string') toneState.family = saved.tone.family;
        if (typeof saved.tone.auto === 'boolean') toneState.auto = saved.tone.auto;
        if (Number.isFinite(saved.tone.amount)) toneState.amount = Math.min(1.25, Math.max(0.25, saved.tone.amount));
    }

    updateMasteringUI();
    applyLoudnessMatch();
    syncInspectorStates();

    // Live strength re-scaling: rebuild visible slider values from the
    // current preset every time the strength slider moves so the user
    // sees the effect.  The hidden keys (ceilings, FlickerTamer depth,
    // iterations, etc.) are scaled server-side by apply_preset_strength.
    strengthEl.addEventListener('input', () => {
        renderStrengthBadge();
        const preset = byName.get(presetSelect.value);
        if (preset) {
            controls.setValues(presetToSliderValues(preset, currentStrength()));
            controls.setBaseline(presetToSliderValues(preset, currentStrength()));
        }
        pushSettings();
        schedulePreviewRender();
    });

    function masteringPayload() {
        return {
            enabled: masterEnabled.checked,
            target: masterTarget.value,
            intensity: masterIntensity.value,
            tilt: masterTilt.value,
        };
    }

    // Stage 3 is named by what it will do: "Clean & Master" with
    // mastering on, "Clean" with it off. Button and stepper together.
    function processLabel() {
        return masterEnabled.checked ? 'Clean & Master' : 'Clean';
    }
    function syncProcessLabel() {
        if (processBtn.textContent !== 'Processing…') processBtn.textContent = processLabel();
        const step = stepProcess && stepProcess.querySelector('.step-label');
        if (step) step.textContent = processLabel();
    }

    function updateMasteringUI() {
        const on = masterEnabled.checked;
        $('mastering-options').style.opacity = on ? '1' : '0.5';
        syncProcessLabel();
        // Preserve volume only matters with mastering off. Keep the row in
        // view but greyed while mastering is on, so it can be found when a
        // tip mentions it; the loudness target sets the level meanwhile.
        preserveVolCard.classList.toggle('is-off', on);
        preserveVol.disabled = on;
        if (on) preserveVol.checked = false;
        const note = preserveVolCard.querySelector('.pv-note');
        if (note) {
            note.textContent = on
                ? 'not used while mastering is on; the loudness target sets the level'
                : 'keeps the level the same on a cleaning-only pass';
        }
    }

    function setWizardStep(step) {
        [stepUpload, stepAnalyze, stepProcess].forEach((el, i) => {
            if (el) el.classList.toggle('active', i <= step);
            if (el) el.classList.toggle('done', i < step);
        });
    }

    function renderAnalysisReadout(analysis) {
        if (!analysis || !analysis.loudness) return;
        const l = analysis.loudness;
        masteringReadout.hidden = false;
        masteringReadout.textContent =
            `Input: ${l.lufs_i?.toFixed?.(1) ?? '?'} LUFS · ` +
            `TP ${l.true_peak_dbtp?.toFixed?.(1) ?? '?'} dBTP · ` +
            `LRA ${l.lra?.toFixed?.(1) ?? '?'}`;
    }

    masterEnabled.addEventListener('change', () => {
        updateMasteringUI();
        pushSettings();
        schedulePreviewRender();
    });
    masterTarget.addEventListener('change', () => {
        player.setTargetLufs(
            { streaming: -14, loud: -11, cd: -9 }[masterTarget.value] || -14);
        pushSettings();
        schedulePreviewRender();
    });
    masterIntensity.addEventListener('change', () => {
        pushSettings();
        schedulePreviewRender();
    });
    masterTilt.addEventListener('change', () => {
        pushSettings();
        schedulePreviewRender();
    });
    abLoudnessMatch.addEventListener('change', () => {
        applyLoudnessMatch();
        pushSettings();
    });
    renderToneStrip();

    function hideDoneBanner() {
        doneBanner.hidden = true;
        doneBanner.classList.remove('flash');
        processBtn.classList.remove('btn-secondary');
        processBtn.classList.add('btn-primary');
    }

    function showDoneBanner(chips) {
        doneChips.innerHTML = '';
        for (const c of chips) {
            const span = document.createElement('span');
            span.className = 'done-chip';
            span.textContent = c;
            doneChips.appendChild(span);
        }
        doneBanner.hidden = false;
        // Restart the flash animation.
        doneBanner.classList.remove('flash');
        void doneBanner.offsetWidth;
        doneBanner.classList.add('flash');
        // Shift visual priority: Download becomes the primary action.
        processBtn.classList.remove('btn-primary');
        processBtn.classList.add('btn-secondary');
    }

    function adoptFile(file) {
        currentFile = file;
        lastRun = null;
        if (!keepPlanOnAdopt) passPlan = null;
        priorPassPreset = detectPriorPass(file.name);
        resetTagsForFile(file);
        lastTonePlan = null;
        toneAppliedBands = [];
        toneApplied = false;
        // The previous track's analysis (and its suggested EQ) must not
        // sit under a new file.
        autoDetectResults.hidden = true;
        autoDetectResults.innerHTML = '';
        renderToneStrip();
        const priorNote = $('prior-pass-note');
        if (priorNote) {
            priorNote.hidden = !priorPassPreset;
            priorNote.textContent = priorPassPreset
                ? `Shimmer output · pass 1 was ${labelOf(priorPassPreset)}` : '';
        }
        selectedFile.hidden = false;
        selectedFile.textContent = `${file.name}  (${(file.size/1048576).toFixed(1)} MB)`;
        selectedFile.title = selectedFile.textContent;
        dropzone.classList.add('has-file');
        pickBtn.textContent = 'Change…';
        processBtn.disabled = false;
        if (analyzeDockBtn) analyzeDockBtn.disabled = false;
        closeAnalysisSheet(true);
        setAnalyzeDock('idle');
        syncDockStatus();
        setWizardStep(0);
        picker.reset();
        lastAnalysis = null;
        lastTimeline = null;
        fullMatchDb = null;
        previewMatchDb = null;
        lastFollowUp = null;
        lastRepair = null;
        renderRepairList();
        previewState.anchorMode = 'auto';
        previewCache.clear();
        masteringReadout.hidden = true;
        setMetrics('');
        report.clear();
        hideDoneBanner();

        // Tear down any prior preview session and reset preview UI.
        teardownPreviewSession();
        if (previewToggle.checked) previewToggle.checked = false;
        applyPreviewToggle(false);

        if (previewState.originalBlobUrl) {
            try { URL.revokeObjectURL(previewState.originalBlobUrl); } catch (_) {}
        }
        previewState.originalBlobUrl = URL.createObjectURL(file);
        player.resetTracks();
        player.setSource('original', previewState.originalBlobUrl);
        setPreviewStatus('Tick "Live preview" to loop edits around the playhead.');

        // Scan the edges now rather than when preview is first switched on.
        // A head glitch has to surface while the user is still deciding what
        // to do with the track, not after they have exported it.
        trimPanel?.reset(previewState.originalBlobUrl);
        ensurePreviewSession({quiet: true}).then((sid) => {
            if (currentFile !== file) return;      // superseded by a newer drop
            if (sid) trimPanel?.setSession(sid, previewState.durationS, lastEdges);
            else trimPanel?.setScanFailed();
        });
    }

    pickBtn.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('click', (e) => {
        if (e.target === pickBtn) return;
        fileInput.click();
    });
    fileInput.addEventListener('change', () => {
        if (fileInput.files && fileInput.files[0]) adoptFile(fileInput.files[0]);
    });

    const stopDefault = (e) => { e.preventDefault(); e.stopPropagation(); };
    ['dragenter', 'dragover'].forEach(ev =>
        dropzone.addEventListener(ev, (e) => {
            stopDefault(e); dropzone.classList.add('drag-over');
        }));
    ['dragleave', 'drop'].forEach(ev =>
        dropzone.addEventListener(ev, (e) => {
            stopDefault(e); dropzone.classList.remove('drag-over');
        }));
    dropzone.addEventListener('drop', (e) => {
        if (e.dataTransfer && e.dataTransfer.files[0]) {
            adoptFile(e.dataTransfer.files[0]);
        }
    });

    // The whole window is a drop target once the dropzone has collapsed
    // to its compact chip. (Dropzone drops stop propagation above.)
    window.addEventListener('dragover', (e) => e.preventDefault());
    window.addEventListener('drop', (e) => {
        e.preventDefault();
        const singleActive = document.getElementById('tab-single')
            .classList.contains('active');
        if (singleActive && e.dataTransfer && e.dataTransfer.files[0]) {
            adoptFile(e.dataTransfer.files[0]);
        }
    });

    // ── Auto-detect ──────────────────────────────────────────────────
    const labelOf = (key) => {
        const p = byName.get(key);
        return (p && p.label) || key;
    };

    // Apply a detected preset together with the strength the analysis
    // verified for it.  Strength is set first so the preset's change
    // handler builds the visible sliders at that strength; the server
    // scales the hidden keys from the same `preset_strength` value.
    function applyDetectedPreset(presetName, strength) {
        if (!presetName || !byName.has(presetName)) return;
        if (Number.isFinite(strength)) {
            const s = Math.max(0, Math.min(2, strength));
            strengthEl.value = String(s);
            renderStrengthBadge();
        }
        presetSelect.value = presetName;
        presetSelect.dispatchEvent(new Event('change'));
    }

    // ── Static repair (fixed lines) ─────────────────────────────────────
    const repairListEl = $('repair-list');

    function setRepairPlan(plan) {
        const notches = Array.isArray(plan && plan.notches) ? plan.notches : [];
        // Keep the user's unticks when the same line comes back from a
        // later scan (upload, then Analyze).
        const prev = new Map((lastRepair ? lastRepair.notches : [])
            .map(n => [Math.round(n.hz), n.on]));
        lastRepair = {
            enabled: true,
            notches: notches.map(n => ({
                hz: n.hz, depth_db: n.depth_db, bw_hz: n.bw_hz, kind: n.kind || 'line',
                excess_db: n.excess_db, duty: n.duty,
                on: prev.has(Math.round(n.hz)) ? prev.get(Math.round(n.hz)) : true,
            })),
        };
        renderRepairList();
    }

    // What the server should notch: an explicit list once we have one
    // (so unticks are honoured), otherwise null = scan and decide.
    function repairPayload() {
        if (!lastRepair) return { enabled: true, notches: null };
        return {
            enabled: true,
            notches: lastRepair.notches.filter(n => n.on).map(n => ({
                hz: n.hz, depth_db: n.depth_db, bw_hz: n.bw_hz, kind: n.kind,
                excess_db: n.excess_db, duty: n.duty,
            })),
        };
    }

    function renderRepairList() {
        if (!repairListEl) return;
        repairListEl.innerHTML = '';
        if (!lastRepair) { repairListEl.hidden = true; return; }
        repairListEl.hidden = false;
        const head = document.createElement('div');
        head.className = 'ad-cards-label';
        head.textContent = lastRepair.notches.length
            ? 'Fixed tones notched first in the chain'
            : 'Fixed tones';
        repairListEl.appendChild(head);
        if (!lastRepair.notches.length) {
            const e = document.createElement('div');
            e.className = 'repair-empty';
            e.textContent = 'No fixed generator tones found in this file.';
            repairListEl.appendChild(e);
            return;
        }
        lastRepair.notches.forEach((n, i) => {
            const row = document.createElement('label');
            row.className = 'repair-row' + (n.on ? '' : ' off');
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = !!n.on;
            cb.title = 'Untick to keep this tone';
            cb.addEventListener('change', () => {
                lastRepair.notches[i].on = cb.checked;
                row.classList.toggle('off', !cb.checked);
                pushSettings();
                schedulePreviewRender();
            });
            const hz = document.createElement('span');
            hz.className = 'r-hz';
            hz.textContent = `${(n.hz / 1000).toFixed(2)} kHz`;
            const depth = document.createElement('span');
            depth.className = 'r-depth';
            depth.textContent = `−${Math.round(n.depth_db)} dB`;
            const kind = document.createElement('span');
            kind.className = 'r-kind';
            kind.textContent = n.kind === 'comb' ? 'comb tooth' : 'line';
            row.append(cb, hz, depth, kind);
            repairListEl.appendChild(row);
        });
    }

    // Three-way dialog for the master-once reminder. Resolves to 'off'
    // (turn mastering off for this pass), 'master' (master anyway) or
    // 'cancel' (run nothing). A browser confirm() only has two buttons,
    // and "Cancel = master anyway" surprised people.
    const secondPassModal = $('second-pass-modal');
    function askSecondPass(label) {
        return new Promise((resolve) => {
            if (!secondPassModal) { resolve('master'); return; }
            const presetEl = $('second-pass-preset');
            if (presetEl) presetEl.textContent = label;
            const btnOff = $('second-pass-off');
            const btnMaster = $('second-pass-master');
            const btnCancel = $('second-pass-cancel');
            const finish = (choice) => {
                secondPassModal.hidden = true;
                btnOff.removeEventListener('click', onOff);
                btnMaster.removeEventListener('click', onMaster);
                btnCancel.removeEventListener('click', onCancel);
                document.removeEventListener('keydown', onKey);
                resolve(choice);
            };
            const onOff = () => finish('off');
            const onMaster = () => finish('master');
            const onCancel = () => finish('cancel');
            const onKey = (e) => { if (e.key === 'Escape') finish('cancel'); };
            btnOff.addEventListener('click', onOff);
            btnMaster.addEventListener('click', onMaster);
            btnCancel.addEventListener('click', onCancel);
            document.addEventListener('keydown', onKey);
            secondPassModal.hidden = false;
            btnOff.focus();
        });
    }

    // Plain-language advice shown whenever Analyze suggests a second pass
    // and mastering is on. Mastering limits the sound and sets its
    // loudness; cleaning a mastered file and mastering it again hurts it.

    function showAutoDetectError(msg) {
        autoDetectResults.hidden = false;
        autoDetectResults.innerHTML = '';
        const err = document.createElement('div');
        err.className = 'ad-error';
        err.textContent = msg;
        autoDetectResults.appendChild(err);
    }

    // Verdict first. The applied match is the hero; the other matches are
    // a quiet table; the second pass is a call to action with a button;
    // notes are a Details list. Four status tiles render too, shown only
    // in the workspace sheet (CSS). Amber marks exactly two things: the
    // applied choice and the next action.
    let syncNextStep = null;   // re-checks the second-pass callout when mastering toggles
    // Two-pass bookkeeping. `priorPassPreset` is set when the loaded file
    // is one of Shimmer's own exports (recognised by the export name
    // {stem}_{preset}_processed_{id}.ext), so the card knows pass 1 is
    // already done. `lastRun` remembers the last finished run so pass 2
    // can load its result without a download and re-upload.
    let priorPassPreset = null;
    let lastRun = null;
    function detectPriorPass(name) {
        const m = /^(.*)_(processed|trimmed)_[0-9a-f]{8}\.[a-z0-9]+$/i.exec(name || '');
        if (!m) return null;
        const before = m[1].toLowerCase();
        let best = null;
        for (const key of byName.keys()) {
            if (before.endsWith('_' + key) && (!best || key.length > best.length)) best = key;
        }
        return best;
    }
    masterEnabled.addEventListener('change', () => { if (syncNextStep) syncNextStep(); });
    preserveVol.addEventListener('change', () => { if (syncNextStep) syncNextStep(); });

    function mkEl(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }

    // ── Two-pass plan ────────────────────────────────────────────────
    // Built when Analyze suggests a follow-up. It survives the file swap
    // that Continue does and dies on a new upload. It drives the Passes
    // card and the one-click automation. Status walks: idle → running1 →
    // done1 → loading → loaded2 → running2 → done2.
    let passPlan = null;
    let keepPlanOnAdopt = false;

    function ensurePlan(followUp) {
        const p2 = {
            name: followUp.name,
            label: followUp.label || labelOf(followUp.name),
            strength: Number.isFinite(followUp.strength) ? followUp.strength : 1.0,
        };
        if (passPlan && passPlan.status !== 'idle') {
            passPlan.pass2 = p2;
            return;
        }
        if (priorPassPreset && byName.has(priorPassPreset)) {
            // A re-uploaded pass-1 output: pass 1 is history.
            passPlan = {
                pass1: { name: priorPassPreset, label: labelOf(priorPassPreset), strength: null, external: true },
                pass2: p2, status: 'loaded2', jobs: {}, loud: {}, auto: false,
            };
            return;
        }
        passPlan = {
            pass1: { name: presetSelect.value, label: labelOf(presetSelect.value), strength: currentStrength() },
            pass2: p2, status: 'idle', jobs: {}, loud: {}, auto: false,
        };
    }

    function waitForRun() {
        return new Promise((resolve) => {
            const h = (e) => {
                document.removeEventListener('shimmer:run-complete', h);
                resolve(e.detail || {});
            };
            document.addEventListener('shimmer:run-complete', h);
        });
    }

    async function runPass(n) {
        if (!passPlan) return false;
        if (n === 1) {
            masterEnabled.checked = false;
            masterEnabled.dispatchEvent(new Event('change'));
            preserveVol.checked = true;
            preserveVol.dispatchEvent(new Event('change'));
            passPlan.pass1 = { name: presetSelect.value, label: labelOf(presetSelect.value), strength: currentStrength() };
            // Pass 1 cleans only: no suggested EQ yet (it is planned for
            // pass 2 on the cleaned file).
            removeTonePlan();
            passPlan.status = 'running1';
        } else {
            applyDetectedPreset(passPlan.pass2.name, passPlan.pass2.strength);
            masterEnabled.checked = true;
            masterEnabled.dispatchEvent(new Event('change'));
            passPlan.status = 'running2';
        }
        renderPassPlan();
        closeAnalysisSheet(true);
        const done = waitForRun();
        processBtn.click();
        const r = await done;
        if (!r.ok) {
            passPlan.status = n === 1 ? 'idle' : 'loaded2';
            renderPassPlan();
            return false;
        }
        passPlan.jobs[n] = r.jobId;
        passPlan.loud[n] = r.loudness || null;
        passPlan.status = n === 1 ? 'done1' : 'done2';
        renderPassPlan();
        return true;
    }

    // Continue: pass 1's result becomes the source, pass 2 is set up.
    // `onStep(text)` hears each step by name (the processing window
    // shows it while the hand-off runs).
    async function loadPass1Result(onStep) {
        if (!passPlan || !passPlan.jobs[1]) return false;
        const step = (text) => { if (onStep) onStep(text); };
        passPlan.status = 'loading';
        renderPassPlan();
        try {
            step('loading the cleaned file…');
            const res = await fetch(resultUrl(passPlan.jobs[1], 'processed'));
            if (!res.ok) {
                throw new Error('The pass 1 result is no longer on the server. Download it and upload it instead.');
            }
            const blob = await res.blob();
            const stem = (currentFile && currentFile.name.replace(/\.[^.]+$/, '')) || 'track';
            const name = `${stem}_${passPlan.pass1.name}_processed_${passPlan.jobs[1].slice(0, 8)}.wav`;
            keepPlanOnAdopt = true;
            try { adoptFile(new File([blob], name, { type: blob.type || 'audio/wav' })); }
            finally { keepPlanOnAdopt = false; }
            applyDetectedPreset(passPlan.pass2.name, passPlan.pass2.strength);
            masterEnabled.checked = true;
            masterEnabled.dispatchEvent(new Event('change'));
            lastFollowUp = { name: passPlan.pass2.name, label: passPlan.pass2.label, strength: passPlan.pass2.strength };
            passPlan.status = 'loaded2';
            autoDetectResults.hidden = false;
            autoDetectResults.innerHTML = '';
            const side = mkEl('div', 'ad-side');
            autoDetectResults.appendChild(side);
            renderPassPlan(side);
            // Pass 2 gets its own Tone plan, judged on the cleaned file
            // with the pass-2 preset and mastering on. Applied when the
            // switch is on, before pass 2 can start.
            const main = mkEl('div', 'ad-main');
            main.appendChild(mkEl('div', 'tone-card busy tone-placeholder', 'Planning the EQ for pass 2…'));
            autoDetectResults.insertBefore(main, side);
            jumpToAnalysis();
            step(`planning the EQ for pass 2 · ${passPlan.pass2.label}…`);
            const plan = await replanTone();
            if (plan && toneState.auto) applyTonePlan();
            renderPassPlan();
            return true;
        } catch (e) {
            passPlan.status = 'done1';
            renderPassPlan();
            showAutoDetectError(e.message);
            return false;
        }
    }

    // ── Between the passes ───────────────────────────────────────────
    // Run both passes (and Continue) hand off to pass 2 by themselves.
    // That hand-off used to look like the end: the window closed on
    // pass 1, its result rendered with a Download button, and pass 2
    // opened the window again a few seconds later. Now the window stays
    // up the whole way: "Pass 1 done" over a busy bar while the cleaned
    // file loads and the EQ is planned, then a big 3-2-1 in front of the
    // pass-2 chain. Stop here (or Esc) keeps the loaded result in place
    // and runs nothing. Resolves true when pass 2 should run now.
    async function bridgeToPass2() {
        if (!passPlan) return false;
        const p2 = passPlan.pass2;
        // Continue after the window has closed: draw pass 1's chain as
        // done above the held line. Run both passes finds it still open,
        // packet leaving through Out, and keeps it as it is.
        const reopen = !processModal.isOpen();
        processModal.hold({
            stage: 'Pass 1 done',
            detail: 'loading the cleaned file…',
            ...(reopen ? { title: 'Cleaning · pass 1 of 2', phases: chainPhases(), planned: plannedPhases() } : {}),
        });
        if (!(await loadPass1Result((text) => processModal.detail(text)))) {
            // The error is on the Analysis card.
            processModal.close();
            return false;
        }
        // Pass 2's settings are in place now (preset, mastering on):
        // draw its chain, pending, and count it in.
        const target = (masterTarget.options[masterTarget.selectedIndex] || {}).text || '';
        const targetShort = target.includes(')') ? target.slice(0, target.indexOf(')') + 1) : target;
        const go = await processModal.countdown({
            seconds: 3,
            modalTitle: 'Cleaning & mastering · pass 2 of 2',
            kicker: 'Pass 2 of 2 · clean & master',
            title: `${p2.label}${targetShort ? ` · ${targetShort}` : ''}`,
            phases: chainPhases(),
            planned: plannedPhases(),
            stopLabel: 'Stop here',
        });
        if (!go) {
            passPlan.auto = false;
            processModal.close();
            renderPassPlan();
            return false;
        }
        return true;
    }

    async function runBothPasses() {
        if (!passPlan) return;
        passPlan.auto = true;
        try {
            if (passPlan.status === 'idle' && !(await runPass(1))) return;
            if (!passPlan.auto) return;
            if (passPlan.status === 'done1' && !(await bridgeToPass2())) return;
            if (!passPlan.auto) return;
            if (passPlan.status === 'loaded2') await runPass(2);
        } finally {
            passPlan.auto = false;
            renderPassPlan();
        }
    }

    // The Passes card. `host` is remembered so state changes re-render in
    // place; a new host (a fresh results render) replaces it.
    let planHost = null;
    function renderPassPlan(host) {
        if (host) planHost = host;
        // The host may not be attached yet (renderAutoDetect appends its
        // side column after filling it), so only require that it exists.
        if (!passPlan || !planHost) return;
        const p = passPlan;
        const st = p.status;
        const p1 = st === 'idle'
            ? { name: presetSelect.value, label: labelOf(presetSelect.value), strength: currentStrength() }
            : p.pass1;
        const p2 = p.pass2;
        const masterOn = masterEnabled.checked;
        const preserveOn = !!preserveVol.checked;
        const old = planHost.querySelector('.ad-next');
        const card = mkEl('div', 'ad-next plan');

        const kickers = {
            idle: 'Two-pass plan', running1: 'Two-pass plan · running pass 1',
            done1: 'Two-pass plan · pass 1 done', loading: 'Two-pass plan · loading the result',
            loaded2: 'Two-pass plan · pass 2 ready', running2: 'Two-pass plan · running pass 2',
            done2: 'Done · both passes',
        };
        card.appendChild(mkEl('div', 'ad-next-kicker', kickers[st] || 'Two-pass plan'));
        const titles = {
            idle: `Pass 1: ${p1.label} now · Pass 2: ${p2.label}`,
            running1: `Running pass 1: ${p1.label}`,
            done1: `Pass 1 done · next: pass 2 with ${p2.label}`,
            loading: 'Loading pass 1\u2019s result…',
            loaded2: `Pass 2: ${p2.label}`,
            running2: `Running pass 2: ${p2.label}`,
            done2: `${p1.label}, then ${p2.label}: finished`,
        };
        card.appendChild(mkEl('div', 'ad-next-title', titles[st] || ''));
        if (st === 'loaded2' && p1.external) {
            card.appendChild(mkEl('div', 'ad-next-prior',
                `This file is Shimmer's output from ${p1.label} (pass 1). ` +
                `The next step is ${p2.label}, not ${p1.label} again.`));
        }
        if ((st === 'idle' || st === 'loaded2') && lastFollowUp && lastFollowUp.reason) {
            card.appendChild(mkEl('div', 'ad-next-reason', lastFollowUp.reason));
        }

        // The three steps.
        const steps = mkEl('ol', 'plan-steps');
        const lufs = (n) => {
            const l = p.loud[n];
            const v = l && Number.isFinite(l.output_lufs_i) ? l.output_lufs_i : null;
            return v == null ? '' : ` · ${v.toFixed(1)} LUFS`;
        };
        const step = (num, name, sub, state, cls) => {
            const li = mkEl('li', `plan-step ${cls}`);
            li.append(mkEl('span', 'ps-num', num));
            const body = mkEl('div', 'ps-body');
            body.append(mkEl('div', 'ps-name', name), mkEl('div', 'ps-sub', sub));
            li.append(body, mkEl('span', 'ps-state', state));
            steps.appendChild(li);
        };
        const s1 = st === 'idle' ? ['next', 'active'] : st === 'running1' ? ['running…', 'active running']
            : [`✓ done${p1.external ? '' : lufs(1)}`, 'done'];
        step(p1.external ? '✓' : '1', `Pass 1 · ${p1.label}`,
             p1.external ? 'already done (this file is its output)' : 'clean only · keeps the level',
             s1[0], s1[1]);
        const target = (masterTarget.options[masterTarget.selectedIndex] || {}).text || '';
        const s2 = st === 'loaded2' ? ['next', 'active'] : st === 'running2' ? ['running…', 'active running']
            : st === 'done2' ? [`✓ done${lufs(2)}`, 'done'] : st === 'loading' ? ['loading…', 'active'] : ['waiting', ''];
        step('2', `Pass 2 · ${p2.label}`, `clean & master${toneState.auto ? ' · suggested EQ' : ''} · ${target.includes(')') ? target.slice(0, target.indexOf(')') + 1) : target}`, s2[0], s2[1]);
        const savingTo = activeSaveFolder();
        step('3', savingTo ? 'Saved & download' : 'Download',
             savingTo ? `the mastered file, saved to ${folderLabel(savingTo)}` : 'the mastered file',
             st === 'done2' ? 'ready' : 'after pass 2', st === 'done2' ? 'active' : '');
        card.appendChild(steps);

        // Settings for the pass about to run, shown as state (the run
        // buttons set them; nothing to click here).
        if (st === 'idle' || st === 'loaded2') {
            const checks = mkEl('div', 'ad-next-checks');
            const row = (label, ok, text) => {
                const r = mkEl('div', `ad-check ${ok ? 'ok' : ''}`);
                r.append(mkEl('span', 'ad-check-dot'), mkEl('span', 'ad-check-label', label),
                         mkEl('span', 'ad-check-state', ok ? `✓ ${text}` : text));
                checks.appendChild(r);
            };
            if (st === 'idle') {
                row('Mastering off for pass 1 (set when it runs)', !masterOn, masterOn ? 'On' : 'Off');
                row('Preserve volume on', preserveOn, preserveOn ? 'On' : 'Off');
                row('Suggested EQ planned for pass 2', toneState.auto, toneState.auto ? 'On' : 'Off');
            } else {
                row('Mastering on for the final pass', masterOn, masterOn ? 'On' : 'Off');
                row('Preserve volume off', !preserveOn, preserveOn ? 'On' : 'Off');
                const nMoves = lastTonePlan && Array.isArray(lastTonePlan.moves) ? lastTonePlan.moves.length : 0;
                row('Suggested EQ (Tone)', toneState.auto && (toneAppliedBands.length > 0 || nMoves === 0),
                    !toneState.auto ? 'Off' : nMoves === 0 ? 'None needed'
                        : toneAppliedBands.length ? `${toneAppliedBands.length} move${toneAppliedBands.length === 1 ? '' : 's'} in the EQ` : 'Planning…');
            }
            card.appendChild(checks);
            card.appendChild(mkEl('div', 'ad-next-why', st === 'idle'
                ? 'Master only once, at the end. Cleaning a mastered file and mastering it again hurts the sound.'
                : 'This is the last pass, so it masters.'));
        }

        // Actions.
        const actions = mkEl('div', 'plan-actions');
        const button = (text, cls, onClick, disabled = false) => {
            const b = mkEl('button', `btn ad-next-btn ${cls}`, text);
            b.type = 'button';
            b.disabled = disabled;
            if (onClick) b.addEventListener('click', onClick);
            actions.appendChild(b);
            return b;
        };
        let hint = '';
        if (st === 'idle') {
            button('Run both passes', 'ready', () => runBothPasses());
            button('Run pass 1 only', 'again', () => runPass(1));
            hint = 'Run both passes sets the settings, cleans, loads the result, applies ' +
                   `${p2.label}${toneState.auto ? ' and the suggested EQ' : ''}, masters, and stops at Download` +
                   (savingTo ? ` (the mastered file is saved to ${folderLabel(savingTo)} as well; pass 1 is not).` : '.');
        } else if (st === 'running1' || st === 'running2' || st === 'loading') {
            button(st === 'loading' ? 'Loading…' : `Running pass ${st === 'running1' ? 1 : 2}…`, 'ready', null, true);
            if (p.auto) button('Stop after this pass', 'again', () => { p.auto = false; renderPassPlan(); });
            hint = p.auto ? 'Running on its own. The processing window stays up between the passes and counts pass 2 in.' : '';
        } else if (st === 'done1') {
            button(`Continue: run pass 2 with ${p2.label}`, 'ready', async () => {
                if (await bridgeToPass2()) await runPass(2);
            });
            button('Load the result, don\u2019t run yet', 'again', () => loadPass1Result());
            button('Run pass 1 again', 'again', () => runPass(1));
            hint = 'Continue loads pass 1\u2019s result here, applies the pass-2 preset, turns mastering on, counts 3-2-1 and runs it.';
        } else if (st === 'loaded2') {
            button(`Run pass 2: ${p2.label} (Clean & Master)`, 'ready', () => runPass(2));
            button('Analyze this result first', 'again', () => autoBtn.click());
            hint = 'This applies the preset and runs the final pass on this file.';
        } else if (st === 'done2') {
            button('Download the mastered file', 'ready', () => downloadLink.click());
            button('Run pass 2 again', 'again', () => runPass(2));
            hint = 'Both passes are done. The What changed chart and the numbers below cover pass 2.';
        }
        card.appendChild(actions);
        if (hint) card.appendChild(mkEl('div', 'ad-next-after', hint));

        if (old) old.replaceWith(card); else planHost.appendChild(card);
        syncNextStep = () => renderPassPlan();
    }

    // ═══════════════════════════════════════════════════════════════════
    // Tone step: the suggested EQ. The server measures the track, judges
    // it after the chosen preset's cleaning (and after the mastering tone
    // match when mastering is on), and returns a short plan. Here it is
    // shown verdict first, applied to the EQ on request or automatically
    // on the final pass, and re-planned when the family changes.
    // ═══════════════════════════════════════════════════════════════════
    const TYPE_LABELS = {
        bell: 'Bell', low_shelf: 'Low shelf', high_shelf: 'High shelf',
        highpass: 'High-pass', lowpass: 'Low-pass', notch: 'Notch',
    };
    const fmtHz = (f) => (f >= 1000
        ? `${(f / 1000).toFixed(f % 1000 ? 1 : 0)} kHz`
        : `${Math.round(f)} Hz`);
    const signed = (v, digits = 1) => `${v > 0 ? '+' : ''}${v.toFixed(digits)}`;

    function analyzeExtras() {
        return {
            tone_family: toneState.family,
            mastering: JSON.stringify(masteringPayload()),
            overrides: JSON.stringify(controls.getValues()),
        };
    }

    function toneTileText(plan) {
        if (!plan || plan.error) return 'Not planned';
        const n = (plan.moves || []).length;
        return n ? `${n} move${n === 1 ? '' : 's'} · ${plan.family_label}` : `Inside ${plan.family_label}`;
    }
    function toneTileTone(plan) {
        if (!plan || plan.error) return 'grey';
        return (plan.moves || []).length ? 'cyan' : 'green';
    }
    function updateToneTile(plan) {
        const t = document.querySelector('.ad-tile.tone');
        if (!t) return;
        t.className = `ad-tile tone ${toneTileTone(plan)}`;
        t.querySelector('.t-value').textContent = toneTileText(plan);
    }

    function fillFamilySelect(sel, current) {
        sel.innerHTML = '';
        const list = toneFamilies.length ? toneFamilies : [{ key: 'neutral', label: 'Neutral' }];
        list.forEach((f) => {
            const o = mkEl('option', null, f.label);
            o.value = f.key;
            if (f.blurb) o.title = f.blurb;
            sel.appendChild(o);
        });
        sel.value = current || 'neutral';
        if (sel.value !== (current || 'neutral')) sel.value = 'neutral';
    }

    function renderTonePlan(plan, ctx = {}) {
        lastTonePlan = plan;
        renderToneStrip();
        const moves = Array.isArray(plan.moves) ? plan.moves : [];
        const card = mkEl('div', 'tone-card');

        const head = mkEl('div', 'tone-head');
        head.appendChild(mkEl('div', 'ad-next-kicker', 'Suggested EQ'));
        const famWrap = mkEl('label', 'tone-family-wrap');
        famWrap.append(mkEl('span', 'tf-label', 'Family'));
        const fam = mkEl('select', 'select tone-family');
        fam.title = 'Genre family: how far from neutral the balance may sit before a move is worth making. A tolerance, not a target. Nothing is guessed.';
        fillFamilySelect(fam, plan.family);
        fam.addEventListener('change', () => {
            toneState.family = fam.value;
            pushSettings();
            replanTone();
        });
        famWrap.appendChild(fam);
        const autoWrap = mkEl('label', 'tone-auto');
        const autoIn = mkEl('input');
        autoIn.type = 'checkbox';
        autoIn.checked = toneState.auto;
        autoIn.title = 'On: the plan goes into the EQ on the final pass by itself (single pass now, pass 2 of a two-pass plan). Off: use Apply to EQ when you want it.';
        autoIn.addEventListener('change', () => {
            toneState.auto = autoIn.checked;
            pushSettings();
            if (autoIn.checked && !ctx.followUp && moves.length) applyTonePlan();
            syncToneCards();
        });
        autoWrap.append(autoIn, mkEl('span', null, 'Use on the final pass'));
        head.append(famWrap, autoWrap);
        card.appendChild(head);

        const verdict = (plan.verdict || (moves.length
            ? `${moves.length} move${moves.length === 1 ? '' : 's'} suggested`
            : 'No EQ needed')).replace(/\.$/, '');
        card.appendChild(mkEl('div', 'tone-title', verdict));
        const why = plan.why || (moves.length ? (plan.summary || '') : `Every region sits inside the ${plan.family_label} range.`);
        card.appendChild(mkEl('div', 'tone-summary', why));
        const stateLine = mkEl('div', 'tone-applied-state');
        card.appendChild(stateLine);
        const syncStateLine = () => {
            const st = toneApplyState(moves, ctx);
            stateLine.textContent = st.text;
            stateLine.className = `tone-applied-state ${st.kind}`;
            stateLine.hidden = !st.text;
        };
        card._syncToneState = syncStateLine;
        syncStateLine();

        // Six regions: where the track sits against the family range.
        const regions = mkEl('div', 'tone-regions');
        (plan.regions || []).forEach((r) => {
            const reg = mkEl('div', `tone-region ${r.status}`);
            reg.appendChild(mkEl('div', 'tr-label', r.label));
            const bar = mkEl('div', 'tr-bar');
            const span = Math.max((r.tol_db || 0) + 4, 6);
            const pct = (v) => 50 + 50 * Math.max(-1, Math.min(1, v / span));
            const band = mkEl('div', 'tr-band');
            band.style.left = `${pct(-r.tol_db)}%`;
            band.style.right = `${100 - pct(r.tol_db)}%`;
            bar.appendChild(band);
            bar.appendChild(mkEl('div', 'tr-center'));
            if (r.status !== 'n/a') {
                const mark = mkEl('div', 'tr-mark');
                mark.style.left = `${pct(r.dev_db)}%`;
                bar.appendChild(mark);
                if (r.dev_after_db != null && Math.abs(r.dev_after_db - r.dev_db) > 0.05) {
                    const after = mkEl('div', 'tr-mark after');
                    after.style.left = `${pct(r.dev_after_db)}%`;
                    bar.appendChild(after);
                }
            }
            reg.appendChild(bar);
            const val = r.status === 'n/a' ? 'above cutoff' : `${signed(r.dev_db)} dB`;
            reg.appendChild(mkEl('div', 'tr-val', val));
            const lo = fmtHz(r.lo_hz), hi = fmtHz(r.hi_hz);
            reg.title = r.status === 'n/a'
                ? `${r.label} (${lo}–${hi}): nothing real above the render's cutoff`
                : `${r.label} (${lo}–${hi}): ${val} from the ${plan.family_label} center · range ±${r.tol_db} dB` +
                  (r.dev_after_db != null ? ` · after the plan ${signed(r.dev_after_db)} dB` : '');
            regions.appendChild(reg);
        });
        card.appendChild(regions);

        if (moves.length) {
            const list = mkEl('div', 'tone-moves');
            moves.forEach((m) => {
                const row = mkEl('label', `tone-move ${m.layer}${m.enabled === false ? ' off' : ''}`);
                const cb = mkEl('input');
                cb.type = 'checkbox';
                cb.checked = m.enabled !== false;
                cb.addEventListener('change', () => {
                    m.enabled = cb.checked;
                    row.classList.toggle('off', !cb.checked);
                    if (toneApplied) applyTonePlan(); else renderToneStrip();
                });
                row.append(cb,
                    mkEl('span', 'tm-pill', m.layer === 'fix' ? 'Fix' : 'Shape'),
                    mkEl('span', 'tm-spec', `${TYPE_LABELS[m.type] || m.type} ${fmtHz(m.freq_hz)}`),
                    mkEl('span', `tm-gain ${m.gain_db < 0 ? 'cut' : 'boost'}`, `${signed(m.gain_db)} dB`),
                    mkEl('span', 'tm-q', `Q ${m.q}`),
                    mkEl('div', 'tm-reason', m.reason || ''));
                list.appendChild(row);
            });
            card.appendChild(list);
        }

        const foot = mkEl('div', 'tone-foot');
        if (moves.length) {
            const amountWrap = mkEl('label', 'tone-amount');
            const amount = mkEl('input');
            amount.type = 'range';
            amount.min = '25'; amount.max = '125'; amount.step = '5';
            amount.value = String(Math.round(toneState.amount * 100));
            const amountVal = mkEl('span', 'tone-amount-val', `${amount.value}%`);
            amount.addEventListener('input', () => {
                toneState.amount = Number(amount.value) / 100;
                amountVal.textContent = `${amount.value}%`;
                if (toneApplied) applyTonePlan(); else renderToneStrip();
            });
            amount.addEventListener('change', () => pushSettings());
            amountWrap.append(mkEl('span', 'ta-label', 'Amount'), amount, amountVal);
            const apply = mkEl('button', 'btn ad-next-btn tone-apply',
                ctx.followUp && toneState.auto ? 'Apply to EQ now, for this pass' : 'Apply to EQ');
            apply.type = 'button';
            const remove = mkEl('button', 'btn btn-ghost btn-sm tone-remove', 'Remove from EQ');
            remove.type = 'button';
            const state = mkEl('span', 'tone-state');
            const syncBtns = () => {
                const on = toneApplied;
                apply.hidden = on;
                remove.hidden = !on;
                state.textContent = on ? '✓ In the EQ · fine-tune it in the EQ panel' : '';
            };
            apply.addEventListener('click', () => applyTonePlan());
            remove.addEventListener('click', () => removeTonePlan());
            card._syncTone = syncBtns;
            syncBtns();
            foot.append(amountWrap, apply, remove, state);
        }
        const v = plan.verify || {};
        if (v.lufs_before != null && v.lufs_after != null && moves.length) {
            const dl = v.lufs_after - v.lufs_before;
            const dp = (v.tp_after ?? 0) - (v.tp_before ?? 0);
            const tail = v.limiter_safe
                ? 'limiter safe'
                : `the limiter works about ${(v.plr_shift_db ?? 0).toFixed(1)} dB harder`;
            foot.appendChild(mkEl('div', 'tone-verify',
                `Checked on the loudest ${Math.round(v.excerpt_s || 20)} s at ${fmtTime(v.excerpt_start_s || 0)}: ` +
                `loudness ${signed(dl)} dB, peaks ${signed(dp)} dB, ${tail}.` +
                (v.boosts_dropped ? ' Boosts were dropped to keep peaks in check.'
                    : v.boosts_scaled ? ' Boosts were halved to keep peaks in check.' : '')));
        }
        const basis = [];
        if (plan.analysis && plan.analysis.cleaning_applied) {
            basis.push(`judged after ${plan.preset_label || 'the preset'} cleaning on the loudest part`);
        }
        if (plan.mastering_on) basis.push('mastering tone match taken into account');
        if (basis.length) foot.appendChild(mkEl('div', 'tone-basis', basis.join(' · ')));
        const stale = mkEl('div', 'tone-stale');
        stale.hidden = true;
        const replan = mkEl('button', 'btn btn-ghost btn-sm', 'Re-plan for the current settings');
        replan.type = 'button';
        replan.addEventListener('click', () => replanTone());
        stale.append(mkEl('span', null, 'Settings changed since this plan. '), replan);
        foot.appendChild(stale);
        card.appendChild(foot);
        return card;
    }

    // What the plan's status is, in one sentence. `ctx.followUp` means a
    // second pass is planned, so this run is pass 1 and stays EQ-free.
    function toneApplyState(moves, ctx = {}) {
        if (!moves || !moves.length) return { kind: 'none', text: '' };
        if (toneApplied) return { kind: 'on', text: '\u2713 In the EQ for this run. Fine-tune it in the EQ card.' };
        if (toneState.auto && ctx.followUp) {
            return { kind: 'held', text: 'Held for pass 2. This run is pass 1, cleaning only; the plan is ' +
                'made again on the cleaned file and goes into the EQ by itself when pass 2 runs. ' +
                'Running only this one pass? Use Apply.' };
        }
        if (toneState.auto) return { kind: 'pending', text: 'Goes into the EQ on the final pass by itself.' };
        return { kind: 'off', text: 'Not in the EQ. Use Apply, or turn on Use on the final pass.' };
    }
    function toneStripState(moves) {
        if (!moves.length) return null;
        if (toneApplied) return { text: '\u2713 In the EQ below', cls: 'on' };
        const held = toneState.auto && !!(lastFollowUp && !priorPassPreset && !(passPlan && passPlan.status === 'loaded2'));
        if (held) return { text: 'Held for pass 2 \u00b7 applied by itself when it runs', cls: 'held' };
        if (toneState.auto) return { text: 'Applied on the final pass', cls: 'pending' };
        return { text: 'Not in the EQ', cls: 'off' };
    }

    function maybeAutoApplyTone(plan, followUp) {
        // Auto-apply only on a final pass: with a second pass ahead, pass 1
        // stays EQ-free and pass 2 plans its own on the cleaned file.
        if (!toneState.auto || followUp) return;
        if (plan && Array.isArray(plan.moves) && plan.moves.length) applyTonePlan();
    }

    function toneBandsNow() {
        if (!lastTonePlan || !Array.isArray(lastTonePlan.moves)) return [];
        return lastTonePlan.moves.filter((m) => m.enabled !== false).map((m) => ({
            type: m.type,
            freq_hz: Math.round(m.freq_hz * 100) / 100,
            gain_db: Math.round(m.gain_db * toneState.amount * 100) / 100,
            q: Math.round(m.q * 1000) / 1000,
            enabled: true,
            source: 'tone',
        }));
    }
    function userEqBands() {
        const cur = eqPanel.getPayload();
        return { enabled: cur.enabled, bands: cur.bands.filter((b) => b.source !== 'tone') };
    }
    function syncToneCards() {
        document.querySelectorAll('.tone-card').forEach((c) => {
            if (c._syncTone) c._syncTone();
            if (c._syncToneState) c._syncToneState();
        });
        renderToneStrip();
        if (syncNextStep) syncNextStep();
    }
    function applyTonePlan() {
        const bands = toneBandsNow();
        const user = userEqBands();
        eqPanel.setPayload({
            enabled: bands.length > 0 || (user.enabled && user.bands.length > 0),
            bands: user.bands.concat(bands).slice(0, 12),
        });
        toneAppliedBands = bands;
        toneApplied = true;
        afterEqChange();
        syncToneCards();
    }
    function removeTonePlan() {
        if (!toneApplied) return;
        const user = userEqBands();
        eqPanel.setPayload({ enabled: user.enabled && user.bands.length > 0, bands: user.bands });
        toneAppliedBands = [];
        toneApplied = false;
        afterEqChange();
        syncToneCards();
    }

    // The strip in the EQ card: the plan's verdict, apply/remove, family
    // and the final-pass switch, next to the editor the bands land in.
    function renderToneStrip() {
        if (!toneStrip) return;
        toneStrip.innerHTML = '';
        const plan = lastTonePlan;
        const moves = plan && Array.isArray(plan.moves) ? plan.moves : [];
        const head = mkEl('div', 'ts-head');
        head.appendChild(mkEl('span', 'ts-kicker', 'Suggested EQ'));
        if (!plan) {
            head.appendChild(mkEl('span', 'ts-text muted', currentFile
                ? 'Run Analyze to plan it for this track.'
                : 'Planned by Analyze for each track.'));
            toneStrip.appendChild(head);
            toneStrip.classList.toggle('empty', true);
            return;
        }
        toneStrip.classList.toggle('empty', false);
        const on = moves.filter((m) => m.enabled !== false).length;
        const text = moves.length
            ? `${on} of ${moves.length} move${moves.length === 1 ? '' : 's'} · ${plan.family_label}`
            : `None needed · inside the ${plan.family_label} range`;
        head.appendChild(mkEl('span', 'ts-text', text));
        if (moves.length) {
            const brief = moves.filter((m) => m.enabled !== false).map((m) =>
                `${TYPE_LABELS[m.type] || m.type} ${fmtHz(m.freq_hz)} ${signed(m.gain_db * toneState.amount)}`).join(' · ');
            head.appendChild(mkEl('span', 'ts-brief', brief));
        }
        toneStrip.appendChild(head);
        const row = mkEl('div', 'ts-row');
        if (moves.length) {
            const st = toneStripState(moves);
            if (st) row.appendChild(mkEl('span', `ts-state ${st.cls}`, st.text));
            if (toneApplied) {
                const remove = mkEl('button', 'btn btn-ghost btn-sm', 'Remove');
                remove.type = 'button';
                remove.addEventListener('click', () => removeTonePlan());
                row.appendChild(remove);
            } else {
                const apply = mkEl('button', 'btn btn-sm ts-apply', st && st.cls === 'held' ? 'Apply now' : 'Apply to EQ');
                apply.type = 'button';
                apply.addEventListener('click', () => applyTonePlan());
                row.appendChild(apply);
            }
        }
        const famWrap = mkEl('label', 'tone-family-wrap');
        famWrap.append(mkEl('span', 'tf-label', 'Family'));
        const fam = mkEl('select', 'select tone-family');
        fillFamilySelect(fam, toneState.family);
        fam.addEventListener('change', () => {
            toneState.family = fam.value;
            pushSettings();
            replanTone();
        });
        famWrap.appendChild(fam);
        const autoWrap = mkEl('label', 'tone-auto');
        const autoIn = mkEl('input');
        autoIn.type = 'checkbox';
        autoIn.checked = toneState.auto;
        autoIn.title = 'On: the plan goes into the EQ on the final pass by itself. Off: use Apply when you want it.';
        autoIn.addEventListener('change', () => {
            toneState.auto = autoIn.checked;
            pushSettings();
            syncToneCards();
        });
        autoWrap.append(autoIn, mkEl('span', null, 'Use on the final pass'));
        row.append(famWrap, autoWrap);
        toneStrip.appendChild(row);
        const seeIt = mkEl('button', 'btn btn-ghost btn-sm ts-jump', 'See why');
        seeIt.type = 'button';
        seeIt.title = 'Jump to the plan in the Analysis card: regions, reasons, the check on the loudest part.';
        seeIt.addEventListener('click', () => {
            const card = document.querySelector('.tone-card');
            if (card) { card.scrollIntoView({ behavior: 'smooth', block: 'center' }); card.classList.add('flash'); setTimeout(() => card.classList.remove('flash'), 1200); }
        });
        row.appendChild(seeIt);
    }

    // Each right-pane section says its state in the summary line, so the
    // pane reads at a glance even when the sections are closed.
    function syncInspectorStates() {
        const eq = eqPanel.getPayload();
        if (stateEls.eq) {
            const n = eq.bands.filter((b) => b.enabled !== false).length;
            stateEls.eq.textContent = !eq.enabled || n === 0 ? 'off'
                : `${n} band${n === 1 ? '' : 's'}${toneApplied ? ' · suggested' : ''}`;
        }
        if (stateEls.master) {
            if (!masterEnabled.checked) {
                stateEls.master.textContent = 'off';
            } else {
                const opt = masterTarget.options[masterTarget.selectedIndex];
                const t = opt ? opt.text : '';
                const short = t.includes('(') ? t.slice(t.indexOf('(') + 1, t.indexOf(')')) : t;
                const iOpt = masterIntensity.options[masterIntensity.selectedIndex];
                const intensity = iOpt ? iOpt.text.split(' ')[0] : '';
                stateEls.master.textContent = `${short} · match ${intensity.toLowerCase()}`;
            }
        }
        if (stateEls.output) {
            const fv = outputFormat.value;
            const f = fv === 'wav16' ? 'WAV 16-bit · 44.1 kHz' : fv.toUpperCase();
            const bits = fv === 'wav' || fv === 'flac' ? ' 24-bit' : '';
            const saving = activeSaveFolder() ? ' · saves to folder' : '';
            stateEls.output.textContent = `${f}${bits}${trimSilence.checked ? ' · trim' : ''}${saving}`;
        }
        if (stateEls.tags) {
            const t = tagsDefaults();
            stateEls.tags.textContent = !t.enabled ? 'off' : (t.artist || 'on');
        }
    }
    function afterEqChange() {
        pushSettings();
        previewCache.clear();
        if (previewState.active) schedulePreviewRender();
    }

    async function replanTone() {
        if (!currentFile) return null;
        const cards = Array.from(document.querySelectorAll('.tone-card'));
        cards.forEach((c) => c.classList.add('busy'));
        try {
            const r = await fetchTonePlan(currentFile, {
                preset: presetSelect.value,
                preset_strength: currentStrength(),
                tone_family: toneState.family,
                mastering: JSON.stringify(masteringPayload()),
                repair: JSON.stringify(repairPayload() || {}),
                overrides: JSON.stringify(controls.getValues()),
            });
            const plan = r.tone_plan;
            const wasApplied = toneApplied;
            const ctx = { followUp: (lastFollowUp && !priorPassPreset && !(passPlan && passPlan.status === 'loaded2')) ? lastFollowUp : null };
            const fresh = renderTonePlan(plan, ctx);
            const live = Array.from(document.querySelectorAll('.tone-card'));
            if (live.length) {
                live[0].replaceWith(fresh);
                live.slice(1).forEach((c) => c.remove());
            }
            if (wasApplied) applyTonePlan();
            updateToneTile(plan);
            return plan;
        } catch (e) {
            document.querySelectorAll('.tone-card.busy').forEach((c) => c.classList.remove('busy'));
            showAutoDetectError(`Tone plan failed: ${e.message}`);
            return null;
        }
    }
    function markToneStale() {
        document.querySelectorAll('.tone-card .tone-stale').forEach((el) => { el.hidden = false; });
    }
    [masterEnabled, masterIntensity, masterTilt, presetSelect].forEach((el) => {
        el.addEventListener('change', markToneStale);
    });
    [masterEnabled, masterTarget, masterIntensity, outputFormat, trimSilence].forEach((el) => {
        el.addEventListener('change', syncInspectorStates);
    });
    strengthEl.addEventListener('change', markToneStale);

    // ── Tags: title from the file, defaults from the user ─────────────
    function titleFromName(name) {
        let stem = (name || '').replace(/\.[^.]+$/, '');
        for (let guard = 0; guard < 6; guard++) {
            const m = /^(.*)_(processed|trimmed)_[0-9a-f]{8}$/i.exec(stem);
            if (!m) break;
            const before = m[1];
            let best = null;
            for (const key of byName.keys()) {
                if (before.toLowerCase().endsWith('_' + key) && (!best || key.length > best.length)) best = key;
            }
            stem = best ? before.slice(0, before.length - key_len(best) - 1) : before;
        }
        return stem.replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
    }
    const key_len = (k) => k.length;
    function resetTagsForFile(file) {
        if (!tagTitle) return;
        tagTitle.dataset.user = '0';
        tagTitle.value = titleFromName(file.name);
        if (tagTitleHint) tagTitleHint.textContent = 'From the filename. Edit it if the real title differs.';
        if (tagFields.track) tagFields.track.value = '';
        Object.values(tagFields).forEach((el) => { if (el) el.placeholder = ''; });
    }
    function prefillTags(source, hint) {
        if (!tagTitle) return;
        const src = source || {};
        if (tagTitle.dataset.user !== '1') {
            const auto = src.title || hint || (currentFile ? titleFromName(currentFile.name) : '');
            if (auto) tagTitle.value = auto;
            if (tagTitleHint) {
                tagTitleHint.textContent = src.title
                    ? "From the file's own tags."
                    : 'From the filename. Edit it if the real title differs.';
            }
        }
        for (const [key, el] of Object.entries(tagFields)) {
            if (!el) continue;
            if (src[key]) el.placeholder = `${src[key]} (from the file)`;
        }
        if (tagFields.track && !tagFields.track.value && src.track) tagFields.track.value = src.track;
    }
    if (tagTitle) {
        tagTitle.addEventListener('input', () => {
            tagTitle.dataset.user = tagTitle.value.trim() ? '1' : '0';
        });
    }
    function tagsDefaults() {
        const g = (el) => (el ? el.value.trim() : '');
        return {
            enabled: !tagsEnabled || tagsEnabled.checked,
            artist: g(tagFields.artist), album_artist: g(tagFields.album_artist),
            album: g(tagFields.album), genre: g(tagFields.genre), year: g(tagFields.year),
            copyright: g(tagFields.copyright), isrc: g(tagFields.isrc),
            keep: !tagsKeep || tagsKeep.checked,
            notes: !tagsNotes || tagsNotes.checked,
        };
    }
    function tagsPayload() {
        const d = tagsDefaults();
        return {
            enabled: d.enabled,
            title: tagTitle ? tagTitle.value.trim() : '',
            track: tagFields.track ? tagFields.track.value.trim() : '',
            artist: d.artist, album_artist: d.album_artist, album: d.album,
            genre: d.genre, year: d.year, copyright: d.copyright, isrc: d.isrc,
            mode: d.keep ? 'fill' : 'overwrite',
            notes: d.notes,
        };
    }
    function restoreTagsDefaults(t) {
        if (!t) return;
        if (tagsEnabled && typeof t.enabled === 'boolean') tagsEnabled.checked = t.enabled;
        for (const key of ['artist', 'album_artist', 'album', 'genre', 'year', 'copyright', 'isrc']) {
            if (tagFields[key] && typeof t[key] === 'string') tagFields[key].value = t[key];
        }
        if (tagsKeep && typeof t.keep === 'boolean') tagsKeep.checked = t.keep;
        if (tagsNotes && typeof t.notes === 'boolean') tagsNotes.checked = t.notes;
    }
    [tagsEnabled, tagsKeep, tagsNotes, ...Object.values(tagFields)].forEach((el) => {
        if (!el) return;
        el.addEventListener('change', () => pushSettings());
    });

    function renderAutoDetect(r) {
        autoDetectResults.hidden = false;
        autoDetectResults.innerHTML = '';
        syncNextStep = null;

        const ranked = Array.isArray(r.ranked) ? r.ranked : [];
        if (ranked.length === 0) {
            const note = document.createElement('div');
            note.className = 'ad-reason';
            note.textContent = 'No artifact detected; safe defaults will do.';
            autoDetectResults.appendChild(note);
            if (r.tone_plan && !r.tone_plan.error) {
                const main = document.createElement('div');
                main.className = 'ad-main';
                main.appendChild(renderTonePlan(r.tone_plan, { followUp: null }));
                autoDetectResults.appendChild(main);
                maybeAutoApplyTone(r.tone_plan, null);
            }
            return;
        }

        const el = (tag, cls, text) => {
            const e = document.createElement(tag);
            if (cls) e.className = cls;
            if (text != null) e.textContent = text;
            return e;
        };
        const matches = ranked.slice(0, 6);
        const followUp = (r.follow_up && r.follow_up.name) ? r.follow_up : null;
        const notches = (r.repair_plan && Array.isArray(r.repair_plan.notches))
            ? r.repair_plan.notches.length : 0;
        const cutoffHz = Number(r.evidence && r.evidence.cutoff_hz) || 0;
        const pctOf = (v) => `${Math.round((Number.isFinite(v) ? v : 1) * 100)}%`;
        const nameOf = (m) => m.label || labelOf(m.name);

        // Status tiles (workspace only).
        const tiles = el('div', 'ad-tiles');
        const tile = (label, value, tone) => {
            const t = el('div', `ad-tile ${tone}`);
            t.append(el('div', 't-label', label), el('div', 't-value', value));
            tiles.appendChild(t);
            return t;
        };
        const appliedTile = tile('Applied', '', 'amber');
        tile('Second pass',
            followUp ? `Recommended · ${nameOf(followUp)}` : 'Not needed',
            followUp ? 'orange' : 'green');
        tile('Fixed tones',
            notches ? `${notches} notched first` : 'None found',
            notches ? 'cyan' : 'green');
        tile('Top end',
            cutoffHz > 0 ? `Stops at ${(cutoffHz / 1000).toFixed(1)} kHz` : 'Full range',
            'grey');
        const toneTile = tile('Suggested EQ', toneTileText(r.tone_plan), toneTileTone(r.tone_plan));
        toneTile.classList.add('tone');

        // Hero + table. Re-rendered whenever Apply moves the choice, so
        // the highlight follows the state, never the position.
        const main = el('div', 'ad-main');
        const hero = el('div', 'ad-hero');
        const othersLabel = el('div', 'ad-others-label', 'Other matches');
        const table = el('div', 'ad-table');
        main.append(hero, othersLabel, table);

        let applied = 0;
        const renderMain = () => {
            const m = matches[applied];
            hero.innerHTML = '';
            const top = el('div', 'ad-hero-top');
            const strength = el('div', 'ad-hero-strength');
            strength.append(el('span', 'v', pctOf(m.strength)), el('span', 'k', 'strength'));
            top.append(el('div', 'ad-hero-name', nameOf(m)),
                       el('span', 'ad-hero-pill', 'Applied'), strength);
            const conf = el('div', 'ad-hero-conf');
            const bar = el('div', 'ad-confidence');
            const fill = el('div', 'ad-confidence-fill');
            fill.style.width = pctOf(m.confidence || 0);
            bar.appendChild(fill);
            conf.append(bar, el('span', 'ad-confidence-pct', `${pctOf(m.confidence || 0)} match`));
            hero.append(top, conf);
            if (m.reason) hero.appendChild(el('div', 'ad-hero-reason', m.reason));
            appliedTile.querySelector('.t-value').textContent =
                `${nameOf(m)} · ${pctOf(m.strength)}`;

            table.innerHTML = '';
            matches.forEach((entry, i) => {
                if (i === applied) return;
                const row = el('div', 'ad-row');
                row.title = entry.reason || '';
                const bar2 = el('div', 'ad-confidence');
                const fill2 = el('div', 'ad-confidence-fill');
                fill2.style.width = pctOf(entry.confidence || 0);
                bar2.appendChild(fill2);
                const btn = el('button', 'btn btn-ghost ad-apply-btn', 'Apply');
                btn.type = 'button';
                btn.addEventListener('click', () => {
                    applied = i;
                    applyDetectedPreset(entry.name,
                        Number.isFinite(entry.strength) ? entry.strength : 1.0);
                    renderMain();
                    setAnalyzeDock('done', `${nameOf(entry)} ${pctOf(entry.strength)}`);
                    syncDockStatus();
                });
                row.append(el('span', 'ad-row-rank', String(i + 1)),
                           el('span', 'ad-row-name', nameOf(entry)),
                           bar2, el('span', 'ad-row-strength', pctOf(entry.strength)), btn);
                table.appendChild(row);
            });
            const none = table.childElementCount === 0;
            othersLabel.hidden = none;
            table.hidden = none;
            if (syncNextStep) syncNextStep();
        };
        renderMain();

        // Tone: the suggested EQ, judged after this preset's cleaning.
        if (r.tone_plan && !r.tone_plan.error) {
            main.appendChild(renderTonePlan(r.tone_plan, { followUp }));
            maybeAutoApplyTone(r.tone_plan, followUp);
        } else if (r.tone_plan && r.tone_plan.error) {
            main.appendChild(el('div', 'ad-reason', `Tone plan skipped: ${r.tone_plan.error}`));
        }

        // Side: next step (second pass) and details.
        const side = el('div', 'ad-side');
        if (followUp) {
            ensurePlan(followUp);
            renderPassPlan(side);
        } else if (passPlan && passPlan.status !== 'idle') {
            // Mid-plan (a loaded pass-1 result) and Analyze found nothing
            // further: keep the plan card so the flow can finish.
            renderPassPlan(side);
        } else {
            // Say so, rather than leaving a gap where the plan would be.
            const one = el('div', 'ad-single');
            one.append(el('div', 'ad-next-kicker', 'One pass'),
                       el('div', 'ad-single-text',
                          'One pass is enough. Analyze tried the runner-ups on the cleaned ' +
                          'result and none of them found more worth removing. Clean & Master ' +
                          'runs the applied preset and masters in one go.'));
            side.appendChild(one);
        }
        const notes = Array.isArray(r.notes) ? r.notes : [];
        if (notes.length) {
            const details = el('div', 'ad-details');
            details.appendChild(el('div', 'ad-details-label', 'Details'));
            notes.forEach((t) => details.appendChild(el('div', 'ad-detail', t)));
            side.appendChild(details);
        }

        autoDetectResults.append(tiles, main);
        if (side.childElementCount > 0) autoDetectResults.appendChild(side);

        const tl = r.timeline && Array.isArray(r.timeline.intensity)
            ? r.timeline.intensity : [];
        if (tl.length > 0) {
            const stepS = (r.timeline.step_s > 0) ? r.timeline.step_s : 1;
            const totalS = tl.length * stepS;
            const wrap = document.createElement('div');
            wrap.className = 'ad-timeline-wrap';

            // Caption row: title left, colour key right. Sits above the
            // strip so it never runs through the bars.
            const head = document.createElement('div');
            head.className = 'ad-timeline-head';
            const title = document.createElement('span');
            title.className = 'ad-timeline-title';
            title.textContent = 'Noise over time';
            const key = document.createElement('span');
            key.className = 'ad-timeline-key';
            const hotSw = document.createElement('i'); hotSw.className = 'sw hot';
            const coolSw = document.createElement('i'); coolSw.className = 'sw cool';
            key.append(hotSw, ' worst stretches ', coolSw,
                ' quieter · Live loop starts at the worst stretch · click to jump');
            head.append(title, key);

            const strip = document.createElement('div');
            strip.className = 'ad-timeline';
            for (let i = 0; i < tl.length; i++) {
                const v = tl[i];
                const bar = document.createElement('div');
                bar.className = 'ad-timeline-bar';
                if (v >= 0.4) bar.classList.add('hot');
                bar.style.height = `${Math.max(4, Math.round(v * 100))}%`;
                bar.title = `${fmtTime(i * stepS)} · noise ${(v * 100).toFixed(0)}%`;
                strip.appendChild(bar);
            }
            // One listener for the whole strip: the click position maps
            // to a time on the track.
            strip.addEventListener('click', (ev) => {
                const rect = strip.getBoundingClientRect();
                if (rect.width <= 0) return;
                const frac = (ev.clientX - rect.left) / rect.width;
                jumpToTime(Math.max(0, Math.min(totalS, frac * totalS)));
            });

            // Time axis: start, quarter marks, end.
            const axis = document.createElement('div');
            axis.className = 'ad-timeline-axis';
            for (let q = 0; q <= 4; q++) {
                const tick = document.createElement('span');
                tick.textContent = fmtTime(totalS * q / 4);
                axis.appendChild(tick);
            }

            wrap.append(head, strip, axis);
            autoDetectResults.appendChild(wrap);
        }
    }

    // Timeline click: with Live on, move the loop window there (manual
    // anchor, same as "Set from playhead"); otherwise seek the player.
    function jumpToTime(t) {
        if (previewState.active) {
            previewState.anchorMode = 'manual';
            previewState.anchorS = t;
            doPreviewRender();
        } else {
            player.seek(t);
        }
    }

    autoBtn.addEventListener('click', async () => {
        if (!currentFile) {
            showAutoDetectError('Select a file first.');
            return;
        }
        const originalLabel = autoBtn.textContent;
        autoBtn.textContent = 'Analyzing…';
        autoBtn.disabled = true;
        setAnalyzeDock('busy');
        const busyEl = $('analysis-busy');
        const hintEl = $('analysis-hint');
        if (busyEl) busyEl.hidden = false;
        if (hintEl) hintEl.hidden = true;
        let done = false;
        try {
            const r = await runAutoDetect(currentFile, analyzeExtras());
            lastFollowUp = (r.follow_up && r.follow_up.name) ? r.follow_up : null;
            if (r.repair_plan) setRepairPlan(r.repair_plan);
            if (r.findings) picker.setFindings(r.findings);
            applyDetectedPreset(r.preset, r.strength);
            renderAutoDetect(r);
            const pct = Math.round((Number(r.strength) || 1) * 100);
            setAnalyzeDock('done', `${labelOf(r.preset)} ${pct}%`);
            done = true;
            if (r.timeline && Array.isArray(r.timeline.intensity) &&
                r.timeline.intensity.length > 0) {
                lastTimeline = r.timeline.intensity;
                // Re-anchor a live loop onto the newly-found hot region.
                if (previewState.active && previewState.anchorMode === 'auto') {
                    schedulePreviewRender();
                }
            }
            if (r.analysis) {
                lastAnalysis = r.analysis;
                renderAnalysisReadout(r.analysis);
                eqPanel.refreshSpectrum();
            }
            if (r.source_tags) prefillTags(r.source_tags, null);
            setWizardStep(1);
        } catch (e) {
            showAutoDetectError(`Analyze failed: ${e.message}`);
        } finally {
            autoBtn.textContent = originalLabel;
            autoBtn.disabled = false;
            if (busyEl) busyEl.hidden = true;
            if (hintEl && !done) hintEl.hidden = false;
            if (!done) setAnalyzeDock('idle');
        }
    });

    // ── Persistence wiring ────────────────────────────────────────────
    // Always write the current UI (Batch reuses EQ in-session). Restore
    // on next visit only when remember_settings is true.
    // Signal Chain bridge: the chain view asks for the exact state a
    // Clean & Master click would send, so the server renders the chain
    // from real Params instead of a hand-written list.
    window.shimmerChainState = () => {
        const t = trimPanel ? trimPanel.getTrim() : null;
        return {
            preset: presetSelect.value,
            preset_strength: currentStrength(),
            overrides: controls.getValues(),
            mastering: masteringPayload(),
            eq: eqPanel.getPayload(),
            preserve_volume: preserveVol.checked && !masterEnabled.checked,
            trim_silence: trimSilence.checked,
            output_format: outputFormat.value,
            save_folder: activeSaveFolder(),
            trim_armed: !!(t && (t.inS > 0 || t.outS != null)),
            repair: repairPayload(),
        };
    };

    function pushSettings() {
        if (advDrawer && !advDrawer.hidden) syncAdvancedHeader();
        // The Signal Chain view re-renders from live settings on this.
        document.dispatchEvent(new CustomEvent('shimmer:settings-changed'));
        syncDockStatus();
        syncInspectorStates();
        saveSettings({
            remember_settings: !!(rememberSettings && rememberSettings.checked),
            preset: presetSelect.value,
            preset_strength: currentStrength(),
            sliders: controls.getValues(),
            preserve_volume: preserveVol.checked,
            trim_silence: trimSilence.checked,
            output_format: outputFormat.value,
            mastering: masteringPayload(),
            eq: eqPanel.getPayload(),
            ab_loudness_match: abLoudnessMatch.checked,
            downloads: downloadPrefs(),
            tags: tagsDefaults(),
            tone: { family: toneState.family, auto: toneState.auto, amount: toneState.amount },
        });
    }
    preserveVol.addEventListener('change', () => {
        pushSettings();
        schedulePreviewRender();
    });
    trimSilence.addEventListener('change', pushSettings);
    // The Trim card mirrors the export silence-trim setting, so the
    // artifact cut and the floor trim sit together. Two-way sync with
    // the checkbox in Output; one source of truth (#trim-silence).
    const trimSilenceMirror = $('trim-silence-mirror');
    if (trimSilenceMirror) {
        trimSilenceMirror.checked = trimSilence.checked;
        trimSilenceMirror.addEventListener('change', () => {
            trimSilence.checked = trimSilenceMirror.checked;
            trimSilence.dispatchEvent(new Event('change'));
        });
        trimSilence.addEventListener('change', () => {
            trimSilenceMirror.checked = trimSilence.checked;
        });
    }
    if (rememberSettings) {
        rememberSettings.addEventListener('change', pushSettings);
    }
    outputFormat.addEventListener('change', pushSettings);

    // ── Settings · Downloads ──────────────────────────────────────────
    // What the Download step at the end of a run does: start the browser
    // download by itself, or have the server write the file into a
    // folder. Saved with the tags (a preference, not run state).
    function downloadPrefs() {
        return {
            auto: !!(dlAuto && dlAuto.checked),
            location: (dlLocFolder && dlLocFolder.checked) ? 'folder' : 'browser',
            folder: saveFolder ? saveFolder.value.trim() : '',
        };
    }
    // The folder a run saves into, or '' when the location is the
    // browser or no folder is set yet. Everything that mentions saving
    // reads this.
    function activeSaveFolder() {
        const d = downloadPrefs();
        return (d.location === 'folder' && d.folder) ? d.folder : '';
    }
    function folderLabel(path) {
        const p = String(path || '').replace(/[\\/]+$/, '');
        const parts = p.split(/[\\/]/);
        return parts[parts.length - 1] || p;
    }
    function syncDownloadControls() {
        const useFolder = !!(dlLocFolder && dlLocFolder.checked);
        if (saveFolderRow) saveFolderRow.hidden = !useFolder;
        if (!dlState) return;
        const d = downloadPrefs();
        if (d.location === 'folder' && d.folder) {
            dlState.textContent = `Finished files are written to ${d.folder} as the run ends; the Download step offers Show in folder.`
                + (d.auto ? ' A browser download is not needed in this mode, so "download automatically" does nothing here.' : '');
        } else if (d.location === 'folder') {
            dlState.textContent = 'Choose a folder, or the browser download is used.';
        } else {
            dlState.textContent = d.auto
                ? 'Finished files download by themselves to your browser’s Downloads folder.'
                : 'The processing window ends on a Download step; click it to save the file with your browser.';
        }
    }
    async function pickSaveFolder() {
        if (!browseSaveBtn || !saveFolder) return false;
        browseSaveBtn.disabled = true;
        try {
            const path = await browseFolder({
                initialDir: saveFolder.value.trim() || undefined,
                title: 'Save finished files to',
            });
            if (path) saveFolder.value = path;
            return !!path;
        } catch (_) {
            return false;
        } finally {
            browseSaveBtn.disabled = false;
        }
    }
    function afterDownloadPrefsChange() {
        syncDownloadControls();
        pushSettings();
        renderPassPlan();
    }
    if (dlLocFolder) dlLocFolder.addEventListener('change', async () => {
        syncDownloadControls();
        // Choosing "This folder" with no folder yet asks for one right
        // away; a cancelled picker falls back to the browser rather than
        // "a folder, nowhere".
        if (dlLocFolder.checked && saveFolder && !saveFolder.value.trim()) {
            const ok = await pickSaveFolder();
            if (!ok && !saveFolder.value.trim() && dlLocBrowser) dlLocBrowser.checked = true;
        }
        afterDownloadPrefsChange();
    });
    if (dlLocBrowser) dlLocBrowser.addEventListener('change', afterDownloadPrefsChange);
    if (dlAuto) dlAuto.addEventListener('change', afterDownloadPrefsChange);
    if (browseSaveBtn) browseSaveBtn.addEventListener('click', async () => {
        if (await pickSaveFolder()) afterDownloadPrefsChange();
    });
    if (saveFolder) saveFolder.addEventListener('change', afterDownloadPrefsChange);
    // "…is in Settings" pointers elsewhere on the page open the tab.
    document.querySelectorAll('[data-open-tab]').forEach((b) => b.addEventListener('click', () => {
        const tab = document.querySelector(`.tab[data-tab="${b.dataset.openTab}"]`);
        if (tab) tab.click();
    }));
    syncDownloadControls();

    // ── Live preview ──────────────────────────────────────────────────
    // Original keeps the full file; only Processed and Removed loop a
    // small slice that re-renders on every slider change.

    function setPreviewStatus(text, kind = '') {
        previewStatus.textContent = text;
        previewStatus.classList.remove('live', 'error', 'busy');
        if (kind) previewStatus.classList.add(kind);
    }

    async function teardownPreviewSession() {
        if (previewState.renderInflight) {
            try { previewState.renderInflight.abort(); } catch (_) {}
            previewState.renderInflight = null;
        }
        if (previewState.debounceTimer) {
            clearTimeout(previewState.debounceTimer);
            previewState.debounceTimer = null;
        }
        if (previewState.sessionId) {
            const sid = previewState.sessionId;
            previewState.sessionId = null;
            dropSession(sid);  // fire-and-forget
        }
        previewState.durationS = 0;
        previewState.renderPending = false;
    }

    function clampWindow(anchor, windowS, total) {
        if (!Number.isFinite(total) || total <= 0) {
            return {start: 0, end: Math.min(windowS, 1.0)};
        }
        let start = Math.max(0, Math.min(total, anchor));
        let end = start + windowS;
        if (end > total) {
            end = total;
            start = Math.max(0, end - windowS);
        }
        return {start, end};
    }

    // Start time of the max-intensity contiguous window in the Analyze
    // timeline, or null when no timeline exists yet.
    function hottestAnchor(winSec, totalS) {
        if (!lastTimeline || !lastTimeline.length ||
            !Number.isFinite(totalS) || totalS <= 0) return null;
        const binS = totalS / lastTimeline.length;
        const winBins = Math.max(1, Math.round(winSec / binS));
        let sum = 0, bestSum = -Infinity, bestIdx = 0;
        for (let i = 0; i < lastTimeline.length; i++) {
            sum += lastTimeline[i];
            if (i >= winBins) sum -= lastTimeline[i - winBins];
            if (i >= winBins - 1 && sum > bestSum) {
                bestSum = sum;
                bestIdx = i - winBins + 1;
            }
        }
        return bestIdx * binS;
    }

    // `quiet` suppresses the preview status line. The edge scan at file-drop
    // needs a session but is not a preview render, and "Preparing preview…"
    // is only ever cleared by a render completing — so a quiet caller must
    // not set it, or it stays on screen forever.
    async function ensurePreviewSession({quiet = false} = {}) {
        if (previewState.sessionId) return previewState.sessionId;
        if (!currentFile) return null;
        if (!quiet) setPreviewStatus('Preparing preview…', 'busy');
        try {
            const r = await uploadFile(currentFile);
            previewState.sessionId = r.session_id;
            previewState.durationS = r.duration_s;
            // The recents list keys its "stems ready" badge on the digest.
            document.dispatchEvent(new CustomEvent('shimmer:uploaded', { detail: {
                name: currentFile.name, size: currentFile.size,
                digest: r.digest || null, stems_tiers: r.stems_tiers || [],
            } }));
            lastEdges = r.edges || null;
            if (r.repair && r.repair.plan) setRepairPlan(r.repair.plan);
            picker.setFindings(r.findings || []);
            if (r.analysis) {
                lastAnalysis = r.analysis;
                renderAnalysisReadout(r.analysis);
                eqPanel.refreshSpectrum();
            }
            prefillTags(r.source_tags || {}, r.title_hint || null);
            return r.session_id;
        } catch (e) {
            if (!quiet) setPreviewStatus(`Preview failed: ${e.message}`, 'error');
            return null;
        }
    }

    // Install a render (fresh or cached) into the player and refresh the
    // match gains from the slice loudness in its metadata.
    function applyPreviewResult(entry, start, end, region, note) {
        // Toggled off mid-render: don't re-enter the loop (see the abort
        // note in applyPreviewToggle). Abort rejects the fetch, but a render
        // resolving during decode can still land here after Live went off.
        if (!previewState.active) return;
        player.setPreviewBuffers({
            processedBuf: entry.processedBuf,
            removedBuf: entry.removedBuf,
            startS: start,
            endS: end,
        });
        const meta = entry.meta || {};
        previewMatchDb =
            (typeof meta.lufs_processed === 'number' &&
             typeof meta.lufs_original === 'number')
                ? meta.lufs_processed - meta.lufs_original : null;
        applyLoudnessMatch();
        setPreviewStatus(`Live · loop ${region} · ${note}`, 'live');
    }

    async function doPreviewRender() {
        if (!previewState.active) return;
        const sid = await ensurePreviewSession();
        if (!sid) return;

        // If a render is already running, mark another as pending and return;
        // the in-flight render's finally-block will pick up the latest state.
        if (previewState.renderInflight) {
            previewState.renderPending = true;
            return;
        }

        const winSec = parseFloat(previewWindow.value) || 10;
        previewState.windowS = winSec;

        // Auto mode anchors on the artifact-hot region once Analyze has
        // produced a timeline; "Set from playhead" switches to manual.
        let regionNote = '';
        if (previewState.anchorMode === 'auto') {
            const hot = hottestAnchor(winSec, previewState.durationS);
            if (hot != null) {
                previewState.anchorS = hot;
                regionNote = ' (hottest region)';
            }
        }

        const {start, end} = clampWindow(
            previewState.anchorS, winSec, previewState.durationS);
        const region = `${fmtTime(start)}–${fmtTime(end)}${regionNote}`;

        const overrides = controls.getValues();
        const payload = {
            session_id: sid,
            start_s: start,
            end_s: end,
            preset: presetSelect.value,
            preset_strength: currentStrength(),
            overrides,
            preserve_volume: preserveVol.checked && !masterEnabled.checked,
            mastering: masteringPayload(),
            eq: eqPanel.getPayload(),
            repair: repairPayload(),
            ...picker.payload(),
        };

        // Decoded-render cache: same window + same params = instant swap.
        const cacheKey = JSON.stringify([
            start, end, payload.preset, payload.preset_strength,
            overrides, payload.preserve_volume, payload.mastering, payload.repair,
            payload.eq, payload.fixes, payload.auto,
        ]);
        const hit = previewCache.get(cacheKey);
        if (hit) {
            previewCache.delete(cacheKey);
            previewCache.set(cacheKey, hit);  // LRU refresh
            applyPreviewResult(hit, start, end, region, 'cached');
            return;
        }

        const ctrl = new AbortController();
        previewState.renderInflight = ctrl;
        setPreviewStatus(`Rendering preview · ${region}…`, 'busy');

        try {
            const r = await renderPreview(payload, {signal: ctrl.signal});
            const [processedBuf, removedBuf] = await Promise.all([
                player.decodeAudio(r.processed),
                player.decodeAudio(r.removed),
            ]);
            const entry = {processedBuf, removedBuf, meta: r.meta};
            previewCache.set(cacheKey, entry);
            while (previewCache.size > PREVIEW_CACHE_MAX) {
                previewCache.delete(previewCache.keys().next().value);
            }
            applyPreviewResult(
                entry, start, end, region,
                `rendered in ${r.meta.render_ms} ms`);
        } catch (e) {
            if (e.name !== 'AbortError') {
                setPreviewStatus(`Preview failed: ${e.message}`, 'error');
            }
        } finally {
            previewState.renderInflight = null;
            if (previewState.renderPending && previewState.active) {
                previewState.renderPending = false;
                doPreviewRender();
            }
        }
    }

    function schedulePreviewRender() {
        if (!previewState.active) {
            // An edit with Live off is the teachable moment — nudge once.
            maybePreviewNudge();
            return;
        }
        if (previewState.debounceTimer) {
            clearTimeout(previewState.debounceTimer);
        }
        previewState.debounceTimer = setTimeout(() => {
            previewState.debounceTimer = null;
            doPreviewRender();
        }, PREVIEW_DEBOUNCE_MS);
    }

    function capturePlayheadTime() {
        const t = Number(player.getTime());
        return Number.isFinite(t) ? t : 0;
    }

    function applyPreviewToggle(on) {
        previewState.active = !!on;
        previewControls.hidden = !on;

        if (on) {
            // Turning Live on satisfies the nudge — retire it for good and
            // drop the actionable hint so the explainer can revert later.
            markNudgeSeen();
            if (previewExplainer) previewExplainer.classList.remove('nudge');
            if (previewToggleRow) previewToggleRow.classList.remove('nudge-pulse');
            syncPreviewExplainer();
            // Auto mode resolves to the artifact-hot region inside
            // doPreviewRender; the playhead is the fallback anchor.
            previewState.anchorS = capturePlayheadTime();
            previewState.windowS = parseFloat(previewWindow.value) || 20;
            if (!currentFile) {
                setPreviewStatus('Drop a file first.');
                return;
            }
            applyLoudnessMatch();  // switch match source to preview LUFS
            doPreviewRender();
        } else {
            // Cancel any render requested while Live was on. Without this
            // an in-flight (or debounced) render resolves *after* we exit
            // and calls setPreviewBuffers, silently re-entering the loop —
            // the "sometimes locked into loop timing" glitch. The guard in
            // applyPreviewResult covers the decode window abort can't reach.
            if (previewState.renderInflight) {
                try { previewState.renderInflight.abort(); } catch (_) {}
                previewState.renderInflight = null;
            }
            if (previewState.debounceTimer) {
                clearTimeout(previewState.debounceTimer);
                previewState.debounceTimer = null;
            }
            previewState.renderPending = false;
            player.exitPreview();
            player.setSource('processed', null);
            player.setSource('removed', null);
            applyLoudnessMatch();  // back to full-run metrics
            setPreviewStatus(currentFile
                ? 'Live preview off — playhead runs the full track.'
                : 'Drop a file to start.');
            syncPreviewExplainer();  // status pill is hidden while off → show explainer
        }
    }

    previewToggle.addEventListener('change', () => {
        applyPreviewToggle(previewToggle.checked);
    });
    previewWindow.addEventListener('change', () => {
        previewState.windowS = parseFloat(previewWindow.value) || 20;
        schedulePreviewRender();
    });
    previewHereBtn.addEventListener('click', () => {
        // Re-anchor the loop window at the shared playhead (manual
        // override of the auto hot-region anchoring).
        previewState.anchorMode = 'manual';
        previewState.anchorS = capturePlayheadTime();
        if (!previewState.active) {
            previewToggle.checked = true;
            applyPreviewToggle(true);
        } else {
            doPreviewRender();
        }
    });
    window.addEventListener('beforeunload', () => {
        if (previewState.sessionId) dropSession(previewState.sessionId);
    });

    // ── Clean & Master progress modal ─────────────────────────────────
    // ── The processing window: the chain, live ─────────────────────────
    // Shared with the Remix tab (progress-chain.js). This tab hands it the
    // Signal Chain's phases and which of them this run will use.
    function plannedPhases() {
        const st = window.shimmerChainState ? window.shimmerChainState() : null;
        const masterOn = masterEnabled.checked;
        const set = new Set(['repair', 'split', 'fine', 'engine', 'recombine', 'post', 'export']);
        if (st && st.trim_armed) set.add('edit');
        if (masterOn) { set.add('pre'); set.add('master'); }
        else if (preserveVol.checked) set.add('level');
        return set;
    }
    function chainPhases() {
        return CHAIN_PHASES.map(([k, l, c]) => [k, l === 'Fine pass' ? 'Fine' : l, c]);
    }
    function openProcessModal() {
        // The title must say what this run actually does, and where it
        // sits in a two-pass plan.
        const job = masterEnabled.checked ? 'Cleaning & mastering' : 'Cleaning';
        const pass = !passPlan ? '' : passPlan.status === 'running1' ? ' · pass 1 of 2'
            : passPlan.status === 'running2' ? ' · pass 2 of 2' : '';
        processModal.open({
            title: job + pass,
            phases: chainPhases(),
            planned: plannedPhases(),
            stage: 'Preparing…',
            detail: 'reading the file',
        });
    }
    function closeProcessModal() { processModal.close(); }
    function failProcessModal(message) { processModal.fail(message); }
    // The Download step at the end of a run, in the processing window.
    // Browser location: a Download button, pressed for you when
    // "download automatically" is on. Folder location: the file is
    // already in the folder, so Show in folder leads and a copy can
    // still be downloaded. `mm` is the job's metrics; `savedInfo` its
    // export.saved block.
    function offerDownloadStep(mm, savedInfo, savedOk) {
        const ex = (mm && mm.export) || {};
        const fmt = formatLabel(ex.format_key || ex.format || outputFormat.value || 'wav');
        const stem = (currentFile && currentFile.name.replace(/\.[^.]+$/, '')) || 'track';
        const name = ex.name || `${stem}.${String(ex.format || outputFormat.value || 'wav')}`;
        const size = Number.isFinite(ex.size_bytes) ? ` · ${fmtBytes(ex.size_bytes)}` : '';
        const prefs = downloadPrefs();
        if (savedOk) {
            processModal.offerDownload({
                title: `Saved to ${folderLabel(savedInfo.folder)}`,
                sub: `${savedInfo.name || name}${size} · ${savedInfo.path}`,
                primary: { label: 'Show in folder', onClick: () => revealSaved(savedInfo.path) },
                secondary: { label: 'Download a copy', onClick: () => downloadLink.click() },
            });
            return;
        }
        const failed = (savedInfo && savedInfo.enabled && savedInfo.error)
            ? ` Could not save to ${savedInfo.folder}: ${savedInfo.error}.` : '';
        if (prefs.auto) {
            downloadLink.click();
            processModal.offerDownload({
                title: 'Downloading…',
                sub: `Your browser is saving ${name}${size}.${failed} If it did not start, click Download again.`,
                primary: { label: `Download ${fmt} again`, onClick: () => downloadLink.click() },
                secondary: null,
            });
            return;
        }
        processModal.offerDownload({
            title: 'Your file is ready',
            sub: `${name}${size}${failed ? '.' + failed : ''}`,
            primary: { label: `Download ${fmt}`, onClick: () => downloadLink.click() },
            secondary: null,
        });
    }
    // The short name of an output-format key for chips and buttons.
    function formatLabel(v) {
        return v === 'wav16' ? 'WAV 16-bit' : String(v || 'wav').toUpperCase();
    }
    function fmtBytes(n) {
        if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
        if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
        if (n >= 1e3) return `${(n / 1e3).toFixed(0)} kB`;
        return `${n} B`;
    }
    async function revealSaved(path) {
        try {
            await revealPath(path);
        } catch (e) {
            setMetrics(`Could not open the folder: ${e.message}`);
        }
    }
    function setProcessStage(key, label, detail) { processModal.stage(key, label, detail); }
    function updateProcessModal(frac) {
        // No stage events (an older server): say what the fraction means.
        processModal.progress(frac, (f) => (f < 0.85 ? 'Cleaning AI artifacts…'
            : (masterEnabled.checked ? 'Mastering & finalizing…' : 'Finalizing…')));
    }
    const processModalClose = $('process-modal-close');
    document.addEventListener('keydown', (e) => {
        // Not dismissable while running (no cancel support); Esc closes only
        // once the error Close button is offered. Between the passes the
        // countdown takes Esc itself and stops the hand-off.
        if (e.key === 'Escape' && processModal.isOpen() && processModalClose && !processModalClose.hidden) {
            closeProcessModal();
        }
    });

    // ── Process ───────────────────────────────────────────────────────
    // Never save an error message as a file. The result lives in the
    // server's memory; if the server restarted since the run, the link
    // answers with a JSON error and a plain <a download> would save that
    // JSON as the "WAV". Check first, then download for real.
    downloadLink.addEventListener('click', async (e) => {
        const href = downloadLink.getAttribute('href');
        if (!href) return;
        e.preventDefault();
        try {
            // Probe with a GET and drop the body: the route has no HEAD.
            const probe = await fetch(href);
            const ct = probe.headers.get('content-type') || '';
            if (!probe.ok || ct.startsWith('application/json')) {
                let msg = `Download failed (${probe.status}).`;
                try {
                    const body = await probe.json();
                    if (body && body.detail) msg = `Download failed: ${body.detail}.`;
                } catch (_) { /* no JSON body */ }
                if (/unknown job/i.test(msg)) {
                    msg += ' The server was restarted since this run, so the ' +
                           'result is gone. Run Clean & Master again.';
                }
                setMetrics(msg);
                return;
            }
            try { await probe.body?.cancel(); } catch (_) { /* already drained */ }
            const a = document.createElement('a');
            a.href = href;
            a.download = '';
            document.body.appendChild(a);
            a.click();
            a.remove();
        } catch (err) {
            setMetrics(`Download failed: ${err.message}`);
        }
    });

    processBtn.addEventListener('click', async () => {
        if (!currentFile) return;
        // Analyze found a second pass and mastering is on: ask before we
        // master a file that still needs another cleaning pass. Three
        // real choices; Cancel means cancel.
        // Skip the master-once question on a file that is already pass 1's
        // output: this run is the last pass, and it should master.
        if (lastFollowUp && masterEnabled.checked && !priorPassPreset) {
            const label = lastFollowUp.label || labelOf(lastFollowUp.name);
            const choice = await askSecondPass(label);
            if (choice === 'cancel') return;
            if (choice === 'off') {
                masterEnabled.checked = false;
                masterEnabled.dispatchEvent(new Event('change'));
                preserveVol.checked = true;
                preserveVol.dispatchEvent(new Event('change'));
            }
        }
        // Full-file processing replaces the slice players; turn live
        // preview off so the loop state doesn't fight the new sources.
        if (previewState.active) {
            previewToggle.checked = false;
            applyPreviewToggle(false);
        }
        processBtn.disabled = true;
        const ranWithMastering = masterEnabled.checked;
        processBtn.textContent = 'Processing…';
        progressEl.value = 0;
        openProcessModal();
        setMetrics('Preparing…');
        renderReleaseCard(null);

        try {
            const overrides = controls.getValues();
            const paramsBody = {
                preset: presetSelect.value,
                preset_strength: currentStrength(),
                overrides,
                mastering: masteringPayload(),
                eq: eqPanel.getPayload(),
                repair: repairPayload(),
                tags: tagsPayload(),
                ...picker.payload(),
            };
            if (lastAnalysis) paramsBody.mastering_analysis = lastAnalysis;

            const wantTrim = trimSilence.checked;
            const edit = trimPanel ? trimPanel.getTrim() : null;
            // Save to folder skips pass 1 of a two-pass plan: that file is
            // a stepping stone, and only the final master belongs in the
            // folder. Pass 2, and any single-pass run, is saved.
            const isPassOneOfTwo = !!(lastFollowUp && !ranWithMastering && !priorPassPreset);
            const saveTo = isPassOneOfTwo ? '' : activeSaveFolder();
            const job = await submitProcess(
                currentFile,
                paramsBody,
                outputFormat.value,
                preserveVol.checked && !masterEnabled.checked,
                wantTrim,
                edit,
                saveTo,
            );

            await new Promise((resolve, reject) => {
                openSSE(`/api/progress/${job.job_id}`, {
                    onMessage: (msg) => {
                        if (msg.stage) setProcessStage(msg.stage, msg.status, msg.detail);
                        if (typeof msg.fraction === 'number') {
                            progressEl.value = msg.fraction;
                            updateProcessModal(msg.fraction);
                        }
                        if (msg.error) reject(new Error(msg.error));
                    },
                    onDone: (msg) => msg.error ? reject(new Error(msg.error)) : resolve(),
                    onError: (e) => reject(e),
                });
            });

            await player.loadFromJob(job.job_id);
            player.setTrack('processed');

            downloadLink.href = resultUrl(
                job.job_id, wantTrim ? 'trimmed' : 'processed');
            setWizardStep(2);
            lastRun = { jobId: job.job_id, masteringOn: ranWithMastering, preset: presetSelect.value };
            if (syncNextStep) syncNextStep();

            const bannerChips = [];
            if (lastFollowUp && !ranWithMastering && !priorPassPreset) {
                bannerChips.push('pass 1 of 2 · cleaning only');
            } else if (priorPassPreset && ranWithMastering) {
                bannerChips.push('pass 2 of 2 · mastered');
            }
            const m = await fetchMetrics(job.job_id);
            if (m && m.metrics) {
                const mm = m.metrics;
                // Grouped readout: loudness first (what a release check
                // needs), then what the cleaning did, then the job facts.
                // Warnings get their own unlabeled row at the end.
                const loudness = [];
                const cleaning = [];
                const job = [];
                const warnings = [];
                const fmt = (v, digits = 2) =>
                    (v == null || Number.isNaN(v)) ? 'n/a' : v.toFixed(digits);
                const pctOf = (v) =>
                    (v == null || Number.isNaN(v)) ? 'n/a' : `${Math.round(v * 100)}%`;

                fullMatchDb = null;
                const mast = mm.mastering;
                if (mast && mast.enabled && mast.before && mast.after) {
                    loudness.push(
                        `LUFS ${mast.before.lufs_i?.toFixed(1)} → ${mast.after.lufs_i?.toFixed(1)} (target ${mast.target_lufs})`);
                    loudness.push(
                        `TP ${mast.before.true_peak_dbtp?.toFixed(1)} → ${mast.after.true_peak_dbtp?.toFixed(1)} dBTP`);
                    if (typeof mast.after.lra === 'number' && typeof mast.before.lra === 'number') {
                        loudness.push(`LRA ${mast.before.lra.toFixed(1)} → ${mast.after.lra.toFixed(1)} LU`);
                    }
                    if (mast.limiter && mast.limiter.max_gain_reduction_db != null) {
                        const gr = mast.limiter.max_gain_reduction_db;
                        loudness.push(gr > -0.05
                            ? 'Limiter: no gain reduction'
                            : `Limiter ${gr.toFixed(1)} dB max GR`);
                        // Warm tilt boosts the low end, which is what drives
                        // limiter pumping at loud targets — warn when the
                        // combination is actually working the limiter hard.
                        const warmTilt = mast.tilt === 'warm' || mast.tilt === 'warmer';
                        if (warmTilt && gr < -3) {
                            warnings.push(
                                '⚠ Warm tilt + loud target is pushing the limiter — ' +
                                'possible pumping. Try a lower loudness target.');
                        }
                    }
                    lastMasteringReport = mast;
                    fullMatchDb = -(mast.ab_match_gain_db || 0);
                    player.setTargetLufs(mast.target_lufs);
                    bannerChips.push(
                        `${mast.before.lufs_i?.toFixed(1)} → ${mast.after.lufs_i?.toFixed(1)} LUFS`);
                    bannerChips.push(
                        `TP ${mast.after.true_peak_dbtp?.toFixed(1)} dBTP`);
                }
                loudness.push(
                    `Peak ${mm.input.peak_dbfs.toFixed(1)} → ${mm.output.peak_dbfs.toFixed(1)} dBFS`,
                    `RMS ${mm.input.rms_dbfs.toFixed(1)} → ${mm.output.rms_dbfs.toFixed(1)} dBFS`);
                // Loudness match with mastering off: use the whole-file
                // LUFS pair the server now measures on every run.
                const loud = mm.loudness;
                if (fullMatchDb == null && loud &&
                    typeof loud.input_lufs_i === 'number' &&
                    typeof loud.output_lufs_i === 'number') {
                    fullMatchDb = loud.output_lufs_i - loud.input_lufs_i;
                }
                applyLoudnessMatch();
                // Release-check extras: peak-to-loudness ratio and stereo
                // correlation, in and out.
                if (loud && loud.input_plr_db != null && loud.output_plr_db != null) {
                    loudness.push(
                        `PLR ${loud.input_plr_db.toFixed(1)} → ${loud.output_plr_db.toFixed(1)} dB`);
                }
                if (loud && (loud.output_correlation != null || loud.input_correlation != null)) {
                    const fc = (v) => (v == null ? 'mono' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}`);
                    loudness.push(
                        `Stereo correlation ${fc(loud.input_correlation)} → ${fc(loud.output_correlation)}`);
                }

                const diag = mm.diagnostic;
                if (diag && diag.before && diag.after) {
                    const b = diag.before;
                    const a = diag.after;
                    cleaning.push(
                        `5–8 kHz energy ${fmt(b.band_5_8k_rms_db, 1)} → ${fmt(a.band_5_8k_rms_db, 1)} dB`);
                    cleaning.push(
                        `Flicker depth ${pctOf(b.band_5_8k_am_depth)} → ${pctOf(a.band_5_8k_am_depth)}`);
                    if (Array.isArray(a.top_peaks) && a.top_peaks.length) {
                        const peaks = a.top_peaks
                            .slice(0, 3)
                            .map(pk => `${(pk.hz / 1000).toFixed(2)}k +${fmt(pk.excess_db, 1)}dB`)
                            .join(', ');
                        cleaning.push(`Narrow peaks left: ${peaks}`);
                    } else {
                        cleaning.push('Narrow peaks left: none');
                    }
                }
                if (mm.declick && mm.declick.enabled) {
                    cleaning.push(`Clicks fixed: ${mm.declick.clicks ?? 0}`);
                }
                if (mm.repair && mm.repair.enabled) {
                    const n = mm.repair.notches ?? 0;
                    cleaning.push(`Fixed tones notched: ${n}`);
                }
                if (mm.cutoff_hz > 0) {
                    cleaning.push(`Top end stops at ${(mm.cutoff_hz / 1000).toFixed(1)} kHz`);
                }

                // State the applied cut on the result, not just in the panel:
                // the user should never wonder whether the trim went through.
                if (mm.edge_trim && mm.edge_trim.applied) {
                    const et = mm.edge_trim;
                    const parts = [];
                    if (et.cut_head_s > 0) parts.push(`${(et.cut_head_s * 1000).toFixed(0)} ms head`);
                    if (et.cut_tail_s > 0) parts.push(`${(et.cut_tail_s * 1000).toFixed(0)} ms tail`);
                    job.push(`Trimmed ${parts.join(' + ')}`);
                    bannerChips.push(`Trimmed ${parts.join(' + ')}`);
                }
                if (mm.trim && mm.trim.enabled) {
                    const cut = (mm.trim.cut_head_s || 0) + (mm.trim.cut_tail_s || 0);
                    job.push(cut > 0.05
                        ? `Export trims ${cut.toFixed(1)}s silence`
                        : 'Export trim: no silence found');
                }
                if (mm.eq && mm.eq.enabled) {
                    job.push(`EQ: ${mm.eq.bands} band${mm.eq.bands === 1 ? '' : 's'}`);
                }
                if (mm.export && mm.export.tags && mm.export.tags.written) {
                    const t = mm.export.tags.tags || {};
                    const who = [t.title, t.artist].filter(Boolean).join(' · ');
                    job.push(`Tags written${who ? ': ' + who : ''} (${mm.export.tags.form})`);
                }
                const chStr = mm.channels === 1 ? 'mono' : (mm.channels === 2 ? 'stereo' : `${mm.channels} ch`);
                job.push(`${fmtTime(mm.duration_s)} · ${(mm.sample_rate / 1000).toFixed(1)} kHz · ${chStr}`);
                // What the download actually is: format, bit depth, dither.
                if (mm.export && mm.export.format) {
                    const ex = mm.export;
                    const fmt = ex.format.toUpperCase();
                    let line = ex.bit_depth ? `${ex.bit_depth}-bit ${fmt}` : fmt;
                    if (ex.bitrate) line += ` ${ex.bitrate.replace('k', ' kbps')}`;
                    if (ex.bit_depth) {
                        line += ex.dither ? ' · TPDF dither'
                            : (ex.bit_depth >= 24 ? ' · no dither needed' : ' · no dither');
                    }
                    job.push(`Export ${line}`);
                }
                // Where the file went, when Save to folder was on.
                const sv = mm.export && mm.export.saved;
                if (sv && sv.enabled) {
                    if (sv.error) {
                        warnings.push(`Could not save to ${sv.folder}: ${sv.error}. Use Download instead.`);
                    } else {
                        job.push(`Saved to ${sv.folder}`);
                    }
                } else if (isPassOneOfTwo && activeSaveFolder()) {
                    job.push('Not saved to folder: pass 1 of 2 (the final master will be)');
                }

                setMetrics([
                    { label: 'Loudness', chips: loudness },
                    { label: 'Cleaning', chips: cleaning },
                    { label: 'Job', chips: job },
                    { label: '', chips: warnings },
                ]);
                report.show(mm.spectra);
                renderReleaseCard(mm.release);
                if (mm.release && mm.release.status) {
                    bannerChips.push(mm.release.status === 'pass' ? 'release check ✓'
                        : mm.release.status === 'fail' ? 'release check ✕' : 'release check ⚠');
                }
            }

            if (bannerChips.length === 0) bannerChips.push('Cleaned');
            bannerChips.push(formatLabel(outputFormat.value));
            const savedInfo = m && m.metrics && m.metrics.export && m.metrics.export.saved;
            const savedOk = !!(savedInfo && savedInfo.enabled && !savedInfo.error);
            if (savedOk) bannerChips.push(`saved to ${folderLabel(savedInfo.folder)}`);
            downloadLink.textContent =
                `Download ${formatLabel(outputFormat.value)}`;
            const doneTitle = doneBanner.querySelector('.done-title');
            if (doneTitle) doneTitle.textContent = savedOk ? '✓ Saved to your folder' : '✓ Ready to download';
            showDoneBanner(bannerChips);
            // Success: the packet leaves through Out. The final file gets
            // the Download step in the same window (Settings say whether
            // it downloads by itself, and where). Pass 1 of a two-pass
            // plan is a stepping stone: its window closes by itself, or
            // the plan cancels that and holds it (bridgeToPass2).
            if (isPassOneOfTwo) {
                processModal.closeSoon(900);
            } else {
                offerDownloadStep(m && m.metrics ? m.metrics : null, savedInfo, savedOk);
            }
            document.dispatchEvent(new CustomEvent('shimmer:run-complete', { detail: {
                ok: true, jobId: job.job_id, masteringOn: ranWithMastering,
                loudness: (m && m.metrics && m.metrics.loudness) || null,
            } }));
        } catch (e) {
            setMetrics(`Error: ${e.message}`);
            failProcessModal(e.message);  // keep modal open with a Close
            document.dispatchEvent(new CustomEvent('shimmer:run-complete', { detail: { ok: false } }));
        } finally {
            processBtn.disabled = false;
            processBtn.textContent = processLabel();
            progressEl.hidden = true;
        }
    });

}
