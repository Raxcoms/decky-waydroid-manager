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

type AndroidApp = { name: string; package: string; icon: string; iconPath: string; shortcutId?: number };
type Shortcut = { name: string; exe: string; startDir: string; launchOptions: string; icon: string; key: string };

function AndroidRobotIcon() {
  return (
    <svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-label="Android robot">
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
const launchWaydroid = callable<[], void>("launch_waydroid");
const launchApp = callable<[string], void>("launch_app");
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
    throw new Error("Steam shortcut API is unavailable");
  }

  const appId = Number(await apps.AddShortcut(shortcut.name, shortcut.exe, shortcut.startDir, shortcut.launchOptions));
  if (!appId) {
    throw new Error("Steam did not create the shortcut");
  }
  apps.SetShortcutName?.(appId, shortcut.name);
  apps.SetShortcutLaunchOptions?.(appId, shortcut.launchOptions);
  if (shortcut.icon) {
    apps.SetShortcutIcon?.(appId, shortcut.icon);
  }
  return appId;
}

async function removeFromSteam(appId: number) {
  const apps = window.SteamClient?.Apps;
  if (!apps?.RemoveShortcut) {
    throw new Error("Steam shortcut API is unavailable");
  }
  await apps.RemoveShortcut(appId);
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

function AppRow({ app, refresh, setMessage }: { app: AndroidApp; refresh: () => Promise<void>; setMessage: (message: string | null) => void }) {
  const add = async () => {
    const shortcut = await getAppShortcut(app.package);
    await recordShortcut(shortcut.key, await addToSteam(shortcut));
  };
  const remove = async () => {
    if (!app.shortcutId) {
      throw new Error("Steam shortcut state is unavailable");
    }
    await removeFromSteam(app.shortcutId);
    await removeShortcutRecord(app.package);
  };
  const openMenu = () => {
    showContextMenu(
      <Menu label={app.name}>
        <MenuItem onSelected={run(() => launchApp(app.package), refresh, setMessage)}>Launch</MenuItem>
        {app.shortcutId ? (
          <MenuItem onSelected={run(remove, refresh, setMessage, [app.name, "Removed from Steam."])}>Remove from Steam</MenuItem>
        ) : (
          <MenuItem onSelected={run(add, refresh, setMessage, [app.name, "Added to Steam."])}>Add to Steam</MenuItem>
        )}
      </Menu>,
    );
  };

  return (
    <PanelSectionRow>
      <ButtonItem layout="below" onClick={openMenu}>
        <div style={{ display: "flex", alignItems: "center", gap: "14px", width: "100%", minWidth: 0, minHeight: "32px", padding: 0, transform: "translateX(-16px)" }}>
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

  const refresh = useCallback(async () => {
    const nextStatus = await getStatus();
    setStatus(nextStatus);
    setApps(nextStatus.initialized ? await listApps() : []);
  }, []);

  useEffect(() => {
    refresh().catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
  }, [refresh]);

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
            toast(shortcut.name, "Added to Steam.");
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

  const resolution = status?.resolution ? `${status.resolution.width} × ${status.resolution.height}` : "Unavailable";
  const addWaydroid = async () => {
    const shortcut = await getWaydroidShortcut();
    await recordShortcut(shortcut.key, await addToSteam(shortcut));
  };
  const removeWaydroidShortcut = async () => {
    if (!status?.waydroidShortcutId) {
      throw new Error("Steam shortcut state is unavailable");
    }
    await removeFromSteam(status.waydroidShortcutId);
    await removeShortcutRecord("waydroid");
  };

  return (
    <div>
      <PanelSection title="Waydroid">
        <PanelSectionRow>
          <Field label={status?.initialized ? "Waydroid is installed" : "Waydroid is not installed"} description={`Detected display: ${resolution}`} />
        </PanelSectionRow>
        {status && !status.gamescopeInstalled && (
          <PanelSectionRow>
            <Field label="Gamescope is unavailable" description="Gamescope is bundled by ArmadaOS. Update or repair this deployment before launching Waydroid." />
          </PanelSectionRow>
        )}
        {!status?.initialized && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => confirm("Install GAPPS image", "Download and initialize the official GAPPS Waydroid image for this device architecture. This may take several minutes.", run(installGapps, refresh, setMessage, ["Waydroid", "GAPPS image installed."]))}
            >
              Install Waydroid with GAPPS
            </ButtonItem>
          </PanelSectionRow>
        )}
        {status?.initialized && (
          <>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={run(launchWaydroid, refresh, setMessage)}>Launch Waydroid</ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={status.waydroidShortcutId ? run(removeWaydroidShortcut, refresh, setMessage, ["Waydroid", "Removed from Steam."]) : run(addWaydroid, refresh, setMessage, ["Waydroid", "Added to Steam."])}
              >
                {status.waydroidShortcutId ? "Remove Waydroid from Steam" : "Add Waydroid to Steam"}
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      {status?.initialized && (
        <PanelSection title={`Android apps (${apps.length})`}>
          {apps.map((app) => <AppRow key={app.package} app={app} refresh={refresh} setMessage={setMessage} />)}
          {!apps.length && <PanelSectionRow><Field description="No generated Waydroid desktop entries were found yet." /></PanelSectionRow>}
          <PanelSectionRow>
            <ToggleField
              label="Add new apps to Steam"
              description="Add apps installed after this is enabled. Removed shortcuts stay removed."
              checked={status.autoAddApps}
              onChange={(enabled) => run(() => setAutoAddApps(enabled), refresh, setMessage)()}
            />
          </PanelSectionRow>
        </PanelSection>
      )}

      {status?.initialized && (
        <PanelSection title="Danger zone">
          <PanelSectionRow>
            <ToggleField
              label="Keep service warm"
              description="Start the Waydroid container on boot for faster launches."
              checked={status.autoStart}
              onChange={(enabled) => run(() => setAutoStart(enabled), refresh, setMessage)()}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label={`Service: ${status.serviceRunning ? "Running" : "Stopped"}`} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Focusable style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
              <DialogButton style={{ flex: "1 1 max-content", maxWidth: "100%" }} onClick={run(startService, refresh, setMessage)}>Start</DialogButton>
              <DialogButton style={{ flex: "1 1 max-content", maxWidth: "100%" }} onClick={run(restartService, refresh, setMessage)}>Restart</DialogButton>
              <DialogButton style={{ flex: "1 1 max-content", maxWidth: "100%" }} onClick={run(stopService, refresh, setMessage)}>Stop</DialogButton>
            </Focusable>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => confirm("Remove Waydroid", "This permanently removes the Waydroid images, Android data, app entries, and disables its service. Installed Android apps cannot be recovered.", run(removeWaydroid, refresh, setMessage, ["Waydroid", "Image and data removed."]))}
            >
              Remove Waydroid image and data
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}

      {message && <div className={staticClasses.PanelSectionRow} style={{ padding: "8px 16px", opacity: 0.8 }}>{message}</div>}
    </div>
  );
}

export default definePlugin(() => ({
  name: "Waydroid Manager",
  titleView: <div className={staticClasses.Title}>Waydroid Manager</div>,
  content: <Content />,
  icon: <AndroidRobotIcon />,
}));
