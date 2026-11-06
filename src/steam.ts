import type { Shortcut } from "./backend";
import { t } from "./i18n";
import { waitForShortcut } from "./library";

export async function addToSteam(shortcut: Shortcut) {
  const apps = window.SteamClient?.Apps;
  if (!apps?.AddShortcut) {
    throw new Error(t("shortcutApiUnavailable"));
  }

  const appId = Number(await apps.AddShortcut(shortcut.name, shortcut.exe, shortcut.startDir, shortcut.launchOptions));
  if (!appId) {
    throw new Error(t("shortcutNotCreated"));
  }
  try {
    await configureSteamShortcut(appId, shortcut);
    if (!await waitForShortcut(appId)) throw new Error(t("shortcutNotCreated"));
  } catch (error) {
    await apps.RemoveShortcut?.(appId);
    throw error;
  }
  return appId;
}

export async function configureSteamShortcut(appId: number, shortcut: Shortcut) {
  const apps = window.SteamClient?.Apps;
  if (!apps?.SetShortcutLaunchOptions) {
    throw new Error(t("shortcutApiUnavailable"));
  }
  await apps.SetShortcutLaunchOptions(appId, shortcut.launchOptions);
  if (shortcut.icon) {
    try {
      await apps.SetShortcutIcon?.(appId, shortcut.icon);
    } catch {
    }
  }
}

export async function removeFromSteam(appId: number) {
  const apps = window.SteamClient?.Apps;
  if (!apps?.RemoveShortcut) {
    throw new Error(t("shortcutApiUnavailable"));
  }
  await apps.RemoveShortcut(appId);
}

export function launchSteamShortcut(appId: number) {
  const gameId = ((BigInt(appId >>> 0) << 32n) | 0x02000000n).toString();
  const apps = window.SteamClient?.Apps;
  if (apps?.RunGame) {
    apps.RunGame(gameId, "", -1, 100);
    return;
  }
  const url = (window.SteamClient as unknown as { URL?: { ExecuteSteamURL?: (url: string) => void } } | undefined)?.URL;
  if (url?.ExecuteSteamURL) {
    url.ExecuteSteamURL(`steam://rungameid/${gameId}`);
    return;
  }
  throw new Error(t("shortcutApiUnavailable"));
}

