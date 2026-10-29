# Features

## Image management

- Initializes the official GAPPS Waydroid image with `waydroid init --system_type GAPPS`.
- Shows whether Waydroid is installed, whether its container service is running, and the detected display resolution adjusted for the active Game Mode rotation.
- Removes `/var/lib/waydroid`, user Waydroid data, generated Waydroid desktop entries and Steam shortcuts, and disables the container service only after confirmation.

## Lifecycle controls

- Start, stop, and restart `waydroid-container.service`.
- Enable or disable the service for boot. Keeping it enabled gives a warm container for faster Game Mode launches.
- Verifies that ArmadaOS's bundled Gamescope runtime is available before launching Android.

## Android application library

Waydroid generates one desktop entry for each installed Android application, as KDE exposes in its application menu. The plugin reads those `waydroid.<package>.desktop` files and only accepts entries whose main command is `waydroid app launch <package>`. It displays the icon from the same desktop-entry path used by KDE. Selecting an app opens Decky's native action menu, where it can be launched or added to Steam individually.

## Game Mode rendering

The bundled launcher starts Gamescope's SDL backend on Steam's current Xwayland display and creates a fresh Wayland socket for every launch. It points the Waydroid session at that socket before opening Android or a selected application. This separates the Android session from Steam's compositor while inheriting the active Game Mode target size.
