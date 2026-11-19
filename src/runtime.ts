import { syncRuntime } from "./backend";
import { observeFrameLimit } from "./steamSettings";

export function watchRuntime() {
  let busy = false;
  let reported = false;
  let disposed = false;
  let pending: number | null | undefined;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let retryDelay = 1000;
  const sync = async () => {
    if (busy || disposed) return;
    busy = true;
    try {
      while (pending !== undefined && !disposed) {
        const fps = pending;
        pending = undefined;
        try {
          await syncRuntime(fps);
          reported = false;
          retryDelay = 1000;
        } catch (error) {
          if (disposed) break;
          if (!reported) console.warn("Waydroid runtime synchronization failed", error);
          reported = true;
          if (pending === undefined) pending = fps;
          retry = setTimeout(() => { retry = undefined; void sync(); }, retryDelay);
          retryDelay = Math.min(retryDelay * 2, 30000);
          break;
        }
      }
    } finally {
      busy = false;
    }
  };
  const stop = observeFrameLimit((fps) => {
    if (fps !== null && (!Number.isInteger(fps) || fps < 0 || fps > 1000)) return;
    pending = fps;
    if (retry !== undefined) { clearTimeout(retry); retry = undefined; }
    void sync();
  });
  return () => { disposed = true; stop(); if (retry !== undefined) clearTimeout(retry); };
}
