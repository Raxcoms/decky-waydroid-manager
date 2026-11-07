import { pendingArtwork, getArtwork, recordGeneratedArtwork, type ArtworkRole as Role } from "./backend";
import { artworkSlots, iconHue, renderArtwork } from "./artworkCards";

const artworkVersion = 1;
const fallbackIcon = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g fill="none" stroke="white" stroke-width="6" stroke-linecap="round"><path d="M15 65a35 35 0 0 1 70 0Z M28 28l-8-12 M72 28l8-12"/><circle cx="35" cy="48" r="2"/><circle cx="65" cy="48" r="2"/></g></svg>');
const refreshers = new Set<() => void>();

export function requestArtworkUpdate() {
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

async function recordArtwork(appId: number, role: Role | "logoPosition", bytes: Uint8Array<ArrayBuffer>) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  await recordGeneratedArtwork(appId, role, Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join(""), artworkVersion);
}

export function watchShortcutArtwork() {
  let busy = false;
  let disposed = false;
  const sync = async () => {
    const apps = window.SteamClient?.Apps as unknown as {
      SetCustomArtworkForApp?: (id: number, data: string, extension: string, type: number) => Promise<void>;
    };
    if (busy || disposed || !apps?.SetCustomArtworkForApp) return;
    busy = true;
    try {
      for (const { key, appId } of await pendingArtwork()) {
        if (disposed) break;
        try {
          const artwork = await getArtwork(key, appId);
          if (!artwork.roles.length) continue;
          const icon = await loadImage(artwork.icon || fallbackIcon).catch(() => loadImage(fallbackIcon));
          const hue = iconHue(icon);
          for (const role of artwork.roles) {
            if (disposed) break;
            const png = renderArtwork(role, artwork.name, icon, hue);
            await apps.SetCustomArtworkForApp(appId, png, "png", artworkSlots[role][0]);
            await recordArtwork(appId, role, Uint8Array.from(atob(png), (character) => character.charCodeAt(0)));
          }
          const details = (window as unknown as { appDetailsStore?: {
            GetCustomLogoPosition?: (app: unknown) => unknown;
            SaveCustomLogoPosition?: (app: unknown, position: unknown) => Promise<void>;
          } }).appDetailsStore;
          const overview = window.appStore?.GetAppOverviewByAppID(appId);
          // Steam shortcuts need a logo position before their logo is displayed.
          if (artwork.roles.includes("logo") && overview && details?.SaveCustomLogoPosition && !details.GetCustomLogoPosition?.(overview)) {
            const logoPosition = { pinnedPosition: "BottomLeft", nWidthPct: 50, nHeightPct: 50 };
            await details.SaveCustomLogoPosition(overview, logoPosition);
            await recordArtwork(appId, "logoPosition", new TextEncoder().encode(JSON.stringify({ nVersion: 1, logoPosition })));
          }
        } catch (error) {
          console.warn("Waydroid shortcut artwork failed", key, error);
        }
      }
    } catch (error) {
      console.warn("Waydroid shortcut artwork failed", error);
    } finally {
      busy = false;
    }
  };
  const refresh = () => void sync();
  refreshers.add(refresh);
  refresh();
  const timer = window.setInterval(refresh, 15000);
  return () => { disposed = true; refreshers.delete(refresh); window.clearInterval(timer); };
}
