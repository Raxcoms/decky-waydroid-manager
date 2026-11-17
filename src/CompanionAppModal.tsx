import { ConfirmModal, DialogBodyText, DropdownItem } from "@decky/ui";
import { useRef, useState } from "react";
import { type AndroidApp } from "./backend";
import { t } from "./i18n";

type Props = {
  app: AndroidApp;
  apps: AndroidApp[];
  onSelect: (packageName: string) => Promise<void>;
  onError: (error: unknown) => string;
  closeModal?: () => void;
};

export function CompanionAppModal({ app, apps, onSelect, onError, closeModal }: Props) {
  const [selected, setSelected] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = useRef(false);
  const options = apps.filter((candidate) => candidate.package !== app.package).map((candidate) => ({
    data: candidate.package,
    label: <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
      {candidate.icon && <img src={candidate.icon} alt="" width={24} height={24} style={{ objectFit: "contain" }} />}
      <span>{candidate.name}</span>
    </span>,
  }));
  const save = async () => {
    if (!selected || running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      await onSelect(selected);
      closeModal?.();
    } catch (failure) {
      setError(onError(failure));
    } finally {
      running.current = false;
      setBusy(false);
    }
  };
  const close = () => { if (!running.current) closeModal?.(); };
  return <ConfirmModal
    strTitle={t("linkCompanion")}
    strDescription={t("companionDescription", { name: app.name })}
    strOKButtonText={t("linkCompanion")}
    strCancelButtonText={t("cancel")}
    bOKDisabled={!selected || busy}
    bCancelDisabled={busy}
    bDisableBackgroundDismiss={busy}
    bHideCloseIcon={busy}
    closeModal={close}
    onCancel={close}
    onOK={() => void save()}
  >
    <div style={{ marginBlockStart: 24 }}>
      <DropdownItem label={t("companionApp")} menuLabel={t("companionApp")}
        strDefaultLabel={t("selectCompanion")} rgOptions={options} selectedOption={selected}
        onChange={(option) => setSelected(option.data)} disabled={busy || !options.length} />
    </div>
    {!options.length && <DialogBodyText>{t("noCompanionApps")}</DialogBodyText>}
    {error && <div role="alert"><DialogBodyText>{error}</DialogBodyText></div>}
  </ConfirmModal>;
}
