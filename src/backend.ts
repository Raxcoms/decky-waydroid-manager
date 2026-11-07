import { callable } from "@decky/api";

export type Status = {
  initialized: boolean;
  hasAppEntries: boolean;
  serviceRunning: boolean;
  sessionAvailable: boolean;
  autoAddApps: boolean;
  accountId: number | null;
  userHome: string;
  waydroidShortcutId?: number;
};

export type AndroidApp = { name: string; package: string; icon: string; iconPath: string; shortcutId?: number; removable: boolean };
export type Shortcut = { accountId: number; name: string; exe: string; startDir: string; launchOptions: string; icon: string; key: string };
export type ArtworkRole = "portrait" | "hero" | "landscape";
export type ImageProgress = { stage: "preparing" | "downloading" | "finalizing" | "starting" | "booting" | "language" | "apps" | "cleaning" | "stopping" | "deleting"; percent: number | null };
export type Artwork = { roles: ArtworkRole[]; clearLogo: boolean; name: string; icon: string };

export const getStatus = callable<[number | null], Status>("get_status");
export const listApps = callable<[number | null], AndroidApp[]>("list_apps");
export const installGapps = callable<[string], boolean>("install_gapps");
export const getImageProgress = callable<[], ImageProgress | null>("get_image_progress");
export const startService = callable<[], void>("start_service");
export const stopService = callable<[], void>("stop_service");
export const restartService = callable<[], void>("restart_service");
export const uninstallApp = callable<[string, number | null], number | null>("uninstall_app");
export const getWaydroidShortcut = callable<[number], Shortcut>("get_waydroid_shortcut");
export const getAppShortcut = callable<[number, string], Shortcut>("get_app_shortcut");
export const saveShortcutRecord = callable<[number, string, number], void>("record_shortcut");
export const removeShortcutRecord = callable<[number, string], void>("remove_shortcut_record");
export const setAutoAddApps = callable<[number, boolean], void>("set_auto_add_apps");
export const pendingAutoShortcuts = callable<[number, number[] | null], Shortcut[]>("pending_auto_shortcuts");
export const pendingShortcutRemovals = callable<[number, number[] | null], { ids: number[]; waiting: boolean }>("pending_shortcut_removals");
export const legacyShortcuts = callable<[number], { appId: number; launchOptions?: string; name?: string }[]>("legacy_shortcuts");
export const removeWaydroidImage = callable<[number | null], number[]>("remove_waydroid");
export const installPackage = callable<[string], boolean>("install_package");
export const confirmPackageInstall = callable<[string, string, boolean], void>("confirm_package_install");

export const getPackageProgress = callable<[string, string], { stage: string; confirmation?: string }>("get_package_progress");
export const syncRuntime = callable<[number | null], void>("sync_runtime");
export const pendingArtwork = callable<[number], { key: string; appId: number }[]>("pending_shortcut_artwork");
export const getArtwork = callable<[number, string, number], Artwork>("get_shortcut_artwork");
export const recordGeneratedArtwork = callable<[number, number, ArtworkRole, string, number], void>("record_shortcut_artwork");
