# Experimental second screen

## Status

This is an investigation plan. The current Waydroid hardware composer exposes one Android display, so there is no safe configuration switch that can add an external display.

The eventual feature must make Android behave as though a USB-C monitor is connected. Moving a Waydroid app window to another host output is not enough because Android still reports one display to the app.

## User experience

The Android app menu will eventually show **Enable second screen support** or **Disable second screen support**. The full Waydroid menu will provide the same choice for the container launch.

Selecting Enable opens a confirmation dialog that says the feature takes effect after a reboot. A selection changes only Waydroid Manager state. It must not change the installed Waydroid image or an ordinary Waydroid launch.

The full-container setting applies to full launches. An app setting overrides the container setting for that app. Removing an app also removes its saved setting.

## Required runtime boundary

Waydroid mounts `/var/lib/waydroid/overlay/vendor` before starting its container. Replacing `hwcomposer.waydroid.so` there is technically possible, but it is not acceptable for this feature:

- the overlay is global to Waydroid, not the plugin;
- a failed cleanup or plugin removal could affect ordinary Waydroid starts;
- the library is loaded when the Android container starts, so copying it while Android is running cannot change the active hardware composer.

The feature therefore needs a plugin-owned container start path. It must create the vendor mount and start the container inside a private mount namespace, with the patched HWC bind-mounted only in that namespace. The Steam launcher owns that namespace and stops the container before it exits. Once the launcher has exited, a normal `waydroid` start must see the untouched vendor image.

Do not use a persistent systemd drop-in, a persistent Waydroid overlay, or a replacement under `/var/lib/waydroid/images`.

## Hardware composer work

The patched HWC needs to:

1. Keep the existing primary display unchanged.
2. Create a second display context with separate buffers, fences, dimensions, and presentation timing.
3. Report the external display through Android's HWC hotplug callback, and remove it during plugin-launch cleanup.
4. Present that display through a distinct Wayland toplevel, allowing Gamescope to place it on a physical or virtual output.
5. Support Android's per-display prepare, set, configuration, power, and VSync requests.

The current HWC uses only `HWC_DISPLAY_PRIMARY`; it does not have an external-display implementation to enable with a property. The patched library must be built for the exact Waydroid Android and vendor-image ABI used by the device.

## Android launch policy

After Android sees the external display, a plugin-owned privileged helper must launch the selected activity on it. It should use Android's display-aware activity launch API and leave existing app data and system settings unchanged. The first implementation can use a non-touch external display; pointer and touch routing can be added after display presentation is reliable.

## Safety checks

Before exposing the enable action, the runtime must verify all of the following:

- the matching HWC payload is bundled and its architecture matches the device;
- Waydroid is stopped and no unrelated Waydroid session is active;
- the private launch path can create its own mount namespace;
- Gamescope provides a usable second output or virtual output;
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
