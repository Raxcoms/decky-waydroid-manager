import { callable, definePlugin } from "@decky/api";
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
};

type AndroidApp = { name: string; package: string; icon: string };

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
const addWaydroidShortcut = callable<[], boolean>("add_waydroid_shortcut");
const addAppShortcut = callable<[string, string], boolean>("add_app_shortcut");
const removeWaydroid = callable<[], void>("remove_waydroid");

function run(action: () => Promise<unknown>, refresh: () => Promise<void>, setMessage: (message: string) => void) {
  return async () => {
    try {
      await action();
      setMessage("Done");
      await refresh();
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

function AppRow({ app, refresh, setMessage }: { app: AndroidApp; refresh: () => Promise<void>; setMessage: (message: string) => void }) {
  const openMenu = () => {
    showContextMenu(
      <Menu label={app.name}>
        <MenuItem onSelected={run(() => launchApp(app.package), refresh, setMessage)}>Launch</MenuItem>
        <MenuItem onSelected={run(() => addAppShortcut(app.package, app.name), refresh, setMessage)}>Add to Steam</MenuItem>
      </Menu>,
    );
  };

  return (
    <PanelSectionRow>
      <ButtonItem layout="below" label={app.name} description={app.package} onClick={openMenu} />
    </PanelSectionRow>
  );
}

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [apps, setApps] = useState<AndroidApp[]>([]);
  const [message, setMessage] = useState("Loading status...");

  const refresh = useCallback(async () => {
    const nextStatus = await getStatus();
    setStatus(nextStatus);
    setApps(nextStatus.initialized ? await listApps() : []);
  }, []);

  useEffect(() => {
    refresh().catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
  }, [refresh]);

  const resolution = status?.resolution ? `${status.resolution.width} × ${status.resolution.height}` : "Unavailable";

  return (
    <div>
      <PanelSection title="Waydroid">
        <PanelSectionRow>
          <Field label={status?.initialized ? "GAPPS image installed" : "Waydroid is not installed"} description={`Detected panel mode: ${resolution}. Nested Gamescope inherits Steam's current target size.`} />
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
              onClick={() => confirm("Install GAPPS image", "Download and initialize the official GAPPS Waydroid image for this device architecture. This may take several minutes.", run(installGapps, refresh, setMessage))}
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
              <ButtonItem layout="below" onClick={run(addWaydroidShortcut, refresh, setMessage)}>Add Waydroid to Steam</ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ToggleField
                label="Keep service warm"
                description="Start the Waydroid container on boot for faster launches."
                checked={status.autoStart}
                onChange={(enabled) => run(() => setAutoStart(enabled), refresh, setMessage)()}
              />
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      {status?.initialized && (
        <PanelSection title="Service">
          <PanelSectionRow>
            <Field label={status.serviceRunning ? "Running" : "Stopped"} />
          </PanelSectionRow>
          <PanelSectionRow>
            <Focusable style={{ display: "flex", gap: "8px" }}>
              <DialogButton onClick={run(startService, refresh, setMessage)}>Start</DialogButton>
              <DialogButton onClick={run(restartService, refresh, setMessage)}>Restart</DialogButton>
              <DialogButton onClick={run(stopService, refresh, setMessage)}>Stop</DialogButton>
            </Focusable>
          </PanelSectionRow>
        </PanelSection>
      )}

      {status?.initialized && (
        <PanelSection title={`Android apps (${apps.length})`}>
          {apps.map((app) => <AppRow key={app.package} app={app} refresh={refresh} setMessage={setMessage} />)}
          {!apps.length && <PanelSectionRow><Field description="No generated Waydroid desktop entries were found yet." /></PanelSectionRow>}
        </PanelSection>
      )}

      {status?.initialized && (
        <PanelSection title="Danger zone">
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => confirm("Remove Waydroid", "This permanently removes the Waydroid images, Android data, app entries, and disables its service. Installed Android apps cannot be recovered.", run(removeWaydroid, refresh, setMessage))}
            >
              Remove Waydroid image and data
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}

      <div className={staticClasses.PanelSectionRow} style={{ padding: "8px 16px", opacity: 0.8 }}>{message}</div>
    </div>
  );
}

export default definePlugin(() => ({
  name: "Waydroid Manager",
  titleView: <div className={staticClasses.Title}>Waydroid Manager</div>,
  content: <Content />,
  icon: <AndroidRobotIcon />,
}));
