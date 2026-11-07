# Install Waydroid Manager

## Before you start

Use a native Steam Game Mode session with Decky Loader. Your device needs Waydroid, working Android Binder support, LXC tools, systemd, Python 3.10 or newer, and a Gamescope build that can present native Wayland windows to Steam. ArmadaOS is the tested platform.

## Install the plugin

1. Open a successful [GitHub Actions build](https://github.com/Raxcoms/decky-waydroid-manager/actions/workflows/build.yml) and download its `waydroid-manager-<commit>` artifact.
2. Copy the ZIP to your device. In Game Mode, open Decky's settings and use **Install Plugin from ZIP** in the developer options.
3. Select the ZIP, confirm installation, then open **Waydroid Manager** in Decky.

## Set up Android

1. Select **Install Waydroid with GAPPS**. Waydroid chooses the image for your device.
2. Wait for the progress dialog to finish. The first setup downloads the image, boots Android, and waits for the app list. Fresh Android data starts with Steam's language and English as a fallback. You can change this later in Android Settings.
3. Select **Add Waydroid to Steam**, then open it from your Steam library or choose **Launch Waydroid** in Decky.

If first setup was interrupted, choose **Finish Waydroid setup** to complete it.

Continue with the [user guide](features.md) to install Android apps or adjust how they launch.
