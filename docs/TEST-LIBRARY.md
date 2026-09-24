# The test library

A fix tuned on one song can hurt the next. The Shimmer model learned from
the author's own masters and kept exactly the sizzle it should remove, and
the first Amount limits were set on 8 seconds of five songs
([CHAIN-AUDIT.md](CHAIN-AUDIT.md)). The test library is the answer: a few
hundred real AI songs, labeled by generator version and style, that every
fix and every master is run against before it ships.

The songs are private, so the library lives next to them, never in this
repo. The repo holds only the tool: `scripts/test_library.py`.

## Build it

```bash
python scripts/test_library.py build "D:/MusicVault" --out library.json
```

- **Every folder named `suno`** under the root holds one song's original
  exports. Its main WAV is the song. Files in folders below it are older
  takes, and folders named `Templates` are skipped.
- **The version** comes from the date in the MP3's tag ("made with suno;
  created=…"), mapped to the version that was the default that day. With no
  tag, the WAV's file date stands in, marked `"dated": "file"`, because a
  copied file's date can be later than the export.
- **The style** is the artist, for `Artist/albums/Album/Song/suno`, or else
  the folder above the song.
- **`--add another.json`** merges in more songs, such as a sample from a
  downloads archive whose records give each song's version directly.

## Run a fix or a master over it

```bash
python scripts/test_library.py run library.json --card grain=0.5 --out grain.json
python scripts/test_library.py run library.json --card grain=0.5 --mode vocal --out grain-vocal.json
python scripts/test_library.py run library.json --master cd --out master.json
python scripts/test_library.py run library.json --master cd --mp3 --out master-mp3.json
```

Each song goes through `core.render()`, the same path the app uses, and
the results are grouped by version:

| Run | Per song |
|---|---|
| `--card` | How much the fix takes from the whole song and from its own band (dB), and the share of the song where it takes more than 1 dB of its band |
| `--master` | The loudness reached, the true peak at 8x, the gain, and the share of the song the peak shaper touched |

`--mp3` uses the MP3 export in place of the WAV. `--only v6` runs one
version (repeat it for more). `--limit N` runs only the first N songs. A song that fails is reported and the run goes on.

## What it can and cannot tell

- **It can tell where a fix acts,** how much, and whether that changes by
  version or style. A fix that takes much more from one version, or acts on
  every song the same, is worth a listen before it ships.
- **It cannot tell whether that is right.** Every song here is AI output,
  so there is no clean version to compare against. The cost on clean music
  is still measured on released songs by other artists, and the final word
  is a level-matched listen (`GOALS.md`, rule 4).
