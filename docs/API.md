# The seam: every call the screens make to the engine

Written 2026-09-12 as rebuild Step 3 (ARCHITECTURE.md §15). The screens stay; the
engine behind them is rebuilt. This file is the contract between the two: every
HTTP route the frontend calls, what it sends, what it reads back, and what the
rebuild does with it. Anything not listed here is free to change.

It was mapped from the code on branch `rebuild` (read, 2026-09-12). Line
references were true on that day.

**Fates:**

- **Keep** — same path, same fields the UI reads.
- **Keep, new fields** — same path; some request or response fields change,
  listed.
- **Retire** — nothing calls it, or its idea is retired.
- **New** — added by the rebuild.

Fields the server sends that no screen reads are not part of the contract and
may be dropped.

---

## 0. The transition rule (added after review, 2026-09-12)

The routes move to the new engine in Step 4, but the screens are re-wired in
Step 6. In between, the untouched screens must keep working:

- **Old fields are still accepted.** Every route that moves still accepts
  the old fields — `preset`, `preset_strength`, `overrides`, `auto_detect`,
  `static_repair` and `cleaning.preset` — and maps them through
  `shimmer.core.settings.migrate()`.
- **Old fields are still returned.** Until the screen that reads them is
  re-wired:
  - `/api/suggest` keeps returning `preset`, `strength`, `ranked` and
    `follow_up`, beside `findings[]`.
  - `GET /api/settings` keeps returning `preset`, `preset_strength` and
    `sliders`.
- **Each old field is dropped in a named step:** the Master tab's in Step 6,
  and Batch's and Remix's in Step 7.
- **`file` stays as a fallback.** Routes that take `session_id` still take
  `file`. The screens resend the file when a session answers 404 (it
  expired, or the server restarted).
- **Exports and Analyze decode the session's original file,** never the
  preview copy, which stops at 30 minutes (`preview_store.py:32`).

---

## 1. Decisions for sign-off

These change what a user can see or do. Everything else in this file keeps
behaviour the same. **All nine were signed off by the author on
2026-09-12.**

1. **The song is uploaded once.** Today the screens send the whole file again
   for Analyze, for every EQ re-plan, and for export (up to four uploads).
   `/api/suggest`, `/api/tone` and `/api/process` will accept the `session_id`
   from `/api/upload` instead. Same results, faster.
2. **Presets give way to the "What do you hear?" cards** (ARCHITECTURE
   §13.2a). `/api/presets` retires. One new route, `/api/rules`, serves the
   cards, the Loudness choices, the formats and the EQ limits, so the screens
   stop keeping their own copies.
3. **The routine second pass retires**, along with the "Run both passes"
   flow. The evidence branch found it partly answered a number the first pass
   had created (PITFALLS, "Relative measures inflate").
4. **Three dead lines leave the results panel.** The 5-8 kHz, flicker-depth
   and narrow-peak lines under "Cleaning" read a `diagnostic` block the server
   has never sent, so they can never appear.
5. **Four unused routes are removed** (§8), plus `?kind=original` on
   `/api/result`. FEATURES.md documents `/api/analyze` and
   `/api/stems/status`, so the changelog says they are gone.
6. **The Advanced artifact controls drawer and the Preset strength slider
   retire.** Each card that is on gets one Amount slider instead
   (ARCHITECTURE §19.3).
7. **Every other place presets appear changes with them:**
   - Batch's Fixed/Auto preset choice and its strength slider
   - the Remix cleanup menu, with saved Remix projects migrated
   - the Help "Pick a preset" tab and its quiz
   - the command palette's preset entries
   - the "19 presets" text on the page
   - the CLI's `--preset`, `--list-presets` and `--suggest`
8. **Download names change.** Today they are
   `{song}_{preset}_{processed|removed|trimmed}_{id}`. The 2.0 pattern is
   decided before Step 4 (§4).
9. **Decided 2026-09-12:** Commercial (-9 LUFS) becomes the default, and the
   Loudness choices get new names (ARCHITECTURE §15 Step 5, §19.2 D1). They
   show as three cards once a mockup is signed off.

Decision 3 matters less than it reads. The automatic second pass has been off
since 2026-09-08 (HANDOFF-CHECKLIST item 8), so users lose the "Run both
passes" flow, not a suggestion they see today. Re-processing an export by hand
still works, and its tags still say "pass 2".

---

## 2. Sessions

