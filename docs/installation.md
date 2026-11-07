# Installation

## Requirements

- Decky Loader, Waydroid, LXC command-line tools, system Python 3.10 or newer, and systemd user services. ArmadaOS is the tested platform.
- A working ARM64 binder setup. ArmadaOS images already provide this.
- Steam's Gamescope session, bundled by ArmadaOS. Native game-window detection and direct touch use its existing support for Wayland windows, also used by Lepton. The plugin does not install system extensions, replace Gamescope, or add a second compositor.

## Install the plugin

1. Download the `waydroid-manager-<commit>` artifact from a GitHub Actions build, where `<commit>` is the built revision's short SHA. Its ZIP contains the `waydroid-manager` plugin directory directly, with no nested ZIP.
2. In Game Mode, open Decky Loader settings and install the ZIP.
3. Open **Waydroid Manager** from the Decky quick-access menu.
4. Select **Install Waydroid with GAPPS**. Waydroid selects the image for the running architecture using its configured channels. If the Waydroid package ships without channels, the plugin supplies the [official OTA URLs](https://docs.waydro.id/usage/install-on-desktops) to the CLI for that install.

New Android data starts with Steam's interface language and English as the fallback. The plugin sets this once during image setup. Changes in Android Settings apply to later launches.
5. After the download completes, select **Add Waydroid to Steam**. The launch option appears once the shortcut exists; Android connects to Steam's Gamescope through a private Wayland socket.
6. Use **Install APK or XAPK** in the Android apps section and choose a package from the user home folder. Installation starts with background Android startup when needed and phase progress. If Android blocks this install for a Play Protect decision, a second prompt offers **Install anyway** or **Cancel**. That choice applies only to this package operation; Android's saved verification settings stay unchanged.

The first initialization downloads Android images and can take several minutes. Installing again is intentionally blocked while an image exists, so installed Android data is not replaced accidentally.

## Steam shortcuts

Use **Add Waydroid to Steam** for the Android launcher, or **Add to Steam** beside an Android app. New shortcuts appear immediately through Steam's live shortcut API. The launcher requests service startup from the running Decky backend when needed.

Android receives the shortcut's selected resolution and the primary compositor's refresh rate. The QAM frame limiter is synchronized to the foreground app on Android 13. Shortcuts run the bundled launcher directly under Steam's launch reaper. The plugin does not require Armada's game-launch wrapper.

Existing shortcuts created by older versions have that exact wrapper removed through Steam's live API. Other custom launch options are preserved. Decky must be running for automatic shortcut discovery, runtime frame/GPU synchronization, and starting an inactive container service. The plugin installs no host services or sudoers entries; its control socket and input unit are temporary. See [the review](review.md) for ownership and platform requirements.
