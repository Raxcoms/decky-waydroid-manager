# Live validation

## Thor, 6 November 2026

The plugin was deployed with backups and tested in the existing primary Gamescope session. The device also had a separate companion-screen compositor. No OS packages, system extensions, replacement compositor, or forced composition were used.

| Check | Result |
| --- | --- |
| QAM limiter | Warframe measured 29.99 FPS at a 30 FPS target. The user confirmed the overlay showed the correct rate and followed slider changes. A later shortcut launch measured 60.01 FPS under its 60 FPS profile. |
| Duplicate reporting | During a five-second Warframe sample, 300 incoming commits became 150 forwarded commits after redundant commits were removed. |
| Controller layout | Android enumerated the Steam virtual controller with stock Xbox stick, trigger, and D-pad metadata. The user confirmed X/Y and all D-pad directions matched Desktop Mode. |
| Individual shortcut launches | Warframe displayed its launcher through its own Steam shortcut twice consecutively. The app and owned session were quit between runs; the system container service was not restarted. |
| Shortcut resolution | With Warframe set to 720p, its inherited game display was 1280x720 while Android initially stayed at 1920x1080. After the relay update and a fresh Steam shortcut launch, the relay log and Android's physical display mode both reported 1280x720. The native compositor capture showed Warframe at that size. Its 120 Hz mode and existing 30 FPS Android overrides remained present. |
| Actual game buffers and fullscreen | A deeper check found that Warframe initially retained a 1920x1072 app buffer, which Android scaled to its 1280x720 display. After the user selected 720p inside Warframe, SurfaceFlinger reported a 1280x720 active app buffer with no scaling transform. WindowManager reported FULLSCREEN, full 1280x720 bounds, and hidden status/navigation bars. The user confirmed direct touch and controller input still worked. |
| App-level frame limiting | With Warframe's own cap kept at 60, QAM was temporarily tested at 30 and 20 FPS through the real slider. Warframe's layer buffer-ready timestamps measured 29.87 and 20.06 FPS; its actual-presentation timestamps measured 30.02 and 19.96 FPS. These measurements came from the Android app layer rather than MangoHud or the relayed output. QAM was restored to its original 120 FPS setting and the game was left running. |
| Library actions | Calculator was added and removed through the real app menu. Launch and Remove appeared after addition. Both completion toasts appeared, focus stayed on Calculator, and the expanded list retained all 20 apps. The original removed-shortcut state was restored. |
| Uninstall | Soul Knight was removed through the real app menu and confirmation while Android was stopped. The temporary background session became ready, completed removal, and stopped afterward. Its desktop entry, Steam app record, and shortcut history were removed. Steam's notification tray recorded the success toast. The previously active container service stayed active, with the Android container stopped. Boot failures, timeouts, and service restoration have unit coverage. |
| Uninstall progress | A temporary frontend preview targeted a protected system package, so no user app could be removed. The native bar showed Android readiness at 25%, with the button changed to Desinstalando and controls visually disabled. The protected-package rejection produced an error toast, restored the dialog's buttons, and stopped the temporary session. The production frontend was restored and its hash verified afterward. |
| Reinstalled shortcut | Soul Knight's old state contained an ID absent from Steam's live library. Its stale tracking was backed up and requeued without changing Android data. The normal automatic watcher created a real Steam app overview, recorded its ID, and emitted the addition toast. The production menu then showed Launch, Remove from Steam, and Uninstall. MHOutlanders' changed ID was also reconciled. State-race and remove/uninstall/reinstall behavior have regression coverage. |
| App pagination | The native app menu, confirmation dialog, and file picker each returned to all 20 expanded apps. Leaving through Decky's plugin back button and reopening returned to ten apps with Show more available. |
| Installation failures | A harmless invalid APK was selected through Decky's real file picker. A stopped session and an invalid archive both produced error toasts with their causes. The fixture was removed afterward. |
| Top scrolling | Paced Steam Up navigation from the bottom reached scroll position zero while focus remained in the Waydroid section. The next Up reached Decky's back button with the top content visible. |
| Artwork | Missing Soul Knight artwork slots were populated from bundled app assets and icon-based cards. Existing Warframe custom images were preserved. Generated output was downloaded and inspected. |
| Artwork after shortcut recreation | Soul Knight's recreated shortcut had no files for its new app ID while Android was stopped. Offline discovery found its five installed APKs and bundled icon resources. The watcher populated all four artwork slots without starting Android; its pending queue became empty. Downloaded portrait, hero, and logo images were inspected, and Steam's actual Soul Knight details page displayed the generated hero and logo. This APK's selected image candidates were icons, so the covers use app-icon cards rather than publisher cover art. |
| GPU usage | Android renderer and SurfaceFlinger DRM counters were present while the relay initially had none. After enabling the handle bridge, MangoApp opened the relay's real Android fdinfo records. The user confirmed that GPU usage changed above zero in Warframe. |

