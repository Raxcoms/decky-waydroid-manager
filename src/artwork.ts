import { toaster } from "@decky/api";
import { pendingArtwork, getArtwork, recordGeneratedArtwork, type ArtworkRole as Role, type Shortcut } from "./backend";
import { artworkSlots, iconBackground, renderArtwork } from "./artworkCards";
import { currentSteamAccount, liveShortcutIds } from "./library";
import { t } from "./i18n";

const artworkVersion = 6;
const fallbackIcon = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g fill="none" stroke="white" stroke-width="6" stroke-linecap="round"><path d="M15 65a35 35 0 0 1 70 0Z M28 28l-8-12 M72 28l8-12"/><circle cx="35" cy="48" r="2"/><circle cx="65" cy="48" r="2"/></g></svg>');
const refreshers = new Set<() => void>();
const addedShortcuts = new Map<number, Map<number, Pick<Shortcut, "key" | "name">>>();

export function requestArtworkUpdate(shortcut: Shortcut, appId: number) {
  const added = addedShortcuts.get(shortcut.accountId) ?? new Map();
  added.set(appId, { key: shortcut.key, name: shortcut.name });
  addedShortcuts.set(shortcut.accountId, added);
  refreshers.forEach((refresh) => refresh());
}

function loadImage(source: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Could not decode the Android launcher icon"));
    image.src = source;
  });
}

async function recordArtwork(accountId: number, appId: number, role: Role, bytes: Uint8Array<ArrayBuffer>) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  await recordGeneratedArtwork(accountId, appId, role, Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join(""), artworkVersion);
}

function missingFromLibrary(appId: number, live = liveShortcutIds()): boolean {
  return live !== null && !live.includes(appId) && !window.appStore?.GetAppOverviewByAppID?.(appId);
}

export function watchShortcutArtwork() {
  let busy = false;
  let disposed = false;
  let refreshPending = false;
  const refresh = () => {
    if (busy) refreshPending = true;
    else void sync();
  };
  const sync = async () => {
    const apps = window.SteamClient?.Apps as unknown as {
      SetCustomArtworkForApp?: (id: number, data: string, extension: string, type: number) => Promise<void>;
      ClearCustomArtworkForApp?: (id: number, type: number) => Promise<void>;
    };
    const accountId = currentSteamAccount();
    if (!accountId || busy || disposed || !apps?.SetCustomArtworkForApp) return;
    busy = true;
    try {
      const updates = new Map((await pendingArtwork(accountId)).map(({ key, appId }) => [appId, key]));
      if (disposed || currentSteamAccount() !== accountId) return;
      const added = addedShortcuts.get(accountId);
      const live = liveShortcutIds();
      for (const [appId, shortcut] of added ?? []) {
        if (missingFromLibrary(appId, live)) added?.delete(appId);
        else updates.set(appId, shortcut.key);
      }
      for (const [appId, key] of updates) {
        if (disposed || currentSteamAccount() !== accountId) break;
        try {
          const artwork = await getArtwork(accountId, key, appId);
          if (disposed || currentSteamAccount() !== accountId) break;
          if (artwork.clearLogo) await apps.ClearCustomArtworkForApp?.(appId, 2);
          if (artwork.roles.length) {
            const icon = await loadImage(artwork.icon || fallbackIcon).catch(() => loadImage(fallbackIcon));
            const background = iconBackground(icon);
            for (const role of artwork.roles) {
              if (disposed || currentSteamAccount() !== accountId) break;
              const png = renderArtwork(role, artwork.name, icon, background);
              await apps.SetCustomArtworkForApp(appId, png, "png", artworkSlots[role][0]);
              await recordArtwork(accountId, appId, role, Uint8Array.from(atob(png), (character) => character.charCodeAt(0)));
            }
          }
          if (!added?.has(appId) || disposed || currentSteamAccount() !== accountId) continue;
          const ready = artwork.roles.length ? (await getArtwork(accountId, key, appId)).ready : artwork.ready;
          const shortcut = added.get(appId);
          if (shortcut && ready && !disposed && currentSteamAccount() === accountId && !missingFromLibrary(appId)) {
            added.delete(appId);
            toaster.toast({ title: shortcut.name, body: t("addedToSteam") });
          }
        } catch (error) {
          console.warn("Waydroid shortcut artwork failed", key, error);
        }
      }
    } catch (error) {
      console.warn("Waydroid shortcut artwork failed", error);
    } finally {
      busy = false;
      if (refreshPending && !disposed) {
        refreshPending = false;
        refresh();
      }
    }
  };
  refreshers.add(refresh);
  refresh();
  const timer = window.setInterval(refresh, 15000);
  return () => { disposed = true; refreshers.delete(refresh); window.clearInterval(timer); };
}
