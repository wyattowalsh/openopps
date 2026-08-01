"use client";

import { useEffect, useState } from "react";

import type { SavedSearchRecord } from "@/components/jobs-board/jobs-board-local-state";
import {
	loadSavedSearchCounts,
	SAVED_SEARCH_COUNT_BATCH_SIZE,
} from "@/components/openopps-search/search-index-loader";

export function useSavedSearchFullCounts(savedSearches: SavedSearchRecord[]) {
	const [savedSearchFullCounts, setSavedSearchFullCounts] = useState<
		Record<string, number>
	>({});

	useEffect(() => {
		const records = savedSearches.filter(
			(record) => record.reviewStatus === "current" && record.reviewCursor,
		);
		if (records.length === 0) {
			setSavedSearchFullCounts({});
			return;
		}
		const controller = new AbortController();
		async function refreshSavedSearchCounts() {
			const next: Record<string, number> = {};
			try {
				for (let start = 0; start < records.length; start += SAVED_SEARCH_COUNT_BATCH_SIZE) {
					const batch = records.slice(start, start + SAVED_SEARCH_COUNT_BATCH_SIZE);
					const response = await loadSavedSearchCounts(
						batch.map((record) => ({
							id: record.id,
							filters: record.filters,
							sortKey: record.sortKey,
							reviewedAt: record.reviewCursor?.reviewedAt ?? "",
						})),
						{ signal: controller.signal },
					);
					for (const count of response.counts) {
						next[count.id] = count.newMatches;
					}
				}
				if (!controller.signal.aborted) {
					setSavedSearchFullCounts(next);
				}
			} catch {
				if (!controller.signal.aborted) {
					setSavedSearchFullCounts({});
				}
			}
		}
		void refreshSavedSearchCounts();
		return () => {
			controller.abort();
		};
	}, [savedSearches]);

	return savedSearchFullCounts;
}
