import { describe, expect, it } from "vitest";

import { resolveExplorerListKeyAction } from "./explorer-list-keydown";

describe("explorer list keydown", () => {
	it("moves from unset focus to first row on ArrowDown", () => {
		expect(
			resolveExplorerListKeyAction({
				key: "ArrowDown",
				focusedIndex: -1,
				rowCount: 3,
			}),
		).toEqual({ nextIndex: 0, activateLink: false });
	});

	it("activates the focused row link on Enter", () => {
		expect(
			resolveExplorerListKeyAction({
				key: "Enter",
				focusedIndex: 1,
				rowCount: 3,
			}),
		).toEqual({ nextIndex: 1, activateLink: true });
	});

	it("ignores Enter when no row is focused", () => {
		expect(
			resolveExplorerListKeyAction({
				key: "Enter",
				focusedIndex: -1,
				rowCount: 3,
			}),
		).toBeNull();
	});

	it("ignores unrelated keys", () => {
		expect(
			resolveExplorerListKeyAction({
				key: "Tab",
				focusedIndex: 0,
				rowCount: 3,
			}),
		).toBeNull();
	});
});
