import { isListFocusKey, resolveListFocusIndex } from "./list-focus";

export type ExplorerListKeyAction = {
	nextIndex: number;
	activateLink: boolean;
};

export function resolveExplorerListKeyAction({
	key,
	focusedIndex,
	rowCount,
}: {
	key: string;
	focusedIndex: number;
	rowCount: number;
}): ExplorerListKeyAction | null {
	if (rowCount <= 0) {
		return null;
	}
	if (key === "Enter") {
		if (focusedIndex < 0) {
			return null;
		}
		return { nextIndex: focusedIndex, activateLink: true };
	}
	if (!isListFocusKey(key)) {
		return null;
	}
	return {
		nextIndex: resolveListFocusIndex(focusedIndex, rowCount, key),
		activateLink: false,
	};
}
