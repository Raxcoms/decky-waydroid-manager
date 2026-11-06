import { callable, definePlugin, FileSelectionType, openFilePicker, toaster, useQuickAccessVisible } from "@decky/api";
import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  Field,
  Focusable,
  Menu,
  MenuItem,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  gamepadDialogClasses,
  showContextMenu,
  showModal,
  staticClasses,
  type MenuProps,
} from "@decky/ui";
import { useCallback, useEffect, useState, type ReactElement } from "react";
import { t } from "./i18n";
import { watchRuntime } from "./runtime";
import { requestArtworkUpdate, watchShortcutArtwork } from "./artwork";
import { operationError } from "./errors";
import { liveShortcutIds, waitForShortcut } from "./library";
import { PackageOperationModal } from "./PackageOperationModal";
import { AppListState } from "./panelState";

type Status = {
  initialized: boolean;
  serviceRunning: boolean;
  gamescopeInstalled: boolean;
  autoAddApps: boolean;
  waydroidShortcutId?: number;
};

type AndroidApp = { name: string; package: string; icon: string; iconPath: string; shortcutId?: number; removable: boolean };
type Shortcut = { name: string; exe: string; startDir: string; launchOptions: string; icon: string; key: string };

function AndroidRobotIcon() {
  return (
    <svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-label={t("androidRobot")}>
      <path d="M6 14a6 6 0 0 1 12 0Z" />
      <path d="m8.5 8-1.4-2M15.5 8l1.4-2" />
      <circle cx="9.5" cy="11" r=".8" fill="currentColor" stroke="none" />
      <circle cx="14.5" cy="11" r=".8" fill="currentColor" stroke="none" />
    </svg>
  );
}

const getStatus = callable<[], Status>("get_status");
const listApps = callable<[], AndroidApp[]>("list_apps");
const installGapps = callable<[], void>("install_gapps");
const startService = callable<[], void>("start_service");
const stopService = callable<[], void>("stop_service");
const restartService = callable<[], void>("restart_service");
const uninstallApp = callable<[string], number | null>("uninstall_app");
const getWaydroidShortcut = callable<[], Shortcut>("get_waydroid_shortcut");
const getAppShortcut = callable<[string], Shortcut>("get_app_shortcut");
const saveShortcutRecord = callable<[string, number], void>("record_shortcut");
const removeShortcutRecord = callable<[string], void>("remove_shortcut_record");
const setAutoAddApps = callable<[boolean], void>("set_auto_add_apps");
const pendingAutoShortcuts = callable<[number[] | null], Shortcut[]>("pending_auto_shortcuts");
const removeWaydroid = callable<[], void>("remove_waydroid");
const installPackage = callable<[string], void>("install_package");

const autoAddAttempted = new Set<string>();
const autoAddFailures = new Set<string>();
const libraryListeners = new Set<() => void>();
let cachedStatus: Status | null = null;
let cachedApps: AndroidApp[] = [];
const appListState = new AppListState();

async function recordShortcut(key: string, appId: number) {
  await saveShortcutRecord(key, appId);
  requestArtworkUpdate();
}

function toast(title: string, body: string) {
  toaster.toast({ title, body });
}

function reportError(error: unknown, setMessage?: (message: string | null) => void) {
  let message = operationError(error) || t("operationFailed");
  const messages: Record<string, Parameters<typeof t>[0]> = {
    WAYDROID_NOT_RUNNING: "androidMustBeRunning", INVALID_PACKAGE_FILE: "invalidPackageFile",
    INVALID_PACKAGE_ARCHIVE: "invalidPackageArchive", INVALID_APK_MANIFEST: "invalidApkManifest",
    XAPK_NO_APKS: "xapkNoApks", XAPK_INVALID_NAMES: "xapkInvalidNames",
    WAYDROID_NOT_INSTALLED: "installWaydroidFirst", PACKAGE_OPERATION_FAILED: "packageOperationFailed",
    APP_NOT_REMOVABLE: "appNotRemovable",
    WAYDROID_START_FAILED: "androidStartFailed",
    XAPK_TOO_MANY_APKS: "xapkTooManyApks", PACKAGE_NO_SPACE: "packageNoSpace",
  };
  if (messages[message]) message = t(messages[message]);
  setMessage?.(message);
  toast(t("operationFailed"), message);
}