| Route | Fate | UI sends | UI reads |
|---|---|---|---|
| `POST /api/upload` | Keep | multipart `file` | `session_id`, `duration_s`, `digest`, `stems_tiers`, `title_hint`, `project.remix.*`; `edges.{found,head,tail}` (each edge: `artifact_ms`, `artifact_peak_db`, `gap_ms`, `suggested_s`, `artifact_start_s`, `artifact_end_s`); `repair.plan.notches[].{hz,depth_db,bw_hz,kind,excess_db,duty}`; `analysis.loudness.{lufs_i,true_peak_dbtp,lra}`, `analysis.spectrum.{freqs_hz,band_db}`, `analysis.cutoff_hz`; `source_tags.{title,track,artist,album_artist,album,genre,year,copyright,isrc}` |
| `DELETE /api/upload/{session_id}` | Keep | — | nothing |
| `GET /api/envelope/{session_id}?start_s&end_s&points` | Keep | query (points 16-4000) | `start_s`, `end_s`, `db[]` |

The whole `analysis` object goes back to the server as
`params.mastering_analysis` on export. With the session reused (decision 1),
that echo is no longer needed.

`digest` is SHA-1 of the uploaded file's bytes (stems.py:434-441). Remix
projects, the stem cache and the Recents list all key on it, so it must not
change.

## 3. Analyze and tone

| Route | Fate | Notes |
|---|---|---|
| `GET /api/presets` | **Retire** (Step 6, when the preset browser is re-wired) | Replaced by `/api/rules`. Until then it stays, served by the old code. Called four times on every page load today. |
| `POST /api/suggest` | Keep, new fields | See below. |
| `POST /api/tone` | Keep, new fields | Accepts `session_id`. **Fix:** when no notch list is sent, scan for one; today `{"enabled":true,"notches":null}` silently builds the plan with no notches. |
| `GET /api/tone/families` | Keep | Reads `families[].{key,label,blurb}`. Also carried in `/api/rules`. |
| `POST /api/chain` | Keep, new fields | The chain is built from the new module list. The body swaps `preset`, `preset_strength` and `overrides` for `fixes`. The UI reads `modules[]`, `gates`, `summary` (field list in §9). |
| **`GET /api/rules`** | **New** | See §7. |

**`/api/suggest` today.**

- **Sends:** `file`, `tone_family`, `mastering` (JSON
  `{enabled,target,intensity,tilt}`), `overrides` (JSON, the 15 stage
  sliders).
- **Reads:**
  - `preset`, `strength`
  - `follow_up.{name,label,strength,reason}`
  - `ranked[].{name,label,confidence,strength,reason}`
  - `repair_plan`, `evidence.cutoff_hz`, `notes[]`
  - `timeline.{intensity,step_s}`
  - `analysis`, `source_tags`
  - `tone_plan`, with `moves[]`, `regions[]`, `verify`, `verdict`, `why`,
    `summary`, `family`, `family_label`, `preset_label`, `mastering_on` and
    `analysis.cleaning_applied`

**`/api/suggest` after the rebuild.**

- **Sends:** `session_id` (or `file`), `tone_family`, `mastering`.
- **Returns:**
  - `findings[]`: `{card, value, unit, detail}`, one per card that fired
    (ARCHITECTURE §19.3)
  - `timeline`, `notes`, `analysis`, `source_tags` and `tone_plan`, unchanged
- **Retired with the presets:** `preset`, `strength`, `ranked`, `follow_up`,
  `scores`, `metrics`.

## 4. Render, export and jobs

**`POST /api/process`** — Keep, new fields.

- **Sends today:** multipart `file`, `params` (JSON), `output_format`
  (`wav|wav16|flac|mp3|ogg|m4a`), `preserve_volume`, `trim_silence`, and when
  set, `trim_in_s`, `trim_out_s` and `save_folder`.
- **`params` today:**
  - `preset`, `preset_strength`, `overrides`
  - `mastering{enabled,target,intensity,tilt}`
  - `eq{enabled,bands[{type,freq_hz,gain_db,q,enabled,source?}]}`
  - `repair{enabled,notches}`
  - `tags{enabled,title,track,artist,album_artist,album,genre,year,
    copyright,isrc,mode,notes}`
  - `mastering_analysis`
- **After the rebuild:**
  - `session_id` may replace `file`.
  - `fixes` (card to amount) and `auto` replace `preset`, `preset_strength`
    and `overrides`.
  - `mastering.target` keeps its keys (`streaming`, `loud`, `cd`); only the
    labels change (ARCHITECTURE §15 Step 5).
  - Everything else stays.
- **Returns:** `{job_id}`, unchanged.

**`POST /api/preview`** — Keep, new fields.

- **Sends:** `session_id`, `start_s`, `end_s`, `mastering`, `eq`, `repair`,
  `preserve_volume`, and `fixes`/`auto` in place of
  `preset`/`preset_strength`/`overrides`.
