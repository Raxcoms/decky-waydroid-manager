# Cleanup review

This review is maintained on `cleanup-review`. Changes are split into package lifecycle, Steam integration, packaging, runtime ownership, and frontend commits. This is a drop-in plugin for an existing Waydroid and Steam Game Mode platform; the plugin does not install missing OS capabilities.

## Review coverage

| Topic | Finding and change | Current boundary |
| --- | --- | --- |
| Workarounds | Removed an unused display helper, direct VDF writers, obsolete launch RPCs, negative row offsets, and an undocumented modal-closing prop. | The Wayland commit filter remains necessary to avoid duplicate presentation reports. It forwards unchanged traffic when object tracking becomes unsupported. |
| Standardization | Shared container constants, environment cleanup, process discovery, archive validation, state persistence, RPC contracts, and Steam actions. | Linux, Waydroid, Steam and Android protocol identifiers are kept explicit rather than disguised as device settings. |
| Architecture | Narrow modules separate UI contracts, library compatibility, artwork, input, service control, state, frame limits, and Wayland transport. `main.py` composes them and exposes Decky RPCs. | Shell entry points still own the Steam process/session lifetime; replacing working process supervision is outside this cleanup. |
| Hardcoded selection | Removed highest-DRM-mode and device-name display inference. Launches inherit Steam's display/socket. Package operations discover the Steam user's session. Account selection follows MostRecent and rejects ambiguity. Multiple Steam installations require an identifiable active Steam process. | Standard Waydroid paths, systemd service names, and Steam artwork sizes describe external interfaces. They are not Thor settings. |
| Hardware behavior | Steam's virtual controller uses the installed Android Xbox keylayout, including its axis metadata. No physical handheld layout or button correction is copied. | The Steam virtual VID/PID identifies a protocol device. Android input GID is an Android ABI value. Other controller protocols use the platform's own sharing support. |
| Duplication | Install and uninstall share the same hidden startup/cleanup context, boot-readiness wait, and progress modal. APK and split XAPK installation use one native install-session helper with explicitly approved per-install verification and failure abandonment. Existing sessions that are still booting are waited for and preserved. All frontend backend callables live in `backend.ts`; Steam actions live in `steam.ts`. | UI state and native API compatibility have independent, focused tests. |
| Maintainability | Bounded file parsing, typed state, unsigned shortcut IDs, unchanged-write suppression, worker-thread command execution, and logical CI packaging replace implicit assumptions. | Add a new module when it owns a distinct interface, not just to shorten a file. |
| Armada dependencies | New shortcuts run the bundled launcher directly. Existing exact Armada-wrapper launch options are migrated through Steam's API. A root-backend runtime socket starts the service without sudoers or an installed host service. | Native Wayland window identity and direct touch require support in the running Gamescope. This was tested on Armada's implementation; upstream Gamescope compatibility is not established. |
| Persistent modifications | Replaced the persistent Android controller keylayout with a temporary bind view under Android `/dev`. Input nodes are owned and restored. Frame overrides are restored on launch exit/unload. Image removal stops the service without changing its boot enablement. | Image/package installation, explicit deletion, plugin preferences, Steam shortcuts/artwork, and launcher logs are intentional persistent user actions/data. |
| Passive inspection | Waydroid's status CLI can activate its D-Bus service. Offline session checks and package polling now check systemd state before contacting Waydroid. | Verify a stopped service through systemd, not `waydroid status`; otherwise the inspection itself can start it. |
| Drop-in installation | Every helper is shipped in the plugin. No package overlays, OS extensions, compositor replacement, rootfs edits, sudoers rules, or installed system units are used. | Waydroid, Binder, LXC tooling, systemd user services, Python and a compatible Steam compositor must already exist. |
| Frontend | Native Field, ButtonItem, ToggleField, Menu, ModalRoot, Dialog components, ProgressBar, picker and toast APIs replace custom row composition and undocumented modal behavior. App fields use standard padding and native focus highlighting. | A scoped scroll-to-top callback remains because Steam otherwise reveals only the first button, clipping the status above it. It changes scroll position, not CSS or focus ownership. |
| Validation and delivery | Linux/Windows unit coverage, TypeScript, frontend tests/build, shell syntax, clean packaging, and live Thor checks accompany the changes. CI builds all branches and uploads a plugin directory directly. | Physical controller feel, extended game pacing, rotation and other devices still need broader testing. |

## Ownership and lifetime

