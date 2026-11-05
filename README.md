# Waydroid Manager

Waydroid Manager is a Decky Loader plugin for ArmadaOS handhelds. It initializes the official GAPPS-enabled Waydroid image, runs Android inside a nested Gamescope session from Game Mode, exposes installed Android apps, and creates Steam library shortcuts for Android or individual apps.

## What it provides

- One-confirmation GAPPS setup that follows the running device architecture.
- A nested Gamescope launcher that inherits Steam's active global or per-game resolution.
- Android app discovery from Waydroid's generated desktop entries.
- Steam shortcut creation and launch for Waydroid or individual apps.
- Steam shortcut state, removal, and optional automatic shortcuts for newly installed Android apps.
- Local APK and split-package XAPK installation through Decky's file picker.
- Container start, stop, restart, and boot-time warm-start controls.
- A confirmed, full image and Android-data removal action.

## Documentation

- [Installation](docs/installation.md)
- [Features](docs/features.md)
- [Architecture](docs/architecture.md)

## Development

```sh
pnpm install
pnpm run check
pnpm run build
```

The build produces `dist/index.js`. GitHub Actions uploads the installable `waydroid-manager` plugin directory directly as its artifact.
