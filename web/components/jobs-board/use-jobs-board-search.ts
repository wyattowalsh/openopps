"use client";

import { useEffect, useRef, useState } from "react";

import type { JobBoardFilters, JobSortKey } from "@/components/jobs-board/jobs-board-filter-engine";
import { JOBS_BOARD_PAGE_SIZE } from "@/components/jobs-board/jobs-board-constants";
import {
	isDefaultJobsHomeView,
	t0SearchChunkPage,
} from "@/components/jobs-board/jobs-board-t0";
import {
	loadInitialJobsChunk,
	loadJobsSearchResults,
} from "@/components/openopps-search/search-index-loader";
import type { SearchManifest, SearchRow } from "@/components/openopps-search/search-types";
import { formatLoadError } from "@/components/openopps-search/search-utils";
import { trackTelemetry } from "@/lib/telemetry";

export type JobsBoardSearchMeta = {
	totalMatches: number;
	truncated: boolean;
	complete: boolean;
	limit: number;
	page: number;
	pageSize: number;
	totalPages: number;
	hasNextPage: boolean;
	hasPreviousPage: boolean;
	labeledAsMatches: boolean;
};

type UseJobsBoardSearchOptions = {
	manifest: SearchManifest | null;
	deferredFilters: JobBoardFilters;
	page: number;
	setPage: (page: number) => void | Promise<void>;
	activeFilterCount: number;
	sortKey: JobSortKey;
	onIndexErrorClear?: () => void;
};

export function resolveJobsBoardSortKey(query: string): JobSortKey {
	return query ? "relevance" : "latest";
}

export function useJobsBoardSearch({
	manifest,
	deferredFilters,
	page,
	setPage,
	activeFilterCount,
	sortKey,
	onIndexErrorClear,
}: UseJobsBoardSearchOptions) {
	const [searchRows, setSearchRows] = useState<SearchRow[]>([]);
	const [searchLoading, setSearchLoading] = useState(false);
	const [searchError, setSearchError] = useState<string | null>(null);
	const [searchRetryKey, setSearchRetryKey] = useState(0);
	const [searchMeta, setSearchMeta] = useState<JobsBoardSearchMeta | null>(null);
	const searchRequestIdRef = useRef(0);
	const mountedRef = useRef(false);
	// Keep callback out of the fetch effect deps — an unstable identity (e.g. inline
	// arrow in the parent) would abort/restart the search on every parent re-render.
	const onIndexErrorClearRef = useRef(onIndexErrorClear);
	useEffect(() => {
		onIndexErrorClearRef.current = onIndexErrorClear;
	}, [onIndexErrorClear]);

	useEffect(() => {
		mountedRef.current = true;
		return () => {
			mountedRef.current = false;
			searchRequestIdRef.current += 1;
		};
	}, []);

	useEffect(() => {
		if (!manifest) {
			return;
		}
		const requestId = searchRequestIdRef.current + 1;
		searchRequestIdRef.current = requestId;
		const controller = new AbortController();

		async function loadSearchResults() {
			const defaultHome = isDefaultJobsHomeView(deferredFilters, sortKey, page);
			if (!defaultHome) {
				setSearchLoading(true);
			}
			let paintedT0 = false;
			try {
				if (defaultHome && manifest) {
					try {
						const chunk = await loadInitialJobsChunk(manifest);
						if (mountedRef.current && searchRequestIdRef.current === requestId) {
							const t0 = t0SearchChunkPage(
								chunk,
								manifest.openJobCount ?? chunk.count,
							);
							setSearchRows(t0.rows);
							onIndexErrorClearRef.current?.();
							setSearchError(null);
							setSearchMeta(t0.meta);
							setSearchLoading(false);
							paintedT0 = true;
							trackTelemetry("jobs.search_loaded", {
								activeFilterCount,
								page: 1,
								pageSize: t0.meta.pageSize,
								query: deferredFilters.query,
								rows: t0.rows.length,
								sortKey,
								totalMatches: t0.meta.totalMatches,
								totalPages: t0.meta.totalPages,
								truncated: t0.meta.truncated,
								complete: false,
								t0: true,
							});
						}
					} catch {
						paintedT0 = false;
					}
				}
				const result = await loadJobsSearchResults(deferredFilters, sortKey, {
					page,
					pageSize: JOBS_BOARD_PAGE_SIZE,
					signal: controller.signal,
				});
				if (mountedRef.current && searchRequestIdRef.current === requestId) {
					setSearchRows(result.rows);
					onIndexErrorClearRef.current?.();
					setSearchError(null);
					setSearchMeta({
						totalMatches: result.totalMatches,
						truncated: result.truncated,
						complete: result.complete !== false,
						limit: result.limit,
						page: result.page,
						pageSize: result.pageSize,
						totalPages: result.totalPages,
						hasNextPage: result.hasNextPage,
						hasPreviousPage: result.hasPreviousPage,
						labeledAsMatches: activeFilterCount > 0,
					});
					if (result.page !== page) {
						void setPage(result.page);
					}
					trackTelemetry("jobs.search_loaded", {
						activeFilterCount,
						page: result.page,
						pageSize: result.pageSize,
						query: deferredFilters.query,
						rows: result.rows.length,
						sortKey,
						totalMatches: result.totalMatches,
						totalPages: result.totalPages,
						truncated: result.truncated,
						complete: result.complete !== false,
					});
				}
			} catch (caught) {
				if (
					mountedRef.current &&
					searchRequestIdRef.current === requestId &&
					!controller.signal.aborted
				) {
					if (paintedT0) {
						return;
					}
					const message = formatLoadError(caught);
					setSearchError(message);
					trackTelemetry("jobs.search_error", { message });
				}
			} finally {
				if (searchRequestIdRef.current === requestId && mountedRef.current) {
					setSearchLoading(false);
				}
			}
		}

		void loadSearchResults();
		return () => {
			controller.abort();
		};
	}, [
		activeFilterCount,
		deferredFilters,
		manifest,
		page,
		searchRetryKey,
		setPage,
		sortKey,
	]);

	const clearSearchError = () => {
		if (searchError) {
			setSearchError(null);
		}
	};

	const retrySearch = () => {
		trackTelemetry("jobs.search_retry", { activeFilterCount });
		setSearchError(null);
		setSearchRetryKey((value) => value + 1);
	};

	return {
		searchRows,
		searchLoading,
		searchError,
		setSearchError,
		searchMeta,
		clearSearchError,
		retrySearch,
	};
}
