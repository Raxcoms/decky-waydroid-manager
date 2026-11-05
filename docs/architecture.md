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

The launcher runs as the logged-in ArmadaOS user, not as Decky root. The backend reads `DISPLAY`, `WAYLAND_DISPLAY`, and `GAMESCOPE_WAYLAND_DISPLAY` from Steam's own process environment, preferring Steam over its web helpers. This identifies the current Game Mode compositor without assuming a socket name, user ID, display number, or device model. It also passes Steam's current rotation-aware target size to nested Gamescope. The launcher starts with a minimal environment, drops Steam's Vulkan-layer and compatibility variables, carries only Steam's shared limiter file, disables the Gamescope WSI layer, and nests Gamescope on the active Wayland socket. Its child command receives a fresh Wayland socket for the Waydroid session. It supervises nested Gamescope using Steam's owning launch process, so closing the Steam shortcut also stops the session and removes the old socket. A transient user service owns the session and waits for Android's ready message before opening the full UI or an app. Each launcher process writes session logs under `~/.local/state/waydroid-manager`.

The root backend also starts a transient input synchronizer while the plugin is loaded. It mirrors Steam Input's virtual X-Box controller node into the active Android container with Android's expected ownership and permissions. Armada's built-in Waydroid input service continues to own physical controller sharing; the synchronizer covers Steam's virtual output so per-game mappings and mouse mode reach Android without changing the base deployment.

Steam writes its own `shortcuts.vdf` data after the frontend calls `SteamClient.Apps.AddShortcut`. The backend provides the trusted launcher, working directory, arguments, and Waydroid-provided app icon path. Shortcut launch options use Armada's `armada-game-launch %command%` wrapper so Steam Input and per-game performance settings remain attached. It records returned shortcut IDs in `~/.config/waydroid-manager/state.json`, and also recognizes Armada-rewritten shortcut records by their app name. The frontend periodically asks the backend for newly discovered apps when automatic additions are enabled; the backend keeps a durable observed and removed set so the feature only queues genuinely new installed apps.
