# External display composer

This patch is being adapted for Waydroid's Lineage 20 hardware composer at
`a575cfcc12ab79a122844218f2c6df5bd208cca0`.

It is not yet built or enabled by the plugin. Do not install it into a live vendor
image until the build and display lifecycle tests pass.

The implementation uses `waydroid.wayland_display_ext` to connect to the external
Wayland socket supplied for a plugin session. Display sizes come from the host
compositor. There are no device names, DRM connectors, or panel rules.

The starting implementation is adapted from virtudude's external-display patch
in Armada's Lepton sources. The plugin carries and builds its own adaptation;
the installed host does not need that patch. Upstream source licenses apply.

## Build workspace

Run `scripts/prepare_hwc_build.sh` with a dedicated Linux build directory to fetch
the Lineage 20 and Waydroid sources. The script records resolved source revisions
in `source-manifest.xml` after synchronization.

The completed payload will need to include the compiled library and its source
manifest. Selection must check Android architecture, vendor ABI, and the original
composer hash before any overlay is activated.
