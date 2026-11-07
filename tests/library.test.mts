import assert from "node:assert/strict";
import test from "node:test";
import { currentSteamAccount, liveShortcutIds, waitForShortcut } from "../src/library.ts";

test("Steam account IDs come from the logged-in client without rounding the SteamID", (t) => {
  const original = globalThis.App;
  t.after(() => { globalThis.App = original; });
  globalThis.App = {
    BHasCurrentUser: () => true,
    GetCurrentUser: () => ({ strSteamID: "76561197960265729" }),
  } as typeof globalThis.App;
  assert.equal(currentSteamAccount(), 1);
  globalThis.App.BHasCurrentUser = () => false;
  assert.equal(currentSteamAccount(), null);
});

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
