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
import {
	needsFullJobsIndexConfirmation,
	resolveSelectedJobRow,
	shouldLoadFullJobsIndex,
} from "@/components/jobs-board/jobs-board-load-state";
import { JobsBoardEmpty } from "@/components/jobs-board/jobs-board-empty";
import { JobsBoardList } from "@/components/jobs-board/jobs-board-list";
import { JobsBoardMetrics } from "@/components/jobs-board/jobs-board-metrics";
import { JobsBoardPreview } from "@/components/jobs-board/jobs-board-preview";
import { JobsBoardPreviewSheet } from "@/components/jobs-board/jobs-board-preview-sheet";
import { JobsBoardToolbar } from "@/components/jobs-board/jobs-board-toolbar";
import {
	loadEntityChunk,
	loadInitialJobsChunk,
	loadSearchManifest,
} from "@/components/openopps-search/search-index-loader";
import type {
	JobDetail,
	SearchManifest,
	SearchRow,
} from "@/components/openopps-search/search-types";
import {
	detailPath,
	formatLoadError,
	J,
	text,
} from "@/components/openopps-search/search-utils";
import { Button } from "@/components/ui/button";
import { safeJobExternalUrl } from "@/lib/job-url";
import { trackTelemetry } from "@/lib/telemetry";

type JobsBoardProps = {
	initialJobId?: string;
};

function errorMessage(error: unknown) {
	return formatLoadError(error);
}

