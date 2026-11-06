# Waydroid Manager

Waydroid Manager is a Decky Loader plugin for ArmadaOS handhelds. It initializes the official GAPPS-enabled Waydroid image, presents Android through Steam's existing Gamescope in Game Mode, exposes installed Android apps, and creates Steam library shortcuts for Android or individual apps.

## What it provides

- One-confirmation GAPPS setup that follows the running device architecture.
- A private Wayland socket that connects Android directly to Steam's compositor without another rendering pass.
- Primary Steam compositor discovery for devices with separate display compositors and explicit Android touch passthrough.
- Steam global and per-shortcut resolution selection through the launch's virtual display mode.
- Android app discovery from Waydroid's generated desktop entries.
- Steam shortcut creation and launch for Waydroid or individual apps.
- Steam shortcut state, removal, and optional automatic shortcuts for newly installed Android apps.
- Library artwork from installed APK images even while Android is stopped, with app-icon cards for missing artwork and preservation of custom images.
- Local APK and split-package XAPK installation through Decky's file picker.
- APK/XAPK installation and third-party app uninstall with background startup, phase progress, cleanup, and completion or failure notifications.
- Explicit per-install verification approval without screen monitoring or Android policy changes.
- Android 13 QAM frame-limit synchronization and redundant frame-commit filtering.
- Android DRM client telemetry for MangoHud GPU usage, without a second rendering pass.
- Container start, stop, and restart controls.
- A confirmed, full image and Android-data removal action.

## Documentation

- [Installation](docs/installation.md)
- [Features](docs/features.md)
- [Live validation and remaining limits](docs/validation.md)
- [Architecture](docs/architecture.md)
- [Cleanup review and compatibility boundaries](docs/review.md)

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

Use Node 22 or newer and the pnpm version declared in `package.json`. Building the bundled verification Dex also requires JDK 17 or newer, Android SDK build-tools 35.0.0 and platform android-35; set `JAVA_HOME` and `ANDROID_HOME` to those installations. These are build dependencies only. Python runtime helpers require Linux and Python 3.10 or newer. Linux-only socket/device tests are skipped on Windows; run the packaged-backend import check on Linux. The build produces `dist/index.js` and `bin/waydroid-verifier.dex`; the package command stages `out/waydroid-manager` into an empty output directory without Python caches. GitHub Actions builds both helpers, runs the checks and uploads the installable plugin directory directly, including for cleanup branches.

The direct Wayland path has been tested on Thor with app presentation, direct touch, controller input, repeat launches, Android 13 QAM cap changes, and per-game resolution overrides. Extended gameplay, other devices and rotation need broader validation. Native Gamescope mouse-cursor support remains a platform limitation; see the validation and review notes.
