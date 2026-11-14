# Experimental second screen

## Status

The preferences, shared launch registration, external socket discovery, payload validation, and temporary mount lifecycle are implemented. The plugin-owned Android payload is being built and has not passed display presentation tests yet.

The enabled launch path requires a matching bundled payload. Until one is available, disable second-screen support to use the standard launch path. Rebooting alone cannot supply a missing payload.

The eventual feature must make Android behave as though a USB-C monitor is connected. Moving a Waydroid app window to another host output is not enough because Android still reports one display to the app.

## User experience

The Android app menu will eventually show **Enable second screen support** or **Disable second screen support**. The full Waydroid menu will provide the same choice for the container launch.

Selecting Enable opens a confirmation dialog that says the feature takes effect after a reboot. A selection changes only Waydroid Manager state. It must not change the installed Waydroid image or an ordinary Waydroid launch.

The full-container setting applies to full launches. An app setting overrides the container setting for that app. Removing an app also removes its saved setting.

## Required runtime boundary

Waydroid already supports rootfs overlays. It mounts `/var/lib/waydroid/overlay` over the system image and `/var/lib/waydroid/overlay/vendor` over the vendor image before it starts the container. This is the correct deployment point for a matching external-display HWC because the original images remain unchanged.

The overlay is global while Waydroid is running, so the launch path must still own its lifecycle:

- compose a matching HWC and adapter ahead of the existing vendor overlay using a temporary overlay mount;
- add a temporary framework resource overlay that disables automatic external display mirroring;
- discover a host-provided external Wayland socket and bind it into the container as `wayland-1` before Waydroid starts;
- add `waydroid.wayland_display_ext=wayland-1` only to the generated properties for that launch;
- remove the temporary mounts when the final compatible plugin launch ends.

The launcher must never acquire, hold, or release a DRM lease. The host compositor owns its lease and arbitrates it with its existing applications. The plugin requests use by mapping its external Wayland surface only for a second-screen session. When the final eligible Waydroid app exits, the HWC closes that surface, returning presentation to the compositor and its previous user.

The HWC extension is owned by this plugin and has no device, connector, panel, or touch-controller rules. Its only host input is the external Wayland socket supplied for that session. A host integration may expose the socket through an environment file, a launcher, or an explicit plugin setting, but it remains responsible for lease policy. On Thor, the existing secondary Gamescope is one example of this contract: it holds a yielded DRM lease and exposes a socket for normal client applications. It is a validation fixture, not a runtime dependency.

Runtime files live under `/run`. Temporary bind mounts expose the configuration only for the plugin session, leaving the original files intact. A separate root guard stops the owned session and removes those mounts if the backend exits. Rebooting removes the mounts automatically. The HWC retains the stock primary path and treats a missing `wayland-1` socket as no external display. The installed images and host lease service are unchanged.

Apps can share an active session when their second-screen settings match. A launch that requests a different setting asks the user to close the existing shortcuts before switching the global container configuration.

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
- a usable host-provided external Wayland socket is present and can be bound as `wayland-1`;
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

The feature is not ready for release until the private runtime path and at least one matching HWC payload pass these checks on hardware.

### Linux helper validation

The focused suite passed all 24 tests on Thor on November 14, 2026. This covers socket discovery, authenticated launch registration, shared launch release accounting, cancellation during cleanup, overlay restoration, and configuration recovery. Tests used temporary files and sockets, which were removed afterward. This does not validate Android display presentation or returning the physical screen to an existing application.

The full Python suite passes 193 tests under Linux. Thor also passed a mount integration test that checked both normal release and a backend process crash: the independent guard restored the original fixture files and overlays. The test did not modify the installed plugin or Waydroid configuration.
