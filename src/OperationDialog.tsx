import { DialogBody, DialogBodyText, DialogButtonPrimary, DialogButtonSecondary, DialogFooter, DialogHeader, Focusable, ModalRoot, ProgressBar } from "@decky/ui";
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
    <ModalRoot
      bDisableBackgroundDismiss={busy}
      bHideCloseIcon={busy}
      bOKDisabled={busy}
      bCancelDisabled={busy}
      closeModal={onClose}
      onCancel={onClose}
    >
      <DialogHeader>{title}</DialogHeader>
      <DialogBody>
        {description && <DialogBodyText>{description}</DialogBodyText>}
        {error && <div role="alert"><DialogBodyText>{error}</DialogBodyText></div>}
        {busy && (
          <div aria-live="polite">
            <DialogBodyText>{progress.label}</DialogBodyText>
            <ProgressBar nProgress={progress.percent} indeterminate={progress.percent === undefined} focusable={false} />
          </div>
        )}
      </DialogBody>
      <DialogFooter>
        <Focusable className="DialogTwoColLayout _DialogColLayout" flow-children="row">
          <DialogButtonPrimary disabled={busy} onClick={(event) => { event.preventDefault(); onStart(); }}>
            {action}
          </DialogButtonPrimary>
          <DialogButtonSecondary disabled={busy} onClick={(event) => { event.preventDefault(); onClose(); }}>
            {t("cancel")}
          </DialogButtonSecondary>
        </Focusable>
      </DialogFooter>
    </ModalRoot>
  );
}
