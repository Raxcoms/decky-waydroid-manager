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
2. Run `scripts/build_hwc.sh ANDROID_SOURCE_DIRECTORY OUTPUT_DIRECTORY`.
   It checks the pinned composer revision, applies the composer and adapter
   patches, and builds the native libraries and framework resource overlay.
3. Inspect the target vendor image with `inspect_vendor` from
   `py_modules/waydroid_manager/display_payload.py` and save its `VendorIdentity`
   fields as JSON.
4. Run `python scripts/bundle_display_payload.py OUTPUT_DIRECTORY IDENTITY.json`.
   This records hashes, sources, and licenses under `bin/display-payloads`.
5. Test normal launch, secondary-home presentation, navigation on both displays,
   release, reconnection, backend exit, and an ordinary Waydroid launch afterward.

For a native-only rebuild, `scripts/build_framework_overlay.py` can build the
resource overlay with Android SDK build tools 35 and the Android 28 platform.
Pass its APK as `WAYDROID_MANAGER_OVERLAY_APK` to `build_hwc.sh`. The SDK script
requires an explicit signing key and certificate; never bundle private keys.

## Runtime

The temporary properties select the external socket and control its hotplug
lifecycle. The framework overlay disables mirroring and enables independent
display focus. Vendor defaults enable Android's secondary home and local input
method on the external Android display. Existing vendor-overlay display settings
are merged into staging and left unchanged on disk.

Payload selection checks the original composer and adapter hashes, vendor
fingerprint, SDK, ELF architecture, and every runtime payload file. A different
Waydroid image needs its own validated payload. Device detection is not involved.
