# Install Waydroid Manager

## Before you start

Use a native Steam Game Mode session with Decky Loader. Your device needs Waydroid, working Android Binder support, LXC tools, systemd, Python 3.10 or newer, and a Gamescope build that can present native Wayland windows to Steam. ArmadaOS is the tested platform.

Use the interfaces already supplied by ArmadaOS. Installing the plugin does not require changing its immutable base or adding compiler packages. Native display extensions currently support Android 13 / VNDK 33 / ARM64 after interface validation. A secondary host Wayland output is required only for second-screen features.

## Install the plugin

1. Open the [latest official release](https://github.com/Raxcoms/decky-waydroid-manager/releases/latest) and download the `waydroid-manager-<version>.zip` asset.
2. Copy the ZIP to your device. In Game Mode, open Decky's settings and use **Install Plugin from ZIP** in the developer options.
3. Select the ZIP, confirm installation, then open **Waydroid Manager** in Decky.

For development testing, download `waydroid-manager-<version>-ci.zip` from a successful [CI build](https://github.com/Raxcoms/decky-waydroid-manager/actions/workflows/build.yml) and install it the same way.

The plugin ZIP includes the native libraries and private resource-preparation tools. You do not need to download separate display or runtime artifacts.

## Set up Android

1. Select **Install Waydroid**. Waydroid chooses the image for your device and includes Google Play services.
2. Wait for the progress dialog to finish. The first setup downloads the image, boots Android, and waits for the current Android user to unlock and the app list to become available. Fresh Android data starts with Steam's language, English as a fallback, and media volume at 100%. Use your device's volume slider to control playback.
3. Select **Add Waydroid to Steam**, then open it from your Steam library or choose **Launch Waydroid** in Decky.

If first setup was interrupted, choose **Finish Waydroid setup** to complete it.

## Use an existing Waydroid image

If Waydroid is already installed, skip the image download and select **Add Waydroid to Steam**. Your current Android apps, language, and settings are kept.

Close any Waydroid window in Desktop Mode before launching from Steam. The plugin uses Steam's `XDG_DATA_HOME` when that variable is set so app discovery and background setup use the same Android data as the shortcut.

Fresh and existing images use the graphics drivers supplied by the host. If you see a black screen, try the same image in Desktop Mode and check the plugin's `wayland.log` under `~/.local/state/waydroid-manager/` after a failed Steam launch. A warning about staged vendor libraries means Waydroid did not mount the host's overlay. Check the Waydroid service journal before considering changes to your image.

Continue with the [user guide](features.md) to install Android apps or adjust how they launch.

## Prepare a second screen

On a supported host, open an app's menu and enable second-screen support. To configure only the Waydroid shortcut, use **Waydroid actions > Enable second screen for the Waydroid shortcut**.

The first-enable progress dialog reads the installed Android framework and System UI, then builds and caches matching resource overlays locally. No native build environment or dependency download is needed on the device. Close running Android shortcuts and relaunch after confirming the restart notice.

Image or resource updates can require preparation again. An unsupported native interface needs a matching tested build profile; changing the preference cannot make an incompatible image supported. See the [second-screen guide](dual-screen-investigation.md).

## Upgrade or remove

Close running Android shortcuts before replacing the plugin ZIP. Existing apps, data and preferences are retained. Resource caches are checked against the current image and recipe before reuse.

To remove Android and its data, use **Waydroid actions > Uninstall Waydroid**. Removing only the Decky plugin does not uninstall Android. A separate runtime guard restores temporary mounts if the backend disappears, so second-screen preferences do not permanently change ordinary Waydroid launches.
