# Installation

## Requirements

- ArmadaOS with Decky Loader and the `waydroid` package.
- A working ARM64 binder setup. ArmadaOS images already provide this.
- Gamescope, bundled by ArmadaOS. The plugin checks for its executable and reports an incompatible or incomplete deployment if it is unavailable.

## Install the plugin

1. Download the `waydroid-manager` artifact from a GitHub Actions build. Its ZIP contains the plugin directory directly, with no nested ZIP.
2. In Game Mode, open Decky Loader settings and install the ZIP.
3. Open **Waydroid Manager** from the Decky quick-access menu.
4. Select **Install Waydroid with GAPPS**. The plugin runs `waydroid init --system_type GAPPS`, so Waydroid selects the official image for the running architecture rather than a device-name mapping.
5. After the download completes, select **Add Waydroid to Steam**. The launch option appears once the shortcut exists; Android performs its first boot inside a nested Gamescope session.
6. With Waydroid running, use **Install APK or XAPK** in the Android apps section to install a package from the user home folder.

The first initialization downloads Android images and can take several minutes. Installing again is intentionally blocked while an image exists, so installed Android data is not replaced accidentally.

## Steam shortcuts

Use **Add Waydroid to Steam** for the Android launcher, or **Add to Steam** beside an Android app. New shortcuts appear immediately through Steam's live shortcut API. Start the service from the plugin before using a shortcut.

Steam's global and per-game resolution settings control the nested Game Mode surface. The launcher detects that rotation-aware target size and passes it to nested Gamescope instead of assuming a particular handheld resolution. Shortcuts retain Armada's game-launch wrapper, allowing Steam to apply the selected controller configuration and per-game performance settings.
