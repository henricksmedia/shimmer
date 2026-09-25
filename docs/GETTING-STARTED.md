# Getting started with Shimmer 2.3.0

Shimmer is a free app that cleans and masters songs made with AI music
tools such as Suno and Udio. It runs on your own computer, on Windows,
macOS and Linux. After the first setup, it works offline. Your songs are
never uploaded.

This guide is for you if you have just downloaded Shimmer. You do not need
to know how to master a song. The steps are in the order you will do them.

Version 2.3.0 came out on 2026-09-24. Shimmer is made by The Treq.

**How to read this guide.** Words in **bold** are the words you will see on
the screen: buttons, menus, cards and switches. When a sound term comes up
for the first time, a short plain explanation follows it.

For every feature in detail, see [FEATURES.md](FEATURES.md).

## Contents

1. [What you need](#1-what-you-need)
2. [Install and first launch](#2-install-and-first-launch)
3. [Updating from 1.1.1](#3-updating-from-111)
4. [Your first master](#4-your-first-master)
5. [Good habits](#5-good-habits)
6. [Batch a folder, and album mode](#6-batch-a-folder-and-album-mode)
7. [Remix: split a song into stems](#7-remix-split-a-song-into-stems)
8. [The Settings tab and "Remember settings"](#8-the-settings-tab-and-remember-settings)
9. [The command line in three examples](#9-the-command-line-in-three-examples)
10. [If something goes wrong](#10-if-something-goes-wrong)
11. [What is not in 2.3.0 yet](#11-what-is-not-in-230-yet)

---

## 1. What you need

- **A computer running Windows, macOS or Linux.** Shimmer was built on
  Windows, so Windows is the most tested.
- **A web browser.** Shimmer's screens open in your browser, but the app
  runs on your computer. Nothing is sent to a website.
- **An internet connection for the first setup only.** The first launch
  downloads the audio libraries. After that, Shimmer works offline. Two
  things still need the internet the first time you use them: the Remix
  tab's separation engine, and each stem model.
- **Disk space.**
  - About 200 MB for the audio libraries, plus the copy of Python that
    Shimmer's installer sets up.
  - Only if you use the Remix tab: a one-time separation engine (the
    screen says the download is about 3 GB), plus each stem model you
    pick (80 MB to about 1.2 GB). The stems you split are kept on disk
    too.
- **You do not need to install Python.** The launcher uses a free tool
  called uv, which gets the right Python for you.
- **ffmpeg, for MP3 and M4A files only.** ffmpeg is a free tool that reads
  and writes compressed audio. WAV, FLAC and OGG work without it. To read
  or write MP3 or M4A, install ffmpeg once, then restart Shimmer:

  | System | Command to run in a terminal |
  |---|---|
  | Windows | `winget install ffmpeg` |
  | macOS | `brew install ffmpeg` |
  | Linux | `apt install ffmpeg` |

- **An NVIDIA graphics card is optional.** It only speeds up stem
  separation on the Remix tab. Everything else runs on your computer's
  main processor (CPU). Without an NVIDIA card, Remix still works. It is
  just several times slower. On a Mac, Remix runs on the CPU.

---

## 2. Install and first launch

### Windows

1. Go to the
   [latest release](https://github.com/henricksmedia/shimmer/releases/latest).
2. Download `Source code (zip)`.
3. Unzip it into a folder you will keep. Do not use your Downloads folder.
4. Open the folder and double-click `start.bat`.
5. If Windows warns you about a downloaded file, click **More info**, then
   **Run anyway**. You can open `start.bat` in a text editor first to read
   it. Each step has a comment.
6. A black window opens. If it asks `Install uv now? [Y/n]:`, press Enter.
   uv is the free tool that installs Python and the audio libraries for
   Shimmer. It takes about a minute.
7. If the window says "uv was installed but this window cannot see it
   yet", close the window. Then double-click `start.bat` again.
8. Wait for the first-time setup. The window says "Creating a local Python
   environment...", then "Installing audio libraries...". This downloads
   up to 200 MB. Allow 5 to 10 minutes.
9. When it says "Setup complete. Future launches start in seconds.", your
   browser opens Shimmer at <http://localhost:7860> by itself. If it does
   not, type that address into your browser.

### macOS and Linux

1. Get Shimmer in one of two ways:
   - Download the
     [latest release](https://github.com/henricksmedia/shimmer/releases/latest)
     and unzip it into a folder you will keep, or
   - clone it with git:

     ```bash
     git clone https://github.com/henricksmedia/shimmer.git
     ```

2. Open a terminal in the Shimmer folder.
3. Run `./start.sh`.
4. If it asks `Install uv now? [Y/n]:`, press Enter. It installs uv with
   Homebrew if you have it, or from uv's own site if you do not.
5. If it says "uv was installed but this shell cannot see it yet", open a
   new terminal and run `./start.sh` again.
6. Wait for the first-time setup: 5 to 10 minutes.
7. Your browser opens Shimmer at <http://localhost:7860> when it is ready.

### Keep the window open

The black window (or terminal) is Shimmer itself. The browser tab is only
its screen. Leave the window open while you work.

**To stop Shimmer:**

- **Windows:** close the black window.
- **macOS and Linux:** press **Ctrl+C** in the terminal.

Closing the browser tab does not stop Shimmer.

### What was installed, and where

- The app's libraries go in a `.venv` folder inside the Shimmer folder.
- Apart from uv, nothing is installed on the rest of your system.
- To remove Shimmer, delete the Shimmer folder. Your saved settings are
  kept in a separate small folder (see
  [Where Shimmer keeps its files](#where-shimmer-keeps-its-files)).

The next time you launch, Shimmer starts in a few seconds. If an older
Shimmer is still running, the launcher closes it first.

---

## 3. Updating from 1.1.1

1. Get 2.3.0 the same way you got 1.1.1: download the new release zip, or
   run `git pull` in your clone.
2. Launch it as before, with `start.bat` or `./start.sh`. From 2.1.0 on, a
   git clone updates itself: each time the launcher starts, it moves a
   clone on the `main` branch to the newest release. It skips this when the
   clone has unsaved changes or there is no network.
3. Wait while the launcher installs the new libraries 2.0 needs. It sees
   that the list changed and installs them before it starts.

What carries over:

- **Your saved settings.** They are kept outside the Shimmer folder, so a
  new folder still finds them.
- **Your old preset, as a card.** If you used 1.x with **Remember settings
  next time** on, the preset you saved turns on the card it became, at
  that card's starting Amount. For example, Suno Hash turns on
  **Shimmer**, and Muddy / Boxy turns on **Low-mid build-up**. To see the
  whole list, run the command line with `--list` (see
  [section 9](#9-the-command-line-in-three-examples)).
- **Kept as saved:** your loudness choice, format, EQ, silence trim,
  Preserve volume, Tone match and Tilt. The loudness choices have new
  names: CD / Club is now **Commercial**, Loud is now **Balanced**, and
  Streaming is now **Streaming standard**.
- **Your Remix projects.** They are saved with your settings.

What does not carry over:

- **Preset strength.** The old presets applied their filters at twice
  their setting, so the old numbers mean nothing now.
- **The old cleaning sliders.** The **Advanced artifact controls** drawer
  is still there, but its sliders do not change the sound in 2.0.

Two things to check:

- **The default loudness is louder now.** New songs start at **Commercial**
  (−9 LUFS). 1.1.1 started at −14 LUFS. If you had saved Streaming, you
  still get −14 LUFS until you pick another target.
- **Stems you already split.** They are kept in the `stem_cache` folder
  inside the Shimmer folder. If you unzipped 2.3.0 into a new folder,
  copy `stem_cache` from the old folder into the new one. A new folder
  also means the first-time setup runs once more.

---

## 4. Your first master

This is the main job: one song in, one finished file out. It happens on
the **Master** tab. The three steps show across the top: **1 Upload**,
**2 Analyze**, **3 Clean & Master**.

Nothing is permanent until you export. The cards, sliders and EQ only
change what you hear in the preview. Your original file is never changed.

### The screen at a glance

- **Side rail (left):** the tabs **Master**, **Remix**, **Batch**,
  **Signal Chain**, **Settings** and **Help**. Below them, a card shows
  the song you loaded.
- **Bottom bar:**
  - **Transport:** back to the start, back 5 seconds, play/pause, forward
    5 seconds, and a scrubber you can click or drag.
  - **Monitor:** **1 Original**, **2 Processed**, **3 Removed**, and the
    **Loudness-matched A/B** switch.
  - **Preview loop:** the **Live** switch, the loop length, and **Set from
    playhead**.
- **Keys:**

  | Key | What it does |
  |---|---|
  | Space | Play and pause |
  | 1, 2, 3 | Switch to Original, Processed or Removed |
  | Left and right arrows | Skip back or forward 5 seconds |
  | Ctrl+K | Open a command menu: switch tabs, play, run Analyze, open Help |

- **Help:** click **?** next to a card or control for help on that one.

### Step 1: Drop in a song

1. Drag your song onto the box that says "Drop a track to clean &
   master". Or click **Choose file…** and pick it.
2. Use a WAV, MP3, FLAC, OGG or M4A file. MP3 and M4A need ffmpeg (see
   [section 1](#1-what-you-need)).

Songs you opened before show under **Recent sessions** (up to six). In
Chromium-based browsers, a click reloads the song and its settings. In
other browsers, drop the file again.

### Step 2: Click Analyze

1. Click **Analyze**. It is in the **Analysis** card, and also as step
   **2 Analyze** in the right column.
2. Wait about 10 seconds for a four-minute song.

Analyze only measures. It never changes your song. It does four things:

- **It measures loudness and peaks.** Loudness is shown in **LUFS**, the
  unit streaming services use for how loud a song is. The closer to zero,
  the louder: −9 LUFS is louder than −14 LUFS. Peaks are shown as **true
  peak** in **dBTP**. True peak is the highest point the sound reaches,
  including peaks that appear between samples when the file is played or
  converted. 0 dBTP is the most a file can hold.
- **It looks for fixed tones.** These are steady whistles that the AI
  tool left at one pitch for the whole song. If it finds any, it turns on
  the **Fixed tones** card.
- **It moves the preview loop** to where the top end is busiest, so you
  hear problems there first.
- **It plans a Suggested EQ** (see [Step 8](#step-8-optional-check-the-suggested-eq)).

Then the **Analysis** card lists what it found as a checklist. Each row
says what ticking it does and whether it is **On** now. Leave the ticks as
they are to take Analyze's advice, or change them, then press **Apply**.
Nothing Analyze suggests changes your sound until it says **On**.

The **Suggested EQ** row sits under its own **Suggestion** label. It is not
a problem Analyze found: Analyze suggests it for every song. Click **See
the moves ↓** on that row to jump down to the moves.

Under the list, a **Next: Clean & Master** bar shows the next step. Its
button is the same as the **Clean & Master** button at the top of the
right-hand panel, which glows until you press it. Everything under the bar
is optional.

**Quick or Advanced.** The switch at the top of the Master tab picks how
much you see. **Quick** gives three sliders, set for your song by
Analyze: **Clean-up** (Off, Light, Recommended, Strong), **Loudness**
(Streaming, Balanced, Commercial) and **Tone** (Warmer to Brighter).
**Advanced** shows every card and control. Both change the same settings.

These cards can get a **Found** note, with how much: **some** or **a lot**:

- **Fixed tones:** each tone found, with its pitch.
- **Loudness:** how far the song is under your loudness target, when it is
  1 dB or more.
- **Lack of air:** how many dB the top end sits under the tone target. The
  checklist offers a brighter Tilt; it starts unticked.
- **Vocal grain**, **Low-mid build-up**, **Sibilance** and **Harshness:**
  how much of the problem is there. Vocal grain starts at 40 % for some and
  75 % for a lot. Their fix turns on, at 50 % for some and 100 % for a
  lot. Sibilance and Harshness take a few seconds more, so they listen in
  the background as soon as the song is loaded.

Change an Amount or turn a card off, and Analyze leaves it that way for
this song. For every other card, your ears decide.

**Expand** opens the analysis in a bigger panel. Its **Loop the worst
part** button turns on Live and loops the worst stretch.

### Step 3: Pick what you hear

Under **What do you hear?**, the cards come in two groups: **Artifacts**
and **Tone and level**. An artifact is a sound the AI tool added that is
not part of your music.

1. Listen to your song.
2. Click each card that matches a problem you can hear. The card turns
   on.
3. Click a card again to turn it off.

Each card turns on one tool:

| Card | What you hear | What it turns on | State in 2.3.0 |
|---|---|---|---|
| **Shimmer** | Fizzy, flickering hiss up top | **Spectral de-noise**: turns noise down frequency by frequency, from 1.5 to 16 kHz | On, to try |
| **Vocal grain** | Grainy hiss riding on the voice | **Voice de-noise**: takes out a steady hiss, a hiss that follows the voice, and sharp little spikes, strongest at 4 to 8 kHz | New, to try. Asks you to check the first time |
| **Fixed tones** | A whistle or whine that never changes | **Notch filter**: a very narrow cut at each steady tone, so the music on either side is kept | Ready. Analyze turns it on |
| **Sibilance** | Harsh, spitty "s" and "sh" | **De-esser**: turns down 4.5 to 10 kHz only while an "s", "sh", "t" or "ch" sticks out | On, to try |
| **Clicks and crackle** | Short pops, ticks or static | **De-click**: finds short pops and fills them in | Not built yet. Changes nothing |
| **Harshness** | Piercing, painful upper mids | **Dynamic EQ** (2 to 5 kHz): turns the band that sticks out most down while it is louder than usual | On, to try |
| **Phasiness** | Grainy or watery reverb tails | Nothing yet | No fix yet. Changes nothing |
| **Low-mid build-up** | Muddy, boxy, words hard to hear | **Dynamic EQ** (200 to 500 Hz) | On, to try |
| **Lack of air** | Dull, no sparkle | Sets **Tilt** to Bright in Mastering | Ready |
| **Loudness** | Quieter than released music | Sets the **Loudness target** to **Commercial** in Mastering | Ready |

Hz (hertz) measures pitch, from low to high. 1 kHz is 1,000 Hz. EQ
(equalizer) turns ranges of pitch up or down.

What the states mean:

- **On, to try:** the fix passed its measurements and is turned on so you
  can try it. It has not had its blind listening test yet.
- **Not built yet** and **No fix yet:** you can still click the card. It
  shows as "noted" and changes nothing. Your pick is saved on your
  computer to help test new fixes.

A few more things:

- **Lack of air** and **Loudness** change Mastering settings instead of
  running a fix. Turning either one on turns mastering on.
- **Vocal grain asks first.** The first time you turn it on, a box asks
  you to check: on a song without grain, this fix takes some sparkle away.
  Listen to the Removed track. It should hold only hiss and grit. Its
  **Works on** menu picks **Centre of the mix** (needs nothing extra) or
  **Vocal only**, which splits out the vocal first with the Remix splitter
  and leaves cymbals alone. The first split takes a minute or more.
- **The Shimmer card takes a while the first time.** Its spectral
  de-noise reads the whole song once: about 50 seconds for a 3-minute
  song. The status line at the bottom says "Getting ready for this
  song…", then how far it has got. After that, changes are quick.
  Turning the card off during this first read stops it.
- **Not sure which card?** Open **Help**, then the **What do you hear?**
  tab. It has a short quiz that points you to a card.

### Step 4: Set the Amount

Each card you turn on adds a row under **Fixes on**. The row shows the
tool, the card, who turned it on ("by you" or "by Analyze"), and an
**Amount** slider.

1. Leave the Amount where it starts for your first listen. Most cards
   start at 50 %. **Fixed tones** starts at 100 %.
2. Listen (Steps 5 and 6).
3. Move the slider if you need more or less.

What the numbers mean:

- 0 % changes nothing.
- 100 % is the deepest cut that fix allows. The top of each slider was set
  by measurement: at 100 %, a fix takes no more than 0.10 sones from a
  clean song. A sone is a unit for how loud a sound seems to the ear.

A card Analyze did not measure says "Analyze didn't measure this.
Starting gentle — check the Removed track."

### Step 5: Turn on Live preview and listen

1. In the bottom bar, under **Preview loop**, turn on **Live**. A short
   part of the song starts to loop.
2. Pick the loop length: 10, 20 (the default) or 30 seconds.
3. To loop a different part, move the playhead there and click **Set from
   playhead**.
4. Press Space to play.
5. Press **1** to hear the **Original**. Press **2** to hear the
   **Processed** song. Press **3** to hear the **Removed** track.
6. Switch back and forth. This is how you judge the result.

**Processed** and **Removed** look dimmed until something has been
rendered. Click either one (or press 2 or 3) and Shimmer turns on **Live**
for you, then plays that track when the loop is ready.

Every change you make renders the loop again. The preview uses the same
sound path as the export, level included, so what you hear is what the
file will be.

Leave **Loudness-matched A/B** on. A/B means switching between two
versions to compare them. A louder version almost always sounds better,
even when it is not. This switch turns the louder track down while you
listen, so you judge the sound, not the level. The bar shows what it is
doing, for example "Processed −2.2 dB". It only changes what you hear. It
never changes your file.

### Step 6: Listen to the Removed track

Press **3**. The **Removed** track plays only what the fixes took out, and
nothing else. It does not include the tone shaping, the EQ or mastering.

- It is marked **boosted**. The player turns it up so you can hear it.
  That boost never goes into your file.
- **It should sound like hiss, fizz, whistles or sizzle.** That means the
  fixes are taking out the problem.
- **If you hear vocals, snare hits or melody in it,** a fix is cutting
  into your music:
  1. Turn the cards off one at a time to find which fix it is.
  2. Turn that card back on.
  3. Lower its **Amount** until the music is gone from Removed.

### Step 7: Set up Mastering

Mastering gets the song ready to release. It sets the final loudness,
shapes the tone, and keeps the peaks under a safe ceiling. It is in the
**Mastering** section of the right column. **Master for release** is on
by default.

**1. Pick a Loudness target.** Click one of the three cards:

| Card | Level | What it means |
|---|---|---|
| **Commercial** (DEFAULT) | −9 LUFS | As loud as most released songs |
| **Balanced** | −11 LUFS | A little quieter, with more punch left in |
| **Streaming standard** | −14 LUFS | The level streaming apps play songs at; sounds quiet in other players |

If you are not sure, leave it on **Commercial**.

**2. Pick a Tone target.** This is the tone your song moves toward.

- **Built-in** (the default) is a tone shape measured from finished
  masters. Two menus control it:
  - **Tone match:** how far to move toward the target. **Low — gentle
    EQ**, **Medium** (the default) or **High — more correction**. It
    changes tone only, not loudness.
  - **Tilt:** from **Brightest** to **Warmer**, with **Neutral — no
    tilt** as the default. It tips the balance by up to about 2 dB at the
    ends of the range.
- **Reference track** moves your song's tone toward a released song you
  like:
  1. Click **Reference track** and pick the song.
  2. Set **Amount**: how far toward the reference to go. It starts at
     50 %. The screen advises 50 % or lower, since more can sound forced.
  3. Read the chart: **Your song**, the **Reference**, and the **EQ
     Shimmer applies**.
  4. To go back to the built-in target, click **Remove**.

  Both songs are matched in level before they are compared, so only the
  tone is matched. Loudness still follows your Loudness target.

**What mastering does, in order.** You do not need to set these. They
explain the numbers you will see later.

1. **A low-cut at 25 Hz.** A low-cut (also called a high-pass filter)
   removes sound below a set pitch. This one only removes deep rumble,
   below the bass.
2. **One steady gain** for the whole song, to reach the target.
3. **A peak shaper** that softly rounds the tallest peaks.
4. **A true-peak limiter.** A limiter holds every peak under a ceiling.
   This one holds the true peak under −1.0 dBTP for WAV and FLAC, and
   −2.0 dBTP for MP3, OGG and M4A.

**With mastering off,** the big button says **Clean** instead of **Clean
& Master**. There is no loudness target and no limiter. **Preserve
volume** (in **Output**, on by default) keeps the cleaned song at the
same level as your original.

### Step 8 (optional): Check the Suggested EQ

Analyze planned a few EQ moves. They show as **Suggested EQ** at the top
of the **Parametric EQ** section.

- The plan fixes problems first (a ringing tone, mud, a harsh band). Then
  it makes at most three broad, gentle moves to the overall balance.
- **Use on the final pass** is on by default. It puts the plan into the
  EQ by itself. Turn it off if you do not want it.
- **Apply to EQ** puts the moves into the **Parametric EQ** now. Every
  move stays editable there.
- **Family** sets how far from neutral the balance may be before a move is
  worth making. Neutral is the default. Shimmer does not guess your
  genre. The family is your call.
- The **EQ presets…** menu holds starting points for your own EQ.

### Step 9: Pick a format

Open the **Output** section and pick a **Format**:

| Format | What it is | Use it for |
|---|---|---|
| **WAV (24-bit PCM)** (default) | Full quality, at the song's own sample rate | Keeping a master, or more work in other software |
| **WAV release copy (16-bit · 44.1 kHz · dithered)** | 16-bit at 44.1 kHz, the file stores ask for | Sending to a distributor or a store |
| **FLAC (24-bit)** | Full quality, smaller than WAV | Keeping a master in less space |
| **FLAC release copy (16-bit · 44.1 kHz · dithered)** | The same audio as the WAV release copy, about half the size | Upload sites with a file size limit |
| **MP3 (320 kbps)** | Compressed. Needs ffmpeg | Listening, sharing |
| **OGG Vorbis** | Compressed | Listening, sharing |
| **M4A (AAC)** | Compressed. Needs ffmpeg | Listening, sharing |

"Dithered" means a very quiet, even noise is added when the file is made
16-bit, so quiet fades do not turn grainy.

Below the menu, Shimmer shows how big the file will be.

Also in **Output**:

- **Preserve volume:** only matters with mastering off (see Step 7).
- **Trim leading/trailing silence on export:** removes the quiet part
  (below −60 dBFS) from the start and end of the file, and keeps a short
  natural pad.
- **Remember settings next time:** see
  [section 8](#8-the-settings-tab-and-remember-settings).

### Step 10: Fill in the tags

Tags are the song details that players and stores read from the file.
Open the **Tags** section:

1. Check the **Title**. It is filled from the file. Change it if the real
   title is different.
2. Fill in **Artist**, **Album artist**, **Album**, **Genre**, **Year**,
   **Track no.** and **Copyright** as you need. A blank copyright is
   filled as "© year artist" when both are known.
3. **ISRC** is optional. An ISRC is a code that identifies a recording.
   Your distributor gives you one if you do not have one.

Three switches, all on by default:

- **Write tags on the export**
- **Keep the file's own tags:** the file's own tags stay, and your fields
  only fill the blanks. Turn it off to replace the file's tags with what
  you typed.
- **Add a Shimmer note to the comment:** one line that says what was
  done, for example which fixes ran and the loudness target.

Your artist name comes back next time, even with **Remember settings next
time** off.

### Step 11: Click Clean & Master

1. (Optional) Open the **Signal Chain** tab to see what each stage will
   do with your settings. It only reads your settings. It changes
   nothing.
2. Click **Clean & Master** (step 3 in the right column).
3. Wait. A progress window lights each stage as it runs: Read, Trim,
   Sample rate, Fixes, Tone, EQ, Master, Export, Report. A stage that does
   not run for this song is dashed.

There is no Cancel button yet, so let the run finish. If the Shimmer
card is on and has not read the song yet, that read happens now, and the
window shows it under Fixes.

### Step 12: Read the results

When the file is written, the progress window ends on a Download step
that says "Your file is ready". The Master tab then shows three things.

**The ✓ Ready to download banner**, with a **Download** button.

**What changed:** a chart of the whole song's spectrum, before and after.
A spectrum shows how much sound there is at each pitch, from low to high.
The chart shows **Before**, **After**, **Removed**, and **After minus
before, level-matched**. Hover over it for the numbers at any pitch.

**Release check:** is this file ready to upload? Shimmer opens the file it
just wrote and checks it. It only measures. It runs when mastering is on.
You get one verdict first:

- **✓ Ready to upload**
- **⚠ … to look at** (for example, "⚠ 2 things to look at")
- **✕ Not ready** (for example, "✕ Not ready · 1 problem")

Then one line for each check:

| Check | It passes when | If it does not |
|---|---|---|
| Loudness | within 0.5 LU of your target | |
| True peak | at or under the format's ceiling | An MP3, OGG or M4A passes at or under −1.0 dBTP as played back |
| Clipping in the source | the file you uploaded was not already clipped | This is about your upload, not Shimmer's file |
| Sample rate | 44.1 or 48 kHz (higher rates pass too) | |
| Format | WAV or FLAC | A compressed file is fine for listening, not for a store. Pick a WAV or FLAC release copy |
| Start, End | no long silence at the start or end | Try **Trim leading/trailing silence on export** |
| Length | 30 seconds or more | |
| DC offset | none | |
| Mono check | the left and right channels are not out of phase | |
| Bass in mono | the bass below 100 Hz does not drop more than 3 dB in mono | |
| Tags | title, artist and album are written | Fill them in under **Tags** |
| ISRC | noted, not required | Your distributor assigns one |

"Mono" means both speakers play the same signal, as on many phones and
small speakers.

Below the checks, it shows how loud the song will play on each streaming
service, and whether that service turns quiet songs up.

### Step 13: Download

1. Click **Download**, in the progress window or on the banner.
2. Find the file in your browser's Downloads folder.

The file is named after your song, for example `mysong_processed_1a2b3c4d.wav`
(or `_trimmed_` with silence trim on). To have files download by
themselves, or go straight into a folder of yours, see
[section 8](#8-the-settings-tab-and-remember-settings).

Download soon. A session you do not use for one hour is removed, with its
files.

---

## 5. Good habits

**Listen to Removed after every card.** It is the one check that catches a
fix cutting into your music. You will not always hear the damage on the
Processed track, but Removed shows it.

**Start gentle.** Turn on only the cards for problems you can hear. Leave
each Amount where it starts, then change it in small steps. Turning all
five fixes (Shimmer, Vocal grain, Sibilance, Harshness, Low-mid build-up)
up to 100 % at once can take too much.

**Compare at matched loudness.** Keep **Loudness-matched A/B** on. Switch
between **1** and **2** often. Louder fools your ears.

**Fix first, master once.** Start each new pass from your original file,
not from a file Shimmer already mastered. Mastering first and cleaning
after makes the noise louder.

**Use the release copy for stores.** Pick **WAV release copy (16-bit ·
44.1 kHz · dithered)**, or the FLAC release copy if your upload site has a
size limit. Use MP3, OGG and M4A for listening and sharing.

**Before you upload, check that:**

- [ ] The **Release check** says **✓ Ready to upload**, or you have read
      each line it flagged.
- [ ] The format is a WAV or FLAC release copy (or what your distributor
      asks for).
- [ ] **Title**, **Artist** and **Album** are filled in.
- [ ] The **Removed** track holds only noise, no music.
- [ ] You played the whole finished song once, not only the loop.
- [ ] There is no click or cut-off at the very start or end. If there is,
      use the **Trim** card on the Master tab. It can also fade the song in
      or out.
- [ ] The file is under your upload site's size limit, if it has one.

---

## 6. Batch a folder, and album mode

The **Batch** tab runs every song in a folder through the same sound path
as the Master tab, one file at a time.

1. Open the **Batch** tab.
2. Under **Input folder**, type or paste the folder's path, or click
   **Browse…**. Batch reads the WAV, MP3, FLAC, OGG and M4A files in that
   folder, but not in folders inside it.
3. Under **Output folder (optional)**, pick where the finished files go.
   Leave it blank to make a new folder with `_deshimmered` added to the
   input folder's name.
4. Under **Preset**, pick a preset. Batch still shows the 1.x preset
   menu. Each preset turns on the card it became (for example, Suno Hash
   turns on Shimmer). **Generic** turns on no card. Fixed tones are found
   and cut in each file either way.
5. Under **Processing**, pick the **Output format**.
6. Choose the options you want:
   - **Preserve volume**
   - **Trim leading/trailing silence**
   - **Apply EQ from Master tab:** the EQ bands you set on the Master
     tab.
   - **Suggested EQ per file:** plans a short EQ for each file on its own.
     Pick its **Family for the suggested EQ**.
   - **Write tags from the Master tab:** your artist, album and other
     tags. Each file keeps its own title, or takes it from its file name.
7. Set mastering: **Master for release**, **Loudness target**, **Tone
   match** and **Tone** (the tilt).
8. For an album or EP, turn on **Album mode** (see below).
9. Click **Process All**.
10. Watch the **Log**. It shows one line per file as it goes: the length,
    the peaks, the loudness and true peak, the release check, and what
    was found. A file that could not be done shows **FAILED** and the
    reason.

Notes:

- A file with the same name in the output folder is replaced. Your source
  files are never written over.
- **Preset strength (no effect in 2.0)** and **Auto-detect each file** do
  not change anything in 2.0.
- Batch has no Cancel button. The only way to stop a batch early is to
  stop Shimmer (see [section 2](#keep-the-window-open)).

### Album mode

Without album mode, every song is brought to the loudness target on its
own. A quiet ballad would end up as loud as the single.

Album mode masters the folder as one record. It keeps the songs' levels
in step:

1. **Pass 1** measures every song. Nothing is written.
2. Shimmer works out **one gain** that brings the loudest song to the
   target. The log shows the loudest song, the gain, and the spread from
   the loudest to the quietest song.
3. **Pass 2** renders every song with that one gain. The quieter songs
   stay quieter than the loudest one, by the same amount as before.

Album mode needs **Master for release** on. Each song's release check
grades its loudness against the level album mode gives it, not against the
target.

---

## 7. Remix: split a song into stems

Stems are the separate parts of a song, such as vocals, drums and bass.
The **Remix** tab splits a song into stems, lets you change the balance
and add effects, then renders a mastered remix. Its steps show across the
top: **1 Upload**, **2 Separate**, **3 Mix & Render**.

1. Open the **Remix** tab.
2. Drop a song on the box, or click **Choose file…**.
3. Under **How many stems?**, click a choice. This starts the split.

   | Choice | Stems | First download |
   |---|---|---|
   | **Fast** | vocals, drums, bass, other | about 80 MB |
   | **Best** | the same four, from a fine-tuned model; about 2.5 times slower than Fast | about 330 MB |
   | **6 stems** | adds guitar and piano (experimental) | about 80 MB |
   | **Ultra** | four stems, three models blended; the slowest | 160 MB more than Best |
   | **Studio** | four stems, with a separate vocal model | 915 MB, plus about 300 MB for its runner |

4. **The first time only,** Shimmer installs its separation engine. The
   screen says "Separation engine not installed · the first Separate
   installs it (about 3 GB, one time)". You need the internet for this,
   and for each model the first time you pick it. After that, Remix works
   offline.
5. Wait for the split. With an NVIDIA graphics card, a four-minute song
   takes about 10 seconds at Fast and 25 seconds at Best. Without one, it
   takes several times longer. Stems are kept, so a song only waits once.
6. Mix the lanes. Each stem gets a lane with:
   - mute and solo
   - a fader (the lane's level) and pan (its place from left to right)
   - an **FX** rack: formant (the character of a voice, without changing
     its pitch), saturation (warmth and drive), doubler (thickens a part)
     and reverb (room and depth)

   A **Residual** lane holds what the separator left out, such as reverb
   tails and most of the AI fizz. With it in the mix, an untouched remix
   matches your original.
7. Try the **Quick** buttons if you like: **Instrumental** (vocals
   muted), **Acapella** (vocals alone), **Vocal lift** (vocals up 2 dB)
   and **Reset** (every lane back to neutral).
8. Listen. Live preview is always on in Remix. Press **1** for the
   **Original** and **2** for the **Remix**. The loop plays at once, marked
   "level approximate". A few seconds later it switches to the export's
   own render and says "matches the export".
9. Set **Mastering**: **Master the remix**, **Loudness target**, **Tone
   match** and **Tilt**.
10. Set **Artifact cleanup on export**. **Auto — find and cut fixed tones
    in the remix** is the default. **Off — export the mix as-is** skips
    it. The old 1.x presets are on this menu too, and each one turns on
    its card.
11. Pick a **Format**.
12. Click **Render & Download**. When it is done, you see **✓ Remix
    rendered** and a **Download** button.

**To download the stems themselves,** open the **Stems** section:

- **Download stems as separated:** every lane exactly as split, so the
  files add back up to the original.
- **Download stems with this mix:** each lane through its fader and
  effects. Muted lanes are left out.

Both give you a ZIP of 24-bit WAV files, one per lane.

Your Remix settings save as you work. Open the same song again and they
come back, with its stems.

---

## 8. The Settings tab and "Remember settings"

### The Settings tab

The **Settings** tab has one card, **Downloads**. It says what happens
when a run finishes.

- **Download automatically when a run finishes:** the file starts
  downloading as the run ends. The Download step stays as a backup.
- **Download location:**
  - **My browser's Downloads folder** (the default).
  - **This folder:** Shimmer writes the finished file straight into a
    folder you pick. Type the path or click **Browse…**. The Download
    step then offers **Show in folder** and **Download a copy**.
- **Size limit:** turn on **Warn when a file is over** and set a size in
  MB (50 by default). Set it to the largest file your upload site takes.
  If a file will be too big, Shimmer warns you and offers a lossless
  format that fits (lossless means no quality is lost, as with WAV and
  FLAC). It offers MP3 only when nothing lossless fits. It never changes
  the format or cuts the song by itself.

These choices come back every time you open Shimmer.

### Remember settings next time

This switch is in the **Output** section of the Master tab. It is off at
first.

- **On:** your card picks, mastering, EQ, format and other Master choices
  come back on your next visit. Your own card picks also stay when you
  load a new song.
- **Off:** each time you open Shimmer, the Master tab starts from the
  defaults.

Either way, your tags (such as your artist name), the Settings tab
choices, and the Suggested EQ family come back.

One settings file serves every copy of Shimmer you have open. The Batch
tab reads the Master tab's EQ, tags and family from it.

---

## 9. The command line in three examples

The command line runs one song through the same sound path as the Master
tab. It is useful for scripts.

1. Open a terminal in the Shimmer folder.
2. Use Shimmer's own Python to run it:
   - **Windows:** `.venv\Scripts\python -m shimmer`
   - **macOS and Linux:** `.venv/bin/python -m shimmer`

The examples below show the Windows form. On macOS and Linux, use
`.venv/bin/python` instead.

**Example 1: master a song at Commercial (−9 LUFS).**

```
.venv\Scripts\python -m shimmer "my song.wav" "my song master.wav" --target cd
```

Fixed tones that Shimmer finds are cut too. Add `--no-auto` to turn that
off.

**Example 2: make the release copy for a store.**

```
.venv\Scripts\python -m shimmer "my song.wav" "my song release.wav" --master --release
```

`--release` writes 16-bit at 44.1 kHz with dither.

**Example 3: turn on cards, with an Amount from 0 to 1.**

```
.venv\Scripts\python -m shimmer "my song.wav" "my song master.wav" --master --fix sibilance --fix harshness=0.8
```

Good to know:

- The output format follows the output file's ending: `.wav`, `.flac`,
  `.mp3`, `.ogg` or `.m4a`.
- On the command line, mastering is off unless you add `--master` or
  `--target`.
- `--list` prints the cards, loudness targets, formats, and which 1.x
  preset became which card.
- `--help` prints every option. [FEATURES.md](FEATURES.md#9-command-line)
  lists them all.

---

## 10. If something goes wrong

### Common problems

| What you see | What to do |
|---|---|
| The launcher asks `Install uv now? [Y/n]:` and you said no | Install uv yourself, then launch again. Windows: `winget install --id=astral-sh.uv -e`. macOS: `brew install uv` |
| "uv was installed but this window cannot see it yet" | Close the window and start Shimmer again (Windows). Open a new terminal and run `./start.sh` again (macOS, Linux) |
| The window closes at once | Open a terminal in the Shimmer folder and run `start.bat` (or `./start.sh`) from there, so you can read the message |
| macOS: "permission denied" | Run `chmod +x start.sh`, then `./start.sh`. Or run `bash start.sh` |
| "ERROR: the audio libraries did not install correctly." | Scroll up in the window for the reason. Common causes: no internet, a company proxy or antivirus blocking downloads, or low disk space |
| "ERROR: port 7860 is still in use and could not be freed." | Another program is using that port. Start Shimmer on another one. Windows: `set SHIMMER_PORT=7870 && start.bat`. macOS, Linux: `SHIMMER_PORT=7870 ./start.sh`. Then open <http://localhost:7870> |
| The browser opens, but the page does not load | Wait a few seconds and refresh. The first start is the slow one |
| "ffmpeg is needed for MP3 and M4A files. Install ffmpeg and add it to PATH." | Install ffmpeg (see [section 1](#1-what-you-need)) and restart Shimmer. Or use a WAV, FLAC or OGG file |
| Icons show as words | You are offline. The icon font loads from the internet. Everything still works |
| **2 Processed** and **3 Removed** do nothing | Turn on **Live**, or run **Clean & Master** first |
| The preview is slow after you turn on **Shimmer** | This is the first read of the song: about 50 seconds for a 3-minute song. Watch the status line at the bottom |
| "Download failed" and "the result is gone" | Shimmer was restarted since the run. Run **Clean & Master** again |
| The export is quieter than other songs | Check that **Master for release** is on, and that the **Loudness target** is **Commercial** |
| The result sounds dull, or cymbals lost their sparkle | Lower the **Amount** on **Vocal grain**, **Shimmer** or **Sibilance**. Turn off any card for a problem you cannot hear. With Vocal grain on, try **Works on: Vocal only** |
| Vocals sound lispy, or the "s" sounds went missing | Lower the **Amount** on **Sibilance** |
| The low end or the voice feels thin | Lower the **Amount** on **Low-mid build-up**, or turn it off. Check the **Parametric EQ** for a cut you did not mean |
| A warble or an "underwater" sound appeared | Lower the **Amount** on **Shimmer**. Try half and listen again |
| The **Removed** track has music in it | Turn cards off one at a time to find the fix. Lower its **Amount** until only noise is left in Removed |
| Batch **Browse…** does not open (macOS, Linux) | Type or paste the folder path instead. Homebrew users can run `brew install python-tk` |
| Remix is slow | Without an NVIDIA card, separation runs on the CPU and takes several times longer. It only waits once per song and choice |

More help is in the app: **Help**, then the **Troubleshoot** tab. If you
are still stuck,
[open an issue](https://github.com/henricksmedia/shimmer/issues) and paste
what the black window says.

### Where Shimmer keeps its files

| What | Where |
|---|---|
| The app and its libraries | The Shimmer folder, with its libraries in `.venv` |
| The Remix separation engine | `.venv-stems` in the Shimmer folder |
| Stems you split | `stem_cache` in the Shimmer folder |
| Your settings | `settings.json` in `%APPDATA%\Shimmer\` on Windows, or `~/.config/shimmer/` on macOS and Linux |
| Remix projects | The `projects` folder, in the same place as your settings |
| Recent sessions, and "noted" card picks | Your browser's own storage |
| Songs and exports while you work | Temporary folders, removed after one hour unused |
| Finished files | Your browser's Downloads folder, or the folder you set in **Settings** |

To remove Shimmer, delete the Shimmer folder. To remove your saved
settings too, delete the settings folder. uv is a separate tool and stays
installed.

---

## 11. What is not in 2.3.0 yet

- **Clicks and crackle and Phasiness have no working fix.** The de-click
  is built but has not passed its tests, so the card says **Not built
  yet**. (The command line can run it with `--fix clicks`.) Phasiness
  says **No fix yet**. Both cards change nothing.
- **Remix and Batch still show the old preset menu.** Each preset turns on
  the card it became. In Batch, **Preset strength** and **Auto-detect each
  file** do nothing.
- **The Advanced artifact controls drawer is still on the Master tab.** Its
  sliders do not change the sound.
- **No screen has a Cancel button,** Batch included. Turning the Shimmer
  card off does stop its first read of a song.
- **Icons show as words when you are offline.**
- **The fixes marked "On, to try" have not had their blind listening
  tests yet.** With all four at 100 %, two of five test songs lost a
  little more than one fix is allowed to take.

The full list is in [FEATURES.md, Known limits](FEATURES.md#10-known-limits-in-200).
