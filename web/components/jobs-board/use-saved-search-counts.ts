"use client";

import { useEffect, useState } from "react";

import {
	savedSearchNewMatchCountFromSummary,
	type SavedSearchRecord,
} from "@/components/jobs-board/jobs-board-local-state";
import { loadJobsSearchSummary } from "@/components/openopps-search/search-index-loader";

export function useSavedSearchFullCounts(savedSearches: SavedSearchRecord[]) {
	const [savedSearchFullCounts, setSavedSearchFullCounts] = useState<
		Record<string, number>
	>({});

	useEffect(() => {
		const records = savedSearches.filter((record) => record.baselineScope === "full");
		if (records.length === 0) {
			return;
		}
		let cancelled = false;
		async function loadSavedSearchCounts() {
			const entries = await Promise.all(
				records.map(async (record) => {
					try {
						const summary = await loadJobsSearchSummary(record.filters, record.sortKey);
						return [
							record.id,
							savedSearchNewMatchCountFromSummary(record, summary),
						] as const;
					} catch {
						return [record.id, null] as const;
					}
				}),
			);
			if (cancelled) {
				return;
			}
			setSavedSearchFullCounts(
				Object.fromEntries(
					entries.filter(
						(entry): entry is readonly [string, number] => entry[1] !== null,
					),
				),
			);
		}
		void loadSavedSearchCounts();
		return () => {
			cancelled = true;
		};
	}, [savedSearches]);

	return savedSearchFullCounts;
}