function revealPanelTop(event: Event) {
  let parent = (event.target as HTMLElement | null)?.parentElement;
  while (parent) {
    if (parent.scrollHeight > parent.clientHeight && /auto|scroll/.test(getComputedStyle(parent).overflowY)) {
      const panel = parent;
      // Steam reveals the button alone, leaving the status fields above it clipped.
      requestAnimationFrame(() => panel.scrollTo({ top: 0, behavior: "instant" }));
      break;
    }
    parent = parent.parentElement;
  }
}

function watchAutoShortcuts() {
  let busy = false;
  let disposed = false;
  const sync = async () => {
    if (busy || disposed) return;
    busy = true;
    try {
      for (const shortcut of await pendingAutoShortcuts(liveShortcutIds())) {
        if (disposed || autoAddAttempted.has(shortcut.key)) continue;
        autoAddAttempted.add(shortcut.key);
        try {
          await recordShortcut(shortcut.key, await addToSteam(shortcut));
          toast(shortcut.name, t("addedToSteam"));
          autoAddFailures.delete(shortcut.key);
          libraryListeners.forEach((listener) => listener());
        } catch (error) {
          if (!autoAddFailures.has(shortcut.key)) reportError(error);
          autoAddFailures.add(shortcut.key);
        } finally {
          autoAddAttempted.delete(shortcut.key);
        }
      }
    } catch (error) {
      console.warn("Waydroid automatic shortcuts failed", error);
    } finally {
      busy = false;
    }
  };
  void sync();
  const timer = window.setInterval(() => void sync(), 5000);
  return () => {
    disposed = true;
    window.clearInterval(timer);
  };
}

