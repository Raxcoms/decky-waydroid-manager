import { getPackageProgress } from "./backend";
import { DialogBody, DialogBodyText, DialogButtonPrimary, DialogButtonSecondary, DialogFooter, DialogHeader, ModalRoot, ProgressBar } from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { t } from "./i18n";

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
  onError: (error: unknown) => string;
  closeModal?: () => void;
};

export function PackageOperationModal({ name, operation, target, perform, autoStart = false, onError, closeModal }: Props) {
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<keyof typeof phases>("preparing");
  const [error, setError] = useState<string | null>(null);
  const running = useRef(false);

  useEffect(() => {
    if (!busy) return;
    let disposed = false;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const next = await getPackageProgress(operation, target);
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
    setError(null);
    setStage("preparing");
    setBusy(true);
    try {
      await perform();
      closeModal?.();
    } catch (error) {
      setError(onError(error));
    } finally {
      running.current = false;
      setBusy(false);
    }
  };

  useEffect(() => { if (autoStart) void start(); }, [autoStart]);

  return (
    <ModalRoot
      bDisableBackgroundDismiss={busy}
      bHideCloseIcon={busy}
      bOKDisabled={busy}
      bCancelDisabled={busy}
      closeModal={closeIfIdle}
      onCancel={closeIfIdle}
    >
      <DialogHeader>{operation === "install" ? t("installPackageTitle", { name }) : t("uninstallApp", { name })}</DialogHeader>
      <DialogBody>
        <DialogBodyText>{operation === "install" ? t("installPackageProgress") : t("uninstallAppDescription")}</DialogBodyText>
        {error && <div role="alert"><DialogBodyText>{error}</DialogBodyText></div>}
        {busy && <div aria-live="polite"><DialogBodyText>{t(phases[stage][1])}</DialogBodyText><ProgressBar nProgress={phases[stage][0]} /></div>}
      </DialogBody>
      <DialogFooter>
        <DialogButtonPrimary disabled={busy} onClick={(event) => { event.preventDefault(); void start(); }}>
          {busy ? t(operation === "install" ? "installing" : "uninstalling") : t(operation === "install" ? "install" : "uninstall")}
        </DialogButtonPrimary>
        <DialogButtonSecondary disabled={busy} onClick={(event) => { event.preventDefault(); closeIfIdle(); }}>{t("cancel")}</DialogButtonSecondary>
      </DialogFooter>
    </ModalRoot>
  );
}
