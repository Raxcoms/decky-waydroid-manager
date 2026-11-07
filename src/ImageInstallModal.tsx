import { useEffect, useRef, useState } from "react";
import { getImageProgress, type ImageProgress } from "./backend";
import { t } from "./i18n";
import { OperationDialog } from "./OperationDialog";

type Props = {
  perform: () => Promise<void>;
  onError: (error: unknown) => string;
  closeModal?: () => void;
};

export function ImageInstallModal({ perform, onError, closeModal }: Props) {
  const running = useRef(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ImageProgress | null>(null);
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

  const percent = progress?.percent ?? undefined;
  const label = progress?.stage === "downloading"
    ? percent === undefined ? t("imageDownloading") : t("imageDownloadPercent", { percent })
    : progress?.stage === "finalizing" ? t("imageFinalizing") : t("imagePreparing");
  return <OperationDialog
    title={t("installGapps")}
    description={t("installGappsDescription")}
    action={t(busy ? "installing" : "install")}
    busy={busy}
    progress={{ label, percent }}
    error={error}
    onStart={() => void start()}
    onClose={() => { if (!running.current) closeModal?.(); }}
  />;
}
