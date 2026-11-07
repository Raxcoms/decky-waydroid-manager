import { requestArtworkUpdate } from "./artwork";
import { pendingShortcutRemovals, saveShortcutRecord, type Shortcut } from "./backend";
import { t } from "./i18n";
import { currentSteamAccount, liveShortcutIds, waitForShortcut, waitForShortcutRemoval } from "./library";

const pendingAdds = new Map<string, Promise<number>>();
const pendingRemovals = new Map<number, Promise<boolean>>();

export function requireSteamAccount(accountId: number | null | undefined): number {
  if (!accountId || currentSteamAccount() !== accountId) throw new Error(t("shortcutStateUnavailable"));
  return accountId;
}

export function addToSteam(shortcut: Shortcut): Promise<number> {
  const key = `${shortcut.accountId}:${shortcut.key}`;
  const pending = pendingAdds.get(key);
  if (pending) return pending;
  const creation = createSteamShortcut(shortcut).finally(() => pendingAdds.delete(key));
  pendingAdds.set(key, creation);
  return creation;
}

async function createSteamShortcut(shortcut: Shortcut) {
  requireSteamAccount(shortcut.accountId);
  const apps = window.SteamClient?.Apps;
  if (!apps?.AddShortcut) {
    throw new Error(t("shortcutApiUnavailable"));
  }

  const appId = Number(await apps.AddShortcut(shortcut.name, shortcut.exe, shortcut.startDir, shortcut.launchOptions)) >>> 0;
  if (!appId) {
    throw new Error(t("shortcutNotCreated"));
  }
  try {
    if (!await waitForShortcut(appId)) throw new Error(t("shortcutNotCreated"));
    await configureSteamShortcut(appId, shortcut);
    requireSteamAccount(shortcut.accountId);
    await saveShortcutRecord(shortcut.accountId, shortcut.key, appId);
  } catch (error) {
    try {
      if (currentSteamAccount() === shortcut.accountId) await apps.RemoveShortcut?.(appId);
    } catch (rollbackError) {
      console.warn("Waydroid shortcut rollback failed", appId, rollbackError);
    }
    throw error;
  }
  requestArtworkUpdate();
  return appId;
}

async function configureSteamShortcut(appId: number, shortcut: Shortcut) {
  await updateSteamShortcut(appId, shortcut, shortcut.accountId);
  requireSteamAccount(shortcut.accountId);
  const apps = window.SteamClient?.Apps;
  if (shortcut.icon) {
    try {
      await apps?.SetShortcutIcon?.(appId, shortcut.icon);
    } catch {
    }
  }
}

export async function updateSteamShortcut(appId: number, update: { name?: string; startDir?: string; launchOptions?: string }, accountId: number) {
  requireSteamAccount(accountId);
  const apps = window.SteamClient?.Apps;
  if (!apps || (update.name !== undefined && !apps.SetShortcutName)
    || (update.startDir !== undefined && !apps.SetShortcutStartDir)
    || (update.launchOptions !== undefined && !apps.SetShortcutLaunchOptions)) {
    throw new Error(t("shortcutApiUnavailable"));
  }
  if (update.name !== undefined) await apps.SetShortcutName(appId, update.name);
  if (update.startDir !== undefined) {
    requireSteamAccount(accountId);
    await apps.SetShortcutStartDir(appId, update.startDir);
  }
  if (update.launchOptions !== undefined) {
    requireSteamAccount(accountId);
    await apps.SetShortcutLaunchOptions(appId, update.launchOptions);
  }
}

export async function removeFromSteam(appId: number, accountId: number) {
  requireSteamAccount(accountId);
  const apps = window.SteamClient?.Apps;
  if (!apps?.RemoveShortcut) {
    throw new Error(t("shortcutApiUnavailable"));
  }
  await apps.RemoveShortcut(appId);
}

export function retrySteamShortcutRemovals(accountId: number): Promise<boolean> {
  const pending = pendingRemovals.get(accountId);
  if (pending) return pending;
  const cleanup = removeQueuedShortcuts(accountId).finally(() => pendingRemovals.delete(accountId));
  pendingRemovals.set(accountId, cleanup);
  return cleanup;
}

async function removeQueuedShortcuts(accountId: number): Promise<boolean> {
  if (currentSteamAccount() !== accountId) return false;
  const { ids, waiting } = await pendingShortcutRemovals(accountId, liveShortcutIds());
  let complete = !waiting;
  for (const appId of ids) {
    if (currentSteamAccount() !== accountId) return false;
    const live = liveShortcutIds();
    if (live === null) return false;
    if (!live.includes(appId)) continue;
    try {
      await removeFromSteam(appId, accountId);
      if (!await waitForShortcutRemoval(appId, accountId)) complete = false;
    } catch (error) {
      console.warn("Waydroid Steam shortcut cleanup will retry", appId, error);
      complete = false;
    }
  }
  return complete;
}

export function launchSteamShortcut(appId: number, accountId: number) {
  requireSteamAccount(accountId);
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

