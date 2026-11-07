import assert from "node:assert/strict";
import test from "node:test";
import { operationError } from "../src/errors.ts";

test("extracts Decky Python failures when the JavaScript message is empty", () => {
  const error = Object.assign(new Error(), { name: "Python Exception", pythonTraceback: 'Traceback (most recent call last):\n  File "plugin.py", line 10\nException: WAYDROID_NOT_RUNNING\n' });
  assert.equal(operationError(error), "WAYDROID_NOT_RUNNING");
});

test("keeps native API errors and picker cancellation messages", () => {
  assert.equal(operationError(new Error("Steam did not create the shortcut")), "Steam did not create the shortcut");
  assert.equal(operationError("User canceled"), "User canceled");
  assert.equal(operationError(null), "");
});

test("keeps Android failure causes instead of Java traceback tails", () => {
  assert.equal(operationError({ pythonTraceback: "RuntimeError: Exception occurred while executing install:\njava.lang.IllegalArgumentException: Failed to parse APK\n  at com.android.server.PackageManager\nCaused by: android.content.pm.PackageParser$PackageParserException: Invalid manifest\n  ... 12 more" }), "Invalid manifest");
  assert.equal(operationError({ pythonTraceback: "RuntimeError: Failure [INSTALL_FAILED_INVALID_APK: Invalid manifest]\n  ... 12 more" }), "INSTALL_FAILED_INVALID_APK: Invalid manifest]");
});
