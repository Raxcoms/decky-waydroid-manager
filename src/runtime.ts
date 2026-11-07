import { syncRuntime } from "./backend";
import { currentFrameLimit } from "./steamSettings";

export function watchRuntime() {
  let busy = false;
  let reported = false;
  const sync = async () => {
    if (busy) return;
    busy = true;
    try {
      const fps = currentFrameLimit();
      if (fps === null || (Number.isInteger(fps) && fps >= 0 && fps <= 1000)) {
        await syncRuntime(fps);
      }
      reported = false;
    } catch (error) {
      if (!reported) console.warn("Waydroid runtime synchronization failed", error);
      reported = true;
    } finally {
      busy = false;
    }
  };
  void sync();
  const timer = window.setInterval(() => void sync(), 1000);
  return () => window.clearInterval(timer);
}
