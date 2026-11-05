# Features

## Image management

- Initializes the official GAPPS Waydroid image with `waydroid init --system_type GAPPS`.
- Shows whether Waydroid is installed, whether its container service is running, and the detected display resolution adjusted for the active Game Mode rotation.
- Removes `/var/lib/waydroid`, user Waydroid data, generated Waydroid desktop entries and Steam shortcuts, and disables the container service only after confirmation.

## Lifecycle controls

- Start, stop, and restart `waydroid-container.service`.
- Enable or disable the service for boot. Keeping it enabled gives a warm container for faster Game Mode launches.
- Verifies that ArmadaOS's bundled Gamescope runtime is available before launching Android.
- Starts with a minimal environment, preserves Steam's app identity and shared frame limiter, and disables Gamescope WSI so Android games do not inherit the host Vulkan swapchain layer.
- Enables Waydroid controller hotplug so Steam Input's virtual controller is exposed to Android after the next Waydroid session starts.

## Android application library

Waydroid generates one desktop entry for each installed Android application, as KDE exposes in its application menu. The plugin reads those `waydroid.<package>.desktop` files and only accepts entries whose main command is `waydroid app launch <package>`. It displays the icon from the same desktop-entry path used by KDE. Selecting an app opens Decky's native action menu, where it can be added to or removed from Steam. Launch appears after the shortcut exists and uses that Steam entry.

Use **Install APK or XAPK** to select a package from the user home folder. Waydroid must already be running. APK files use Waydroid's supported single-package installer. XAPK files are unpacked into Waydroid's temporary data directory and installed with Android's split-package installer; the temporary files are removed after the operation.

The optional **Add new apps to Steam** control appears before the app list. It records the apps present when enabled, then queues only later discovered desktop entries. This prevents existing apps from being added unexpectedly and preserves a removal choice: an app removed from Steam is never automatically added again. Shortcut IDs are saved in the user's Waydroid Manager state and existing matching launcher shortcuts are detected from Steam's shortcut file to avoid duplicates. The app list is alphabetized and initially shows ten apps; **Show more** adds ten at a time.

Third-party Android packages can be removed directly from the app action menu through `waydroid app remove`. System packages are never offered this action.

Waydroid exports launcher icons but does not export Steam grid, hero, logo, or portrait artwork. The plugin assigns the exported Android icon through Steam's shortcut API; Steam's other artwork remains user-configurable in the library.

## Game Mode rendering

The bundled launcher nests Gamescope on Steam's dynamically discovered Wayland socket and creates a fresh Wayland socket for every launch. It passes Steam's rotation-aware target size to nested Gamescope, then points the Waydroid session at that socket before opening Android or a selected application. The transient user service waits until Android reports itself ready, detects when Steam has closed the nested launcher, and stops only that session. This separates the Android session from Steam's compositor while avoiding premature app launch requests.
