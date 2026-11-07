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

Close the running Android shortcut before opening another. Waydroid uses one Android session at a time.

- Set the resolution in Steam's shortcut properties before launching. Android receives the selected display size when Steam exposes it. An in-game resolution setting still controls how the game renders.
- Adjust the frame cap in Steam's Quick Access performance settings. The plugin synchronizes supported caps to the foreground app on Android 13. Games can run below the selected cap.
- Use Steam Input and direct touch where supported by your Game Mode session. On some Gamescope builds, mouse mode can deliver pointer input with no visible cursor.
- Use Steam's performance overlay to monitor the launch. GPU usage requires a compatible driver and MangoHud.

## Manage Waydroid

Use **Start**, **Restart**, or **Stop** under **Danger Zone** to manage the container service. Use **Remove image and data** to delete the Waydroid installation, Android apps and data, and the associated Steam shortcuts.