| Resource | Owner | Lifetime and cleanup |
| --- | --- | --- |
| Plugin settings/history | User's `~/.config/waydroid-manager/state.json` | Atomic replacement under a shared edit lock; paths must stay inside the user home; unchanged state is not rewritten. |
| Steam shortcuts/artwork | Steam client | Add/remove/update through Steam's live API. VDF is read-only. Existing custom artwork is preserved. Launching an entry does not rewrite its options or icon. |
| Service-control socket | Root Decky backend, accessible only to the Decky user | `/run/user/UID/waydroid-manager-control.sock`, peer-authenticated, fixed START command, bounded clients/timeouts, removed on unload. |
| Input synchronizer | Root Decky backend | Transient systemd unit while the plugin is loaded. Android input changes apply only during a plugin-owned relay launch. |
| Keylayout view | Active Android container | Temporary `/dev` directory bound over the stock keylayout directory. Only the Steam virtual identity is added; stock files are copied unchanged. The mount is removed on exit or disappears with the container. |
| Mirrored input nodes | Active plugin launch | Private Android input directory only. Existing nodes are backed up and restored. Externally replaced nodes are not removed. Host evdev nodes are not chmod/chowned. |
| Package-operation session | Backend operation | Unique transient user unit; background boot; stopped in cleanup. An existing session is retained. A service started only for the operation is stopped when no session needs it. |
| Wayland/metrics sockets and child processes | Steam shortcut | Private runtime directory; handles, sockets and owned process groups are closed on launch exit. |
| Android frame overrides | Runtime limiter | Original per-UID values are saved and restored. No persistent Android width, height, refresh or frame-rate properties are written. |

Older plugin keylayout files are removed only when the ownership marker and file contents both match the former plugin output. A custom user keylayout is preserved. No generic cleanup of Android system configuration is performed.

## Frontend implementation rules

Use the published component props from the installed `@decky/ui` version. In particular, [Field](https://github.com/SteamDeckHomebrew/decky-frontend-lib/blob/main/src/components/Field.ts) supplies padding, icons, labels, descriptions and activation. [ModalRoot and showModal](https://github.com/SteamDeckHomebrew/decky-frontend-lib/blob/main/src/components/Modal.ts) supply modal lifecycle and dismissal controls. Keep pagination while a real menu/modal/picker owns the transition; reset it when the plugin is actually left.

App rows are full-width native fields with an action menu. An inline button's minimum width was found to overflow the QAM during live review and was removed. Service controls use separate native rows. There are no `!important` rules, injected style sheets, negative offsets, fixed QAM widths, or fake modal overlays. SVG robot icons and canvas-generated Steam artwork are content assets, not substitutes for native controls.

Package failures show both a toast and a retained error in the operation dialog. Progress uses named phase milestones, not a fabricated elapsed-time estimate. Busy operations reject repeated submission and dismissal; failures re-enable retry and cancellation.

## Deliberate compatibility limits

- SurfaceFlinger transaction 1039 is guarded to verified Android SDK 33. Supporting another Android release requires confirming its interface and override reporting; the plugin will not guess a Binder transaction.
- GPU telemetry uses `pidfd_getfd`, Android PID namespace matching, and render-node client identities. Primary DRM/display-master handles are excluded. Driver counters that do not exist cannot be synthesized accurately.
- The installed Gamescope's native XDG cursor implementation remains incomplete (`NO CURSOR IMPL XDG`). Direct touch and gamepad input are separate paths. The plugin does not patch the compositor or force composition to hide this limitation.
- The selected game resolution is discovered read-only from Steam's inherited Xwayland mode. Rendering stays on Wayland. Without that optional discovery tool, the compositor's original size hints are retained.
- An app can keep its own internal render-resolution or frame-rate setting. Android display size, app buffer size, producer timestamps, and Steam/MangoHud reporting must be checked separately.
- Android provides one user session. Starting a Steam launch reconnects that session to its private socket; simultaneous independent Android sessions are not supported.
- Flatpak userdata discovery is supported, but launching Waydroid from a Flatpak-confined Steam environment has not been validated. Live checks use native Steam.

## Validation

See [validation.md](validation.md) for measured results and the cleanup-branch checks. Automated tests cover package success/failure cleanup, verification-request ownership, archive validation, state/history races, shortcut ownership/account selection, protocol fragmentation and descriptor handling, native-library snapshots, controller-layout ownership, and control-socket authentication. Live package testing uses the APK and XAPK explicitly supplied by the user.
