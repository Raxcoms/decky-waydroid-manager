import { getStatus, listApps, installGapps, startService, stopService, restartService, uninstallApp, getWaydroidShortcut, getAppShortcut, saveShortcutRecord, removeShortcutRecord, setAutoAddApps, pendingAutoShortcuts, legacyShortcuts, removeWaydroidImage, installPackage, type Status, type AndroidApp } from "./backend";
import { addToSteam, removeFromSteam, launchSteamShortcut, updateSteamShortcut } from "./steam";
import { definePlugin, FileSelectionType, openFilePicker, toaster, useQuickAccessVisible } from "@decky/api";
import {
  ButtonItem,
  Field,
  Focusable,
  Menu,
  MenuItem,
  PanelSection,
  PanelSectionRow,
  ToggleField,
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
import { liveShortcutIds } from "./library";
import { PackageOperationModal } from "./PackageOperationModal";
import { ImageOperationModal } from "./ImageOperationModal";
import { AppListState } from "./panelState";

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
    ANDROID_VERIFICATION_UNAVAILABLE: "androidVerificationUnavailable", ANDROID_VERIFICATION_AMBIGUOUS: "androidVerificationUnavailable",
    PACKAGE_INSTALL_TIMEOUT: "packageInstallTimeout",
    INVALID_PACKAGE_ARCHIVE: "invalidPackageArchive", INVALID_APK_MANIFEST: "invalidApkManifest",
    XAPK_NO_APKS: "xapkNoApks", XAPK_INVALID_NAMES: "xapkInvalidNames",
    WAYDROID_NOT_INSTALLED: "installWaydroidFirst", PACKAGE_OPERATION_FAILED: "packageOperationFailed",
    APP_NOT_REMOVABLE: "appNotRemovable",
    WAYDROID_START_FAILED: "androidStartFailed",
    WAYDROID_CLEANUP_FAILED: "packageCleanupFailed",
    XAPK_TOO_MANY_APKS: "xapkTooManyApks", PACKAGE_NO_SPACE: "packageNoSpace",
    IMAGE_APP_EXPORT_TIMEOUT: "imageAppExportTimeout",
  };
  if (messages[message]) message = t(messages[message]);
  setMessage?.(message);
  toast(t("operationFailed"), message);
  return message;
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
  const migrated = new Set<number>();
  const sync = async () => {
    if (busy || disposed) return;
    busy = true;
    try {
      const live = liveShortcutIds();
      for (const shortcut of await legacyShortcuts()) {
        if (disposed || !live?.includes(shortcut.appId) || migrated.has(shortcut.appId)) continue;
        await updateSteamShortcut(shortcut.appId, shortcut);
        migrated.add(shortcut.appId);
      }
      for (const shortcut of await pendingAutoShortcuts(live)) {
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

  const icon = app.icon
    ? <img src={app.icon} alt="" width={24} height={24} />
    : <AndroidRobotIcon />;
  return (
    <PanelSectionRow>
      <Field label={app.name} description={app.package} icon={icon} padding="standard"
        bottomSeparator={isLast ? "none" : "standard"} focusable highlightOnFocus onActivate={openMenu} />
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
  const setupPending = status?.initialized && status.hasAppEntries === false;
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
  const removeWaydroid = async (showLibraryProgress: () => void) => {
    const shortcuts = await removeWaydroidImage();
    if (shortcuts.length) showLibraryProgress();
    for (const id of shortcuts) await removeFromSteam(id);
    await refresh();
    setMessage(null);
    toast(t("waydroid"), t("imageRemoved"));
  };
  const initializeWaydroid = async () => {
    const languageSet = await installGapps(navigator.language);
    await refresh();
    setMessage(null);
    toast(t("waydroid"), t("gappsInstalled"));
    if (!languageSet) toast(t("waydroid"), t("imageLanguageUnavailable"));
  };
  const launchFullWaydroid = async () => {
    if (!status?.waydroidShortcutId) {
      throw new Error(t("shortcutStateUnavailable"));
    }
    launchSteamShortcut(status.waydroidShortcutId);
  };

  return (
    <div>
      <Focusable flow-children="column" onGamepadFocus={revealPanelTop}>
      <PanelSection title={t("waydroidStatus")}>
        <PanelSectionRow>
          <Field label={status?.initialized ? t("installed") : t("notInstalled")} />
        </PanelSectionRow>
        {status && !status.sessionAvailable && (
          <PanelSectionRow>
            <Field label={t("gamescopeUnavailable")} description={t("gamescopeUnavailableDescription")} />
          </PanelSectionRow>
        )}
        {(!status?.initialized || setupPending) && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              bottomSeparator="none"
              onClick={() => openModal(<ImageOperationModal
                operation={setupPending ? "setup" : "install"}
                perform={initializeWaydroid}
                onError={(error) => reportError(error, setMessage)}
              />)}
            >
              {t(setupPending ? "finishImageSetup" : "installWaydroid")}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {status?.initialized && !setupPending && (
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

      {status?.initialized && !setupPending && (
        <PanelSection title={t("androidApps", { count: apps.length })}>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              bottomSeparator="none"
              onClick={() => {
                const release = appListState.retainForOverlay();
                openFilePicker(FileSelectionType.FILE, status.userHome, true, true)
                  .then(async (result) => {
                    release();
                    const path = result.realpath || result.path;
                    if (!path) return;
                    openModal(<PackageOperationModal
                      name={path.split("/").pop() || path}
                      operation="install" target={path} autoStart
                      onError={(error) => reportError(error, setMessage)}
                      perform={async () => {
                        if (!await installPackage(path)) return;
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
            <ButtonItem layout="below" onClick={run(startService, refresh, setMessage)}>{t("start")}</ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={run(restartService, refresh, setMessage)}>{t("restart")}</ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" bottomSeparator="thick" onClick={run(stopService, refresh, setMessage)}>{t("stop")}</ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              bottomSeparator="none"
              onClick={() => openModal(<ImageOperationModal
                operation="remove"
                perform={removeWaydroid}
                onError={(error) => reportError(error, setMessage)}
              />)}
            >
              {t("removeWaydroidButton")}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}

      {message && <PanelSection><PanelSectionRow><Field description={message} bottomSeparator="none" /></PanelSectionRow></PanelSection>}
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
