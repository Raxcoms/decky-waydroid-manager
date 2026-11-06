# Waydroid Manager

Waydroid Manager is a Decky Loader plugin for ArmadaOS handhelds. It initializes the official GAPPS-enabled Waydroid image, presents Android through Steam's existing Gamescope in Game Mode, exposes installed Android apps, and creates Steam library shortcuts for Android or individual apps.

## What it provides

- One-confirmation GAPPS setup that follows the running device architecture.
- A private Wayland socket that connects Android directly to Steam's compositor without another rendering pass.
- Primary Steam compositor discovery for devices with separate display compositors and explicit Android touch passthrough.
- Android app discovery from Waydroid's generated desktop entries.
- Steam shortcut creation and launch for Waydroid or individual apps.
- Steam shortcut state, removal, and optional automatic shortcuts for newly installed Android apps.
- Library artwork from bundled APK images, with app-icon cards for missing artwork and preservation of custom images.
- Local APK and split-package XAPK installation through Decky's file picker.
- Third-party app uninstall with background startup, phase progress, cleanup, and completion or failure notifications.
- Android 13 QAM frame-limit synchronization and redundant frame-commit filtering.
- Android DRM client telemetry for MangoHud GPU usage, without a second rendering pass.
- Container start, stop, and restart controls.
- A confirmed, full image and Android-data removal action.

## Documentation

- [Installation](docs/installation.md)
- [Features](docs/features.md)
- [Live validation and remaining limits](docs/validation.md)
- [Architecture](docs/architecture.md)

## Development

```sh
pnpm install
pnpm run check
pnpm run build
```

The build produces `dist/index.js`. GitHub Actions uploads the installable `waydroid-manager` plugin directory directly as its artifact.

The direct Wayland path has been tested on Thor with working app presentation, direct touch, controller input, and live QAM cap changes on Android 13. Duplicate frame reporting, repeated launches, and per-game resolution overrides remain under live validation; see the architecture notes.
