## Spectrum Visualizer Requirements

Build a **stylized audio spectrum visualizer** for Shimmer’s player that shows the current audio state: **Before / Source**, **After / Master**, or **Removed Signal**.

### Core Requirements

* Display a wide horizontal spectrum panel inside the audio player.
* Show frequency energy from low frequencies on the left to high frequencies on the right.
* Use a colorful gradient spectrum line/fill for the active audio signal.
* Include a subtle mirrored lower waveform/reflection for depth.
* Add a small status label in the top-left:

  * `BEFORE · SOURCE`
  * `AFTER · SHIMMER`
  * `REMOVED · SIGNAL`
* Animate the spectrum during playback.
* Show a static idle state when audio is paused or not loaded.
* Keep the visual smooth, premium, and non-technical.

### Playback States

The visualizer must update based on selected mode:

* **Original**: shows the uploaded source track.
* **Master**: shows the selected Shimmer master.
* **Removed Signal**: shows what Shimmer removed from the track.

### Visual Style

* Dark glass/black background.
* Soft smoky texture or glow behind the spectrum.
* Rounded container corners.
* Thin bright spectrum line with translucent filled body.
* Gradient colors may move from blue/teal to green/yellow/orange/pink.
* Avoid cluttered axes, numbers, or engineering labels in the main UI.

### Important Rule

This is a **listening aid and visual identity element**, not the primary diagnostic tool. Real diagnostics should appear separately as plain-language findings like mud, harshness, loudness, stereo width, and true peak risk.
