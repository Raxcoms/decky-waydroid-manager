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
