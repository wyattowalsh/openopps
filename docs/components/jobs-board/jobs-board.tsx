"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
	filterAndSortJobs,
	type JobSortKey,
} from "@/components/jobs-board/jobs-board-filter-engine";
import { useJobBoardFilterState } from "@/components/jobs-board/jobs-board-filter-state";
import {
	baselineLookupFromSavedSearch,
	isDurableJobWorkflowRecord,
	jobLifecycleIndicators,
	savedSearchNewMatchCount,
	useJobsLocalState,
	type JobLifecycleIndicator,
	type RetainedJobDetailRecord,
	type SavedSearchRecord,
} from "@/components/jobs-board/jobs-board-local-state";
import { JobsBoardLocalDataPanel } from "@/components/jobs-board/jobs-board-local-data-panel";
import { resolveSelectedJobRow } from "@/components/jobs-board/jobs-board-load-state";
import { JobsBoardEmpty } from "@/components/jobs-board/jobs-board-empty";
import { JobsBoardList } from "@/components/jobs-board/jobs-board-list";
import { JobsBoardMetrics } from "@/components/jobs-board/jobs-board-metrics";
import { JobsBoardPreview } from "@/components/jobs-board/jobs-board-preview";
import { JobsBoardPreviewSheet } from "@/components/jobs-board/jobs-board-preview-sheet";
import { JobsBoardToolbar } from "@/components/jobs-board/jobs-board-toolbar";
import {
	loadInitialJobsChunk,
	loadJobsSearchResults,
	loadSearchManifest,
} from "@/components/openopps-search/search-index-loader";
import type {
	JobDetail,
	SearchManifest,
	SearchRow,
} from "@/components/openopps-search/search-types";
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

function errorMessage(error: unknown) {
	return formatLoadError(error);
}

