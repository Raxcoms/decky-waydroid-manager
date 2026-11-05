# Architecture

```text
Decky UI
  -> root Decky backend
     -> Waydroid CLI and systemd service
     -> launcher and Waydroid icon metadata
  -> Steam client shortcut API
  -> bundled launcher started as the ArmadaOS user
     -> nested Gamescope window on Steam's active Xwayland display
        -> fresh nested Wayland socket
        -> Waydroid session
           -> Android full UI or selected package
```

The backend owns system-wide operations because the Waydroid image and container service are root-owned. The frontend does not compose shell commands: it calls narrow backend methods with validated package names. It creates shortcuts through Steam's live shortcut API, so new entries appear in the library immediately instead of waiting for Steam to reread `shortcuts.vdf`.

The launcher runs as the logged-in ArmadaOS user. The backend reads graphics variables from Steam's process environment, preferring Steam over its web helpers. The shortcut inherits Steam's own target display. The launcher drops Vulkan-layer and compatibility overrides, retains Steam identity and limiter metadata, and disables the Gamescope WSI layer. Nested Gamescope provides a fresh Wayland socket to Android. Steam's launch process owns its lifetime, and a transient user service owns the Waydroid session. Readiness is checked before opening the full UI or requested app. Session logs are under `~/.local/state/waydroid-manager`.

The launcher preserves `SteamAppId` and `SteamGameId` as identity metadata. The display helper finds the same user's Gamescope process with `--steam`, then identifies its control Xwayland server through shared socket descriptors. This also handles Xwayland servers reparented to systemd and avoids selecting a separate second-screen compositor. It reads the primary compositor's refresh rate at launch for Android's advertised display. It does not copy `GAMESCOPE_FPS_LIMIT`: that property can retain an inactive value while QAM uses the combined refresh-cycle protocol. The SDL host backend uses a FIFO Vulkan swapchain; actual frame pacing and QAM cap changes still require live validation.

Nested Gamescope uses its SDL X11 host backend on Steam's inherited `DISPLAY`, with `SDL_VIDEODRIVER=x11`. Android still connects to the nested compositor's Wayland socket. This gives Steam an X11 game window with the launch process's shortcut identity. The native Wayland host backend failed to keep a focusable window published during direct app launches on the tested Armada build. Background Android startup remains in use; the launcher does not open the Android desktop before launching the requested package. Forced composition is not enabled. `--default-touch-mode 4` forwards touch to Android instead of using Gamescope's default mouse-click emulation.

The nested instance sets `GAMESCOPE_MANGOAPP_SOCKET_DISABLE=1`. Gamescope instances share Mangoapp's legacy message queue, so nested telemetry must not mix with the primary compositor's stream. The primary compositor continues to report the final Steam game window. An overlay count above the display refresh rate must be checked against actual presentation timing; mixed telemetry is not proof that Android rendered that many distinct displayed frames.

Each launch reconnects Android even if the Wayland socket name matches a previous launch, because a new compositor can reuse that name. A fixed transient user service owns the plugin's session. Shutdown stops that service before terminating nested Gamescope; a five-second bound prevents a stuck compositor from leaving Steam tracking the old shortcut indefinitely. The launcher clears stale readiness markers before starting a session and allows up to three minutes for Android readiness.

The root backend also starts a transient input synchronizer while the plugin is loaded. It mirrors Steam Input's virtual X-Box controller node into the active Android container with Android's expected ownership and permissions. It detects the InputPlumber shared physical controller and uses that controller's installed Armada Android keylayout for Steam's virtual identity. Armada's built-in Waydroid input service continues to own physical controller sharing. Live Android device enumeration must be checked when investigating duplicate input; pointer events from Steam mouse mappings are a separate input source.

Steam writes its own `shortcuts.vdf` data after the frontend calls `SteamClient.Apps.AddShortcut`. The backend provides the trusted launcher, working directory, arguments, and Waydroid-provided app icon path. Shortcut launch options use Armada's `armada-game-launch %command%` wrapper so Steam Input and per-game performance settings remain attached. It records returned shortcut IDs in `~/.config/waydroid-manager/state.json`, and also recognizes Armada-rewritten shortcut records by their app name. The frontend periodically asks the backend for newly discovered apps when automatic additions are enabled; the backend keeps a durable observed and removed set so the feature only queues genuinely new installed apps.
