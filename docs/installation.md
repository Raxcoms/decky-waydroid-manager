# Installation

## Requirements

- ArmadaOS with Decky Loader and the `waydroid` package.
- A working ARM64 binder setup. ArmadaOS images already provide this.
- Steam's Gamescope session, bundled by ArmadaOS. Native game-window detection and direct touch use its existing support for Wayland windows, also used by Lepton. The plugin does not install system extensions, replace Gamescope, or add a second compositor.

## Install the plugin

1. Download the `waydroid-manager` artifact from a GitHub Actions build. Its ZIP contains the plugin directory directly, with no nested ZIP.
2. In Game Mode, open Decky Loader settings and install the ZIP.
3. Open **Waydroid Manager** from the Decky quick-access menu.
4. Select **Install Waydroid with GAPPS**. The plugin runs `waydroid init --system_type GAPPS`, so Waydroid selects the official image for the running architecture rather than a device-name mapping.
5. After the download completes, select **Add Waydroid to Steam**. The launch option appears once the shortcut exists; Android connects to Steam's Gamescope through a private Wayland socket.
6. Use **Install APK or XAPK** in the Android apps section to install a package from the user home folder. Android starts in the background when needed, with progress shown during installation and cleanup.

The first initialization downloads Android images and can take several minutes. Installing again is intentionally blocked while an image exists, so installed Android data is not replaced accidentally.

## Steam shortcuts

Use **Add Waydroid to Steam** for the Android launcher, or **Add to Steam** beside an Android app. New shortcuts appear immediately through Steam's live shortcut API. Start the service from the plugin before using a shortcut.

Android receives the shortcut's selected resolution and the primary compositor's refresh rate. The QAM frame limiter is synchronized to the foreground app on Android 13. Shortcuts run the bundled launcher directly under Steam's launch reaper. The plugin does not require Armada's game-launch wrapper.
