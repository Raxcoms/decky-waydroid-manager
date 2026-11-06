# Architecture

```text
Decky UI
  -> root Decky backend
     -> Waydroid CLI and systemd service
     -> launcher and Waydroid icon metadata
  -> Steam client shortcut API
  -> bundled launcher started as the ArmadaOS user
     -> private Wayland socket relay
        -> Steam's existing Gamescope compositor
        -> Waydroid session
           -> Android full UI or selected package
```

The backend owns system-wide operations because the Waydroid image and container service are root-owned. The frontend does not compose shell commands: it calls narrow backend methods with validated package names. It creates shortcuts through Steam's live shortcut API, so new entries appear in the library immediately instead of waiting for Steam to reread `shortcuts.vdf`.

The launcher runs as the logged-in ArmadaOS user. The backend reads graphics variables from Steam's process environment, preferring Steam over its web helpers. The shortcut inherits Steam's own target compositor socket, avoiding a separate companion-screen compositor. The launcher drops Vulkan-layer and compatibility overrides and retains Steam identity. Steam's launch process owns its lifetime, and a transient user service owns the Waydroid session. Readiness is checked before opening the full UI or requested app. Session logs are under `~/.local/state/waydroid-manager`.

Android's SurfaceFlinger runs outside Steam's launch process tree. Connecting it directly does not give its native window the shortcut identity. The relay opens the upstream connection from a process descended from Steam's launch reaper. Gamescope sees that process as the Wayland client and associates the Android window with the existing shortcut. This allows Steam to select the window and apply Steam Input without an X11 host window.

`waydroid-wayland-relay` uses Python's standard Unix socket APIs. It forwards protocol bytes and `SCM_RIGHTS` file descriptors in both directions. DMA-BUF and shared-memory buffers remain shared file descriptors; the relay does not map, copy, render, or composite their pixels. Partial writes transfer each descriptor once, queues apply backpressure, and disconnects close queued descriptors. Each launch creates a private directory under the user's runtime directory and a socket with mode `0600`. The socket and owned child processes are removed on exit.

Armada's existing Gamescope support reports native Wayland windows to Steam and passes direct touch to them, as used by Lepton. The plugin does not extend system files or replace Gamescope. A second Gamescope's native backend requires `wl_subcompositor` and `wp_viewporter`, which the tested primary compositor does not advertise. Its automatic SDL fallback always composites, so the plugin uses the socket relay instead. Background Android startup remains in use; the launcher does not open the Android desktop before launching the requested package. Relay diagnostics are saved to `~/.local/state/waydroid-manager/wayland.log`.

The relay creates no compositor telemetry stream. Android gets its output dimensions and refresh rate from the existing compositor's Wayland output. Per-game resolution overrides still require live validation. The display helper remains available for diagnosing the primary compositor's control display and refresh; it does not copy the potentially stale `GAMESCOPE_FPS_LIMIT` property.

Waydroid's hardware composer uses a timed VSync loop rather than waiting for Wayland frame callbacks, so direct presentation alone does not enforce QAM's limit. The frontend reads the same `settingsStore` fields as the modern QAM slider, with the legacy performance store as a fallback for older clients. A background RPC follows changes even when the plugin panel is closed. The root backend finds the current relay process, identifies Android's foreground package and UID, and applies SurfaceFlinger's temporary per-UID frame-rate override. Existing overrides are preserved and restored when limiting is disabled, the launch ends, or the plugin unloads. This API is currently verified for Android 13, SDK 33; other versions fail explicitly instead of assuming the same Binder transaction.

Live Android per-UID limiting produced 24.01 FPS and median frame intervals around 41.7 ms in the game's SurfaceFlinger timestamps. Slider changes were also verified without restarting the app. The overlay still reports twice the Android frame rate: Waydroid commits its root surface twice per frame. Duplicate frame reporting remains under investigation. These measurements do not establish final display pacing or the absence of graphical artifacts.

System commands use Armada's existing subprocess environment cleanup pattern. Decky's PyInstaller library paths must not reach `/usr/bin/python3` or the Waydroid CLI; otherwise Python loads Decky's bundled runtime without its standard library.

Each launch reconnects Android to a fresh private socket. A fixed transient user service owns the plugin's session. Shutdown stops that service before terminating the relay and its command process group. The launcher clears stale readiness markers before starting a session and allows up to three minutes for Android readiness.

The root backend also starts a transient input synchronizer while the plugin is loaded. It mirrors Steam Input's virtual X-Box controller node into the active Android container with Android's expected ownership and permissions. Steam's virtual identity uses Android's stock Xbox 360 keylayout, including its D-pad hat axes and stick metadata. Physical handheld layouts are not copied onto it: Armada's physical-driver face-button correction uses different codes. Armada's built-in Waydroid input service continues to own physical controller sharing. Live Android device enumeration must be checked when investigating duplicate input; pointer events from Steam mouse mappings are a separate input source.

Steam writes its own `shortcuts.vdf` data after the frontend calls `SteamClient.Apps.AddShortcut`. The backend provides the trusted launcher, working directory, arguments, and Waydroid-provided app icon path. Shortcut launch options use Armada's `armada-game-launch %command%` wrapper so Steam Input and per-game performance settings remain attached. It records returned shortcut IDs in `~/.config/waydroid-manager/state.json`, and also recognizes Armada-rewritten shortcut records by their app name. A plugin-lifetime watcher checks for new apps every five seconds, including when the panel is closed. The backend keeps a durable observed and removed set so the feature only queues genuinely new installed apps.

Artwork discovery reads package paths from Android's package manager, resolves them within the active container root, and inspects APK ZIP entries without extracting them. Individual images, total bytes, and candidate counts are bounded. The frontend decodes the candidates, selects images by dimensions and role, and renders Steam's four artwork formats on a canvas. Missing roles use the exported app icon and name. A background watcher checks for missing artwork every fifteen seconds and calls `SetCustomArtworkForApp`; it also initializes Steam's shortcut logo position when absent. Existing image files are left alone. No external artwork service or image-processing package is required.
