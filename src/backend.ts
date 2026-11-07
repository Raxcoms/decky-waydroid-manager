import { callable } from "@decky/api";

export type Status = {
  initialized: boolean;
  serviceRunning: boolean;
  sessionAvailable: boolean;
  autoAddApps: boolean;
  userHome: string;
  waydroidShortcutId?: number;
};

export type AndroidApp = { name: string; package: string; icon: string; iconPath: string; shortcutId?: number; removable: boolean };
export type Shortcut = { name: string; exe: string; startDir: string; launchOptions: string; icon: string; key: string };
export type ArtworkRole = "portrait" | "hero" | "logo" | "landscape";
export type ImageProgress = { stage: "preparing" | "downloading" | "finalizing"; percent: number | null };
export type Artwork = { roles: ArtworkRole[]; ready: boolean; name: string; icon: string; images: { name: string; data: string }[] };

export const getStatus = callable<[], Status>("get_status");
export const listApps = callable<[], AndroidApp[]>("list_apps");
export const installGapps = callable<[], void>("install_gapps");
export const getImageProgress = callable<[], ImageProgress | null>("get_image_progress");
export const startService = callable<[], void>("start_service");
export const stopService = callable<[], void>("stop_service");
export const restartService = callable<[], void>("restart_service");
export const uninstallApp = callable<[string], number | null>("uninstall_app");
export const getWaydroidShortcut = callable<[], Shortcut>("get_waydroid_shortcut");
export const getAppShortcut = callable<[string], Shortcut>("get_app_shortcut");
export const saveShortcutRecord = callable<[string, number], void>("record_shortcut");
export const removeShortcutRecord = callable<[string], void>("remove_shortcut_record");
export const setAutoAddApps = callable<[boolean], void>("set_auto_add_apps");
export const pendingAutoShortcuts = callable<[number[] | null], Shortcut[]>("pending_auto_shortcuts");
export const legacyShortcuts = callable<[], { appId: number; launchOptions?: string; name?: string }[]>("legacy_shortcuts");
export const removeWaydroidImage = callable<[], number[]>("remove_waydroid");
export const installPackage = callable<[string], boolean>("install_package");
export const confirmPackageInstall = callable<[string, string, boolean], void>("confirm_package_install");

export const getPackageProgress = callable<[string, string], { stage: string; confirmation?: string }>("get_package_progress");
export const syncRuntime = callable<[number | null], void>("sync_runtime");
export const pendingArtwork = callable<[], { key: string; appId: number }[]>("pending_shortcut_artwork");
export const getArtwork = callable<[string, number], Artwork>("get_shortcut_artwork");
export const recordGeneratedArtwork = callable<[number, ArtworkRole | "logoPosition", string], void>("record_shortcut_artwork");
