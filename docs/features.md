# Features

## Image management

- Initializes the official GAPPS Waydroid image with `waydroid init --system_type GAPPS`.
- Shows whether Waydroid is installed, whether its container service is running, and the detected display resolution adjusted for the active Game Mode rotation.
- Removes `/var/lib/waydroid`, user Waydroid data, generated Waydroid desktop entries and Steam shortcuts, and disables the container service only after confirmation.

## Lifecycle controls

- Start, stop, and restart `waydroid-container.service`.
- Verifies that ArmadaOS's bundled Gamescope runtime is available before launching Android.
- Starts with a minimal environment and disables Gamescope WSI so Android games do not inherit the host Vulkan swapchain layer.
- Mirrors Steam Input's virtual controller into Android while leaving Armada's physical-controller bridge in control of physical devices.

## Android application library

Waydroid generates one desktop entry for each installed Android application, as KDE exposes in its application menu. The plugin reads those `waydroid.<package>.desktop` files and only accepts entries whose main command is `waydroid app launch <package>`. It displays the icon from the same desktop-entry path used by KDE. Selecting an app opens Decky's native action menu, where it can be added to or removed from Steam. Launch appears after the shortcut exists and uses that Steam entry.

Use **Install APK or XAPK** to select a package from the user home folder. Waydroid must already be running. APK files use Waydroid's supported single-package installer. XAPK files are unpacked into Waydroid's temporary data directory and installed with Android's split-package installer; the temporary files are removed after the operation.

The optional **Add new apps to Steam** control appears before the app list. It records the apps present when enabled, then queues only later discovered desktop entries. This prevents existing apps from being added unexpectedly and preserves a removal choice: an app removed from Steam is never automatically added again. Shortcut IDs are saved in the user's Waydroid Manager state and existing matching launcher shortcuts are detected from Steam's shortcut file to avoid duplicates. The app list is alphabetized and initially shows ten apps; **Show more** adds ten at a time.

Third-party Android packages can be removed directly from the app action menu through `waydroid app remove`. System packages are never offered this action.

Waydroid exports launcher icons but does not export Steam grid, hero, logo, or portrait artwork. The plugin assigns the exported Android icon through Steam's shortcut API; Steam's other artwork remains user-configurable in the library.

## Game Mode rendering

The bundled launcher creates a private Wayland socket that relays Android directly to Steam's existing Gamescope. It inherits Steam's target socket rather than assuming which compositor drives the primary screen. The relay carries the shortcut's process identity, so Steam recognizes the native Android window. Direct touch and controller input were verified live on Thor. It forwards shared buffer descriptors without another rendering pass and does not modify system files.

The transient user service waits until Android reports itself ready before opening the full UI or requested application. Each launch gets a new private socket, and shutdown removes that socket and stops only the owned session and relay. On Android 13, QAM's current cap is applied to the foreground Android app without restarting it, and previous Android overrides are restored afterward. Duplicate frame reporting, repeated launches, and per-game resolution overrides remain under validation.
