# Performance investigation handoff

This document records the remaining performance and startup work from the Nova
investigation. The current implementation and these findings are not a complete
fix for the issues below.

## Current state

- Branch: `fix/install-startup`. The audio accounting change is in `366e060`;
  its CI build integration is in `573b689`.
- CI run [45932852257](https://github.com/Raxcoms/decky-waydroid-manager/actions/runs/45932852257)
  passed for `c6d35f3`, which contains the buffer-cache fix. Nova is restored
  to that build and the plugin has been reloaded after the timing experiment.
- The temporary timing and logging experiments are on `fix/phase-test`, not the
  working branch. They contain a Nova-specific test value and must not be merged
  as a production solution. `fix/audio-loop` also contains diagnostic work.
- Steam composition must not be forced. Keep display handling device-independent,
  preserve direct scanout, avoid continuous diagnostic polling, and do not require
  installing or overlaying host system packages on immutable Armada devices.

## Motion wobble and frame pacing

### What was observed

Super Hexagon on Nova shows recurring periods of smooth motion followed by a
visible trembling or catch-up effect. The user also previously observed startup
switching between 60 and 120 FPS and intermittent flicker and wrong colors.
Those earlier symptoms have not been conclusively reproduced or resolved in the
latest tests. A refresh-matched HWC timing experiment reduced the visible effect,
according to the user, but did not remove it.

During a synchronized one-minute capture, MangoHUD showed frame-time variation
of about 5.5 to 11 ms during a strong wobble. Independent DRM vblank measurements
stayed near 8.32 to 8.34 ms. Gamescope's per-app frame counter and Android's
reported presentation timestamps were close to the physical cadence where the
samples overlapped. These interfaces measure different stages; their agreement
or disagreement does not by itself establish which image was scanned out. The
Android surface timestamp ring buffer also had gaps between samples.

The game's Android buffer-ready times drifted against physical vblank. In one
capture their average was about 8.333 ms, compared with about 8.330 ms for the
physical display. The game render thread was observed sleeping in
`ofTimer::waitNext()` inside its openFrameworks library. This supports an
independent game timer as a contributor, but does not prove it is the only
cause of visible wobble.

A temporary test gave Android the measured display period at startup. Android
accepted it, but the game buffer-ready cadence stayed near 8.333 ms and the
MangoHUD variation remained. The actual display period also changed slightly
between captures. Do not use the diagnostic's fixed period as a general fix.
A short comparison of different callback offsets was inconclusive.

### Latest display comparison

One-minute captures on Nova compared the normal blocking acquire-fence wait
with an experimental DMA-BUF fence import on the `test/hwc-trace` branch. In
the 59 complete seconds available for comparison, the blocking capture had
about 4 discarded presentation feedback events per second. The experiment had
about 0.3 per second, and its Android HWC made about 120 imports per second
without blocking acquire waits. Gamescope reported 365 intervals above 12.5 ms
in the first capture and 140 in the second. These were separate runs, not a
controlled benchmark. The verified screenshot after the second capture showed
the game's stage-complete screen; the captures do not prove a gameplay fix.

The worst MangoHUD seconds correlated strongly with missed Gamescope intervals
in the blocking capture, but not in the experiment. The experiment still had
frame-time variation, so missed presentations are not the whole explanation.
Physical vblank stayed near 120 Hz. Android SurfaceFlinger was using client
composition during the test; this does not mean Steam composition was enabled.

A later per-frame capture found that the Android HWC received the geometry
changed flag on every frame. Over ten seconds, it cycled through three native
buffer handles but created 1,199 different Wayland buffers, because the current
implementation clears its entire import cache on each geometry change. None of
those tracked buffers reached the release callback before retirement. In the
one-minute capture, per-second MangoHUD frame-time variation correlated with
discarded Wayland presentations (0.90), and was also associated with longer
acquire-fence waits. During the worst periods, commits arrived later in the
physical display cycle. This is evidence of a Waydroid-side bottleneck; it does
not establish that cache churn is its sole cause.

The production fix keeps imported buffers across geometry updates, validates
backing identity before reuse, tracks compositor releases without software sync,
and evicts unused cache entries using Android's buffer-slot limit. On Nova,
software-sync creation attempts fell from 361 to 2 over three seconds. A normal
Android release fence is still unavailable on hosts without `/dev/sw_sync`, so
producer-to-compositor ownership remains an open correctness concern.

At a 14 FPS cap, a 30-second synchronized trace showed Android vsync and
submission intervals near 71.4 ms. Wayland presentation feedback was mostly
67 or 75 ms, consistent with sampling a 120 Hz display. At 40 FPS, most
feedback intervals were near 25 ms, with some 17/33 ms pairs. Gamescope's
per-app query also reported short/long pairs that did not match those Wayland
feedback timestamps. These are compositor-reported times, not independent
proof of physical scanout.

A phase-alignment experiment did not materially improve the 40 FPS Gamescope
query and was not merged. A separate earlier-vsync experiment, with synchronized
Wayland feedback, was tested as `9756f60`. At 120 FPS, the baseline 30-second
trace had 78 discarded
presentation-feedback events among 3,485 Android submissions; longer acquire
waits coincided with the worst intervals. Pairing feedback with submissions in
arrival order, 61 of the 78 discards followed commits within 4 ms of the next
measured vblank; commits with more margin were usually presented. Feedback may
arrive out of order, so this pairing is an indication to test rather than proof
of individual frame causality.

The earlier-vsync test moved commits approximately 2 ms earlier in the display
cycle, but also produced 78 discarded feedback events in about 3,483 submissions.
MangoHUD frame-time standard deviation increased from 1.10 ms to 1.55 ms in
these separate captures. This does not support shipping the phase adjustment.
The audio service averaged about 1.9% of one CPU core during the test; longer
validation is still required.

The test initially tried every native-handle file descriptor, including a
metadata memfd. A short ioctl trace showed that importing the metadata failed.
The revised test imports only the image planes already identified by the Cros
gralloc handler, and falls back to the original wait elsewhere. This remains a
diagnostic only. Without a working release fence, it is not established that
Android can safely reuse buffers after handing them to the compositor. Do not
ship the asynchronous path until ownership and synchronization are proven on
supported image and compositor combinations. The experiment does not force
Steam composition or copy frames.

### Remaining work

1. Trace the timing from game buffer submission through Android, the Waydroid
   HWC and Gamescope to the actual displayed image. Correlate full-frame
   timestamps and use a low-overhead capture that does not create the stutter.
2. Determine how the game timer interacts with Android buffer backpressure and
   physical presentation. Check other Android games before generalizing from
   Super Hexagon or adding an app-specific workaround.
3. Nova does not expose `/dev/sw_sync`. The current fallback restores launch
   compatibility but cannot provide the normal Wayland release fence. A GPU-copy
   prototype provided safer ownership at a measurable cost and did not improve
   the user's reported jitter. Do not merge it on that evidence. Investigate
   a portable, copy-free release-fence path and verify its cost and correctness
   before using it. DRM sync objects are available on Nova, but an empty
   unsignaled sync object could not be exported as a sync file in a simple test.
4. Revalidate live limiter changes, arbitrary caps, startup at 120 FPS, single
   and dual-screen shortcuts, and visual output on supported devices. Confirm
   that MangoHUD statistics continue to describe the primary screen.

Relevant implementation: `android/native/frame_clock.h`,
`android/hwc/adaptive-presentation.patch`, `android/hwc/frame-rate.patch`,
and `py_modules/waydroid_manager/display_frame_limit.py`.

## Audio CPU usage

An Android audio service writer was observed using almost one full CPU core
while blocked in the ALSA Pulse playback path. Restarting that guest service
returned its usage to around 1% and the user reported quieter fans and working
audio. Motion jitter remained, so the audio load is a separate problem.

A first patch to drain stale Pulse poll notifications did not prevent the loop
from returning during a longer device test. It was reverted, then reintroduced
alongside the counter correction below. Do not claim that the full busy-loop
issue is resolved solely from a short healthy sample.

Instrumentation confirmed that the playback bridge can write more bytes than
its capped `last_size` counter: observed examples were 4,096 bytes against
4,092 and 4,092 against 2,048. The original unsigned subtraction wraps. The
current branch bounds that subtraction and retains the stale-notification fix.
The corrected diagnostic ran for 90 seconds with the writer around 0–2% of a
core; the production module was verified loaded on Nova and a retry produced
an active audio stream. The intermittent high-CPU loop has not been reproduced
since that fix, and a longer validation is still needed.

The audio module is built from pinned upstream sources in CI and cached. The
plugin checks image SDK, library architecture, exports and required symbols,
and preserves existing user audio overrides. It applies compatible files through
its launch-scoped vendor overlay. Unsupported images skip the module; no device
compiler or host package installation is required.

### Remaining work

1. Run longer sessions and repeated cold starts with audio, including the
   conditions that originally triggered high CPU. Check sound and fan behavior.
2. If the loop returns, capture the writer's stack and poll system calls while
   it is spinning. The isolated diagnostic branch can report Pulse readiness,
   ring pointers and buffer sizes; avoid leaving its logging or test period in
   the production build. Distinguish a stale wakeup from ALSA/Pulse readiness
   disagreement before changing the fix.
3. Validate compatible and incompatible image behavior, user-provided vendor
   overrides, 32-bit and 64-bit modules, crash recovery, and plain Waydroid after
   the plugin session closes or the plugin is removed.

Relevant implementation: `android/audio/readiness.patch`,
`android/audio/sources.json`, `scripts/build_audio.py`, and
`py_modules/waydroid_manager/audio_payload.py`.

## Shortcut startup timeout

During the final Nova validation, the first launch on build `573b689` reported
that Android did not activate the requested display mode within the two-second
wait. The subsequent `am start -W` returned `Status: timeout` after about ten
seconds for Super Hexagon's activity, so the plugin ended the launch. A retry
reached the resumed game activity and started the audio stream. Similar
intermittent startup timeouts appeared during diagnostic builds; their cause is
not established.

Reproduce from a cold plugin-owned session, capture the display-mode transition,
activity state, HWC and relay presentation together, and determine whether this
is a readiness race or a genuine failure to draw. Do not treat a resumed
activity alone as proof that a usable frame is visible. Fix the ordering or
readiness check and add regression coverage without weakening permission-dialog
and failed-launch handling.

Relevant implementation: `py_modules/waydroid_manager/display_frame_limit.py`,
`py_modules/waydroid_manager/guest.py`, `py_modules/waydroid_manager/session.py`,
and `main.py`.

The duplicate-mode warning was traced to equivalent Android modes with different
IDs. Commit `0259c8c` accepts matching resolution and refresh rate and adds
tests. Two Nova cold launches then succeeded without the warning. This does not
by itself establish the cause of every intermittent activity timeout.
