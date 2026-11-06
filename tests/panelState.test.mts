import assert from "node:assert/strict";
import test from "node:test";
import { AppListState } from "../src/panelState.ts";

test("leaving the plugin resets the expanded list", () => {
  const state = new AppListState();
  state.visible = 20;
  state.leave();
  assert.equal(state.visible, 10);
});

test("a menu and nested confirmation preserve expansion until the plugin is left", () => {
  const state = new AppListState();
  state.visible = 30;
  const closeMenu = state.retainForOverlay();
  state.leave();
  const closeConfirmation = state.retainForOverlay();
  closeMenu();
  state.leave();
  assert.equal(state.visible, 30);
  closeConfirmation();
  closeConfirmation();
  assert.equal(state.visible, 30);
  state.leave();
  assert.equal(state.visible, 10);
});
