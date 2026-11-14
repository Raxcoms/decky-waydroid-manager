# Second screen support

Waydroid Manager can expose a real Android external display through the host's
secondary Wayland output. Android keeps its primary display and starts its own
secondary launcher on the other screen. Apps that support Android presentations
can draw their own content there.

The secondary navbar provides Back and Home. Android's standard secondary-display
policy does not expose Recents there.

## Enable or disable

1. Open an Android app's menu, or **Waydroid actions** for the full container.
2. Select **Enable second screen support**.
3. Confirm the dialog. It explains that the feature works after a reboot.
4. Close existing Waydroid launches before starting the enabled shortcut.

The menu then offers **Disable second screen support**. An app's choice overrides
the container default. Removing an app removes its saved choice.

Only launches through Waydroid Manager use these settings. Starting ordinary
Waydroid outside the plugin continues to use its installed image and settings.

## Sharing and returning the screen

Enabled and ordinary Steam shortcuts can share one plugin-owned Android session
when its matching display payload is available. Joining an existing session does
not restart Android. The external display remains connected while at least one
enabled shortcut is open. Closing the final enabled shortcut withdraws it and
returns the secondary output to the host's previous window. Other ordinary
Waydroid shortcuts can keep running.

Closing the final shortcut stops the owned session and removes its temporary
mounts. The host compositor continues to own and arbitrate DRM leases, including
requests from its other applications. The plugin does not stop or replace that
compositor or change Armada's display configuration.

## Compatibility

This requires a host-provided secondary Wayland socket and a payload matching the
installed Waydroid vendor image. The bundled payload targets the tested 64-bit
Android 13 image with vendor fingerprint:

```text
waydroid/lineage_waydroid_arm64/waydroid_arm64:13/TQ3A.230901.001/aleasto10221218:userdebug/test-keys
```

Selection also checks the original composer and adapter hashes and the payload's
architecture, System UI APK hash, and payload file hashes. A different image needs a separately built and
validated payload. Rebooting cannot resolve an image mismatch.

Display discovery uses the current user's host environment snapshots. Integrators
can provide `WAYDROID_MANAGER_EXTERNAL_WAYLAND_DISPLAY` or
`WAYDROID_MANAGER_EXTERNAL_WAYLAND_ENV` to the launcher. The latter names a regular,
user-owned environment file containing `WAYLAND_DISPLAY`. No device name, panel,
or physical connector is hardcoded. Thor is a hardware test device, not a runtime
requirement. Pocket DS and Pocket Duo hardware have not been tested here.

## Reversibility

The plugin stages files under `/run` and temporarily mounts them ahead of the
existing Waydroid overlay. It supplies the composer, adapter, framework resource
overlay, secondary-home defaults, and external touch mapping for that session.
Existing overlay display settings are merged into staging. Installed images and
original configuration files remain unchanged.

A separate root guard monitors the backend and can stop the owned session and
remove its mounts even if the plugin disappears. Its code is copied into `/run`
before activation. A reboot also removes these mounts. Leaving the preference
enabled when removing the plugin does not patch ordinary Waydroid permanently.

If the external compositor disconnects, Android withdraws that display while
keeping its primary display. Close and relaunch the plugin session after the host
output becomes available again.

## Validation

Thor testing on November 14, 2026 verified:

- primary Android output at 1920 by 1080, approximately 120 Hz;
- external Android output at 1240 by 1080, approximately 60 Hz;
- a distinct Android presentation on the real secondary compositor;
- Android's secondary launcher through the actual Steam shortcut;
- visible native Back and Home controls on the secondary output;
- screen withdrawal returning to the existing KDE mobile session, followed by
  reconnection without restarting Android;
- the container menu's enable confirmation and subsequent disable action;
- normal Steam shortcut exit removing the temporary runtime mounts;
- an ordinary Waydroid boot afterward using one display and the original
  composer hash.

A mount integration test also verified guard recovery after a backend process
crash using disposable configuration fixtures. Automated Linux tests cover
shared launch accounting, relay isolation, payload validation, and recovery.
Physical input, suspend/resume, and other device models require their own hardware
validation. No device-wide reboot was performed during these checks.

See [the payload build guide](../android/hwc/README.md) for rebuilding against a
different compatible Waydroid image.
