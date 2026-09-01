import type { Entity } from "@/components/openopps-search/search-types";

import type { ExplorerSortKey } from "./explorer-filter-engine";

type ExplorerFullJobsDecision = {
	entity: Entity;
	hasJobsChunk: boolean;
	fullJobsLoaded: boolean;
	fullJobsRequested: boolean;
	fullJobsError?: string | null;
	activeFilterCount: number;
	sortKey: ExplorerSortKey;
	defaultJobsSort: ExplorerSortKey;
};

export function shouldLoadLineageAggregate({
	inspectOpen,
}: {
	inspectOpen: boolean;
}) {
	return inspectOpen;
}

export function shouldLoadFullJobsIndexForExplorer({
	entity,
	hasJobsChunk,
	fullJobsLoaded,
	fullJobsRequested,
	fullJobsError,
	activeFilterCount,
	sortKey,
	defaultJobsSort,
}: ExplorerFullJobsDecision) {
	if (entity !== "jobs") {
		return false;
	}
	if (!hasJobsChunk || fullJobsLoaded || fullJobsError) {
		return false;
	}
	return (
		activeFilterCount > 0 ||
		fullJobsRequested ||
		sortKey !== defaultJobsSort
	);
}
