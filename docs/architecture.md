# Architecture

```text
Decky UI
  -> root Decky backend
     -> Waydroid CLI and systemd service
     -> launcher and Waydroid icon metadata
  -> Steam client shortcut API
  -> bundled launcher started as the ArmadaOS user
     -> nested Gamescope Wayland socket
        -> Waydroid session
           -> Android full UI or selected package
```

The backend owns system-wide operations because the Waydroid image and container service are root-owned. The frontend does not compose shell commands: it calls narrow backend methods with validated package names. It creates shortcuts through Steam's live shortcut API, so new entries appear in the library immediately instead of waiting for Steam to reread `shortcuts.vdf`.

The launcher runs as the logged-in ArmadaOS user, not as Decky root. The backend maps the Gamescope process running with `--steam` to its exposed Wayland socket and starts a nested Gamescope backend on that socket. This avoids confusing Game Mode with another exposed Gamescope session, such as a secondary display. Gamescope supplies its child command with a new Wayland socket, which `waydroid session start` and the selected UI command then use. Each launcher process writes session logs under `~/.local/state/waydroid-manager`.

Steam writes its own `shortcuts.vdf` data after the frontend calls `SteamClient.Apps.AddShortcut`. The backend only provides the trusted launcher, working directory, arguments, and Waydroid-provided app icon path.