## Cleanup branch review, 6 November 2026

The `cleanup-review` build was deployed on the Thor with per-file backups. The code review and all requested topic boundaries are recorded in [review.md](review.md).

| Check | Result |
| --- | --- |
| Automated checks | The cleanup suite covers verification-request ownership, normal verification without a prompt, concurrent/completed requests, cancellation and commit cleanup. Ten frontend tests, TypeScript and Rollup pass. Linux-only cases run on the Thor; Windows skips those 18 cases. CI also builds the verification Dex, imports the staged backend and verifies its runtime files and clean package contents. |
| Native app fields | Standard Decky Field padding is visually verified on the actual QAM. Icons, names and packages are visible. The scroll container has equal client/scroll widths of 300 CSS pixels, with no horizontal overflow. The inline button experiment that exceeded the row width was removed. |
| Action menu | Selecting the native Calculator field opens its real Steam/Decky menu. Its manually removed shortcut remains removed. |
| Focus and scrolling | Native paced Up navigation from the destructive final control reaches scroll position zero while focus is still on the Waydroid launch button. Only the following Up reaches Decky's back button. |
| Independent service start | With the system container service stopped, the existing full-container Steam shortcut starts it through the root-backend socket and displays Android. A primary Gamescope output capture was downloaded and inspected. |
| Temporary input setup | Live Android enumeration selects `/system/usr/keylayout/Vendor_28de_Product_11ff.kl` from the owned temporary mount. The directory is on Android `/dev`, and the mirror is in Android's private input directory. The tested stock Xbox mapping is retained without an image-file edit. |
| Input/GPU ownership | Closing the controlled launch leaves no running plugin session. A following package-only boot does not recreate launch-specific input mounts. Every discovered Android GPU client uses renderD128, not a primary display node. |
| Install from stopped Android | The real file picker selected a deliberately invalid APK containing a manifest entry. The native modal showed background startup and phase progress with disabled buttons. Android rejected its corrupt XML, no app was installed, and temporary staging/session resources were removed. |
| Cold-service cleanup | An initial check exposed Waydroid status's D-Bus activation. After adding passive systemd guards, service state stayed inactive through normal panel polling, started for installation, and returned to inactive after failure. Verification used systemd rather than the activating Waydroid status command. |
| Error feedback | The dialog initially displayed a Java traceback tail. Cause extraction now shows `Corrupt XML binary file` and restores retry/cancel controls. The error remains readable after the notification disappears. Multiline Android errors have a frontend regression test. |
| Supplied Fortnite XAPK | The user's four-split Fortnite XAPK installed through a native Android install session. Android exported its desktop entry and the automatic watcher recorded a Steam shortcut. |
| Supplied Zenonia APK | A live native-session test installed the user's Zenonia 3 APK after matching its exact verification request and sending approval through Android's framework API. Commit returned `Success`; `pm path com.gamevil.zenonia3.global.skt` returned its installed base APK. The verification setting was `null` before and after. No screen monitoring or settings change was used. Integration testing of the new plugin confirmation follows this API-level test. |

Owned invalid fixtures, staging directories and test sessions are cleaned after validation. The real APK/XAPK tests use files explicitly supplied by the user. These checks do not substitute for physical-controller gameplay testing after the temporary input implementation, nor for fresh rotation and multi-device validation.

## Remaining limits

The installed Gamescope logs `NO CURSOR IMPL XDG` for native window focus. Steam mouse-mode cursor visibility remains unresolved in this compositor path. Direct touch is not disabled to work around it.

These checks cover launcher screens and the interactions above. They do not establish the absence of graphical artifacts, input latency, or frame-pacing problems during extended gameplay. Other resolutions, portrait rotation, and other devices still need broader live validation.
