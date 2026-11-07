# Waydroid Manager

Waydroid Manager is a Decky Loader plugin for ArmadaOS handhelds. It initializes the official GAPPS-enabled Waydroid image, presents Android through Steam's existing Gamescope in Game Mode, exposes installed Android apps, and creates Steam library shortcuts for Android or individual apps.

## What it provides

- GAPPS setup for the device architecture, with progress through the first Android boot and app list.
- Steam's language and an English fallback for new Android data.
- A private Wayland socket that connects Android directly to Steam's compositor without another rendering pass.
- Primary Steam compositor discovery for devices with separate display compositors and explicit Android touch passthrough.
- Steam global and per-shortcut resolution selection through the launch's virtual display mode.
- Android app discovery from Waydroid's generated desktop entries.
- Steam shortcut creation and launch for Waydroid or individual apps.
- Steam shortcut state, removal, and optional automatic shortcuts for newly installed Android apps.
- Matching Steam library artwork based on Android app icons and names, with support for custom artwork.
- Local APK and split-package XAPK installation through Decky's file picker.
- APK/XAPK installation and third-party app uninstall with background startup, phase progress, cleanup, and completion or failure notifications.
- Explicit per-install verification approval without screen monitoring or Android policy changes.
- Android 13 QAM frame-limit synchronization and redundant frame-commit filtering.
- Android DRM client telemetry for MangoHud GPU usage, without a second rendering pass.
- Container start, stop, and restart controls.
- Full image and Android-data removal with confirmation and progress.

## Documentation

- [Installation](docs/installation.md)
- [Features](docs/features.md)
- [Live validation and remaining limits](docs/validation.md)
- [Architecture](docs/architecture.md)
- [Cleanup review and compatibility boundaries](docs/review.md)
- [Reproducible fresh-device test](docs/testing.md)

## Development

```sh
pnpm install
pnpm run check
pnpm run build
python3 scripts/build_android.py
python3 -m unittest discover -s tests -v
node --experimental-strip-types --test tests/*.test.mts
bash -n bin/waydroid-launcher bin/waydroid-session
python3 scripts/package.py out
python3 scripts/check_package.py out/waydroid-manager
```

Use Node 22 or newer and the pnpm version in `package.json`. To build the bundled Android Dex, install JDK 17 or newer, Android SDK build-tools 35.0.0, and platform android-35. Set `JAVA_HOME` and `ANDROID_HOME` to those installations. Run the socket, device, and packaged-backend checks on Linux with Python 3.10 or newer. GitHub Actions builds the frontend and Dex, runs the checks, and uploads the installable plugin.

CI artifacts are named `waydroid-manager-<commit>` using the checked-out revision's short SHA. The plugin directory inside the artifact remains `waydroid-manager` for Decky installation.

The direct Wayland path has been tested on Thor and Nova. See the [validation notes](docs/validation.md) for the device results and remaining limits.
