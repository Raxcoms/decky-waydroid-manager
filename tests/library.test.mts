import assert from "node:assert/strict";
import test from "node:test";
import { liveShortcutIds, waitForShortcut } from "../src/library.ts";

const runtime = globalThis as unknown as { appStore?: { allApps: { appid: number }[]; GetAppOverviewByAppID?: (id: number) => unknown } };

test("unknown and loading libraries do not report every shortcut as removed", () => {
  delete runtime.appStore;
  assert.equal(liveShortcutIds(), null);
  runtime.appStore = { allApps: [] };
  assert.equal(liveShortcutIds(), null);
  delete runtime.appStore;
});

test("native library IDs are unsigned and only non-Steam entries are reported", async () => {
  runtime.appStore = { allApps: [{ appid: 123 }, { appid: -1 }], GetAppOverviewByAppID: (id) => id === 0xffffffff };
  assert.deepEqual(liveShortcutIds(), [0xffffffff]);
  assert.equal(await waitForShortcut(0xffffffff), true);
  delete runtime.appStore;
});
