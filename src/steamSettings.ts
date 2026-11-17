type SettingsStore = { GetClientSetting(key: string): [unknown, unknown] };
type LegacySettings = { fps_limit?: number; is_fps_limit_enabled?: boolean };

export function frameLimit(settings?: SettingsStore, legacy?: LegacySettings): number | null {
  if (settings?.GetClientSetting) {
    const read = (key: string) => settings.GetClientSetting(key)[0];
    const enabled = read("gamescope_enable_app_target_framerate");
    const disabled = read("gamescope_disable_framelimit");
    const target = read("gamescope_app_target_framerate");
    if (typeof enabled === "boolean" && typeof disabled === "boolean" && typeof target === "number") {
      return enabled && !disabled ? target : 0;
    }
  }
  if (typeof legacy?.is_fps_limit_enabled === "boolean") {
    return legacy.is_fps_limit_enabled ? legacy.fps_limit ?? 0 : 0;
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
};

export function observeFrameLimit(changed: (fps: number | null) => void,
  client: FrameEvents = window.SteamClient, read = currentFrameLimit) {
  let disposed = false;
  let queued = false;
  let previous: number | null | undefined;
  const update = () => {
    if (disposed || queued) return;
    queued = true;
    queueMicrotask(() => {
      queued = false;
      if (disposed) return;
      const fps = read();
      if (fps !== previous) {
        previous = fps;
        changed(fps);
      }
    });
  };
  const subscriptions = [client.Settings?.RegisterForSettingsArrayChanges?.(update),
    client.System?.Perf?.RegisterForStateChanges?.(update)].filter((value): value is Subscription => !!value);
  if (!subscriptions.length) console.warn("Steam frame settings change notifications are unavailable");
  update();
  return () => { disposed = true; subscriptions.forEach((subscription) => subscription.unregister()); };
}
