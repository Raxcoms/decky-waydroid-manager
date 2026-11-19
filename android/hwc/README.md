# External display payload

The plugin carries an external-display adaptation for Waydroid's Lineage 20
composer at `a575cfcc12ab79a122844218f2c6df5bd208cca0`. It connects to a
host-provided Wayland output; sizes and timing come from that compositor.
There are no device names, DRM connectors, or panel rules.

The starting implementation is adapted from virtudude's external-display work
in Armada's Lepton sources. The plugin owns and builds this adaptation; the host
does not need Armada's Android patch. Upstream licenses and bundled library
notices are included with each CI-built native bundle.

## Build

The regular plugin build compiles the composer and adapter using the
[standalone native recipe](../native/README.md). It fetches only the required
dependencies into the build cache. Compiled files are not tracked in Git.

Enabling second-screen support reads framework-res.apk and SystemUI.apk from the
installed Android image. The plugin's private compiler builds the resource
overlays against those files, then signs them with a locally generated identity.
This requires no host package installation or device downloads. The cache is
invalidated by changes to the image resources, tool bundle, or owned recipe.

Test normal launch, secondary-home presentation, navigation on both displays,
live frame changes, release, backend exit, and an ordinary Waydroid launch afterward.

## Runtime

The temporary properties select the external socket and control its hotplug
lifecycle. The framework overlay disables mirroring and enables independent
display focus. Vendor defaults enable Android's secondary home and local input
method on the external Android display. Existing vendor-overlay display settings
are merged into staging and left unchanged on disk.

The navigation resource overlay supplies the System UI theme on secondary navbar
views. Without it, Android 13 creates functional buttons with transparent icon
colors. It is compiled with the installed System UI resource table; cache
selection checks that APK's hash as well as the framework resource hash.

Recents uses Android's app-switch key so it also appears on the secondary bar.
The task switcher opens on the primary display. This keeps the resource overlay
small and does not add a separate task switcher.

Native selection checks SDK, VNDK, ELF architecture, required Binder exports, and
the Binder vtable size derived from the compiled headers. A compatible image can
generate its own resource overlays. Unsupported native interfaces fail before
mounting; ordinary shortcuts keep their existing frame-limit fallback. Device
model detection is not involved.
