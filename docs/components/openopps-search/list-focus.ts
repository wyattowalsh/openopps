export type ListFocusKey = "ArrowDown" | "ArrowUp" | "Home" | "End";

export function isListFocusKey(key: string): key is ListFocusKey {
	return (
		key === "ArrowDown" ||
		key === "ArrowUp" ||
		key === "Home" ||
		key === "End"
	);
}

export function resolveListFocusIndex(
	currentIndex: number,
	count: number,
	key: ListFocusKey,
): number {
	if (count <= 0) {
		return -1;
	}
	if (key === "Home") {
		return 0;
	}
	if (key === "End") {
		return count - 1;
	}
	if (currentIndex < 0) {
		return key === "ArrowDown" ? 0 : count - 1;
	}
	if (key === "ArrowDown") {
		return Math.min(currentIndex + 1, count - 1);
	}
	return Math.max(currentIndex - 1, 0);
}

export function clampListFocusIndex(currentIndex: number, count: number) {
	if (count <= 0) {
		return -1;
	}
	if (currentIndex < 0) {
		return -1;
	}
	return Math.min(currentIndex, count - 1);
}
