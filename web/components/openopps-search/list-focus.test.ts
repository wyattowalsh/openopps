import { describe, expect, it } from "vitest";

import {
	clampListFocusIndex,
	isListFocusKey,
	resolveListFocusIndex,
} from "./list-focus";

describe("list focus", () => {
	it("recognizes list navigation keys", () => {
		expect(isListFocusKey("ArrowDown")).toBe(true);
		expect(isListFocusKey("Tab")).toBe(false);
	});

	it("returns -1 for empty lists", () => {
		expect(resolveListFocusIndex(0, 0, "ArrowDown")).toBe(-1);
	});

	it("moves from unset focus to first or last row", () => {
		expect(resolveListFocusIndex(-1, 3, "ArrowDown")).toBe(0);
		expect(resolveListFocusIndex(-1, 3, "ArrowUp")).toBe(2);
	});

	it("clamps arrow navigation within bounds", () => {
		expect(resolveListFocusIndex(1, 3, "ArrowDown")).toBe(2);
		expect(resolveListFocusIndex(2, 3, "ArrowDown")).toBe(2);
		expect(resolveListFocusIndex(1, 3, "ArrowUp")).toBe(0);
		expect(resolveListFocusIndex(0, 3, "ArrowUp")).toBe(0);
	});

	it("jumps to ends with Home and End", () => {
		expect(resolveListFocusIndex(1, 5, "Home")).toBe(0);
		expect(resolveListFocusIndex(1, 5, "End")).toBe(4);
	});

	it("clamps stale focus after a filtered list shrinks", () => {
		expect(clampListFocusIndex(4, 3)).toBe(2);
		expect(clampListFocusIndex(1, 3)).toBe(1);
		expect(clampListFocusIndex(-1, 3)).toBe(-1);
		expect(clampListFocusIndex(0, 0)).toBe(-1);
	});
});
