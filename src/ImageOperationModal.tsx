import { useEffect, useRef, useState } from "react";
import { getImageProgress, type ImageProgress } from "./backend";
import { t } from "./i18n";
import { OperationDialog } from "./OperationDialog";

type Props = {
  operation: "install" | "setup" | "remove";
  perform: (showLibraryProgress: () => void) => Promise<void>;
  onError: (error: unknown) => string;
  closeModal?: () => void;
};

const stageLabels = {
  preparing: "imagePreparing", downloading: "imageDownloading", finalizing: "imageFinalizing",
  starting: "packageStarting", booting: "packageBooting", language: "imageLanguage", apps: "imageAppEntries", cleaning: "packageCleaning",
  stopping: "imageStopping", deleting: "imageDeleting",
} as const;

const dialogLabels = {
  install: { title: "installGapps", description: "installGappsDescription", action: "install", busy: "installing" },
  setup: { title: "finishImageSetup", description: "finishImageSetupDescription", action: "finishImageSetup", busy: "installing" },
  remove: { title: "removeWaydroid", description: "removeWaydroidDescription", action: "removeWaydroid", busy: "imageRemoving" },
} as const;

export function ImageOperationModal({ operation, perform, onError, closeModal }: Props) {
  const running = useRef(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ImageProgress | null>(null);
  const [removingShortcuts, setRemovingShortcuts] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!busy) return;
    let disposed = false;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const next = await getImageProgress();
        if (!disposed && next) setProgress(next);
      } catch (error) {
        console.warn("Waydroid image progress unavailable", error);
      } finally {
        polling = false;
      }
    };
    const timer = window.setInterval(() => void poll(), 1000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [busy]);

  const start = async () => {
    if (running.current) return;
    running.current = true;
    setError(null);
    setProgress(null);
    setRemovingShortcuts(false);
    setBusy(true);
    try {
      await perform(() => setRemovingShortcuts(true));
      closeModal?.();
    } catch (error) {
      setError(onError(error));
    } finally {
      running.current = false;
      setBusy(false);
    }
  };

  const labels = dialogLabels[operation];
  const stage = progress?.stage ?? (operation === "remove" ? "stopping" : "preparing");
  const percent = progress?.percent ?? undefined;
  let label = t(stageLabels[stage]);
  if (stage === "downloading" && percent !== undefined) label = t("imageDownloadPercent", { percent });
  if (removingShortcuts) label = t("imageRemovingShortcuts");
  return <OperationDialog
    title={t(labels.title)}
    description={t(labels.description)}
    action={t(busy ? labels.busy : labels.action)}
    busy={busy}
    progress={{ label, percent }}
    error={error}
    onStart={() => void start()}
    onClose={() => { if (!running.current) closeModal?.(); }}
  />;
}
