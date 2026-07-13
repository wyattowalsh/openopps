"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
	filterAndSortJobs,
	type JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import { useJobBoardFilterState } from "@/components/jobs-board/jobs-board-filter-state";
import { bucketMatchCount, JOBS_BOARD_PAGE_SIZE } from "@/components/jobs-board/jobs-board-constants";
import {
	baselineFromSearchSummary,
	baselineLookupFromSavedSearch,
	isDurableJobWorkflowRecord,
	jobLifecycleIndicators,
	savedSearchNewMatchCount,
	useJobsLocalState,
	type JobLifecycleIndicator,
	type SavedSearchRecord,
} from "@/components/jobs-board/jobs-board-local-state";
import { JobsBoardLocalDataPanel } from "@/components/jobs-board/jobs-board-local-data-panel";
import { resolveSelectedJobRow } from "@/components/jobs-board/jobs-board-load-state";
import { JobsBoardConfirmDialog } from "@/components/jobs-board/jobs-board-confirm-dialog";
import { JobsBoardEmpty } from "@/components/jobs-board/jobs-board-empty";
import { buildJobsBoardLiveStatus } from "@/components/jobs-board/jobs-board-live-status";
import { JobsBoardList } from "@/components/jobs-board/jobs-board-list";
import { JobsBoardMetrics } from "@/components/jobs-board/jobs-board-metrics";
import { JobsBoardPreview } from "@/components/jobs-board/jobs-board-preview";
import { JobsBoardPreviewSheet } from "@/components/jobs-board/jobs-board-preview-sheet";
import {
	detailRowSnapshot,
	retainedRowSnapshot,
} from "@/components/jobs-board/jobs-board-row-snapshots";
import { JobsBoardToolbar } from "@/components/jobs-board/jobs-board-toolbar";
import { useJobDetail } from "@/components/jobs-board/use-job-detail";
import { useJobsBoardManifest } from "@/components/jobs-board/use-jobs-board-manifest";
import { useJobsBoardSearch } from "@/components/jobs-board/use-jobs-board-search";
import { useSavedSearchFullCounts } from "@/components/jobs-board/use-saved-search-counts";
import {
	loadJobsSearchSummary,
} from "@/components/openopps-search/search-index-loader";
import {
	formatCount,
	formatLoadError,
	J,
	text,
} from "@/components/openopps-search/search-utils";
import { Button } from "@/components/ui/button";
import { trackTelemetry } from "@/lib/telemetry";

type JobsBoardProps = {
	initialJobId?: string;
};

