type AppOverview = { appid: number };
type AppStore = { allApps?: AppOverview[]; GetAppOverviewByAppID?: (id: number) => unknown };

function steamApps(): AppStore | undefined {
  return (globalThis as unknown as { appStore?: AppStore }).appStore;
}

export function liveShortcutIds(): number[] | null {
  const apps = steamApps()?.allApps;
  if (!apps?.length) return null;
  return apps.map((app) => app.appid >>> 0).filter((id) => id >= 0x80000000);
}

export async function waitForShortcut(appId: number): Promise<boolean> {
  const store = steamApps();
  if (!store?.GetAppOverviewByAppID) return true;
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    if (store.GetAppOverviewByAppID(appId >>> 0)) return true;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return false;
}
