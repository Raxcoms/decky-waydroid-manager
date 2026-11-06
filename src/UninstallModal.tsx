import { callable } from "@decky/api";
import { ConfirmModal, ProgressBar } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { t } from "./i18n";

const getProgress = callable<[string], string>("get_uninstall_progress");
const phases = {
  preparing: [5, "uninstallPreparing"],
  starting: [10, "uninstallStarting"],
  booting: [25, "uninstallBooting"],
  checking: [40, "uninstallChecking"],
  removing: [55, "uninstallRemoving"],
  cleaning: [80, "uninstallCleaning"],
  library: [95, "uninstallLibrary"],
} as const;

type Props = {
  name: string;
  packageName: string;
  uninstall: () => Promise<void>;
  onError: (error: unknown) => void;
  closeModal?: () => void;
};

export function UninstallModal({ name, packageName, uninstall, onError, closeModal }: Props) {
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
        const next = await getProgress(packageName);
        if (!disposed && next in phases) setStage(next as keyof typeof phases);
      } catch (error) {
        console.warn("Waydroid uninstall progress unavailable", error);
      } finally {
        polling = false;
      }
    };
    const timer = window.setInterval(() => void poll(), 500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [busy, packageName]);

  const closeIfIdle = () => { if (!running.current) closeModal?.(); };
  const remove = async () => {
    if (running.current) return;
    running.current = true;
    setStage("preparing");
    setBusy(true);
    try {
      await uninstall();
      closeModal?.();
    } catch (error) {
      onError(error);
    } finally {
      running.current = false;
      setBusy(false);
    }
  };

  return (
    <ConfirmModal
      // Steam exposes this option, but Decky's types do not include it yet.
      {...{ bCloseAfterOK: false }}
      strTitle={t("uninstallApp", { name })}
      strDescription={t("uninstallAppDescription")}
      strOKButtonText={busy ? t("uninstalling") : t("uninstall")}
      bOKDisabled={busy}
      bCancelDisabled={busy}
      bDisableBackgroundDismiss={busy}
      bHideCloseIcon={busy}
      closeModal={closeIfIdle}
      onOK={remove}
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
