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