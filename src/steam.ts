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
    if (!await waitForShortcut(appId)) throw new Error(t("shortcutNotCreated"));
    await configureSteamShortcut(appId, shortcut);
  } catch (error) {
    await apps.RemoveShortcut?.(appId);
    throw error;
  }
  return appId;
}

async function configureSteamShortcut(appId: number, shortcut: Shortcut) {
  await updateSteamShortcut(appId, shortcut);
  const apps = window.SteamClient?.Apps;
  if (shortcut.icon) {
    try {
      await apps?.SetShortcutIcon?.(appId, shortcut.icon);
    } catch {
    }
  }
}

export async function updateSteamShortcut(appId: number, update: { name?: string; startDir?: string; launchOptions?: string }) {
  const apps = window.SteamClient?.Apps;
  if (!apps || (update.name !== undefined && !apps.SetShortcutName)
    || (update.startDir !== undefined && !apps.SetShortcutStartDir)
    || (update.launchOptions !== undefined && !apps.SetShortcutLaunchOptions)) {
    throw new Error(t("shortcutApiUnavailable"));
  }
  if (update.name !== undefined) await apps.SetShortcutName(appId, update.name);
  if (update.startDir !== undefined) await apps.SetShortcutStartDir(appId, update.startDir);
  if (update.launchOptions !== undefined) await apps.SetShortcutLaunchOptions(appId, update.launchOptions);
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

