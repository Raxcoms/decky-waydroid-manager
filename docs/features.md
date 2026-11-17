# Use Waydroid Manager

## Add Android apps to Steam

1. Open **Waydroid Manager** in Decky.
2. Select an app under **Android Apps**, then choose **Add to Steam**.
3. Use **Launch** from the app menu or open the new shortcut in your Steam library. To remove just the shortcut, choose **Remove from Steam**.

Use **Show more** to reveal ten more apps at a time. Enable **Add new apps to Steam** to create shortcuts for apps installed after you turn it on. If you remove a shortcut, use **Add to Steam** to bring it back. Uninstalling the app clears that removal history, so a later reinstall can be picked up automatically.

Steam shortcuts and automatic-add preferences follow the signed-in Steam account. If you used an older build with several Steam accounts, turn on automatic addition again for each account where you want it.

The plugin generates matching portrait, landscape, and header artwork from the Android app icon. You can also set custom artwork in Steam.

## Install or uninstall an Android app

| To do this | In Waydroid Manager |
| --- | --- |
| Install an APK or XAPK | Choose **Install APK or XAPK** and select the file from your home folder. |
| Uninstall a downloaded app | Select the app, choose **Uninstall**, and confirm. This also removes its Steam shortcut. |
| Respond to an Android verification prompt | Choose **Cancel** or **Install anyway**. The decision applies only to that install. |

The progress dialog follows the operation while Android starts in the background if needed. Per-install verification approval is supported on the tested Android 13 GAPPS image.

If Steam cannot remove a shortcut right away after an uninstall or image removal, Waydroid Manager retries the shortcut cleanup in the background. For another Steam account, cleanup resumes when you sign in to that account.

## Adjust a Steam launch

Plugin shortcuts share one Android session. Close an ordinary Waydroid session
started outside the plugin before launching through Steam.

- Set the resolution in Steam's shortcut properties before launching. Android receives the selected display size when Steam exposes a single active game output. With an ambiguous multi-output layout, Android keeps the size reported by Gamescope. An in-game resolution setting still controls how the game renders.
- Adjust the frame cap in Steam's Quick Access performance settings. See [frame limits](#frame-limits) for compatibility and display behavior.
- Use Steam Input and direct touch where supported by your Game Mode session. On some Gamescope builds, mouse mode can deliver pointer input with no visible cursor.
- Use Steam's performance overlay to monitor the launch. GPU usage requires a compatible driver and MangoHud.

### Frame limits

With a compatible Android 13 composer build, Steam's frame limit controls Android's display cadence while the shortcut is running. Whole-number caps such as 14, 27 and 47 FPS do not need to divide the screen's native refresh rate. Changing the cap also covers Android's launcher, navigation and notification shade.

The limiter works with second-screen support enabled or disabled. Each screen stays within its own native refresh rate. For a device with a 120 Hz primary screen and a 60 Hz second screen:

| Steam cap | Primary cap | Second-screen cap |
| --- | --- | --- |
| 14 FPS | 14 FPS | 14 FPS |
| 40 FPS | 40 FPS | 40 FPS |
| 120 FPS | 120 FPS | 60 FPS |

These are rendering limits, not a guarantee that an app will reach that frame rate. A fixed-refresh panel can still repeat frames unevenly when the cap does not divide its refresh rate. The plugin does not change the physical panel mode.

The composer overlay and frame-limit policy are temporary. Closing the last plugin shortcut releases them. Ordinary Waydroid launches keep the installed display driver and saved Android settings.

Without a compatible native build, the existing Android 13 per-app limiter remains available. That fallback only supports refresh-rate divisors and does not cap every Android UI surface. Other Android versions need a compatible native profile before display-wide limiting can be enabled.

### Interface scaling

Compatible images scale Android's interface with the launch resolution, using the 720p layout as a reference. On the default image, 720p uses 180 DPI and Full HD uses 270 DPI. Existing image density curves and explicit custom DPI settings take priority. The scaling applies only to plugin launches.

### Generated artwork

Generated covers, banners and heroes use twice Steam's standard image dimensions. They use a stronger color gradient over a softened app-icon background, and the hero icon is centered.

When Android is running, the plugin requests a 512-pixel version of the icon from the app's actual launcher activity, including aliases and adaptive icons. It caches that icon for offline artwork generation. Existing exported icons remain the fallback. Only untouched plugin-generated artwork is refreshed; custom artwork is preserved.

## Use a second screen

Choose **Enable second screen support** from an app's menu or **Waydroid actions**.
The enable action appears when the host advertises a secondary Wayland output.
An enabled shortcut keeps its disable action if that output becomes unavailable.
Each app has its own setting, disabled by default. The setting in **Waydroid
actions** applies only to the full Waydroid shortcut.
On first enable, a progress dialog checks the installed Android interfaces and
builds the resource overlays from that image's framework and System UI. This uses
private tools shipped with the plugin and requires no downloads or host OS changes.
Later enables reuse a validated cache. An image or resource update rebuilds it.

Confirm the restart notice, then close existing launches before starting the
enabled shortcut. Android starts a secondary launcher on the host's other screen.
The menu offers **Disable second screen support** after enabling it.

Apps start on the screen running Steam. Android treats the leased screen as an
external display; apps with external-display support can use it for extra content.
Android initializes the second display before the app starts, so dual-screen
apps can detect it during startup. The host window stays hidden until Android
confirms the primary activity has started. A failed launch leaves the physical
screen with its previous user.

The external output returns to its previous host window when the final enabled
shortcut closes. Ordinary Waydroid launches outside the plugin keep their original
configuration. A compatible Waydroid image and host secondary output are required;
see [second screen support](dual-screen-investigation.md) for compatibility and
cleanup details.

### Link a companion app

1. Enable second-screen support for the primary app.
2. Open that app's menu, choose **Link companion app**, and select another installed Android app.
3. Launch the primary app's Steam shortcut. The companion opens on the second screen, while input focus stays on the primary screen.

The menu then shows **Unlink companion app**, with the linked app's icon on the right. Changes apply on the next launch. Disabling second-screen support leaves the saved link inactive until you enable it again.

Both apps use the same Steam shortcut and frame-limit settings. Closing the shortcut also closes its companion, unless another active plugin shortcut still uses that app. Companion links are available only for individual apps.

## Access your host home folder

Your host home folder is shared automatically whenever you launch Waydroid or an
Android app through the plugin. Open **Internal storage > Host > Home** in Android's
file picker. Apps can read and write files there through Android's folder-access
picker.

Changes in Android also change the files in your host home folder. The mount
belongs to the plugin's Android session and disappears when that container exits.
Ordinary Waydroid sessions started outside the plugin keep their original mounts.

Mounted external drives appear as separate folders inside **Host**, named after
their volume labels. Mounting or unmounting a drive on the host updates Android's
folders while the session is running. The plugin uses the host's UDisks storage
service and keeps system partitions out of this list.

The host kernel and home filesystem must support idmapped mounts. Sharing does
not change your host files' ownership or permissions.

## Manage Waydroid

Use **Start**, **Restart**, or **Stop** under **Waydroid Service** to manage the container service. To delete Waydroid, its Android apps and data, and the associated Steam shortcuts, select **Uninstall Waydroid** under **Waydroid Status**.
