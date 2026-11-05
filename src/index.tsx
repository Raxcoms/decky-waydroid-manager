import { callable, definePlugin, toaster } from "@decky/api";
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
  showContextMenu,
  showModal,
  staticClasses,
} from "@decky/ui";
import { useCallback, useEffect, useState } from "react";
import { t } from "./i18n";

type Resolution = { width: number; height: number } | null;
type Status = {
  initialized: boolean;
  serviceRunning: boolean;
  autoStart: boolean;
  gamescopeInstalled: boolean;
  resolution: Resolution;
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
const setAutoStart = callable<[boolean], void>("set_auto_start");
const startService = callable<[], void>("start_service");
const stopService = callable<[], void>("stop_service");
const restartService = callable<[], void>("restart_service");
const uninstallApp = callable<[string], void>("uninstall_app");
const getWaydroidShortcut = callable<[], Shortcut>("get_waydroid_shortcut");
const getAppShortcut = callable<[string], Shortcut>("get_app_shortcut");
const recordShortcut = callable<[string, number], void>("record_shortcut");
const removeShortcutRecord = callable<[string], void>("remove_shortcut_record");
const setAutoAddApps = callable<[boolean], void>("set_auto_add_apps");
const pendingAutoShortcuts = callable<[], Shortcut[]>("pending_auto_shortcuts");
const removeWaydroid = callable<[], void>("remove_waydroid");

const autoAddAttempted = new Set<string>();

function toast(title: string, body: string) {
  toaster.toast({ title, body });
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
  await configureSteamShortcut(appId, shortcut);
  return appId;
}

async function configureSteamShortcut(appId: number, shortcut: Shortcut) {
  const apps = window.SteamClient?.Apps;
  if (!apps?.SetShortcutExe || !apps.SetShortcutStartDir || !apps.SetShortcutLaunchOptions) {
    throw new Error(t("shortcutApiUnavailable"));
  }
  await apps.SetShortcutExe(appId, shortcut.exe);
  await apps.SetShortcutStartDir(appId, shortcut.startDir);
  await apps.SetShortcutLaunchOptions(appId, shortcut.launchOptions);
  await apps.SetShortcutName?.(appId, shortcut.name);
  if (shortcut.icon) await apps.SetShortcutIcon?.(appId, shortcut.icon);
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
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };
}

function confirm(title: string, description: string, onConfirm: () => Promise<void>) {
  showModal(
    <ConfirmModal strTitle={title} strDescription={description} onOK={onConfirm} />,
  );
}

function AppRow({ app, setShortcutId, setMessage }: { app: AndroidApp; setShortcutId: (id?: number) => void; setMessage: (message: string | null) => void }) {
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
    showContextMenu(
      <Menu label={app.name}>
        {app.shortcutId && <MenuItem onSelected={run(launch, async () => {}, setMessage, [app.name, t("launching")])}>{t("launch")}</MenuItem>}
        {app.shortcutId ? (
          <MenuItem onSelected={run(remove, async () => {}, setMessage, [app.name, t("removedFromSteam")])}>{t("removeFromSteam")}</MenuItem>
        ) : (
          <MenuItem onSelected={run(add, async () => {}, setMessage, [app.name, t("addedToSteam")])}>{t("addToSteam")}</MenuItem>
        )}
        {app.removable && (
          <MenuItem onSelected={() => confirm(t("uninstallApp", { name: app.name }), t("uninstallAppDescription"), run(async () => {
            await uninstallApp(app.package);
            if (app.shortcutId) {
              await removeFromSteam(app.shortcutId);
              await removeShortcutRecord(app.package);
            }
          }, async () => {}, setMessage, [app.name, t("appUninstalled")]))}>{t("uninstall")}</MenuItem>
        )}
      </Menu>,
    );
  };

  return (
    <PanelSectionRow>
      <ButtonItem layout="below" onClick={openMenu}>
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
  const [status, setStatus] = useState<Status | null>(null);
  const [apps, setApps] = useState<AndroidApp[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [visibleApps, setVisibleApps] = useState(10);

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
    if (!status?.autoAddApps) {
      return;
    }
    let disposed = false;
    const sync = async () => {
      try {
        for (const shortcut of await pendingAutoShortcuts()) {
          if (autoAddAttempted.has(shortcut.key)) {
            continue;
          }
          autoAddAttempted.add(shortcut.key);
          await recordShortcut(shortcut.key, await addToSteam(shortcut));
          if (!disposed) {
            toast(shortcut.name, t("addedToSteam"));
          }
        }
        if (!disposed) {
          await refresh();
        }
      } catch (error) {
        if (!disposed) {
          setMessage(error instanceof Error ? error.message : String(error));
        }
      }
    };
    void sync();
    const timer = window.setInterval(() => void sync(), 30000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [refresh, status?.autoAddApps]);

  const resolution = status?.resolution ? `${status.resolution.width} × ${status.resolution.height}` : t("unavailable");
  const sortedApps = [...apps].sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: "base" }));
  const shownApps = sortedApps.slice(0, visibleApps);
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
      <PanelSection title={t("waydroid")}>
        <PanelSectionRow>
          <Field label={status?.initialized ? t("installed") : t("notInstalled")} description={t("detectedDisplay", { resolution })} />
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
                onClick={status.waydroidShortcutId ? run(removeWaydroidShortcut, async () => {}, setMessage, [t("waydroid"), t("removedFromSteam")]) : run(addWaydroid, async () => {}, setMessage, [t("waydroid"), t("addedToSteam")])}
              >
                {status.waydroidShortcutId ? t("removeWaydroidShortcut") : t("addWaydroid")}
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      {status?.initialized && (
        <PanelSection title={t("androidApps", { count: apps.length })}>
          <PanelSectionRow>
            <ToggleField
              label={t("autoAddApps")}
              description={t("autoAddAppsDescription")}
              checked={status.autoAddApps}
              onChange={(enabled) => run(() => setAutoAddApps(enabled), refresh, setMessage)()}
            />
          </PanelSectionRow>
          {shownApps.map((app) => <AppRow key={app.package} app={app} setShortcutId={(id) => setApps((current) => current.map((item) => item.package === app.package ? { ...item, shortcutId: id } : item))} setMessage={setMessage} />)}
          {!apps.length && <PanelSectionRow><Field description={t("noApps")} /></PanelSectionRow>}
          {visibleApps < sortedApps.length && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => setVisibleApps((count) => Math.min(count + 10, sortedApps.length))}>
                {t("showMore", { count: Math.min(10, sortedApps.length - visibleApps) })}
              </ButtonItem>
            </PanelSectionRow>
          )}
        </PanelSection>
      )}

      {status?.initialized && (
        <PanelSection title={t("dangerZone")}>
          <PanelSectionRow>
            <ToggleField
              label={t("keepWarm")}
              description={t("keepWarmDescription")}
              checked={status.autoStart}
              onChange={(enabled) => run(() => setAutoStart(enabled), refresh, setMessage)()}
            />
          </PanelSectionRow>
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
            <ButtonItem
              layout="below"
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

export default definePlugin(() => ({
  name: t("pluginName"),
  titleView: <div className={staticClasses.Title}>{t("pluginName")}</div>,
  content: <Content />,
  icon: <AndroidRobotIcon />,
}));