- **Returns:** the binary layout, unchanged. All integers are little-endian.

  | Bytes | What |
  |---|---|
  | 4 | u32: length of the JSON meta |
  | that many | JSON meta |
  | 4 | u32: length of the processed WAV |
  | that many | processed WAV |
  | the rest | removed WAV |

- **UI reads from the meta:** `lufs_processed`, `lufs_original`,
  `render_ms`.
- **Behaviour change:** the preview is now `render()` on a window. By
  construction it matches the export (contract test
  `test_the_preview_is_the_export_on_a_window`).

**`GET /api/progress/{job_id}`** — Keep, new stage keys. Server-sent events.

- **Events:** `{fraction, status}` first, then `{fraction}`,
  `{fraction, stage, status, detail}`, `{fraction, message, ...}` (stem
  separation), and a final `{done:true}` or `{error, done:true}`.
- **Keepalive:** one every 15 s.
- **Stage keys:** these change with the new chain. The screens' phase lists
  are read from `/api/rules` instead of copied (single.js:2786-2797,
  remix.js:16-48, chain.js:21-33). These keys stay:
  - separation: `setup`, `separate`, `load` and `null`
  - Remix render: `mix`, `analyze`
  - stem export: `mix`, `export`
- **The server says which stages a run will use.** `progress-chain.js:213-215`
  ignores keys it does not know, so a missing key shows up as a chain that
  never lights, not as an error.
- **Known limit:** one listener per job. A second tab or a reconnect steals
  events. The new job runner fixes this.

**`POST /api/cancel/{job_id}`** — **New** (built 2026-09-12).

- **Returns:** `{cancelled: true}`, or `{cancelled: false, reason}` when the
  job has already finished or is a 1.x job (Remix, stems) that cannot stop
  early yet.
- A cancelled job ends its progress stream with
  `{error: "Cancelled", cancelled: true, done: true}`, and its metrics and
  result answer 409 with `{status: "cancelled"}`.

**`GET /api/metrics/{job_id}`** — Keep.

- **Status codes:** 200 `{status:"done", metrics}`, 202 while running, 500
  on job error, 404 for an unknown job.
- **Fields the single-file screen reads:**
  - `mastering.{enabled,target_lufs,tilt,ab_match_gain_db}`,
    `mastering.{before,after}.{lufs_i,true_peak_dbtp,lra}`,
    `mastering.limiter.max_gain_reduction_db`
  - `input` and `output` `.{peak_dbfs,rms_dbfs}`
  - `loudness.{input_lufs_i,output_lufs_i,input_plr_db,output_plr_db,
    input_correlation,output_correlation}`
  - `declick.{enabled,clicks}`, `repair.{enabled,notches}`, `cutoff_hz`
  - `edge_trim.{applied,cut_head_s,cut_tail_s}`,
    `trim.{enabled,cut_head_s,cut_tail_s}`, `eq.{enabled,bands}`
  - `channels`, `sample_rate`, `duration_s`
  - `export.{format,format_key,name,size_bytes,bit_depth,bitrate,dither}`,
    `export.tags.{written,form,tags.{title,artist}}`,
    `export.saved.{enabled,error,folder,path,name}`
  - `spectra.{centers_hz,before_db,after_db,removed_db,delta_db,gain_db,
    low_max_abs_db,added_max_db,cut{lo_hz,hi_hz,at_hz,max_cut_db}}`
  - `release.{status,failed,warned,checks[].{status,label,value,detail},
    platforms[].{name,note,target_lufs}}`
- **Remix render reads:** `cleaning.{enabled,label,detected_confidence,
  detected_strength,repair_notches}`, `mastering.*`,
  `loudness.output_lufs_i`, `duration_s`.
- **Stem export reads:** `stems[]`.
- **Removed from the screen (decision 4):** `diagnostic.*`.

**`GET /api/result/{job_id}?kind=processed|diff|trimmed`** — Keep.

- **Returns:** the file, with its download name.
- **Change:** an unfinished job will answer **409** with a JSON body instead
  of 202. The UI's existing check (a JSON content type means an error) keeps
  working.
- **Retire:** `kind=original`, which has no caller.
- **Download names** today are `{stem}_{preset}_{kind}_{id8}.ext`
  (server.py:280-295), and Save to folder uses the same name. **Decided
  2026-09-12:** 2.0 names are `{stem}_{processed|removed|trimmed}_{id8}.ext`.
  The preset part simply drops out, and stem bundles keep their
  `{stem}_stems_{model}_{id8}.zip` name.
  `strip_shimmer_suffix` keeps a frozen list of the 1.x preset keys, so a
  re-processed 1.x export still loses its old suffix. Without that list,
  `my_song_generic_processed_ab12cd34` would be cut down to `my`.

