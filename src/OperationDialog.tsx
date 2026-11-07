import { ConfirmModal, DialogBodyText, ProgressBar } from "@decky/ui";
import { t } from "./i18n";

type Props = {
  title: string;
  description?: string;
  action: string;
  busy: boolean;
  progress: { label: string; percent?: number };
  error: string | null;
  onStart: () => void;
  onClose: () => void;
};

export function OperationDialog({ title, description, action, busy, progress, error, onStart, onClose }: Props) {
  return (
    <ConfirmModal
      strTitle={title}
      strDescription={description}
      strOKButtonText={action}
      strCancelButtonText={t("cancel")}
      bDisableBackgroundDismiss={busy}
      bHideCloseIcon={busy}
      bOKDisabled={busy}
      bCancelDisabled={busy}
      closeModal={onClose}
      onCancel={onClose}
      onOK={onStart}
    >
      {error && <div role="alert"><DialogBodyText>{error}</DialogBodyText></div>}
      {busy && (
        <div aria-live="polite">
          <DialogBodyText>{progress.label}</DialogBodyText>
          <ProgressBar nProgress={progress.percent} indeterminate={progress.percent === undefined} focusable={false} />
        </div>
      )}
    </ConfirmModal>
  );
}
