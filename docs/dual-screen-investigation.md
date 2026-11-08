# Experimental second screen

## Status

This is an investigation plan. The current Waydroid hardware composer exposes one Android display, so there is no safe configuration switch that can add an external display.

The eventual feature must make Android behave as though a USB-C monitor is connected. Moving a Waydroid app window to another host output is not enough because Android still reports one display to the app.

## User experience

The Android app menu will eventually show **Enable second screen support** or **Disable second screen support**. The full Waydroid menu will provide the same choice for the container launch.

Selecting Enable opens a confirmation dialog that says the feature takes effect after a reboot. A selection changes only Waydroid Manager state. It must not change the installed Waydroid image or an ordinary Waydroid launch.

The full-container setting applies to full launches. An app setting overrides the container setting for that app. Removing an app also removes its saved setting.

## Required runtime boundary

Waydroid already supports rootfs overlays. It mounts `/var/lib/waydroid/overlay` over the system image and `/var/lib/waydroid/overlay/vendor` over the vendor image before it starts the container. This is the correct deployment point for a matching external-display HWC because the original images remain unchanged.

The overlay is global while Waydroid is running, so the launch path must still own its lifecycle:

- stage only a matching, primary-display-compatible HWC in the vendor overlay;
- bind Armada's existing `gamescope-secondary` socket into the container as `wayland-1` before Waydroid starts;
- add `waydroid.wayland_display_ext=wayland-1` only to the generated properties for that launch;
- remove the staged HWC and temporary mount when the plugin launch ends.

The launcher must never acquire or release the DRM lease. Armada's persistent bottom Gamescope owns that lease and yields it as needed. The HWC maps its external Wayland surface only while Android has content for it; unmapping it returns the panel to the compositor and its previous user.

An interrupted cleanup must leave a normal launch safe. The staged HWC therefore has to retain the stock primary path and treat a missing `wayland-1` socket as no external display. Disabling the feature removes the plugin overlay and temporary configuration, restoring the stock HWC on the next container start. Do not alter `/var/lib/waydroid/images` or the host's DRM-lease service.

## Hardware composer work

The patched HWC needs to:

1. Keep the existing primary display unchanged.
2. Create a second display context with separate buffers, fences, dimensions, and presentation timing.
3. Report the external display through Android's HWC hotplug callback after Android boot.
4. Present that display through a distinct Wayland toplevel, allowing Gamescope to place it on a physical or virtual output.
5. Support Android's per-display prepare, set, configuration, power, and VSync requests.

The current HWC uses only `HWC_DISPLAY_PRIMARY`; it does not have an external-display implementation to enable with a property. The patched library must be built for the exact Waydroid Android and vendor-image ABI used by the device.

## Android launch policy

After Android sees the external display, a plugin-owned privileged helper must launch the selected activity on it. It should use Android's display-aware activity launch API and leave existing app data and system settings unchanged. The first implementation can use a non-touch external display; pointer and touch routing can be added after display presentation is reliable.

## Safety checks

Before using the enable action, the runtime must verify all of the following:

- the matching HWC payload is bundled and its architecture matches the device;
- Waydroid is stopped and no unrelated Waydroid session is active;
- the Armada `gamescope-secondary` socket is present and can be bound as `wayland-1`;
- the launcher can stop its container and remove all temporary mounts on normal exit, crash, and cancellation.

If any check fails, the feature remains unavailable and standard Waydroid launching continues unchanged.

## Validation

Validation must cover both scopes and both cleanup paths:

1. Enable the setting for one app and verify that only its plugin launch reports two Android displays.
2. Enable the container setting and verify a full plugin launch reports two Android displays.
3. Stop the Steam shortcut, then start Waydroid outside the plugin and verify it reports one display and uses the stock HWC.
4. Remove the plugin while the setting is enabled, then start Waydroid normally and verify it still uses the stock image and one display.
5. Reboot during a plugin-owned second-screen launch and verify the next normal Waydroid start remains unchanged.
6. Test an Android app launched on the external display, display removal, rotation, suspend and resume, and a disconnected host output.

No user-facing toggle should be added until the private runtime path and at least one matching HWC payload pass these checks on hardware.