**`POST /api/remix/render`** — Keep. The render moves onto `render()`.

- **Sends:** `{session_id, stems, output_format, mastering,
  cleaning:{preset}}`. `cleaning` becomes `{auto, fixes}` when Remix cleaning
  moves to cards.
- **Returns:** `{job_id}`.
- **Fix:** the export now writes tags and runs the release check, like every
  other tab (ARCHITECTURE §17 row 8).
- **Now (2026-09-12):**
  - The export runs on `render()` and `export()`, on the job runner, so
    `POST /api/cancel/{id}` stops it.
  - Tags come from the original upload's tags, with the provenance note.
  - The release check is in the metrics as `release`.
  - `cleaning.label` says what the engine did. `detected_*` are gone.
  - It reuses the whole mix `/api/remix/preview` built for the same lanes.
  - `/api/remix/preview` plays the loop's own mix at once (`exact: false`),
    then `render()` on a window of the whole mix once it is built
    (`exact: true`): Option A, decided 2026-09-12.

**`POST /api/stems/export`** — Keep.

- **Sends:** `{session_id, processed, stems}`.
- **Returns:** `{job_id}`. The ZIP is fetched with `kind=processed`.

## 5. Batch

**`POST /api/batch`** — Keep, new fields. Server-sent events over a POST,
read with a fetch stream.

- **Body today:**
  - `input_folder`, `output_folder`, `output_format`
  - `preset`, `preset_strength`, `auto_detect`, `static_repair`
  - `preserve_volume`, `trim_silence`
  - `mastering{enabled,target,intensity,tilt}`, `album_mode`
  - `eq`, `auto_eq`, `tone_family`
  - `tags{...}`
- **After the rebuild:** `fixes` and `auto` replace `preset`,
  `preset_strength`, `auto_detect` and `static_repair`. Everything else
  stays.
- **Now (2026-09-12):** every file runs on `render()` and `export()`.
  - `fixes` and `auto` are accepted.
  - The 1.x fields map through the transition rule (§0).
  - `preset_strength` no longer means anything, since the presets it scaled
    are gone.
  - `file_done` sends `findings` in place of `detected_*` and
    `effective_strength`.
  - Album mode's pass 1 measures; it no longer writes parked files.
- **Events the UI reads:**

  | Event | Fields read |
  |---|---|
  | `start` | `total`, `preset`, `output_folder`, `album_mode` |
  | `phase` | `message`, `phase` |
  | `album` | `target_lufs`, `gain_db`, `loudest`, `loudest_lufs`, `album_lufs`, `spread_lu` |
  | `file_start` | `index`, `name` |
  | `file_done` | `phase` (album mode splits its clean and master lines on it, batch.js:219), `duration_s`, `peak_in_db`, `peak_out_db`, `lufs_out`, `true_peak_out`, `limiter_gr_db`, `lufs_clean`, `true_peak_clean`, `release.{status,flags}`, `trim.*`, `tone_moves`, `tags_written`, `effective_strength`, and `detected_*` (the last two become `findings`) |
  | `file_error` | `error` |
  | `end` | `message` |

- **Later:** batch moves onto the job runner, which gives it a cancel button.

## 6. Settings and files

| Route | Fate | Notes |
|---|---|---|
| `GET /api/settings` | Keep | Returns the stored settings. **New:** old presets are migrated to cards on read (`shimmer.core.settings.migrate`). Master reads `remember_settings, preset_strength, preset, sliders, preserve_volume, trim_silence, output_format, ab_loudness_match, eq, mastering.*, tags.*, downloads.*, tone.*`; Batch reads `tone.family, eq.*, tags.*`. |
| `POST /api/settings` | Keep, new fields | The body is the whole schema: `fixes` and `auto` replace `preset`, `preset_strength` and `sliders`. |
| `POST /api/browse-folder` | Keep | Sends `{initial_dir, title}`; reads `path`. |
| `POST /api/reveal` | Keep | Sends `{path}`. **Fix:** today it fails with a 500, because `sys` is not imported. |

## 7. The new rules route

`GET /api/rules` serves, straight from `shimmer.core.catalog`, every rule the
screens copy today:

