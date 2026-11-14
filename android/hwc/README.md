# External display payload

The plugin carries an external-display adaptation for Waydroid's Lineage 20
composer at `a575cfcc12ab79a122844218f2c6df5bd208cca0`. It connects to a
host-provided Wayland output; sizes and timing come from that compositor.
There are no device names, DRM connectors, or panel rules.

The starting implementation is adapted from virtudude's external-display work
in Armada's Lepton sources. The plugin owns and builds this adaptation; the host
does not need Armada's Android patch. Upstream licenses and bundled library
notices are included with each payload.

## Build

1. Run `scripts/prepare_hwc_build.sh` with a dedicated Linux build directory.
   Android sources and build outputs need substantial disk space and memory.
2. Build the two resource overlays with `scripts/build_framework_overlay.py`.
   Supply Android SDK build tools 35, the Android 28 platform, a signing key and
   certificate, and `--system-ui` pointing to `SystemUI.apk` extracted from the
   target image. Never bundle private keys. Keep the outputs in the native build's
   output directory, or set `WAYDROID_MANAGER_OVERLAY_APK` to the framework APK.
3. Run `scripts/build_hwc.sh ANDROID_SOURCE_DIRECTORY OUTPUT_DIRECTORY`.
   It checks the pinned composer revision, applies the composer and adapter
   patches, and builds the native libraries and framework resource overlay.
4. Inspect the target images with `inspect_vendor` from
   `py_modules/waydroid_manager/display_payload.py` and save its `VendorIdentity`
   fields as JSON.
5. Run `python scripts/bundle_display_payload.py OUTPUT_DIRECTORY IDENTITY.json`.
   This records hashes, sources, and licenses under `bin/display-payloads`.
6. Test normal launch, secondary-home presentation, navigation on both displays,
   release, reconnection, backend exit, and an ordinary Waydroid launch afterward.

## Runtime

The temporary properties select the external socket and control its hotplug
lifecycle. The framework overlay disables mirroring and enables independent
display focus. Vendor defaults enable Android's secondary home and local input
method on the external Android display. Existing vendor-overlay display settings
are merged into staging and left unchanged on disk.

The navigation resource overlay supplies the System UI theme on secondary navbar
views. Without it, Android 13 creates functional buttons with transparent icon
colors. It uses the target System UI resource table; selection checks that APK's
hash as well as the native vendor ABI.

Recents uses Android's app-switch key so it also appears on the secondary bar.
The task switcher opens on the primary display. This keeps the resource overlay
small and does not add a separate task switcher.

Payload selection checks the original composer and adapter hashes, vendor
fingerprint, SDK, ELF architecture, and every runtime payload file. A different
Waydroid image needs its own validated payload. Device detection is not involved.
