# Install Waydroid Manager

## Before you start

Use a native Steam Game Mode session with Decky Loader. Your device needs Waydroid, working Android Binder support, LXC tools, systemd, Python 3.10 or newer, and a Gamescope build that can present native Wayland windows to Steam. ArmadaOS is the tested platform.

## Install the plugin

1. Open the [latest official release](https://github.com/Raxcoms/decky-waydroid-manager/releases/latest) and download the `waydroid-manager-<version>.zip` asset.
2. Copy the ZIP to your device. In Game Mode, open Decky's settings and use **Install Plugin from ZIP** in the developer options.
3. Select the ZIP, confirm installation, then open **Waydroid Manager** in Decky.

For development testing, download `waydroid-manager-<version>-dev.zip` from a successful [CI build](https://github.com/Raxcoms/decky-waydroid-manager/actions/workflows/build.yml) and install it the same way.

## Set up Android

1. Select **Install Waydroid**. Waydroid chooses the image for your device and includes Google Play services.
2. Wait for the progress dialog to finish. The first setup downloads the image, boots Android, and waits for the app list. Fresh Android data starts with Steam's language, English as a fallback, and media volume at 100%. Use your device's volume slider to control playback.
3. Select **Add Waydroid to Steam**, then open it from your Steam library or choose **Launch Waydroid** in Decky.

If first setup was interrupted, choose **Finish Waydroid setup** to complete it.

## Use an existing Waydroid image

If Waydroid is already installed, skip the image download and select **Add Waydroid to Steam**. Your current Android apps, language, and settings are kept.

Close any Waydroid window in Desktop Mode before launching from Steam. The plugin uses Steam's `XDG_DATA_HOME` when that variable is set so app discovery and background setup use the same Android data as the shortcut.

Fresh and existing images use the graphics drivers supplied by the host. If you see a black screen, try the same image in Desktop Mode and check the plugin's `wayland.log` under `~/.local/state/waydroid-manager/` after a failed Steam launch. A warning about staged vendor libraries means Waydroid did not mount the host's overlay. Check the Waydroid service journal before considering changes to your image.

Continue with the [user guide](features.md) to install Android apps or adjust how they launch.
