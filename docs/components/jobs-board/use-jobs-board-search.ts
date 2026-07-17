"use client";

import { useEffect, useRef, useState } from "react";

import type { JobBoardFilters, JobSortKey } from "@/components/jobs-board/jobs-board-filter-engine";
import { JOBS_BOARD_PAGE_SIZE } from "@/components/jobs-board/jobs-board-constants";
import { loadJobsSearchResults } from "@/components/openopps-search/search-index-loader";
import type { SearchManifest, SearchRow } from "@/components/openopps-search/search-types";
import { formatLoadError } from "@/components/openopps-search/search-utils";
import { trackTelemetry } from "@/lib/telemetry";

export type JobsBoardSearchMeta = {
	totalMatches: number;
	truncated: boolean;
	limit: number;
	page: number;
	pageSize: number;
	totalPages: number;
	hasNextPage: boolean;
	hasPreviousPage: boolean;
};

type UseJobsBoardSearchOptions = {
	manifest: SearchManifest | null;
	deferredFilters: JobBoardFilters;
	page: number;
	setPage: (page: number) => void | Promise<void>;
	activeFilterCount: number;
	sortKey: JobSortKey;
	searchActive: boolean;
	onIndexErrorClear?: () => void;
};

export function useJobsBoardSearch({
	manifest,
	deferredFilters,
	page,
	setPage,
	activeFilterCount,
	sortKey,
	searchActive,
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
	onIndexErrorClearRef.current = onIndexErrorClear;

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
		if (!searchActive) {
			searchRequestIdRef.current += 1;
			let cancelled = false;
			window.queueMicrotask(() => {
				if (cancelled || !mountedRef.current) {
					return;
				}
				setSearchRows([]);
				setSearchMeta(null);
				setSearchError(null);
				setSearchLoading(false);
				if (page !== 1) {
					void setPage(1);
				}
			});
			return () => {
				cancelled = true;
			};
		}
		const requestId = searchRequestIdRef.current + 1;
		searchRequestIdRef.current = requestId;
		const controller = new AbortController();

		async function loadSearchResults() {
			setSearchLoading(true);
			try {
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
						limit: result.limit,
						page: result.page,
						pageSize: result.pageSize,
						totalPages: result.totalPages,
						hasNextPage: result.hasNextPage,
						hasPreviousPage: result.hasPreviousPage,
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
					});
				}
			} catch (caught) {
				if (
					mountedRef.current &&
					searchRequestIdRef.current === requestId &&
					!controller.signal.aborted
				) {
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
		searchActive,
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