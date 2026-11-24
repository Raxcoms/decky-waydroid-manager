type SettingsStore = { GetClientSetting(key: string): [unknown, unknown] | undefined };
type LegacySettings = { fps_limit?: number; is_fps_limit_enabled?: boolean };

function validTarget(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 1000 ? value : null;
}

export function frameLimit(settings?: SettingsStore, legacy?: LegacySettings): number | null {
  if (settings?.GetClientSetting) {
    const read = (key: string) => settings.GetClientSetting(key)?.[0];
    const enabled = read("gamescope_enable_app_target_framerate");
    const disabled = read("gamescope_disable_framelimit");
    if (disabled === true || enabled === false) return 0;
    if (enabled === true && disabled === false) return validTarget(read("gamescope_app_target_framerate"));
  }
  if (typeof legacy?.is_fps_limit_enabled === "boolean") {
    return legacy.is_fps_limit_enabled ? validTarget(legacy.fps_limit) : 0;
  }
  return null;
}

export function currentFrameLimit(): number | null {
  const runtime = window as unknown as {
    settingsStore?: SettingsStore;
    SystemPerfStore?: { msgSettingsPerApp?: LegacySettings };
  };
  return frameLimit(runtime.settingsStore, runtime.SystemPerfStore?.msgSettingsPerApp);
}

type Subscription = { unregister(): void };
type FrameEvents = {
  Settings?: { RegisterForSettingsArrayChanges?(callback: () => void): Subscription };
  System?: { Perf?: { RegisterForStateChanges?(callback: () => void): Subscription } };
  GameSessions?: { RegisterForAppLifetimeNotifications?(callback: () => void): Subscription };
};

export function observeFrameLimit(changed: (fps: number | null) => void,
  client: FrameEvents = window.SteamClient, read = currentFrameLimit) {
  let disposed = false;
  let queued = false;
  let forced = false;
  let previous: number | null | undefined;
  const update = (force = false) => {
    if (disposed) return;
    forced ||= force;
    if (queued) return;
    queued = true;
    queueMicrotask(() => {
      queued = false;
      if (disposed) return;
      const fps = read();
      if (forced || fps !== previous) {
        forced = false;
        previous = fps;
        changed(fps);
      }
    });
  };
  const subscriptions = [client.Settings?.RegisterForSettingsArrayChanges?.(() => update()),
    client.System?.Perf?.RegisterForStateChanges?.(() => update()),
    client.GameSessions?.RegisterForAppLifetimeNotifications?.(() => update(true))]
    .filter((value): value is Subscription => !!value);
  if (!subscriptions.length) console.warn("Steam frame settings change notifications are unavailable");
  update();
  return () => { disposed = true; subscriptions.forEach((subscription) => subscription.unregister()); };
}
