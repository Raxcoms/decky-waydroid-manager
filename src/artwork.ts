import { callable } from "@decky/api";

type Role = "portrait" | "hero" | "logo" | "landscape";
type Artwork = { roles: Role[]; ready: boolean; name: string; icon: string; images: { name: string; data: string }[] };
type ImageAsset = { name: string; image: HTMLImageElement };
const pendingArtwork = callable<[], { key: string; appId: number }[]>("pending_shortcut_artwork");
const getArtwork = callable<[string, number], Artwork>("get_shortcut_artwork");
const refreshers = new Set<() => void>();

export function requestArtworkUpdate() {
  refreshers.forEach((refresh) => refresh());
}
const slots: Record<Role, [number, number, number]> = {
  portrait: [0, 600, 900], hero: [1, 1920, 620], logo: [2, 960, 320], landscape: [3, 920, 430],
};

function loadImage(source: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Could not decode bundled artwork"));
    image.src = source;
  });
}

function fit(context: CanvasRenderingContext2D, image: HTMLImageElement, x: number, y: number, width: number, height: number, cover = false) {
  const ratio = (cover ? Math.max : Math.min)(width / image.width, height / image.height);
  const w = image.width * ratio;
  const h = image.height * ratio;
  context.drawImage(image, x + (width - w) / 2, y + (height - h) / 2, w, h);
}

function selectImage(images: ImageAsset[], role: Role) {
  return images.filter(({ name, image }) => role === "logo"
    ? /logo/i.test(name) && image.width >= 96 && image.height >= 24
    : !/logo|icon|ic_launcher/i.test(name) && image.width >= 512 && image.height >= 256)
    .sort((a, b) => {
      const score = ({ name, image }: ImageAsset) => {
        const target = role === "portrait" ? 2 / 3 : role === "hero" ? 3.1 : role === "logo" ? 3 : 2.14;
        const match = role === "portrait" ? /cover|portrait/i : role === "hero" ? /background|splash|hero/i : /banner|logo/i;
        return (match.test(name) ? 3 : 0) - Math.abs(Math.log(image.width / image.height / target));
      };
      return score(b) - score(a);
    })[0]?.image;
}

function render(role: Role, name: string, icon: HTMLImageElement | undefined, images: ImageAsset[]) {
  const [, width, height] = slots[role];
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Artwork canvas is unavailable");
  const image = selectImage(images, role);
  if (role === "logo") {
    if (image) fit(context, image, 24, 24, width - 48, height - 48);
    else {
      context.fillStyle = "white";
      context.font = "bold 74px sans-serif";
      context.textAlign = "center";
      context.fillText(name, width / 2, height / 2 + 28, width - 64);
    }
  } else {
    context.fillStyle = "#172735";
    context.fillRect(0, 0, width, height);
    if (image) fit(context, image, 0, 0, width, height, true);
    const gradient = context.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, "rgba(9,18,28,0.15)");
    gradient.addColorStop(1, "rgba(9,18,28,0.95)");
    context.fillStyle = gradient;
    context.fillRect(0, 0, width, height);
    if (icon) {
      const size = role === "portrait" ? 220 : height * 0.4;
      fit(context, icon, (width - size) / 2, role === "portrait" ? height * 0.3 : height * 0.14, size, size);
    }
    context.fillStyle = "white";
    context.font = `bold ${role === "portrait" ? 42 : 48}px sans-serif`;
    context.textAlign = "center";
    context.fillText(name, width / 2, height * 0.82, width - 64);
  }
  return canvas.toDataURL("image/png").split(",")[1];
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
          if (!artwork.ready) continue;
          const decoded = await Promise.all(artwork.images.map(async ({ name, data }) => {
            try { return { name, image: await loadImage(data) }; } catch { return null; }
          }));
          const images = decoded.filter((image): image is ImageAsset => image !== null);
          const fallbackIcon = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g fill="none" stroke="white" stroke-width="6" stroke-linecap="round"><path d="M15 65a35 35 0 0 1 70 0Z M28 28l-8-12 M72 28l8-12"/><circle cx="35" cy="48" r="2"/><circle cx="65" cy="48" r="2"/></g></svg>');
          const bundledIcon = images.filter(({ name, image }) => /icon|ic_launcher/i.test(name.split("/").at(-1) || "")
            && image.width >= 128 && Math.abs(image.width / image.height - 1) < 0.2)
            .sort((a, b) => b.image.width * b.image.height - a.image.width * a.image.height)[0]?.image;
          const icon = bundledIcon || await loadImage(artwork.icon || fallbackIcon).catch(() => undefined);
          for (const role of artwork.roles) {
            if (disposed) break;
            await apps.SetCustomArtworkForApp(appId, render(role, artwork.name, icon, images), "png", slots[role][0]);
          }
          const details = (window as unknown as { appDetailsStore?: {
            GetCustomLogoPosition?: (app: unknown) => unknown;
            SaveCustomLogoPosition?: (app: unknown, position: unknown) => Promise<void>;
          } }).appDetailsStore;
          const overview = window.appStore?.GetAppOverviewByAppID(appId);
          // Steam shortcuts need a logo position before their logo is displayed.
          if (artwork.roles.includes("logo") && overview && !details?.GetCustomLogoPosition?.(overview)) {
            await details?.SaveCustomLogoPosition?.(overview, { pinnedPosition: "BottomLeft", nWidthPct: 50, nHeightPct: 50 });
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
