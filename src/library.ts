type AppOverview = { appid: number };
type AppStore = { allApps?: AppOverview[]; GetAppOverviewByAppID?: (id: number) => unknown };

function steamApps(): AppStore | undefined {
  return (globalThis as unknown as { appStore?: AppStore }).appStore;
}

export function currentSteamAccount(): number | null {
  const app = globalThis.App;
  if (app?.BHasCurrentUser?.() === false) return null;
  const steamId = app?.GetCurrentUser?.()?.strSteamID;
  if (typeof steamId !== "string" || !/^\d{17,20}$/.test(steamId)) return null;
  return Number(BigInt.asUintN(32, BigInt(steamId))) || null;
}

export function liveShortcutIds(): number[] | null {
  const apps = steamApps()?.allApps;
  if (!apps?.length) return null;
  return apps.map((app) => app.appid >>> 0).filter((id) => id >= 0x80000000);
}

async function waitForLibrary(check: () => boolean): Promise<boolean> {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    if (check()) return true;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return false;
}

export async function waitForShortcut(appId: number): Promise<boolean> {
  const store = steamApps();
  return !store?.GetAppOverviewByAppID || waitForLibrary(() => !!store.GetAppOverviewByAppID?.(appId >>> 0));
}

export function waitForShortcutRemoval(appId: number, accountId: number): Promise<boolean> {
  return waitForLibrary(() => currentSteamAccount() === accountId && liveShortcutIds()?.includes(appId) === false);
}