| Field | Replaces the copies at |
|---|---|
| `loudness_targets[].{key,lufs,label,sublabel,default}` | index.html:348-350, 618-620, 812-814; single.js:859; remix.js:463; visualizer.js:293 |
| `formats[].{key,ext,label,ceiling_dbtp,lossy}` | index.html:386-393, 661-668, 767-773; single.js:1922-1924, 2856-2858, 3150 |
| `eq_limits{max_bands,gain_limit_db,freq_min_hz,freq_max_hz,q_min,q_max}` | eq.js:12-27; single.js:1805 |
| `mastering_options{intensity[],tilt[]}` | index.html:357-370, 627-640, 818-828 |
| `cards[]` (the "What do you hear?" cards) | preset-browser.js:12-20; help.js:23-140 |
| `tone_families[]` | single.js:1565; batch.js:25 |
| `stages[]` (chain phases and stage keys) | chain.js:21-33; single.js:2786-2797; remix.js:16-48 |

Contract tests: `tests/api/test_api_contract.py`
(`test_the_rules_route_serves_the_engines_rules`,
`test_the_screens_do_not_copy_the_loudness_choices`).

Stem tiers stay on `/api/stems/engine`; the fallback copy in remix.js:25-38
goes. The Remix fader and effect ranges (remix.js:68-113, stem_effects.py:79-100)
stay with Remix, which keeps working as it does today.

## 8. Stems, remix and projects

All kept, unchanged, because Remix works as it does today.

| Route | UI sends | UI reads |
|---|---|---|
| `GET /api/stems/engine` | — | `tiers[].{key,label,stems,model,gpu_s_per_min,cpu_s_per_min,download_mb,downloaded,engine,author,license,blurb}`, `cuda`, `load_overhead_s`, `default_tier`, `installed`, `ready`, `demucs`, `gpu`, `roformer` |
| `GET /api/stems/library` | — | `items[].{digest,tiers}` |
| `POST /api/stems/separate` | `{session_id, tier}` | `job_id` |
| `GET /api/stems/info/{session_id}` | — | `stems[].{key,label,share,rms_db,peak_db,peaks}`, `mix_peaks`, `tier`, `label`, `cached`, `elapsed_s`, `device`, `model`, `format`, `null_db`, `suggested_loop_s` |
| `POST /api/remix/preview` | `{session_id, start_s, end_s, stems{<lane>:{gain_db,pan,mute,effects{formant,saturation,doubler,reverb}}}, mastering, output_format, cleaning{preset}}` | binary: u32 meta length, meta (`lufs_original, lufs_remix, render_ms, mastered, exact, building`), one WAV. `exact` is false while the whole mix is built in the background (the loop's own mix, level approximate); `building` true means asking again gives the exact preview |
| `POST /api/project/{digest}` | `{name, remix{strips,master,cleanup,tier,format}}` | nothing |

**Retire (no caller):**

- `GET /api/stems/status/{session_id}`
- `POST /api/analyze` (an alias of suggest)
- `GET /api/projects`
- `GET /api/project/{digest}` (the project already comes back with
  `/api/upload`)

## 9. Chain view fields

- **`POST /api/chain` body today:** `preset, preset_strength, overrides,
  mastering, eq, preserve_volume, trim_silence, output_format, save_folder,
  trim_armed, repair`.
- **Response fields the chain view reads (kept):**
  - `modules[].{id,phase,cat,name,gloss,active,off_reason,badges,band,
    detail}` (and `adv.length`)
  - `gates.{flatness,hold_ms,release_ms,low_band_bypass_hz}`
  - `summary.{crossover_hz,active_modules,n_fft,hop,iterations,fine_pass,
    fine_n_fft,fine_hop}`

The gate and summary fields describe the old nine-stage engine. When the
chain view is re-wired, they give way to the new module list. That is a
visible change, and it goes to sign-off with the chain view.

## 10. Known mismatches today (fixed by the rebuild)

1. `metrics.diagnostic` is read (single.js:3090-3106) but never produced.
   Decision 4.
2. `/api/tone` with `notches:null` builds a plan with no notches
   (server.py:1163-1167, 249-253). Fixed in §3.
3. `/api/result` on an unfinished job returns 202 with a JSON body. Fixed in
   §4.
4. The strength clamp in preset.js:58 (`high_shelf_db` up to 0) disagrees
   with params.py:347 (up to +6). This retires with preset strength.
5. The pass-2 file name is always `.wav`, built from the unsanitised source
   name (single.js:1279). This retires with the routine second pass.
6. Comments at api.js:85, 130-131 and 164 list response fields nothing reads.
   They are rewritten with the file.

## 11. Dev routes (keep)

`/api/dev/ab/*` (the listening bench) and `/api/dev/references/*` (the
reference library) are used by:

- static/ab/ and static/references/
- bench.bat and references.bat
- tests/test_abtest_*.py

The rebuild is judged on the bench, so these routes stay as they are.
