# Listening tests

One folder per round. Nothing here is ever overwritten — a re-render always
creates the next `round-N`, because comparing rounds is the point: a change to
the presets or to the damage model is only real if the next round sounds
different from the last one.

    python scripts/make_listening_test.py            # -> the next round-N
    python scripts/make_listening_test.py <path>     # -> somewhere specific

## Rounds

- **round-1** — *not kept.* Its residuals were peak-normalised per file, which
  hid how much each preset removed: the gentlest preset got ~26 dB more gain
  than the heaviest, so all three arrived sounding equally significant. The
  listener could only judge "is this recognisably music", never "how much was
  taken". Results are still useful and are recorded in
  `docs/BRIGHTNESS-ASSESSMENT.md`; the audio was superseded.
- **round-2** — one shared gain for every residual in a song, so their relative
  loudness survives. This is the first round whose residuals can be compared
  to each other.

- **round-3** — old tone target vs the measured one vs the reference master,
  per song. Built before the measured target was retracted (checklist item
  12), so its "new" is the disputed curve.
- **round-4** — the scorer change (items 5 and 10): per song, the untouched
  file, what the old purity-based scorer applied, and what the net-benefit
  scorer applies, cleaning only, no mastering, so the tone target plays no
  part. Loudest 30 s, matched to -18 LUFS, blind. Built by
  `scripts/make_round4.py`. Listen in `round-4/blind`; `round-4/renders` is
  the unblinded audio.

- **round-5** — is the modelled hash the real thing? Per clean host: the
  untouched master, plus the aperiodic hash model at 2.0 and 0.5 sones,
  plus the periodic model at 2.0; alongside the hot 8 s of two real Suno
  renders with high flicker. Not blind: the names say what each is, because
  the question is whether the model sounds like the artifact, not which is
  better. Built by `scripts/make_round5.py`; `KEY.json` gives each file's
  hearing-model and flicker readings. Item 15 rests on the answer.

- **round-6** — the learned hash remover on real renders. Per Suno render
  (hot 8 s): the untouched file and the same passage through the network
  from `scripts/hash_learn` at 100 %, nothing else in the chain. Blind, two
  letters per song, -18 LUFS. `renders/*-removed.wav` is what it took,
  unblinded. Built by `scripts/make_round6.py` (render under .venv-stems,
  then `--blind-only` under .venv).

- **round-7** — the second learned remover (trained on both hash models,
  louder hash, 2494 pairs) on the same six renders as round 6, same layout.

## How to listen

1. Play a song's four `*-master-*.wav` back to back. They are level-matched to
   −18 LUFS, so none can win by being louder. Which sounds most open?
2. Then the `*-residual-*.wav` — **what each preset removed**. Hiss and fizz
   mean the preset did its job. Cymbals, vocal air, reverb tails, transient
   pops or melody mean it took music.
3. Write your ranking down, *then* open `ANSWER-KEY.json`.

One label per song is the untouched source, shuffled so it is not the same
letter each time. Note that it is not expected to win as a *master* — these
sources carry real artifacts, so a cleaned version legitimately sounds better.
It is there as an anchor for the residual judgement: its residual is silence.
