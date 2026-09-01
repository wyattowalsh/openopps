import type {
	JobBoardFilters,
	JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import type {
	JobsSearchResponse,
	JobsSearchSummaryResponse,
	SavedSearchCountQuery,
	SavedSearchCountsResponse,
} from "@/components/openopps-search/search-types";

export type JobsSearchSnapshotDescriptor = {
	baseUrl: string;
	channel: string | null;
	releaseId: string | null;
	offlineCacheName: string | null;
	bootstrapJobsCount?: number | null;
};

export type JobsSearchWorkerRequest =
	| {
			kind: "initialize";
			requestId: number;
			snapshot: JobsSearchSnapshotDescriptor;
	  }
	| {
			kind: "search";
			requestId: number;
			filters: JobBoardFilters;
			sortKey: JobSortKey;
			limit?: number;
			page?: number;
			pageSize?: number;
	  }
	| {
			kind: "summary";
			requestId: number;
			filters: JobBoardFilters;
			sortKey: JobSortKey;
	  }
	| {
			kind: "saved-counts";
			requestId: number;
			searches: SavedSearchCountQuery[];
	  }
	| {
			kind: "cancel";
			requestId: number;
	  };

export type JobsSearchWorkerSuccess =
	| {
			kind: "initialized";
			requestId: number;
			stats: {
				rows: number;
				indexBytes: number;
				dictionaryValues: number;
				cachedResults: number;
				cachedRowReferences: number;
				maxCachedRowReferences: number;
			};
	  }
	| { kind: "search-result"; requestId: number; result: JobsSearchResponse }
	| { kind: "summary-result"; requestId: number; result: JobsSearchSummaryResponse }
	| { kind: "saved-counts-result"; requestId: number; result: SavedSearchCountsResponse };

export type JobsSearchWorkerResponse =
	| JobsSearchWorkerSuccess
	| {
			kind: "error";
			requestId: number;
			name: string;
			message: string;
	  };