export function JobsBoard({ initialJobId }: JobsBoardProps) {
	const [manifest, setManifest] = useState<SearchManifest | null>(null);
	const [rows, setRows] = useState<SearchRow[]>([]);
	const [fullRowsLoaded, setFullRowsLoaded] = useState(false);
	const [loading, setLoading] = useState(true);
	const [loadingFullIndex, setLoadingFullIndex] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [fullIndexError, setFullIndexError] = useState<string | null>(null);
	const [fullIndexConfirmed, setFullIndexConfirmed] = useState(false);
	const [detail, setDetail] = useState<JobDetail | null>(null);
	const [detailLoading, setDetailLoading] = useState(false);
	const [detailError, setDetailError] = useState<string | null>(null);
	const [localDataOpen, setLocalDataOpen] = useState(false);
	const [activeSavedSearchId, setActiveSavedSearchId] = useState<string | null>(
		null,
	);
	const fullIndexRequestIdRef = useRef(0);
	const fullIndexInFlightRef = useRef(false);
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
			fullIndexRequestIdRef.current += 1;
			fullIndexInFlightRef.current = false;
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
					setRows(initialChunk.rows);
					setFullRowsLoaded(
						initialChunk.count >= nextManifest.entities.jobs.count,
					);
					setError(null);
					setFullIndexError(null);
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

	const needsFullIndex = shouldLoadFullJobsIndex({
		activeFilterCount,
		rows,
		selectedJobId,
		fullIndexError,
		jobCount,
		fullIndexConfirmed,
	});

	const pendingFullIndexConfirmation = needsFullJobsIndexConfirmation({
		activeFilterCount,
		rows,
		selectedJobId,
		fullIndexError,
		jobCount,
		fullIndexConfirmed,
	});

	useEffect(() => {
		if (
			!manifest ||
			!needsFullIndex ||
			fullRowsLoaded ||
			fullIndexInFlightRef.current
		) {
			return;
		}
		const currentManifest = manifest;
		const requestId = fullIndexRequestIdRef.current + 1;
		fullIndexRequestIdRef.current = requestId;
		fullIndexInFlightRef.current = true;

		async function loadFullIndex() {
			setLoadingFullIndex(true);
			try {
				const fullChunk = await loadEntityChunk(currentManifest, "jobs");
				if (
					mountedRef.current &&
					fullIndexRequestIdRef.current === requestId
				) {
					setRows(fullChunk.rows);
					setFullRowsLoaded(true);
					setError(null);
					setFullIndexError(null);
					trackTelemetry("jobs.full_index_loaded", {
						rows: fullChunk.rows.length,
						reason: selectedJobId ? "selected_job" : "filters",
					});
				}
			} catch (caught) {
				if (
					mountedRef.current &&
					fullIndexRequestIdRef.current === requestId
				) {
					const message = errorMessage(caught);
					setFullIndexError(message);
					trackTelemetry("jobs.full_index_error", { message });
				}
			} finally {
				if (fullIndexRequestIdRef.current === requestId) {
					fullIndexInFlightRef.current = false;
					if (mountedRef.current) {
						setLoadingFullIndex(false);
					}
				}
			}
	}

	void loadFullIndex();
}, [fullRowsLoaded, manifest, needsFullIndex, selectedJobId]);

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

	const sortKey: JobSortKey = deferredFilters.query ? "relevance" : "latest";

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

	const selectedRow = useMemo(
		() => resolveSelectedJobRow(visibleRows, rowsWithLocalRetainedJobs, selectedJobId),
		[rowsWithLocalRetainedJobs, selectedJobId, visibleRows],
	);
	const selectedWorkflowRecord = selectedJobId
		? localState.jobRecords[selectedJobId] ?? null
		: null;
	const selectedRetainedDetail = selectedJobId
		? localState.retainedJobDetails[selectedJobId]?.detail ?? null
		: null;
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

	const detailRoot =
		manifest?.detailShards?.root ?? "/data/openopps-search/jobs-details";

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
				const path = detailPath(detailRoot, jobId);
				const response = await fetch(path, {
					signal: controller.signal,
					cache: "force-cache",
				});
				if (!response.ok) {
					throw new Error(`Detail bucket not found (${response.status})`);
				}
				const payload = (await response.json()) as Record<string, JobDetail>;
				const nextDetail = payload[jobId];
				if (!nextDetail) {
					throw new Error("Detail record not found in bucket.");
				}
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
	}, [detailRoot, selectedJobId]);

	const clearFullIndexError = () => {
		if (fullIndexError) {
			setFullIndexError(null);
		}
	};

	const handleFiltersChange = (nextFilters: Parameters<typeof setFilters>[0]) => {
		clearFullIndexError();
		setActiveSavedSearchId(null);
		trackTelemetry("jobs.filters_changed", {
			keys: Object.keys(nextFilters),
			hasSelection: Boolean(selectedJobId),
		});
		setFilters(nextFilters);
	};

	const handleClearFilters = () => {
		clearFullIndexError();
		setActiveSavedSearchId(null);
		trackTelemetry("jobs.filters_cleared", {
			activeFilterCount,
			hasSelection: Boolean(selectedJobId),
		});
		clearFilters();
	};

	const confirmFullIndexLoad = () => {
		trackTelemetry("jobs.full_index_confirmed", {
			jobCount,
			activeFilterCount,
			hasSelection: Boolean(selectedJobId),
		});
		setFullIndexConfirmed(true);
	};

	const retryFullIndex = () => {
		trackTelemetry("jobs.full_index_retry", {
			activeFilterCount,
			hasSelection: Boolean(selectedJobId),
		});
		setFullIndexError(null);
	};

	const handleSelectJob = (jobId: string) => {
		clearFullIndexError();
		trackTelemetry("jobs.result_selected", {
			hadPreviousSelection: Boolean(selectedJobId),
		});
		void setSelectedJobId(jobId);
	};

	const handleClosePreview = () => {
		clearFullIndexError();
		trackTelemetry("jobs.preview_closed", {
			hadSelection: Boolean(selectedJobId),
		});
		void setSelectedJobId(null);
	};

	const activeDetail =
		selectedJobId && detail?.id === selectedJobId
			? detail
			: selectedRetainedDetail?.id === selectedJobId
				? selectedRetainedDetail
				: null;
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
		clearFullIndexError();
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

	const indexNote =
		needsFullIndex && loadingFullIndex
			? "Loading the full static jobs index for global matches."
			: fullIndexError
				? "Showing the latest open jobs. Retry the full index for global matches."
			: !fullRowsLoaded
				? "Showing the latest open jobs. Search, filter, or open a deep link to load the full index."
				: null;

	return (
		<section className="not-prose mx-auto w-full max-w-[96rem] px-3 py-4 sm:px-5 lg:px-6">
			<div className="opps-ledger-shell">
				<JobsBoardMetrics manifest={manifest} matchCount={visibleRows.length} />

				<div className="mt-4">
					<JobsBoardToolbar
						filters={filters}
						manifest={manifest}
						matchCount={visibleRows.length}
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

				{pendingFullIndexConfirmation ? (
					<div className="opps-error-banner mt-4 flex flex-wrap items-center justify-between gap-3">
						<span>
							This snapshot has {jobCount.toLocaleString()} jobs. Loading the full
							index in your browser may use significant memory.
						</span>
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={confirmFullIndexLoad}
						>
							Load full jobs index
						</Button>
					</div>
				) : null}

				{fullIndexError ? (
					<div className="opps-error-banner mt-4">
						<span>{fullIndexError}</span>
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={retryFullIndex}
						>
							Retry full jobs index
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
								matchCount={visibleRows.length}
								activeFilterCount={activeFilterCount}
								onClearFilters={handleClearFilters}
								loadingFullIndex={loadingFullIndex && needsFullIndex}
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
										matchCount={visibleRows.length}
										activeFilterCount={activeFilterCount}
										onClearFilters={handleClearFilters}
										loadingFullIndex={loadingFullIndex && needsFullIndex}
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