async function addToSteam(shortcut: Shortcut) {
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

async function configureSteamShortcut(appId: number, shortcut: Shortcut) {
  const apps = window.SteamClient?.Apps;
  if (!apps?.SetShortcutLaunchOptions) {
    throw new Error(t("shortcutApiUnavailable"));
  }
  try {
    await apps.SetShortcutName?.(appId, shortcut.name);
  } catch {
  }
  await apps.SetShortcutLaunchOptions(appId, shortcut.launchOptions);
  if (shortcut.icon) {
    try {
      await apps.SetShortcutIcon?.(appId, shortcut.icon);
    } catch {
    }
  }
}

async function removeFromSteam(appId: number) {
  const apps = window.SteamClient?.Apps;
  if (!apps?.RemoveShortcut) {
    throw new Error(t("shortcutApiUnavailable"));
  }
  await apps.RemoveShortcut(appId);
}

function launchSteamShortcut(appId: number) {
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

function run(action: () => Promise<unknown>, refresh: () => Promise<void>, setMessage: (message: string | null) => void, success?: [string, string]) {
  return async () => {
    try {
      await action();
      await refresh();
      setMessage(null);
      if (success) {
        toast(...success);
      }
    } catch (error) {
      reportError(error, setMessage);
    }
  };
}

function openModal(modal: ReactElement) {
  const release = appListState.retainForOverlay();
  try {
    const result = showModal(modal);
    void result.ClosedPromise.then(release, release);
  } catch (error) {
    release();
    throw error;
  }
}

function confirm(title: string, description: string, onConfirm: () => Promise<void>) {
  openModal(
    <ConfirmModal strTitle={title} strDescription={description} onOK={onConfirm} />,
  );
}

function AppMenu({ release, ...props }: MenuProps & { release: () => void }) {
  useEffect(() => release, [release]);
  return <Menu {...props} />;
}

type AppRowProps = {
  app: AndroidApp;
  isLast: boolean;
  setShortcutId: (id?: number) => void;
  onUninstalled: () => void;
  setMessage: (message: string | null) => void;
};

function AppRow({ app, isLast, setShortcutId, onUninstalled, setMessage }: AppRowProps) {
  const add = async () => {
    const shortcut = await getAppShortcut(app.package);
    const appId = await addToSteam(shortcut);
    await recordShortcut(shortcut.key, appId);
    setShortcutId(appId);
  };
  const remove = async () => {
    if (!app.shortcutId) {
      throw new Error(t("shortcutStateUnavailable"));
    }
    await removeFromSteam(app.shortcutId);
    await removeShortcutRecord(app.package);
    setShortcutId();
  };
  const launch = async () => {
    if (!app.shortcutId) {
      throw new Error(t("shortcutStateUnavailable"));
    }
    const shortcut = await getAppShortcut(app.package);
    await configureSteamShortcut(app.shortcutId, shortcut);
    launchSteamShortcut(app.shortcutId);
  };
  const openMenu = () => {
    const release = appListState.retainForOverlay();
    try {
      showContextMenu(
        <AppMenu label={app.name} release={release}>
          {app.shortcutId && <MenuItem onSelected={run(launch, async () => {}, setMessage, [app.name, t("launching")])}>{t("launch")}</MenuItem>}
          {app.shortcutId ? (
            <MenuItem onSelected={run(remove, async () => {}, setMessage, [app.name, t("removedFromSteam")])}>{t("removeFromSteam")}</MenuItem>
          ) : (
            <MenuItem onSelected={run(add, async () => {}, setMessage, [app.name, t("addedToSteam")])}>{t("addToSteam")}</MenuItem>
          )}
          {app.removable && (
            <MenuItem onSelected={() => openModal(
              <PackageOperationModal name={app.name} operation="uninstall" target={app.package} onError={(error) => reportError(error, setMessage)} perform={async () => {
                const shortcutId = (await uninstallApp(app.package)) ?? app.shortcutId;
                if (shortcutId) await removeFromSteam(shortcutId);
                onUninstalled();
                setMessage(null);
                toast(app.name, t("appUninstalled"));
              }} />,
            )}>{t("uninstall")}</MenuItem>
          )}
        </AppMenu>,
      );
    } catch (error) {
      release();
      reportError(error, setMessage);
    }
  };

  return (
    <PanelSectionRow>
      <ButtonItem layout="below" bottomSeparator={isLast ? "none" : "standard"} onClick={openMenu}>
        <div style={{ display: "flex", alignItems: "center", gap: "14px", width: "100%", minWidth: 0, minHeight: "32px", padding: 0, transform: "translateX(-10px)" }}>
          {app.icon ? (
            <img src={app.icon} alt="" style={{ width: "28px", height: "28px", borderRadius: "6px", objectFit: "cover", flex: "0 0 auto" }} />
          ) : (
            <div style={{ width: "28px", height: "28px", borderRadius: "6px", display: "grid", placeItems: "center", background: "rgba(255, 255, 255, 0.1)", flex: "0 0 auto" }}>
              {app.name.slice(0, 1).toUpperCase()}
            </div>
          )}
          <div style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
            <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: "20px" }}>{app.name}</div>
            <div style={{ opacity: 0.65, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", lineHeight: "16px" }}>{app.package}</div>
          </div>
        </div>
      </ButtonItem>
    </PanelSectionRow>
  );
}

function Content() {
  const quickAccessVisible = useQuickAccessVisible();
  const [status, setStatusState] = useState<Status | null>(cachedStatus);
  const [apps, setAppsState] = useState<AndroidApp[]>(cachedApps);
  const [message, setMessage] = useState<string | null>(null);
  const [visibleApps, setVisibleAppsState] = useState(appListState.visible);
  const setVisibleApps = (next: number | ((current: number) => number)) => {
    setVisibleAppsState((current) => {
      const value = typeof next === "function" ? next(current) : next;
      appListState.visible = value;
      return value;
    });
  };

  useEffect(() => () => appListState.leave(), []);
  useEffect(() => {
    if (!quickAccessVisible) {
      appListState.leave();
      setVisibleAppsState(appListState.visible);
    }
  }, [quickAccessVisible]);
  const setStatus = (next: Status | null | ((current: Status | null) => Status | null)) => {
    setStatusState((current) => {
      const value = typeof next === "function" ? next(current) : next;
      cachedStatus = value;
      return value;
    });
  };
  const setApps = (next: AndroidApp[] | ((current: AndroidApp[]) => AndroidApp[])) => {
    setAppsState((current) => {
      const value = typeof next === "function" ? next(current) : next;
      cachedApps = value;
      return value;
    });
  };

  const refresh = useCallback(async () => {
    const nextStatus = await getStatus();
    setStatus(nextStatus);
    setApps(nextStatus.initialized ? await listApps() : []);
  }, []);

  useEffect(() => {
    refresh().catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
  }, [refresh]);

  useEffect(() => {
    setVisibleApps((current) => Math.min(Math.max(current, 10), apps.length));
  }, [apps.length]);

  useEffect(() => {
    const sync = () => void refresh().catch((error) => setMessage(String(error)));
    libraryListeners.add(sync);
    const timer = window.setInterval(sync, 15000);
    return () => {
      libraryListeners.delete(sync);
      window.clearInterval(timer);
    };
  }, [refresh]);

  const sortedApps = [...apps].sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: "base" }));
  const shownApps = sortedApps.slice(0, visibleApps);
  const hasMoreApps = visibleApps < sortedApps.length;
  const addWaydroid = async () => {
    const shortcut = await getWaydroidShortcut();
    const appId = await addToSteam(shortcut);
    await recordShortcut(shortcut.key, appId);
    setStatus((current) => current ? { ...current, waydroidShortcutId: appId } : current);
  };
  const removeWaydroidShortcut = async () => {
    if (!status?.waydroidShortcutId) {
      throw new Error(t("shortcutStateUnavailable"));
    }
    await removeFromSteam(status.waydroidShortcutId);
    await removeShortcutRecord("waydroid");
    setStatus((current) => current ? { ...current, waydroidShortcutId: undefined } : current);
  };
  const launchFullWaydroid = async () => {
    if (!status?.waydroidShortcutId) {
      throw new Error(t("shortcutStateUnavailable"));
    }
    const shortcut = await getWaydroidShortcut();
    await configureSteamShortcut(status.waydroidShortcutId, shortcut);
    launchSteamShortcut(status.waydroidShortcutId);
  };

  return (
    <div>
      <Focusable flow-children="column" onGamepadFocus={revealPanelTop}>
      <PanelSection title={t("waydroidStatus")}>
        <PanelSectionRow>
          <Field label={status?.initialized ? t("installed") : t("notInstalled")} />
        </PanelSectionRow>
        {status && !status.gamescopeInstalled && (
          <PanelSectionRow>
            <Field label={t("gamescopeUnavailable")} description={t("gamescopeUnavailableDescription")} />
          </PanelSectionRow>
        )}
        {!status?.initialized && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              bottomSeparator="none"
              onClick={() => confirm(t("installGapps"), t("installGappsDescription"), run(installGapps, refresh, setMessage, [t("waydroid"), t("gappsInstalled")]))}
            >
              {t("installWaydroid")}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {status?.initialized && (
          <>
            {status.waydroidShortcutId && (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={run(launchFullWaydroid, async () => {}, setMessage, [t("waydroid"), t("launching")])}>{t("launchWaydroid")}</ButtonItem>
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                bottomSeparator="none"
                onClick={status.waydroidShortcutId ? run(removeWaydroidShortcut, async () => {}, setMessage, [t("waydroid"), t("removedFromSteam")]) : run(addWaydroid, async () => {}, setMessage, [t("waydroid"), t("addedToSteam")])}
              >
                {status.waydroidShortcutId ? t("removeWaydroidShortcut") : t("addWaydroid")}
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>
      </Focusable>

      {status?.initialized && (
        <PanelSection title={t("androidApps", { count: apps.length })}>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              bottomSeparator="none"
              onClick={() => {
                const release = appListState.retainForOverlay();
                openFilePicker(FileSelectionType.FILE, "/var/home", true, true)
                  .then(async (result) => {
                    release();
                    const path = result.realpath || result.path;
                    if (!path) return;
                    openModal(<PackageOperationModal
                      name={path.split("/").pop() || path}
                      operation="install" target={path} autoStart
                      onError={(error) => reportError(error, setMessage)}
                      perform={async () => {
                        await installPackage(path);
                        setApps(await listApps());
                        setMessage(null);
                        toast(t("waydroid"), t("packageInstalled"));
                      }}
                    />);
                  })
                  .catch((error) => { release(); if (error !== "User canceled") reportError(error, setMessage); });
              }}
            >
              {t("installPackage")}
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <Field description={t("installPackageDescription")} />
          </PanelSectionRow>
          <PanelSectionRow>
            <ToggleField
              label={t("autoAddApps")}
              description={t("autoAddAppsDescription")}
              checked={status.autoAddApps}
              onChange={(enabled) => run(() => setAutoAddApps(enabled), refresh, setMessage)()}
            />
          </PanelSectionRow>
          {shownApps.map((app, index) => (
            <AppRow
              key={app.package}
              app={app}
              isLast={!hasMoreApps && index === shownApps.length - 1}
              setShortcutId={(id) => setApps((current) => current.map((item) => item.package === app.package ? { ...item, shortcutId: id } : item))}
              onUninstalled={() => setApps((current) => current.filter((item) => item.package !== app.package))}
              setMessage={setMessage}
            />
          ))}
          {!apps.length && <PanelSectionRow><Field description={t("noApps")} bottomSeparator="none" /></PanelSectionRow>}
          {hasMoreApps && (
            <PanelSectionRow>
              <ButtonItem layout="below" bottomSeparator="none" onClick={() => setVisibleApps((count) => Math.min(count + 10, sortedApps.length))}>
                {t("showMore", { count: Math.min(10, sortedApps.length - visibleApps) })}
              </ButtonItem>
            </PanelSectionRow>
          )}
        </PanelSection>
      )}

      {status?.initialized && (
        <PanelSection title={t("dangerZone")}>
          <PanelSectionRow>
            <Field label={t("service", { state: status.serviceRunning ? t("running") : t("stopped") })} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Focusable style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              <DialogButton style={{ flex: "1 1 max-content", maxWidth: "100%" }} onClick={run(startService, refresh, setMessage)}>{t("start")}</DialogButton>
              <DialogButton style={{ flex: "1 1 max-content", maxWidth: "100%" }} onClick={run(restartService, refresh, setMessage)}>{t("restart")}</DialogButton>
              <DialogButton style={{ flex: "1 1 max-content", maxWidth: "100%" }} onClick={run(stopService, refresh, setMessage)}>{t("stop")}</DialogButton>
            </Focusable>
          </PanelSectionRow>
          <PanelSectionRow>
            <div role="separator" className={gamepadDialogClasses.StandaloneFieldSeparator} style={{ marginTop: "12px", marginBottom: "12px" }} />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              bottomSeparator="none"
              onClick={() => confirm(t("removeWaydroid"), t("removeWaydroidDescription"), run(removeWaydroid, refresh, setMessage, [t("waydroid"), t("imageRemoved")]))}
            >
              {t("removeWaydroidButton")}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}

      {message && <div className={staticClasses.PanelSectionRow} style={{ padding: "8px 16px", opacity: 0.8 }}>{message}</div>}
    </div>
  );
}

export default definePlugin(() => {
  const stopRuntime = watchRuntime();
  const stopAutoShortcuts = watchAutoShortcuts();
  const stopArtwork = watchShortcutArtwork();
  return {
    name: t("pluginName"),
    titleView: <div className={staticClasses.Title}>{t("pluginName")}</div>,
    content: <Content />,
    icon: <AndroidRobotIcon />,
    onDismount: () => {
      stopRuntime();
      stopAutoShortcuts();
      stopArtwork();
    },
  };
});
