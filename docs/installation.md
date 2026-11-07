# Installation

## Requirements

- Decky Loader, Waydroid, LXC command-line tools, system Python 3.10 or newer, and systemd user services. ArmadaOS is the tested platform.
- A working ARM64 binder setup. ArmadaOS images already provide this.
- Steam's Gamescope session, bundled by ArmadaOS. Native game-window detection and direct touch use its existing support for Wayland windows, also used by Lepton. The plugin does not install system extensions, replace Gamescope, or add a second compositor.

## Install the plugin

1. Download the `waydroid-manager-<commit>` artifact from GitHub Actions. The ZIP contains the plugin directory directly. You can rename the downloaded file to `Waydroid Manager.zip` so Decky's confirmation shows that name.
2. In Game Mode, open Decky Loader settings and install the ZIP.
3. Open **Waydroid Manager** from the Decky quick-access menu.
4. Select **Install Waydroid with GAPPS**. Waydroid selects the image for the running architecture using its configured channels. If the Waydroid package ships without channels, the plugin supplies the [official OTA URLs](https://docs.waydro.id/usage/install-on-desktops) to the CLI for that install.

   Setup can take several minutes. On the first boot, the plugin sets Steam's interface language with English as the fallback, then waits for the Android app list. If setup was interrupted, select **Finish Waydroid setup**. You can change the language order later in Android Settings.

5. After setup completes, select **Add Waydroid to Steam**. The launch option appears once the shortcut exists.
6. Use **Install APK or XAPK** in the Android apps section and choose a package from the user home folder. Installation starts with background Android startup when needed and phase progress. If Android blocks this install for a Play Protect decision, a second prompt offers **Install anyway** or **Cancel**. That choice applies only to this package operation; Android's saved verification settings stay unchanged.

## Steam shortcuts

Use **Add Waydroid to Steam** for the Android launcher, or **Add to Steam** beside an Android app. New shortcuts appear immediately through Steam's live shortcut API. The launcher requests service startup from the running Decky backend when needed.

Android receives the shortcut's selected resolution and the primary compositor's refresh rate. The QAM frame limiter is synchronized to the foreground app on Android 13. Shortcuts run the bundled launcher directly under Steam's launch reaper. The plugin does not require Armada's game-launch wrapper.

Existing shortcuts created by older versions have that exact wrapper removed through Steam's live API. Other custom launch options are preserved. Decky must be running for automatic shortcut discovery, runtime frame/GPU synchronization, and starting an inactive container service. The plugin installs no host services or sudoers entries; its control socket and input unit are temporary. See [the review](review.md) for ownership and platform requirements.
