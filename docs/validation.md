# Live validation

## Thor, 6 November 2026

The plugin was deployed with backups and tested in the existing primary Gamescope session. The device also had a separate companion-screen compositor. No OS packages, system extensions, replacement compositor, or forced composition were used.

| Check | Result |
| --- | --- |
| QAM limiter | Warframe measured 29.99 FPS at a 30 FPS target. The user confirmed the overlay showed the correct rate and followed slider changes. A later shortcut launch measured 60.01 FPS under its 60 FPS profile. |
| Duplicate reporting | During a five-second Warframe sample, 300 incoming commits became 150 forwarded commits after redundant commits were removed. |
| Controller layout | Android enumerated the Steam virtual controller with stock Xbox stick, trigger, and D-pad metadata. The user confirmed X/Y and all D-pad directions matched Desktop Mode. |
| Individual shortcut launches | Warframe displayed its launcher through its own Steam shortcut twice consecutively. The app and owned session were quit between runs; the system container service was not restarted. |
| Library actions | Calculator was added and removed through the real app menu. Launch and Remove appeared after addition. Both completion toasts appeared, focus stayed on Calculator, and the expanded list retained all 20 apps. The original removed-shortcut state was restored. |
| Uninstall visibility | The actual APKPure menu retained Uninstall after Android stopped. User apps were not uninstalled for this check; package-manager failures and cleanup ordering have unit coverage. |
| Installation failures | A harmless invalid APK was selected through Decky's real file picker. A stopped session and an invalid archive both produced error toasts with their causes. The fixture was removed afterward. |
| Top scrolling | Paced Steam Up navigation from the bottom reached scroll position zero while focus remained in the Waydroid section. The next Up reached Decky's back button with the top content visible. |
| Artwork | Missing Soul Knight artwork slots were populated from bundled app assets and icon-based cards. Existing Warframe custom images were preserved. Generated output was downloaded and inspected. |

## Remaining limits

The installed Gamescope logs `NO CURSOR IMPL XDG` for native window focus. Steam mouse-mode cursor visibility remains unresolved in this compositor path. Direct touch is not disabled to work around it.

These checks cover launcher screens and the interactions above. They do not establish the absence of graphical artifacts, input latency, or frame-pacing problems during extended gameplay. Per-game resolution overrides and other devices still need live validation. Package installation success was covered with package-manager fixtures rather than installing an unrelated app on the user's device.