export function JobsBoard({ initialJobId }: JobsBoardProps) {
	const [localDataOpen, setLocalDataOpen] = useState(false);
	const [pendingDeleteSavedSearch, setPendingDeleteSavedSearch] =
		useState<SavedSearchRecord | null>(null);
	const [activeSavedSearchId, setActiveSavedSearchId] = useState<string | null>(
		null,
	);
	const localState = useJobsLocalState();
	const markViewed = localState.markViewed;
	const retainJobDetail = localState.retainJobDetail;

	const {
		filters,
		deferredFilters,
		page,
		setPage,
		selectedJobId,
		setFilters,
		setSelectedJobId,
		clearFilters,
		activeFilterCount,
	} = useJobBoardFilterState();

	const { manifest, loading, error, setError } = useJobsBoardManifest();

	const sortKey: JobSortKey = deferredFilters.query ? "relevance" : "latest";
	const searchActive = activeFilterCount > 0;

	const {
		searchRows,
		searchLoading,
		searchError,
		searchMeta,
		setSearchError,
		clearSearchError,
		retrySearch,
	} = useJobsBoardSearch({
		manifest,
		deferredFilters,
		page,
		setPage,
		activeFilterCount,
		sortKey,
		searchActive,
		onIndexErrorClear: () => setError(null),
	});

	const { detail, detailLoading, detailError } = useJobDetail(selectedJobId);
	const savedSearchFullCounts = useSavedSearchFullCounts(localState.savedSearches);

	useEffect(() => {
		if (initialJobId && !selectedJobId) {
			void setSelectedJobId(initialJobId);
		}
	}, [initialJobId, selectedJobId, setSelectedJobId]);

	const rows = searchRows;

	const rowsWithLocalRetainedJobs = useMemo(() => {
		const currentJobIds = new Set(rows.map((row) => text(row[J.id])).filter(Boolean));
		const staleRows = Object.values(localState.retainedJobDetails)
			.filter((retained) => {
				const record = localState.jobRecords[retained.jobId];
				return (
					record?.firstAbsentSnapshotAt &&
					isDurableJobWorkflowRecord(record) &&
					!currentJobIds.has(retained.jobId)
				);
			})
			.map((retained) => retainedRowSnapshot(retained));
		return staleRows.length > 0 ? [...rows, ...staleRows] : rows;
	}, [localState.jobRecords, localState.retainedJobDetails, rows]);

	const visibleRows = useMemo(() => {
		if (rowsWithLocalRetainedJobs.length === 0) {
			return [];
		}
		return rowsWithLocalRetainedJobs.filter((row) => {
			const jobId = text(row[J.id]);
			if (!jobId) {
				return true;
			}
			const record = localState.jobRecords[jobId];
			if (!localState.settings.showHidden && record?.hiddenAt) {
				return false;
			}
			if (localState.settings.hideViewed && record?.viewedAt) {
				return false;
			}
			return true;
		});
	}, [
		localState.jobRecords,
		localState.settings.hideViewed,
		localState.settings.showHidden,
		rowsWithLocalRetainedJobs,
	]);

	const baseSelectedRow = useMemo(
		() => resolveSelectedJobRow(visibleRows, rowsWithLocalRetainedJobs, selectedJobId),
		[rowsWithLocalRetainedJobs, selectedJobId, visibleRows],
	);
	const selectedWorkflowRecord = selectedJobId
		? localState.jobRecords[selectedJobId] ?? null
		: null;
	const selectedRetainedDetail = selectedJobId
		? localState.retainedJobDetails[selectedJobId]?.detail ?? null
		: null;
	const activeDetail =
		selectedJobId && detail?.id === selectedJobId
			? detail
			: selectedRetainedDetail?.id === selectedJobId
				? selectedRetainedDetail
				: null;
	const selectedRow = useMemo(
		() => baseSelectedRow ?? (activeDetail ? detailRowSnapshot(activeDetail) : null),
		[activeDetail, baseSelectedRow],
	);
	const activeSavedSearch = useMemo(
		() =>
			activeSavedSearchId
				? localState.savedSearches.find((record) => record.id === activeSavedSearchId) ??
					null
				: null,
		[activeSavedSearchId, localState.savedSearches],
	);
	const activeSavedSearchBaseline = useMemo(
		() => baselineLookupFromSavedSearch(activeSavedSearch),
		[activeSavedSearch],
	);
	const lifecycleIndicatorsByJobId = useMemo(() => {
		const indicatorsById: Record<string, JobLifecycleIndicator[]> = {};
		for (const row of visibleRows) {
			const jobId = text(row[J.id]);
			if (!jobId) {
				continue;
			}
			const indicators = jobLifecycleIndicators({
				row,
				workflowRecord: localState.jobRecords[jobId],
				baseline: activeSavedSearchBaseline,
			});
			if (indicators.length > 0) {
				indicatorsById[jobId] = indicators;
			}
		}
		return indicatorsById;
	}, [activeSavedSearchBaseline, localState.jobRecords, visibleRows]);
	const selectedLifecycleIndicators = useMemo(() => {
		if (!selectedRow) {
			return [];
		}
		if (selectedJobId && lifecycleIndicatorsByJobId[selectedJobId]) {
			return lifecycleIndicatorsByJobId[selectedJobId];
		}
		return jobLifecycleIndicators({
			row: selectedRow,
			workflowRecord: selectedWorkflowRecord,
			baseline: activeSavedSearchBaseline,
		});
	}, [
		activeSavedSearchBaseline,
		lifecycleIndicatorsByJobId,
		selectedJobId,
		selectedRow,
		selectedWorkflowRecord,
	]);

	const rowsForSavedSearch = useCallback(
		(record: SavedSearchRecord) => filterAndSortJobs(rows, record.filters, record.sortKey),
		[rows],
	);

	const savedSearchSummaries = useMemo(
		() =>
			localState.savedSearches.map((record) => {
				const matches = rowsForSavedSearch(record);
				return {
					record,
					newMatches:
						record.baselineScope === "full"
							? savedSearchFullCounts[record.id] ?? null
							: savedSearchNewMatchCount(record, matches),
				};
			}),
		[localState.savedSearches, rowsForSavedSearch, savedSearchFullCounts],
	);

	useEffect(() => {
		if (!selectedJobId || !selectedRow) {
			return;
		}
		markViewed(selectedJobId, selectedRow, manifest?.snapshotAt ?? null);
	}, [markViewed, manifest?.snapshotAt, selectedJobId, selectedRow]);

	useEffect(() => {
		if (!selectedJobId || !selectedRow || !activeDetail) {
			return;
		}
		if (!isDurableJobWorkflowRecord(selectedWorkflowRecord)) {
			return;
		}
		retainJobDetail(
			selectedJobId,
			selectedRow,
			activeDetail,
			manifest?.snapshotAt ?? null,
		);
	}, [
		activeDetail,
		manifest?.snapshotAt,
		retainJobDetail,
		selectedJobId,
		selectedRow,
		selectedWorkflowRecord,
	]);

	const handleFiltersChange = (nextFilters: Parameters<typeof setFilters>[0]) => {
		clearSearchError();
		setActiveSavedSearchId(null);
		trackTelemetry("jobs.filters_changed", {
			keys: Object.keys(nextFilters),
			hasSelection: Boolean(selectedJobId),
		});
		setFilters(nextFilters);
	};

	const handleClearFilters = () => {
		clearSearchError();
		setActiveSavedSearchId(null);
		trackTelemetry("jobs.filters_cleared", {
			activeFilterCount,
			hasSelection: Boolean(selectedJobId),
		});
		clearFilters();
	};

	const goToPage = (nextPage: number) => {
		const safePage = Math.max(1, Math.min(nextPage, searchMeta?.totalPages ?? nextPage));
		setPage(safePage);
		trackTelemetry("jobs.page_changed", {
			page: safePage,
			pageSize: JOBS_BOARD_PAGE_SIZE,
			totalMatches: searchMeta?.totalMatches ?? 0,
			activeFilterCount,
		});
	};

	const handleSelectJob = (jobId: string) => {
		clearSearchError();
		trackTelemetry("jobs.result_selected", {
			hadPreviousSelection: Boolean(selectedJobId),
		});
		void setSelectedJobId(jobId);
	};

	const handleClosePreview = () => {
		clearSearchError();
		trackTelemetry("jobs.preview_closed", {
			hadSelection: Boolean(selectedJobId),
		});
		void setSelectedJobId(null);
	};

	const activeDetailError = selectedJobId && !selectedRetainedDetail ? detailError : null;
	const activeDetailLoading = Boolean(
		selectedJobId && (detailLoading || (!activeDetail && !activeDetailError)),
	);
	const hasPreviewSelection = Boolean(
		selectedJobId || selectedRow || activeDetail || activeDetailLoading,
	);

	const toggleSelectedFlag = (
		flag: "appliedAt" | "hiddenAt" | "savedAt",
		eventFlag: "applied" | "hidden" | "saved",
	) => {
		if (!selectedJobId) {
			return;
		}
		localState.toggleJobFlag(selectedJobId, flag, {
			row: selectedRow,
			detail: activeDetail,
			snapshotAt: manifest?.snapshotAt ?? null,
		});
		trackTelemetry("jobs.local_flag_changed", {
			flag: eventFlag,
			enabled: !Boolean(selectedWorkflowRecord?.[flag]),
		});
	};

	const handleNotesChange = (notes: string) => {
		if (!selectedJobId) {
			return;
		}
		localState.updateNotes(selectedJobId, notes, {
			row: selectedRow,
			detail: activeDetail,
			snapshotAt: manifest?.snapshotAt ?? null,
		});
	};

	const handleCreateSavedSearch = async () => {
		clearSearchError();
		try {
			const summary = await loadJobsSearchSummary(filters, sortKey);
			localState.createSavedSearch({
				filters,
				rows: visibleRows,
				baseline: baselineFromSearchSummary(summary),
				baselineScope: "full",
				baselineTotalMatches: summary.totalMatches,
				sortKey,
				manifest,
			});
			trackTelemetry("jobs.saved_search_created", {
				activeFilterCount,
				matchBucket: bucketMatchCount(summary.totalMatches),
			});
		} catch (caught) {
			const message = formatLoadError(caught);
			setSearchError(message);
			trackTelemetry("jobs.saved_search_error", { message });
		}
	};

	const handleRestoreSavedSearch = (record: SavedSearchRecord) => {
		clearSearchError();
		setActiveSavedSearchId(record.id);
		localState.updateSavedSearch({
			...record,
			lastOpenedAt: new Date().toISOString(),
		});
		setFilters(record.filters);
		trackTelemetry("jobs.saved_search_restored", {
			newMatchBucket: bucketMatchCount(savedSearchNewMatchCount(record, rowsForSavedSearch(record))),
		});
	};

	const handleReviewSavedSearch = async (record: SavedSearchRecord) => {
		setActiveSavedSearchId(record.id);
		clearSearchError();
		try {
			const summary = await loadJobsSearchSummary(record.filters, record.sortKey);
			localState.markSavedSearchReviewed(record, rowsForSavedSearch(record), manifest, {
				baseline: baselineFromSearchSummary(summary),
				baselineScope: "full",
				baselineTotalMatches: summary.totalMatches,
			});
			trackTelemetry("jobs.saved_search_reviewed", {
				matchBucket: bucketMatchCount(summary.totalMatches),
			});
		} catch (caught) {
			const message = formatLoadError(caught);
			setSearchError(message);
			trackTelemetry("jobs.saved_search_error", { message });
		}
	};

	const handleDeleteSavedSearch = (record: SavedSearchRecord) => {
		setPendingDeleteSavedSearch(record);
	};

	const confirmDeleteSavedSearch = () => {
		const record = pendingDeleteSavedSearch;
		if (!record) {
			return;
		}
		if (activeSavedSearchId === record.id) {
			setActiveSavedSearchId(null);
		}
		localState.deleteSavedSearch(record.id);
		trackTelemetry("jobs.saved_search_deleted");
		setPendingDeleteSavedSearch(null);
	};

	const activeSearchMeta = searchMeta;
	const activeSearchError = searchError;
	const emptyLoadingResults = searchLoading;
	const currentPageRowCount = rows.length;
	const displayedMatchCount =
		activeSearchMeta?.totalMatches ??
		manifest?.openJobCount ??
		manifest?.entities.jobs.count ??
		visibleRows.length;
	const indexNote = searchLoading
		? searchActive
			? "Searching jobs..."
			: "Loading open jobs..."
		: activeSearchError
			? "Showing current results. Retry search for fresh matches."
			: activeSearchMeta
				? `Showing page ${formatCount(activeSearchMeta.page)} of ${formatCount(activeSearchMeta.totalPages)} (${formatCount(currentPageRowCount)} rows on this page).`
				: !searchActive
					? "Enter a search or use filters to browse the indexed jobs."
					: null;

	const liveStatusMessage = buildJobsBoardLiveStatus({
		manifestLoading: loading,
		manifestError: error,
		searchLoading,
		searchActive,
		searchError: activeSearchError,
		indexNote,
	});

	return (
		<section className="not-prose mx-auto w-full max-w-[96rem] px-3 py-4 sm:px-5 lg:px-6">
			<p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
				{liveStatusMessage ?? ""}
			</p>
			<div className="opps-ledger-shell">
				<JobsBoardMetrics
					manifest={manifest}
					matchCount={displayedMatchCount}
					searchActive={searchActive}
				/>

				<div className="mt-4">
					<JobsBoardToolbar
						filters={filters}
						manifest={manifest}
						matchCount={displayedMatchCount}
						searchActive={searchActive}
						activeFilterCount={activeFilterCount}
						showHidden={localState.settings.showHidden}
						savedSearches={savedSearchSummaries}
						onChange={handleFiltersChange}
						onClear={handleClearFilters}
						onShowHiddenChange={(showHidden) =>
							localState.setSettings({ showHidden })
						}
						onSaveSearch={handleCreateSavedSearch}
						onRestoreSavedSearch={handleRestoreSavedSearch}
						onDeleteSavedSearch={handleDeleteSavedSearch}
						onDuplicateSavedSearch={localState.duplicateSavedSearch}
						onReviewSavedSearch={handleReviewSavedSearch}
						onOpenLocalData={() => setLocalDataOpen(true)}
					/>
				</div>

				{indexNote ? (
					<p className="mt-3 text-xs text-muted-foreground">{indexNote}</p>
				) : null}

				{error ? (
					<div
						className="opps-error-banner mt-4"
						role="alert"
						aria-live="assertive"
					>
						<span>{error}</span>
					</div>
				) : null}

				{activeSearchError ? (
					<div
						className="opps-error-banner mt-4"
						role="alert"
						aria-live="assertive"
					>
						<span>{activeSearchError}</span>
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={() => {
								trackTelemetry("jobs.search_retry", {
									activeFilterCount,
									hasSelection: Boolean(selectedJobId),
								});
								retrySearch();
							}}
						>
							Retry search
						</Button>
					</div>
				) : null}

				{loading ? (
					<div
						className="opps-loading mt-4 min-h-[24rem]"
						role="status"
						aria-live="polite"
						aria-busy="true"
					>
						<Loader2 className="size-4 animate-spin" aria-hidden="true" />
						Loading open jobs index…
					</div>
				) : null}

				{!loading && !error ? (
					<div className="mt-4">
						{visibleRows.length === 0 && !hasPreviewSelection ? (
							<div className="grid gap-3">
								<JobsBoardEmpty
									matchCount={displayedMatchCount}
									activeFilterCount={activeFilterCount}
									onClearFilters={handleClearFilters}
									loadingResults={emptyLoadingResults}
								/>
								<SearchPageControls
									meta={activeSearchMeta}
									loading={searchLoading}
									onPageChange={goToPage}
								/>
							</div>
						) : (
							<div
								className={
									hasPreviewSelection
										? "grid gap-4 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]"
										: "grid gap-4"
								}
							>
								{visibleRows.length === 0 ? (
									<div className="grid gap-3">
										<JobsBoardEmpty
											matchCount={displayedMatchCount}
											activeFilterCount={activeFilterCount}
											onClearFilters={handleClearFilters}
											loadingResults={emptyLoadingResults}
										/>
										<SearchPageControls
											meta={activeSearchMeta}
											loading={searchLoading}
											onPageChange={goToPage}
										/>
									</div>
								) : (
									<div className="grid gap-3">
										<JobsBoardList
											rows={visibleRows}
											selectedJobId={selectedJobId ?? ""}
											jobRecords={localState.jobRecords}
											jobLifecycleIndicators={lifecycleIndicatorsByJobId}
											onSelectJob={handleSelectJob}
										/>
										<SearchPageControls
											meta={activeSearchMeta}
											loading={searchLoading}
											onPageChange={goToPage}
										/>
									</div>
								)}
								{hasPreviewSelection ? (
									<div className="hidden lg:block">
										<JobsBoardPreview
											row={selectedRow}
											selectedJobId={selectedJobId}
											detail={activeDetail}
											loading={activeDetailLoading}
											error={activeDetailError}
											workflowRecord={selectedWorkflowRecord}
											lifecycleIndicators={selectedLifecycleIndicators}
											onToggleSaved={() => toggleSelectedFlag("savedAt", "saved")}
											onToggleHidden={() => toggleSelectedFlag("hiddenAt", "hidden")}
											onToggleApplied={() =>
												toggleSelectedFlag("appliedAt", "applied")
											}
											onNotesChange={handleNotesChange}
											onClose={handleClosePreview}
										/>
									</div>
								) : null}
							</div>
						)}
					</div>
				) : null}
			</div>

			<JobsBoardPreviewSheet
				open={hasPreviewSelection}
				row={selectedRow}
				selectedJobId={selectedJobId}
				detail={activeDetail}
				loading={activeDetailLoading}
				error={activeDetailError}
				workflowRecord={selectedWorkflowRecord}
				lifecycleIndicators={selectedLifecycleIndicators}
				onToggleSaved={() => toggleSelectedFlag("savedAt", "saved")}
				onToggleHidden={() => toggleSelectedFlag("hiddenAt", "hidden")}
				onToggleApplied={() => toggleSelectedFlag("appliedAt", "applied")}
				onNotesChange={handleNotesChange}
				onClose={handleClosePreview}
			/>
			<JobsBoardLocalDataPanel
				open={localDataOpen}
				settings={localState.settings}
				storageStatus={localState.storageStatus}
				summary={localState.summary}
				onClose={() => setLocalDataOpen(false)}
				onSettingsChange={localState.setSettings}
				onClearCategory={localState.clearCategory}
				onExport={localState.exportLocalData}
				onImport={localState.importLocalData}
			/>
			<JobsBoardConfirmDialog
				open={pendingDeleteSavedSearch !== null}
				title="Delete saved search?"
				description={
					pendingDeleteSavedSearch
						? `Delete saved search "${pendingDeleteSavedSearch.label}"? This only removes it from this browser.`
						: ""
				}
				confirmLabel="Delete"
				cancelLabel="Keep"
				destructive
				onConfirm={confirmDeleteSavedSearch}
				onCancel={() => setPendingDeleteSavedSearch(null)}
			/>
		</section>
	);
}

function SearchPageControls({
	meta,
	loading,
	onPageChange,
}: {
	meta: {
		page: number;
		totalPages: number;
		totalMatches: number;
		pageSize: number;
		hasNextPage: boolean;
		hasPreviousPage: boolean;
	} | null;
	loading: boolean;
	onPageChange: (page: number) => void;
}) {
	if (!meta || meta.totalMatches <= meta.pageSize) {
		return null;
	}
	return (
		<nav
			className="flex flex-col gap-2 border-t border-border/70 pt-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between"
			aria-label="Jobs result pages"
		>
			<span>
				Page {formatCount(meta.page)} of {formatCount(meta.totalPages)}
			</span>
			<div className="flex items-center gap-2">
				<Button
					type="button"
					variant="outline"
					size="sm"
					disabled={loading || !meta.hasPreviousPage}
					onClick={() => onPageChange(meta.page - 1)}
				>
					Previous
				</Button>
				<Button
					type="button"
					variant="outline"
					size="sm"
					disabled={loading || !meta.hasNextPage}
					onClick={() => onPageChange(meta.page + 1)}
				>
					Next
				</Button>
			</div>
		</nav>
	);
}