import assert from "node:assert/strict";
import test from "node:test";
import { isPetPreference, setPetPreference } from "./petPreferences.js";

test("pet toggle recognizes turtles and other pet species", () => {
  for (const value of ["可養烏龜", "有養烏龜", "可養陸龜", "可養兔子", "可養倉鼠", "可養鳥", "可養魚", "可養守宮", "可養寵物（羊駝）", "可養貓", "可養狗"]) {
    assert.equal(isPetPreference(value), true, value);
  }
  for (const value of ["不養烏龜", "沒有養烏龜", "不可養烏龜", "不需要養寵物", "採光良好", "可開伙"]) {
    assert.equal(isPetPreference(value), false, value);
  }
});

test("toggling preserves the specific pet and removes it when unchecked", () => {
  const preferences = ["採光良好", "可養寵物（烏龜）"];
  assert.deepEqual(setPetPreference(preferences, true), preferences);
  assert.deepEqual(setPetPreference(preferences, false), ["採光良好"]);
  assert.deepEqual(setPetPreference(["採光良好"], true), ["採光良好", "可養寵物"]);
});
