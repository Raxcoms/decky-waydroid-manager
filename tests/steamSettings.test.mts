import assert from "node:assert/strict";
import { test } from "node:test";
import { frameLimit } from "../src/steamSettings.ts";

function settings(values: Record<string, unknown>) {
  return { GetClientSetting: (key: string): [unknown, unknown] => [values[key], undefined] };
}

test("modern QAM target takes priority over stale legacy settings", () => {
  assert.equal(frameLimit(settings({
    gamescope_app_target_framerate: 24,
    gamescope_enable_app_target_framerate: true,
    gamescope_disable_framelimit: false,
  }), { fps_limit: 60, is_fps_limit_enabled: false }), 24);
});

test("reads changed targets and disabled caps without changing settings", () => {
  const values = {
    gamescope_app_target_framerate: 24,
    gamescope_enable_app_target_framerate: true,
    gamescope_disable_framelimit: false,
  };
  const store = settings(values);
  values.gamescope_app_target_framerate = 40;
  assert.equal(frameLimit(store), 40);
  values.gamescope_disable_framelimit = true;
  assert.equal(frameLimit(store), 0);
  values.gamescope_disable_framelimit = false;
  values.gamescope_enable_app_target_framerate = false;
  assert.equal(frameLimit(store), 0);
});

test("supports the legacy cap and leaves unknown settings untouched", () => {
  assert.equal(frameLimit(undefined, { fps_limit: 30, is_fps_limit_enabled: true }), 30);
  assert.equal(frameLimit(), null);
});
