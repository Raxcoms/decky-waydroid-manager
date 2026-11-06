import { callable } from "@decky/api";
import { ConfirmModal, ProgressBar } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { t } from "./i18n";

const getProgress = callable<[string, string], string>("get_package_progress");
const phases = {
  preparing: [5, "packagePreparing"],
  starting: [10, "packageStarting"],
  booting: [25, "packageBooting"],
  checking: [40, "packageChecking"],
  removing: [55, "packageRemoving"],
  installing: [55, "packageInstalling"],
  cleaning: [80, "packageCleaning"],
  library: [95, "packageLibrary"],
} as const;

type Props = {
  name: string;
  operation: "install" | "uninstall";
  target: string;
  perform: () => Promise<void>;
  autoStart?: boolean;
  onError: (error: unknown) => void;
  closeModal?: () => void;
};

export function PackageOperationModal({ name, operation, target, perform, autoStart = false, onError, closeModal }: Props) {
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<keyof typeof phases>("preparing");
  const running = useRef(false);

  useEffect(() => {
    if (!busy) return;
    let disposed = false;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const next = await getProgress(operation, target);
        if (!disposed && next in phases) setStage(next as keyof typeof phases);
      } catch (error) {
        console.warn("Waydroid package progress unavailable", error);
      } finally {
        polling = false;
      }
    };
    const timer = window.setInterval(() => void poll(), 500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [busy, operation, target]);

  const closeIfIdle = () => { if (!running.current) closeModal?.(); };
  const start = async () => {
    if (running.current) return;
    running.current = true;
    setStage("preparing");
    setBusy(true);
    try {
      await perform();
      closeModal?.();
    } catch (error) {
      onError(error);
    } finally {
      running.current = false;
      setBusy(false);
    }
  };

  useEffect(() => { if (autoStart) void start(); }, [autoStart]);

  return (
    <ConfirmModal
      // Steam exposes this option, but Decky's types do not include it yet.
      {...{ bCloseAfterOK: false }}
      strTitle={operation === "install" ? t("installPackageTitle", { name }) : t("uninstallApp", { name })}
      strDescription={operation === "install" ? t("installPackageProgress") : t("uninstallAppDescription")}
      strOKButtonText={busy ? t(operation === "install" ? "installing" : "uninstalling") : t(operation === "install" ? "install" : "uninstall")}
      bOKDisabled={busy}
      bCancelDisabled={busy}
      bDisableBackgroundDismiss={busy}
      bHideCloseIcon={busy}
      closeModal={closeIfIdle}
      onOK={start}
    >
      {busy && (
        <div style={{ marginTop: "16px" }} aria-live="polite">
          <div style={{ marginBottom: "8px" }}>{t(phases[stage][1])}</div>
          <ProgressBar nProgress={phases[stage][0]} />
        </div>
      )}
    </ConfirmModal>
  );
}
