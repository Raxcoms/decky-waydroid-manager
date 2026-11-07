# Fresh-device validation

Use this procedure for a complete release check on a device with no initialized Waydroid image. Keep a private evidence log with the build revision, OS build, actions, screenshots, settings before and after, and observed failures. Do not put supplied packages, real package names, local filenames, credentials or private evidence in the repository.

## Prepare the fixtures and device

Before starting, ask the user to provide:

- An `.apk` suitable for launch and gameplay checks, including any older Android compatibility behavior they want tested.
- A second `.apk` when another renderer, Android version target or controller implementation needs coverage.
- An `.xapk` containing split APKs for uninstall/reinstall and shortcut-history checks.
- Confirmation that these fixtures and their Android data may be removed during the test, and availability for physical touch/controller checks.

Do not download substitute applications or assume an arbitrary app supports controllers. Use generic identifiers such as APK-A, APK-B and XAPK-A in the committed result. Record actual paths, hashes and package identifiers only in private evidence. Stage files in a unique user-owned directory outside the repository and verify their hashes after transfer.

Record these baselines before installation:

- Device architecture, OS, kernel, Decky, Waydroid and Gamescope versions.
- Active Steam user, primary compositor/socket, display orientation and mode.
- Image, user-data, desktop-entry and plugin-state paths that already exist.
- Service activity and boot enablement, current controller/input service state, and existing Steam shortcuts/artwork.
- Steam performance settings and composition flags. Preserve unrelated profiles and custom artwork.

Use the exact CI artifact for the branch revision. Its name contains the short commit SHA. Inspect the archive structure and install it through Decky's native ZIP installer. Do not install OS overlays, replace the compositor, edit system files or change Android verification policy to make the test pass.

## Image and full-environment workflow

1. Open the plugin. Confirm it reports no installed image and exposes initialization.
2. Initialize the GAPPS image through the real button and confirmation. Observe feedback until completion. Verify the resulting image/configuration and architecture, rather than relying only on the button's return value.
3. Confirm the status changes to installed. Add the environment to Steam and check the same control changes to Remove. Verify the actual live Steam entry, name, executable, arguments and ownership.
4. Launch the existing Steam shortcut. Wait for Android readiness and then for actual presentation. Capture the primary compositor; a resumed Android activity alone does not prove Steam's loading screen has cleared.
5. Quit the owned launch normally. Check that its relay, temporary session, input nodes/mounts and frame overrides are released. Repeat at least three times without restarting the container service as a workaround.
6. Enable automatic shortcuts through the real toggle. Verify the saved setting and that the apps already present are treated as the baseline rather than new installations.

## Packages, shortcuts and artwork

1. With Android stopped, select APK-A through the native file picker. Verify background startup, phase progress, disabled busy controls and success/failure feedback.
2. Normal verification must not ask for extra approval. If Android reports a blocking verification decision, confirm that a second native prompt appears for this install only. Exercise Cancel, verify no partial installation/shortcut, then retry and approve when authorized.
3. Verify installation through Android's package manager and generated desktop entry. Confirm the install operation restores any temporary service/session it owned and keeps Android verification settings unchanged.
4. Repeat for APK-B and XAPK-A. Verify every split of the `.xapk` is installed. Also test a deliberately invalid archive generated locally, without modifying a user's package.
5. Close the plugin while installing or adding a later fixture when practical. Verify automatic shortcut discovery continues without reopening the panel.
6. Inspect Steam's live library, not only the plugin's saved IDs. Each package must have one correctly named shortcut with valid launch arguments, its app icon, and portrait, landscape, hero and logo assets. Existing custom assets must survive reconciliation. Icon-based cards are valid when the package has no suitable publisher artwork; record that distinction.
7. Reopen each app menu. Launch and Remove from Steam must appear for an existing shortcut, and Uninstall must appear for a removable third-party package even after the temporary Android session stops. System packages must not offer uninstall.
8. Remove XAPK-A's shortcut through Steam's own library interface. Verify the plugin detects it, changes to Add to Steam, and does not recreate it while the app remains installed.
9. Uninstall XAPK-A through the plugin. Verify native confirmation, progress, feedback, package removal, desktop-entry removal, shortcut removal and clearing of the package's manual-removal history.
10. Reinstall the same `.xapk` with automatic shortcuts still enabled. Verify a real shortcut is created again, with the correct name and artwork and no duplicates.
11. Uninstall it again while its shortcut exists. Confirm the shortcut disappears automatically without a separate removal action.

