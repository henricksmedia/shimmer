# Stems engine: model shortlist (Phase 4 prep)

Research notes for Workstream B in [PLAN.md](PLAN.md). Written
2026-09-05.

**Status, 2026-09-05 (later the same day):** `audio-separator[gpu]`
(MIT) is installed in `.venv-stems` beside Demucs (torch unchanged at
2.5.1+cu121). The **Studio** tier in `stems.py` runs Kimberley Jensen's
Mel-Band RoFormer vocal model (MIT since 2026-04-22; 12.6 dB vocal SDR
in audio-separator's table against 10.8 for htdemucs_ft) for the vocal,
then `htdemucs_ft` on the instrumental. The **Ultra** tier is the
Demucs-only MDX23 recipe (htdemucs_ft + htdemucs + hdemucs_mmi averaged,
2 shifts, 0.5 overlap). Every shipped weight is MIT and listed in
`NOTICE`. Still not offered: the ZFTurbo 4-stem Roformer/SCNet weights
(no published terms; e-mail the author), viperx BS-Roformer (no license),
and the unwa fine-tunes of Kim's model (license not stated).

Decision 3 in the plan says: use the best open models as they are, in
our own side venv, and check the licence of every checkpoint before it
ships. This is that check, as far as public sources allow. "Confirm"
means the licence must be read in the actual repository or model card
at install time; several weight authors never published one.

## 1. What "best" means with open weights

The 13.7 dB average quoted earlier is MVSep's *ensemble of their own
private models*, trained on far more data than the public sets. It is
not downloadable. The best public 4-stem weights sit near 10 dB on the
MUSDB18-HQ test set; the best public vocal models reach 11–13 dB. So the
honest targets for Shimmer's open engine are:

| Stem | Today (htdemucs) | Open target | Best open source |
|---|---|---|---|
| 4-stem average | ~9.2 dB | ≥ 10.0 dB | SCNet XL IHF 10.08; BS-Roformer 9.65 |
| vocals | 8.2 dB | ≥ 11.0 dB | Mel-RoFormer (Kim) 10.98; BS PolarFormer 11.0 |
| drums | 10.9 dB | ≥ 11.5 dB | SCNet XL IHF 11.81 |
| bass | 11.8 dB | ≥ 11.8 dB | htdemucs_ft 11.96 (still the best open bass) |
| other | 5.7 dB | ≥ 7.5 dB | SCNet XL IHF 7.88 |

An ensemble of two or three of these (average or per-stem best) usually
adds 0.3–0.8 dB over the best single model. That is the "better than the
sites" claim we can back with numbers; the rest of the edge comes from
the pipeline around the model (static notches before the split, the
residual stem, per-stem cleaning, a null-test badge).

## 2. Candidate checkpoints

Sizes are approximate; confirm at install. SDR figures are the authors'
own numbers on the sets named in ZFTurbo's model table.

### Tier "Fast" (ships)

| Model | Stems | SDR | Size | Licence | Runner |
|---|---|---|---|---|---|
| htdemucs_ft (Meta) | 4 | 9.3 avg | ~330 MB (4 files) | MIT | demucs (already installed) |
| htdemucs_6s (Meta) | 6 (+guitar, piano) | 4-stem ~9.0; guitar/piano weak | ~80 MB | MIT | demucs |

### Tier "Best" (ships if licences confirm)

| Model | Stems | SDR | Size | Licence | Runner |
|---|---|---|---|---|---|
| SCNet XL IHF (ZFTurbo release) | 4 | 10.08 avg | ~200 MB | ZFTurbo repo is MIT; weights released in the repo — confirm | ZFTurbo inference |
| BS-Roformer 4-stem (ZFTurbo release, MUSDB18HQ) | 4 | 9.65 avg | ~600 MB | as above — confirm | ZFTurbo inference |
| Mel-Band RoFormer vocals (Kimberley Jensen) | vocals / rest | 10.98 vocals | ~700 MB | relicensed **MIT** 2026-04 (was GPL-3.0) | audio-separator or ZFTurbo |
| BS PolarFormer vocals | vocals / rest | 11.0 vocals | ~600 MB | GitHub release — confirm | ZFTurbo inference |

### Sub-stem tree (ships per licence)

| Model | Stems | SDR | Licence | Runner |
|---|---|---|---|---|
| DrumSep MDX23C (jarredou) | kick, snare, toms, hi-hat, cymbals | kick 16.7, snare 11.5, toms 12.3, hats 4.0, cymbals 6.4 | not stated — confirm with author | ZFTurbo inference |
| DrumSep HTDemucs (inagoy) | kick, snare, toms, cymbals | kick 10.5, snare 6.1 | GitHub release — confirm | demucs |
| htdemucs_6s guitar / piano | guitar, piano | weak (guitar ~9 on MVSep's private model; open ~5–7) | MIT | demucs |
| Mel-RoFormer de-reverb (anvuew) | dry vocal / reverb | — | **GPL-3.0** per model card | ZFTurbo inference |
| Mel-RoFormer denoise (aufr33) | clean / noise | 28.0 | not stated — confirm | ZFTurbo inference |
| Mel-RoFormer vocal de-reverb/de-echo (SUC-DriverOld) | dry vocal | 10.0 | HuggingFace — confirm | ZFTurbo inference |

### Not shipped

| Model | Why |
|---|---|
| BS-Roformer "viperx" ep 317 (SDR 12.98 vocals) | Best public vocal number, but no licence was ever published (originally paywalled). No commercial grant found. Optional download only, personal use, with a warning. |
| MVSep piano / guitar / lead-vocal models | Proprietary, cloud only. |
| Anything from a re-upload account | Provenance unclear; take weights only from the author's own release. |

Lead versus backing vocals: no permissively licensed open model was
found in this pass. Candidates are UVR "karaoke" MDX-Net models (licence
to confirm) and the MVSep team's BS-Roformer (proprietary). Treat as a
gap until confirmed.

## 3. Runners and install plan (no training)

- `.venv-stems` already holds torch and demucs. Add
  `audio-separator[gpu]` (MIT; runs Roformer, MDX, VR and Demucs
  checkpoints with CUDA on Windows and has ensemble modes) and a pinned
  checkout of ZFTurbo's Music-Source-Separation-Training (MIT) for the
  release checkpoints it hosts (SCNet, BS-Roformer 4-stem, DrumSep,
  PolarFormer). Both use the same torch.
- Models and caches stay on D: (`stem_cache`, `models/`). Budget: about
  2–3 GB of weights for the Best tier plus sub-stems.
- The runner is selected per model in one table (`stems.py`), cached by
  content hash *and* model set, so switching tiers never re-separates
  what is already done.
- The RTX 4070 (12 GB) runs every model above at fp16. Expect roughly
  20–60 s per model per four-minute track; an ensemble of three plus the
  drum split lands at two to four minutes.

## 4. Benchmark data

- MUSDB18-HQ: research licence (personal benchmarking is fine; the data
  cannot be redistributed). About 30 GB.
- MoisesDB: non-commercial research licence, 12 instrument classes,
  about 80 GB. Optional, for the sub-stem tree.
- The codec-degraded AI-music set is built from these by passing the
  mixes through DAC / Encodec; it inherits the same licence terms.

## 5. Open questions before install

1. Read the licence in ZFTurbo's repository release notes for the
   SCNet / BS-Roformer / PolarFormer weights (the repo is MIT; the
   weights are released inside it).
2. Ask jarredou (DrumSep MDX23C) and aufr33 (denoise) for weight terms,
   or exclude them.
3. Whether GPL-3.0 weights (anvuew de-reverb) are acceptable for a
   personal build; they are not for a distributed one.

## Sources

- ZFTurbo model table: <https://github.com/ZFTurbo/Music-Source-Separation-Training/blob/main/docs/pretrained_models.md>
- MVSep algorithm scores (proprietary ensemble 13.67 dB): <https://mvsep.com/en/algorithms>
- Mel-Band RoFormer relicense to MIT (2026-04): <https://github.com/openmirlab/melband-roformer-infer>
- viperx BS-Roformer licence status: <https://github.com/galenoferreira/xeon_split_audio/blob/main/docs/research/model-licenses.md>
- audio-separator (MIT runner): <https://github.com/nomadkaraoke/python-audio-separator>
- anvuew BS-RoFormer / de-reverb cards (GPL-3.0): <https://huggingface.co/anvuew/BS-RoFormer>
- SCNet official: <https://github.com/starrytong/SCNet>
