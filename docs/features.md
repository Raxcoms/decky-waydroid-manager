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

You can open more than one Android app from Steam. Waydroid keeps one shared Android session and opens each app in its own Wayland window. Closing a Steam shortcut stops only that app; the shared session closes after the final Waydroid shortcut exits.

- Set the resolution in Steam's shortcut properties before launching. Android receives the selected display size when Steam exposes it. An in-game resolution setting still controls how the game renders.
- Adjust the frame cap in Steam's Quick Access performance settings. The result depends on [the refresh mode Waydroid exposes to Android](#known-issue-with-frame-cap-precision).
- Use Steam Input and direct touch where supported by your Game Mode session. On some Gamescope builds, mouse mode can deliver pointer input with no visible cursor.
- Use Steam's performance overlay to monitor the launch. GPU usage requires a compatible driver and MangoHud.

### Known issue with frame cap precision

On the tested Android 13 image, Waydroid takes the Wayland refresh rate at startup and exposes a single Android display mode. The plugin reads that mode's refresh period. Android's frame override schedules app frames at whole multiples of that period. Most caps use the fastest compatible cadence at or below the requested value, with a small rounding allowance. A cap one FPS below the rounded native rate uses the native cadence to avoid halving it.

| Steam cap | Android cadence measured on the Nova's 120 Hz mode |
| --- | --- |
| 17 FPS | About 17.15 FPS |
| 27 FPS | About 24 FPS |
| 100 FPS | About 60 FPS |
| 119 FPS | About 120 FPS |

Live mode switching is the remaining Waydroid work. Its display driver needs to update the virtual VSync period and notify Android of the mode change. A runtime Wayland output update alone leaves the current driver on its startup period. [Waydroid display driver](https://github.com/waydroid/android_hardware_waydroid/blob/lineage-20/hwcomposer/hwcomposer.cpp#L730-L742) · [Android display mode switching](https://source.android.com/docs/core/graphics/multiple-refresh-rate)

A future integration should let the Steam slider change actual Android rendering while the app and container stay running, with no extra composition or host configuration changes. Validate app buffer production and presentation separately at values such as 27 and 100 FPS, and on devices with different refresh modes.

## Manage Waydroid

Use **Start**, **Restart**, or **Stop** under **Danger Zone** to manage the container service. Use **Remove image and data** to delete the Waydroid installation, Android apps and data, and the associated Steam shortcuts.
