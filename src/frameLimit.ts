import { callable } from "@decky/api";
import { currentFrameLimit } from "./steamSettings";

const syncFrameLimit = callable<[number], void>("sync_frame_limit");

export function watchFrameLimit() {
  let busy = false;
  let reported = false;
  const sync = async () => {
    if (busy) return;
    busy = true;
    try {
      const fps = currentFrameLimit();
      if (fps !== null && Number.isInteger(fps) && fps >= 0 && fps <= 1000) {
        await syncFrameLimit(fps);
      }
      reported = false;
    } catch (error) {
      if (!reported) console.warn("Waydroid frame-limit synchronization failed", error);
      reported = true;
    } finally {
      busy = false;
    }
  };
  void sync();
  const timer = window.setInterval(() => void sync(), 1000);
  return () => window.clearInterval(timer);
}