## Launch, input and rendering

- Launch APK-A from its existing Steam shortcut, quit the app fully, and repeat. Check actual presentation and the selected Android activity. Do not restart Waydroid or the input service between launches to conceal a lifecycle failure.
- Inspect Android's gamepad identity, keylayout, stick/trigger/hat metadata and device count. Ask the user to test touch, both sticks, triggers, X/Y and the D-pad. Native virtual-button navigation is UI evidence, not proof of physical-controller delivery. Record app-level controller limitations separately.
- Exercise Steam's global and per-shortcut resolution selectors through their native UI. Verify Android's display mode, touch viewport and app buffer dimensions separately. Account for rotation, fullscreen state, letterboxing and the app's own internal rendering resolution. Restore the original profile after the check.
- In an animated scene, change the QAM limit through at least two values. Compare Android app buffer/presentation timing, the selected target and the performance overlay. Check that changing the slider updates the running app and that frame reporting is not doubled. An app's own lower cap is not a limiter failure.
- Check GPU counters and the other reported statistics against their real data source. Do not infer Android process CPU/RAM from the relay's process accounting.
- Inspect the running compositor's force-composition flag and actual fullscreen presentation state. Verify the plugin launches no extra compositor or rendering stage. Keep QAM/overlays closed when checking scanout; their ordinary composition is different from forcing game composition.
- Record visual artifacts, pacing and input latency during physical gameplay. A still screenshot does not establish frame pacing or the absence of intermittent artifacts.

## Focus and pagination

Test both paced and rapid controller navigation using Steam's real navigation context:

1. Expand the list beyond ten items where available. Confirm alphabetical ordering and guarded batches of ten, including the final smaller batch.
2. Open and close an app menu, file picker, confirmation and nested verification prompt. Check the originating row retains focus and the expanded list remains expanded.
3. Add/remove a shortcut without remounting the panel or collapsing the list.
4. Scroll to the final control and navigate upward. The viewport must reach the first section before focus leaves for Decky's back button. Check the full first field and final control remain visible and there is no horizontal overflow.
5. Leave the plugin normally and reopen it. The list must return to its initial page. Returning from a modal must retain expansion.
6. Inspect install, uninstall, verification and image-removal dialogs. Their action buttons should be side by side, navigate horizontally, remain disabled during busy work, and return focus correctly after cancellation or completion.

## Service commands and full removal

1. With owned launches closed, test Stop, Start and Restart through the plugin. Verify actual service transitions and success/failure feedback. Boot enablement must remain at its baseline.
2. Use the full image/data removal control and its real destructive confirmation. This step is destructive and must be authorized before the test begins.
3. Verify image/configuration, Android user data, generated desktop entries and owned Steam shortcuts are gone. Inspect owned artwork and caches for orphaned files. Preserve unrelated Steam entries, custom data and platform-provided files.
4. Keep the plugin loaded and poll again to ensure background watchers do not recreate deleted entries or stale state. Confirm initialization is offered again and passive polling does not start the service.
5. Compare the filesystem and service state with the recorded baseline. Distinguish intentional plugin preferences/logs and plugin-lifetime runtime resources from orphaned Android image data; report any retained files explicitly.
6. Remove only verified test copies, captures, diagnostic stages and temporary overrides. Preserve original user files and any explicitly retained deployment backup.

## Results and release checks

Use a result table with one row for each stage above: baseline, initialization, full shortcut, auto-create, each package type, manual library removal, uninstall/reinstall, repeated launches, input, resolution, frame limits/statistics, composition, focus/pagination, service controls and full deletion. Record Passed, Failed or Not tested with supporting evidence and limitations. Never convert a workaround or unavailable physical/device check into a pass.

Fix failures on the tested branch in small commits, rerun the checks relevant to the change, update the installed test build, and repeat the failing workflow. Keep APK/XAPK fixtures outside commits and build artifacts. Finish with the Python/frontend checks, TypeScript/build, clean package validation, and a successful CI artifact named for the final revision.
