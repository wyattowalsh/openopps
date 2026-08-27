import { formatCount } from "@/components/openopps-search/search-utils";

export type JobsBoardLiveStatusInput = {
	manifestLoading: boolean;
	manifestError: string | null;
	searchLoading: boolean;
	searchActive: boolean;
	searchError: string | null;
	indexNote: string | null;
};

export function buildJobsBoardLiveStatus({
	manifestLoading,
	manifestError,
	searchLoading,
	searchActive,
	searchError,
	indexNote,
}: JobsBoardLiveStatusInput): string | null {
	if (manifestLoading) {
		return "Loading open jobs index.";
	}
	if (manifestError) {
		return manifestError;
	}
	if (searchLoading) {
		return searchActive ? "Searching jobs." : "Loading open jobs.";
	}
	if (searchError) {
		return searchError;
	}
	return indexNote;
}

export type JobsBoardIndexNoteInput = {
	searchLoading: boolean;
	searchActive: boolean;
	searchError: string | null;
	searchMeta: { page: number; totalPages: number } | null;
	currentPageRowCount: number;
};

export function resolveJobsBoardIndexNote({
	searchLoading,
	searchActive,
	searchError,
	searchMeta,
	currentPageRowCount,
}: JobsBoardIndexNoteInput): string | null {
	if (searchLoading) {
		return searchActive ? "Searching jobs..." : "Loading open jobs...";
	}
	if (searchError) {
		return "Showing current results. Retry search for fresh matches.";
	}
	if (searchMeta) {
		return `Showing page ${formatCount(searchMeta.page)} of ${formatCount(searchMeta.totalPages)} (${formatCount(currentPageRowCount)} rows on this page).`;
	}
	return null;
}

export type JobsBoardMatchDisplayInput = {
	searchActive: boolean;
	searchLoading: boolean;
	totalMatches: number | null | undefined;
	fallbackCount: number;
};

export type JobsBoardMatchDisplay = {
	matchCount: number | null;
	showAsMatches: boolean;
};

export function resolveJobsBoardMatchDisplay({
	searchActive,
	searchLoading,
	totalMatches,
	fallbackCount,
}: JobsBoardMatchDisplayInput): JobsBoardMatchDisplay {
	if (!searchActive) {
		return { matchCount: fallbackCount, showAsMatches: false };
	}
	if (typeof totalMatches === "number") {
		return { matchCount: totalMatches, showAsMatches: true };
	}
	return {
		matchCount: null,
		showAsMatches: searchLoading || searchActive,
	};
}

export function jobsBoardSectionClassName(hasPreviewSelection: boolean): string {
	return hasPreviewSelection
		? "not-prose mx-auto flex w-full max-w-[96rem] flex-col px-3 py-4 sm:px-5 lg:h-[calc(100dvh-3.5rem)] lg:max-h-[calc(100dvh-3.5rem)] lg:min-h-0 lg:overflow-hidden lg:px-6"
		: "not-prose mx-auto w-full max-w-[96rem] px-3 py-4 sm:px-5 lg:px-6";
}

export function jobsBoardLedgerClassName(hasPreviewSelection: boolean): string {
	return hasPreviewSelection
		? "opps-ledger-shell flex min-h-0 flex-1 flex-col overflow-hidden"
		: "opps-ledger-shell";
}

export function jobsBoardResultsFrameClassName(hasPreviewSelection: boolean): string {
	return hasPreviewSelection
		? "mt-4 flex min-h-0 flex-1 flex-col overflow-hidden"
		: "mt-4";
}

export function jobsBoardSplitGridClassName(hasPreviewSelection: boolean): string {
	return hasPreviewSelection
		? "grid min-h-0 flex-1 gap-4 overflow-hidden lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]"
		: "grid gap-4";
}

export function jobsBoardSplitColumnClassName(hasPreviewSelection: boolean): string {
	return hasPreviewSelection
		? "grid h-full min-h-0 grid-rows-[minmax(0,1fr)_auto] gap-3"
		: "grid gap-3";
}

export function jobsBoardSplitListPaneClassName(): string {
	return "flex h-full min-h-0 flex-col overflow-hidden [&>div]:h-full [&>div]:min-h-0 [&>div]:flex-1";
}

export function jobsBoardDesktopPreviewClassName(): string {
	return "hidden h-full min-h-0 overflow-hidden lg:flex lg:flex-col [&>article]:h-full [&>article]:min-h-0 [&>article]:flex-1 [&>div]:h-full [&>div]:min-h-0 [&>div]:flex-1";
}
