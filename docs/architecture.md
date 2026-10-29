# Architecture

```text
Decky UI
  -> root Decky backend
     -> Waydroid CLI and systemd service
     -> Steam shortcuts.vdf
  -> bundled launcher started as the ArmadaOS user
     -> nested Gamescope Wayland socket
        -> Waydroid session
           -> Android full UI or selected package
```

The backend owns system-wide operations because the Waydroid image and container service are root-owned. The frontend does not compose shell commands: it calls narrow backend methods with validated package names.

The launcher runs as the logged-in ArmadaOS user, not as Decky root. It starts Gamescope's Wayland backend on the current Game Mode socket. Gamescope supplies its child command with a new Wayland socket, which `waydroid session start` and the selected UI command then use. Each launcher process writes session logs under `~/.local/state/waydroid-manager`.

Steam shortcuts use Steam's binary `shortcuts.vdf` format. The backend preserves existing shortcut fields, writes the new entry atomically, and does not create duplicate Waydroid launcher entries.