export function JobsBoard({ initialJobId }: JobsBoardProps) {
	const [manifest, setManifest] = useState<SearchManifest | null>(null);
	const [initialRows, setInitialRows] = useState<SearchRow[]>([]);
	const [searchRows, setSearchRows] = useState<SearchRow[]>([]);
	const [loading, setLoading] = useState(true);
	const [searchLoading, setSearchLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [searchError, setSearchError] = useState<string | null>(null);
	const [searchRetryKey, setSearchRetryKey] = useState(0);
	const [searchMeta, setSearchMeta] = useState<{
		totalMatches: number;
		truncated: boolean;
		limit: number;
	} | null>(null);
	const [detail, setDetail] = useState<JobDetail | null>(null);
	const [detailLoading, setDetailLoading] = useState(false);
	const [detailError, setDetailError] = useState<string | null>(null);
	const [localDataOpen, setLocalDataOpen] = useState(false);
	const [activeSavedSearchId, setActiveSavedSearchId] = useState<string | null>(
		null,
	);
	const searchRequestIdRef = useRef(0);
	const mountedRef = useRef(false);
	const reconciledSnapshotKeyRef = useRef<string | null>(null);
	const localState = useJobsLocalState();
	const markViewed = localState.markViewed;
	const reconcileSnapshot = localState.reconcileSnapshot;
	const retainJobDetail = localState.retainJobDetail;

	const {
		filters,
		deferredFilters,
		selectedJobId,
		setFilters,
		setSelectedJobId,
		clearFilters,
		activeFilterCount,
	} = useJobBoardFilterState();

	useEffect(() => {
		mountedRef.current = true;
		return () => {
			mountedRef.current = false;
			searchRequestIdRef.current += 1;
		};
	}, []);

	useEffect(() => {
		if (initialJobId && !selectedJobId) {
			void setSelectedJobId(initialJobId);
		}
	}, [initialJobId, selectedJobId, setSelectedJobId]);

	useEffect(() => {
		let mounted = true;

		async function load() {
			try {
				const nextManifest = await loadSearchManifest();
				const initialChunk = await loadInitialJobsChunk(nextManifest);
				if (mounted) {
					setManifest(nextManifest);
					setInitialRows(initialChunk.rows);
					setError(null);
					setSearchError(null);
					trackTelemetry("jobs.index_loaded", {
						initialRows: initialChunk.count,
						totalRows: nextManifest.entities.jobs.count,
						manifestVersion: nextManifest.version,
					});
				}
			} catch (caught) {
				if (mounted) {
					const message = errorMessage(caught);
					setError(message);
					trackTelemetry("jobs.index_error", { message });
				}
			} finally {
				if (mounted) {
					setLoading(false);
				}
			}
		}

		void load();
		return () => {
			mounted = false;
		};
	}, []);

	const jobCount = manifest?.entities.jobs.count ?? 0;
	const sortKey: JobSortKey = deferredFilters.query ? "relevance" : "latest";
	const searchActive = activeFilterCount > 0;
	const rows = searchActive ? searchRows : initialRows;
	const fullRowsLoaded = initialRows.length > 0 && initialRows.length >= jobCount;

	useEffect(() => {
		if (!manifest || !searchActive) {
			return;
		}
		const requestId = searchRequestIdRef.current + 1;
		searchRequestIdRef.current = requestId;
		const controller = new AbortController();

		async function loadSearchResults() {
			setSearchLoading(true);
			try {
				const result = await loadJobsSearchResults(deferredFilters, sortKey, {
					signal: controller.signal,
				});
				if (mountedRef.current && searchRequestIdRef.current === requestId) {
					setSearchRows(result.rows);
					setError(null);
					setSearchError(null);
					setSearchMeta({
						totalMatches: result.totalMatches,
						truncated: result.truncated,
						limit: result.limit,
					});
					trackTelemetry("jobs.search_loaded", {
						rows: result.rows.length,
						totalMatches: result.totalMatches,
						truncated: result.truncated,
					});
				}
			} catch (caught) {
				if (
					mountedRef.current &&
					searchRequestIdRef.current === requestId &&
					!controller.signal.aborted
				) {
					const message = errorMessage(caught);
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
	}, [deferredFilters, manifest, searchActive, searchRetryKey, sortKey]);

	useEffect(() => {
		if (!manifest || !fullRowsLoaded || rows.length === 0) {
			return;
		}
		const reconciliationKey = [
			manifest.version,
			manifest.snapshotAt ?? "",
			rows.length,
		].join("|");
		if (reconciledSnapshotKeyRef.current === reconciliationKey) {
			return;
		}
		reconciledSnapshotKeyRef.current = reconciliationKey;
		reconcileSnapshot(rows, manifest);
	}, [fullRowsLoaded, manifest, reconcileSnapshot, rows]);

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
		const filteredRows = filterAndSortJobs(
			rowsWithLocalRetainedJobs,
			deferredFilters,
			sortKey,
		);
		return filteredRows.filter((row) => {
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
		deferredFilters,
		localState.jobRecords,
		localState.settings.hideViewed,
		localState.settings.showHidden,
		rowsWithLocalRetainedJobs,
		sortKey,
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
					newMatches: savedSearchNewMatchCount(record, matches),
				};
			}),
		[localState.savedSearches, rowsForSavedSearch],
	);

	useEffect(() => {
		if (!selectedJobId) {
			return;
		}

		const jobId = selectedJobId;
		let mounted = true;
		const controller = new AbortController();

		async function loadDetail() {
			setDetailLoading(true);
			setDetailError(null);
			try {
				const response = await fetch(
					`/api/jobs/detail?id=${encodeURIComponent(jobId)}`,
					{
						signal: controller.signal,
						cache: "force-cache",
					},
				);
				if (!response.ok) {
					throw new Error(`Job detail not found (${response.status})`);
				}
				const nextDetail = (await response.json()) as JobDetail;
				if (mounted) {
					setDetail(nextDetail);
					trackTelemetry("jobs.detail_loaded", {
						sourceKeyPresent: Boolean(nextDetail.sourceKey),
						providerIdPresent: Boolean(nextDetail.providerId),
						hasDescription: Boolean(
							nextDetail.descriptionHtml ?? nextDetail.description,
						),
						payloadSnapshots: nextDetail.payloadSnapshots?.length ?? 0,
					});
				}
			} catch (caught) {
				if (!mounted || controller.signal.aborted) {
					return;
				}
				const message = errorMessage(caught);
				setDetail(null);
				setDetailError(message);
				trackTelemetry("jobs.detail_error", {
					hasSelectedJob: Boolean(jobId),
					message,
				});
			} finally {
				if (mounted) {
					setDetailLoading(false);
				}
			}
		}

		void loadDetail();
		return () => {
			mounted = false;
			controller.abort();
		};
	}, [selectedJobId]);

	const clearSearchError = () => {
		if (searchError) {
			setSearchError(null);
		}
	};

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

	const retrySearch = () => {
		trackTelemetry("jobs.search_retry", {
			activeFilterCount,
			hasSelection: Boolean(selectedJobId),
		});
		setSearchError(null);
		setSearchRetryKey((value) => value + 1);
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

	const handleCreateSavedSearch = () => {
		localState.createSavedSearch({
			filters,
			rows: visibleRows,
			sortKey,
			manifest,
		});
		trackTelemetry("jobs.saved_search_created", {
			activeFilterCount,
			matchBucket: bucketCount(visibleRows.length),
		});
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
			newMatchBucket: bucketCount(savedSearchNewMatchCount(record, rowsForSavedSearch(record))),
		});
	};

	const handleReviewSavedSearch = (record: SavedSearchRecord) => {
		setActiveSavedSearchId(record.id);
		localState.markSavedSearchReviewed(record, rowsForSavedSearch(record), manifest);
		trackTelemetry("jobs.saved_search_reviewed", {
			matchBucket: bucketCount(rowsForSavedSearch(record).length),
		});
	};

	const handleDeleteSavedSearch = (record: SavedSearchRecord) => {
		if (!window.confirm(`Delete saved search "${record.label}"?`)) {
			return;
		}
		if (activeSavedSearchId === record.id) {
			setActiveSavedSearchId(null);
		}
		localState.deleteSavedSearch(record.id);
		trackTelemetry("jobs.saved_search_deleted");
	};

	const activeSearchMeta = searchActive ? searchMeta : null;
	const activeSearchError = searchActive ? searchError : null;
	const displayedMatchCount = activeSearchMeta?.totalMatches ?? visibleRows.length;
	const indexNote = searchActive && searchLoading
		? "Searching open jobs..."
		: activeSearchError
			? "Showing current results. Retry search for fresh matches."
			: activeSearchMeta?.truncated
				? `Showing ${formatCount(visibleRows.length)} of ${formatCount(activeSearchMeta.totalMatches)} matches. Narrow filters for more.`
				: !fullRowsLoaded && !searchActive
					? "Showing latest open jobs."
					: null;

	return (
		<section className="not-prose mx-auto w-full max-w-[96rem] px-3 py-4 sm:px-5 lg:px-6">
			<div className="opps-ledger-shell">
				<JobsBoardMetrics manifest={manifest} matchCount={displayedMatchCount} />

				<div className="mt-4">
					<JobsBoardToolbar
						filters={filters}
						manifest={manifest}
						matchCount={displayedMatchCount}
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
					<div className="opps-error-banner mt-4">
						<span>{error}</span>
					</div>
				) : null}

				{activeSearchError ? (
					<div className="opps-error-banner mt-4">
						<span>{activeSearchError}</span>
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={retrySearch}
						>
							Retry search
						</Button>
					</div>
				) : null}

				{loading ? (
					<div className="opps-loading mt-4 min-h-[24rem]">
						<Loader2 className="size-4 animate-spin" />
						Loading open jobs index…
					</div>
				) : null}

					{!loading && !error ? (
						<div className="mt-4">
							{visibleRows.length === 0 && !hasPreviewSelection ? (
								<JobsBoardEmpty
									matchCount={displayedMatchCount}
									activeFilterCount={activeFilterCount}
									onClearFilters={handleClearFilters}
									loadingResults={searchLoading && searchActive}
								/>
							) : (
								<div
									className={
									hasPreviewSelection
										? "grid gap-4 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]"
										: "grid gap-4"
								}
								>
									{visibleRows.length === 0 ? (
										<JobsBoardEmpty
											matchCount={displayedMatchCount}
											activeFilterCount={activeFilterCount}
											onClearFilters={handleClearFilters}
											loadingResults={searchLoading && searchActive}
										/>
									) : (
									<JobsBoardList
										rows={visibleRows}
										selectedJobId={selectedJobId ?? ""}
										jobRecords={localState.jobRecords}
										jobLifecycleIndicators={lifecycleIndicatorsByJobId}
										onSelectJob={handleSelectJob}
									/>
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
		</section>
	);
}

function bucketCount(value: number) {
	if (value === 0) return "0";
	if (value < 10) return "1-9";
	if (value < 100) return "10-99";
	if (value < 1000) return "100-999";
	return "1000+";
}

function retainedRowSnapshot(record: RetainedJobDetailRecord): SearchRow {
	const row = record.rowSnapshot
		? [...record.rowSnapshot]
		: new Array(J.payloadHash + 1).fill(null);
	row[J.id] = record.jobId;
	row[J.status] = "open";
	row[J.title] = row[J.title] || record.detail.title || "Stale saved role";
	row[J.company] =
		row[J.company] || record.detail.company || record.detail.boardKey || "";
	row[J.source] = row[J.source] || record.detail.sourceKey || "";
	row[J.board] = row[J.board] || record.detail.boardKey || "";
	row[J.provider] = row[J.provider] || record.detail.providerId || "";
	row[J.url] = row[J.url] || record.detail.postingUrl || "";
	row[J.latestObserved] =
		row[J.latestObserved] ||
		record.detail.lastSeenAt ||
		record.detail.syncedAt ||
		record.snapshotAt ||
		"";
	row[J.syncedAt] = row[J.syncedAt] || record.detail.syncedAt || record.snapshotAt || "";
	row[J.firstSeenAt] = row[J.firstSeenAt] || record.detail.firstSeenAt || "";
	row[J.lastSeenAt] = row[J.lastSeenAt] || record.detail.lastSeenAt || "";
	row[J.closedAt] = row[J.closedAt] || record.detail.closedAt || "";
	row[J.contentHash] = row[J.contentHash] || record.detail.contentHash || "";
	row[J.payloadHash] = row[J.payloadHash] || record.detail.payloadHash || "";
	return row;
}

function detailRowSnapshot(detail: JobDetail): SearchRow {
	const row = new Array(J.daysOpen + 1).fill(null);
	row[J.id] = detail.id;
	row[J.source] = detail.sourceKey || "";
	row[J.board] = detail.boardKey || "";
	row[J.provider] = detail.providerId || "";
	row[J.status] = detail.status || "open";
	row[J.title] = detail.title || "Untitled role";
	row[J.company] = detail.company || detail.boardKey || "";
	row[J.department] = detail.department || "";
	row[J.team] = detail.team || "";
	row[J.workplace] = detail.workplaceType || "";
	row[J.remote] = detail.remote || "";
	row[J.type] = detail.employmentType || "";
	row[J.locations] = JSON.stringify(detail.locations ?? []);
	row[J.salaryMin] = detail.salaryMin ?? null;
	row[J.salaryMax] = detail.salaryMax ?? null;
	row[J.currency] = detail.salaryCurrency || "";
	row[J.url] = detail.postingUrl || detail.applyUrl || "";
	row[J.posted] = detail.postedAt || "";
	row[J.latestObserved] =
		detail.lastSeenAt ||
		detail.updatedAt ||
		detail.versionCreatedAt ||
		detail.syncedAt ||
		"";
	row[J.sourceKeys] = JSON.stringify([detail.sourceKey].filter(Boolean));
	row[J.descriptionSnippet] = detailDescriptionSnippet(detail);
	row[J.skillTokens] = (detail.skills ?? [])
		.flatMap((skill) => [skill.name, skill.level, ...(skill.keywords ?? [])])
		.map(text)
		.filter(Boolean)
		.join(",");
	row[J.syncedAt] = detail.syncedAt || "";
	row[J.firstSeenAt] = detail.firstSeenAt || "";
	row[J.lastSeenAt] = detail.lastSeenAt || "";
	row[J.closedAt] = detail.closedAt || "";
	row[J.contentHash] = detail.contentHash || "";
	row[J.payloadHash] = detail.payloadHash || "";
	row[J.seniority] = detail.experience || "";
	return row;
}

function detailDescriptionSnippet(detail: JobDetail) {
	const value =
		text(detail.description) ||
		stripTags(detail.descriptionHtml ?? "") ||
		structuredJobDescriptionText(detail);
	return value.slice(0, 200);
}

function structuredJobDescriptionText(detail: JobDetail) {
	const value = detail.jobDescription?.description;
	if (typeof value !== "string") {
		return "";
	}
	const raw = text(value);
	if (!raw) {
		return "";
	}
	return /<\/?[A-Za-z][^>]*>/.test(raw) ? stripTags(raw) : raw;
}

function stripTags(value: string) {
	return value.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}
