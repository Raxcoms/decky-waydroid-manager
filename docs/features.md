# Features

## Image management

- Initializes the GAPPS Waydroid image and shows download and setup progress in the installation dialog.
- Shows whether Waydroid is installed in the Waydroid status section, with container service state in the danger zone.
- Removes `/var/lib/waydroid`, user Waydroid data, generated Waydroid desktop entries and Steam shortcuts after confirmation. The removal dialog shows progress while it stops the service, deletes Android data, and removes shortcuts.

## Lifecycle controls

- Start, stop, and restart `waydroid-container.service`.
- Detects Steam's active Game Mode Wayland socket before launching Android.
- Starts with a minimal environment and disables Gamescope WSI so Android games do not inherit the host Vulkan swapchain layer.
- Mirrors Steam Input's virtual controller into Android during plugin launches using a temporary stock keylayout view and restored input nodes. Physical-controller sharing remains the platform's responsibility.

## Android application library

Waydroid generates one desktop entry for each installed Android application, as KDE exposes in its application menu. The plugin reads those `waydroid.<package>.desktop` files and only accepts entries whose main command is `waydroid app launch <package>`. It displays the icon from the same desktop-entry path used by KDE. Selecting an app opens Decky's native action menu, where it can be added to or removed from Steam. Launch appears after the shortcut exists and uses that Steam entry.

Use **Install APK or XAPK** to select a package from the user home folder. APKs are checked for an Android manifest and staged in Waydroid's temporary data directory. Android's package manager handles single APKs and split-package XAPKs. Its success result is checked before showing a completion toast, and temporary files are removed afterward. Failed operations, including a stopped session or invalid file, produce an error toast.

Installation validates the selected archive before starting Android. If Android is stopped, it starts silently for the operation and the temporary session is closed afterward, including on failure. The shared package dialog shows preparation, startup, installation, and cleanup phases, disables repeated submissions, and reports success or errors. An existing Android session is preserved. Split names, APK count, and available staging space are checked before extraction. Staged files use Android's temporary directory and are removed afterward.

APK and XAPK files use Android's native install-create, install-write and install-commit session commands. Installation starts after file selection. A second confirmation appears only when Android reports a blocking Play Protect decision for the owned install; normal verification needs no extra prompt. Confirming allows the plugin to approve only that request through Android's API, without screen monitoring or changing Play Protect/verifier settings. Cancel rejects that install. A failed write or commit abandons only the session created for that operation. This per-install approval path is tested on Android 13 GAPPS; unsupported verification interfaces produce an error or timeout instead of a global-policy fallback.

The optional **Add new apps to Steam** control appears before the app list. It records the apps present when enabled, then queues only later discovered desktop entries. This prevents existing apps from being added unexpectedly and preserves a removal choice while the app remains installed. Uninstalling an app through the plugin removes its Steam shortcut and clears its observation and manual-removal history. A future reinstall can then be added automatically. Shortcut IDs are saved in the user's Waydroid Manager state and checked against Steam's live library. Existing matching launcher shortcuts are also detected from Steam's shortcut file to avoid duplicates. The app list is alphabetized and initially shows ten apps; **Show more** adds ten at a time. Leaving the plugin resets it to ten. App menus, confirmation dialogs, and the file picker retain the expanded list when returning to it.

Third-party Android packages can be removed directly from the app action menu through Android's package manager. The last confirmed third-party package list is retained while Android is stopped, so uninstall availability remains visible. If needed, uninstall starts Android in the background, waits for boot completion, then checks the live package list. The confirmation button changes to **Uninstalling...** and is disabled along with cancellation while the operation runs. A native progress bar follows startup, readiness, package removal, temporary-session cleanup, and library removal. Progress represents completed phases rather than an estimated time or Android's byte-level progress. Failures show a toast and re-enable the dialog for retry or cancellation. Removal requires Android's success result before deleting the desktop entry or Steam shortcut. The temporary session is stopped afterward, including on failure. An existing session is left running, and a service started only for removal is stopped when no other session needs it. System packages are never offered this action.

Install, uninstall, library, image-removal, and service failures produce error toasts. Routine polling failures are kept out of the toast stream. Automatic shortcut creation reports a failure once per pending app until it succeeds. The top Waydroid section reveals its status fields when controller focus returns to it, before focus can leave for Decky's back button. A native separator divides service controls from full image removal.

The plugin uses the Android launcher icon and app name to create matching portrait, landscape, hero, and logo artwork for Steam. The icon supplies the accent color, and the hero leaves room for Steam to display the title logo. Existing shortcuts get the new design automatically when their older artwork matches the plugin's records. You can still use your own artwork in any slot.

## Game Mode rendering

The bundled launcher creates a private Wayland socket that relays Android directly to Steam's existing Gamescope. It inherits Steam's target socket rather than assuming which compositor drives the primary screen. The relay carries the shortcut's process identity, so Steam recognizes the native Android window. Direct touch and controller input were verified live on Thor. It forwards shared buffer descriptors without another rendering pass and does not modify system files.

At launch, the relay reads the current mode of the display Steam assigned to that shortcut. This includes Steam's global default and per-shortcut resolution selection. Android receives that size through its Wayland output and window configuration. The current mode already includes rotation, so dimensions are not swapped again. If the display mode cannot be read, the original compositor hints remain in use and the launcher log reports the fallback. Resolution changes take effect on the next launch.

Games with their own resolution selector also control the size of the buffers they submit. Android can scale those buffers to its display size. In Warframe, selecting 720p in both Steam and the game produced a 1280x720 Android display and a matching, unscaled app buffer. Frame limits are ceilings: a game's own lower cap or its rendering performance can produce fewer frames than the QAM target.

The transient user service waits until Android reports itself ready before opening the full UI or requested application. Each launch gets a new private socket, and shutdown removes that socket and stops only the owned session and relay. On Android 13, QAM's current cap is applied to the foreground Android app without restarting it, and previous Android overrides are restored afterward. Redundant Waydroid commits are filtered to avoid doubled FPS reporting. QAM rate changes and corrected reporting were verified live in Warframe. Repeated launches, final display pacing, and per-game resolution overrides still require broader validation.

The tested Gamescope build does not render a cursor for native XDG windows, so Steam mouse mode can deliver pointer input without a visible cursor. This remains a compositor limitation; direct touch and controller routing remain enabled.

## Performance overlay

Gamescope associates the Android window with the plugin's Steam-owned relay. MangoHud therefore samples that process, which normally has no GPU clients. The backend duplicates the active container's DRM client handles into the relay so MangoHud can read the real Android GPU counters there. It discovers clients across Android's PID namespace, including app renderers and SurfaceFlinger, and deduplicates shared clients. This works for the full environment and individual apps without package-name rules.

GPU usage requires Linux `pidfd_getfd`, permission to duplicate Android's handles, and a MangoHud-supported DRM driver. Newly opened clients can take up to MangoHud's own fdinfo rescan interval to appear. Global CPU and RAM readings remain system-wide. Optional process-specific CPU/RAM readings still describe the relay, and fields unsupported by the installed MangoHud driver remain unavailable. No percentages, memory values, API names, or frame timings are fabricated.
