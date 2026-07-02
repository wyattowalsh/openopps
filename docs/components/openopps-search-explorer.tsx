"use client";

import { Loader2 } from "lucide-react";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { ExplorerDashboard } from "@/components/openopps-search/explorer-dashboard";
import { ExplorerEntityTabs } from "@/components/openopps-search/explorer-entity-tabs";
import {
	DEFAULT_EXPLORER_SORT,
	PAGE_SIZE,
	activeFilterCount,
	matchesRow,
	sortRows,
	terms,
	type ExplorerFilters,
} from "@/components/openopps-search/explorer-filter-engine";
import { useExplorerFilterState } from "@/components/openopps-search/explorer-filter-state";
import { shouldLoadFullJobsIndexForExplorer } from "@/components/openopps-search/explorer-load-state";
import { ExplorerResultsPanel } from "@/components/openopps-search/explorer-results-panel";
import { ExplorerStatusBar } from "@/components/openopps-search/explorer-status-bar";
import { ExplorerToolbar } from "@/components/openopps-search/explorer-toolbar";
import {
	loadEntityChunk,
	loadInitialJobsChunk,
	loadSearchManifest,
} from "@/components/openopps-search/search-index-loader";
import type {
	Entity,
	SearchChunk,
	SearchManifest,
} from "@/components/openopps-search/search-types";
import { formatLoadError } from "@/components/openopps-search/search-utils";
import { Button } from "@/components/ui/button";
import { trackTelemetry } from "@/lib/telemetry";

export function OpenOppsSearchExplorer() {
	return (
		<Suspense
			fallback={
				<div className="opps-loading my-8 not-prose">
					<Loader2 className="size-4 animate-spin" />
					Loading dataset explorer…
				</div>
			}
		>
			<OpenOppsSearchExplorerInner />
		</Suspense>
	);
}

function OpenOppsSearchExplorerInner() {
	const {
		entity,
		filters,
		deferredFilters,
		sortKey,
		visibleLimit,
		setEntity,
		setFilters,
		setSortKey,
		setVisibleLimit,
		clearFilters,
		resetPage,
	} = useExplorerFilterState();
	const [manifest, setManifest] = useState<SearchManifest | null>(null);
	const [chunks, setChunks] = useState<Partial<Record<Entity, SearchChunk>>>({});
	const [fullJobsLoaded, setFullJobsLoaded] = useState(false);
	const [fullJobsRequested, setFullJobsRequested] = useState(false);
	const [loadingManifest, setLoadingManifest] = useState(true);
	const [loadingEntity, setLoadingEntity] = useState<Entity | null>(null);
	const [loadingFullJobs, setLoadingFullJobs] = useState(false);
	const [fullJobsError, setFullJobsError] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [showInspector, setShowInspector] = useState(false);
	const [manifestRetryKey, setManifestRetryKey] = useState(0);
	const [chunkRetryKey, setChunkRetryKey] = useState(0);
	const chunkLoadRequest = useRef(0);

	useEffect(() => {
		let mounted = true;

		async function loadManifest() {
			setLoadingManifest(true);
			try {
				const nextManifest = await loadSearchManifest();
				if (mounted) {
					setManifest(nextManifest);
					setChunks({});
					setFullJobsLoaded(false);
					setFullJobsRequested(false);
					setFullJobsError(null);
					setError(null);
					trackTelemetry("explorer.manifest_loaded", {
						manifestVersion: nextManifest.version,
						jobs: nextManifest.entities.jobs.count,
						boards: nextManifest.entities.boards.count,
						providers: nextManifest.entities.providers.count,
						hasDashboard: Boolean(nextManifest.dashboard),
						suggestions: Object.values(nextManifest.suggestions ?? {}).reduce(
							(total, values) => total + (values?.length ?? 0),
							0,
						),
					});
				}
			} catch (caught) {
				if (mounted) {
					const message = formatLoadError(caught);
					setError(message);
					trackTelemetry("explorer.manifest_error", { message });
				}
			} finally {
				if (mounted) {
					setLoadingManifest(false);
				}
			}
		}

		loadManifest();
		return () => {
			mounted = false;
		};
	}, [manifestRetryKey]);

	const activeChunk = chunks[entity];
	const activeFilters = activeFilterCount(entity, filters);
	const shouldLoadFullJobs =
		showInspector &&
		shouldLoadFullJobsIndexForExplorer({
			entity,
			hasJobsChunk: Boolean(chunks.jobs),
			fullJobsLoaded,
			fullJobsRequested,
			fullJobsError,
			activeFilterCount: activeFilters,
			sortKey,
			defaultJobsSort: DEFAULT_EXPLORER_SORT.jobs,
		});

	useEffect(() => {
		const requestId = chunkLoadRequest.current + 1;
		chunkLoadRequest.current = requestId;
		const isCurrentRequest = () => chunkLoadRequest.current === requestId;
		const clearCurrentLoading = () => {
			if (isCurrentRequest()) {
				setLoadingEntity(null);
				setLoadingFullJobs(false);
			}
		};

		if (!manifest) {
			clearCurrentLoading();
			return;
		}
		if (!showInspector) {
			clearCurrentLoading();
			return;
		}
		if (entity !== "jobs" && chunks[entity]) {
			clearCurrentLoading();
			return;
		}
		if (entity === "jobs" && chunks.jobs && !shouldLoadFullJobs) {
			clearCurrentLoading();
			return;
		}
		const currentManifest = manifest;

		async function loadChunk() {
			setLoadingEntity(entity);
			setLoadingFullJobs(entity === "jobs" && Boolean(chunks.jobs));
			try {
				if (entity === "jobs" && !chunks.jobs) {
					const nextChunk = await loadInitialJobsChunk(currentManifest);
					if (isCurrentRequest()) {
						setChunks((current) => ({ ...current, jobs: nextChunk }));
						setFullJobsLoaded(
							nextChunk.count >= currentManifest.entities.jobs.count,
						);
						setFullJobsError(null);
						setError(null);
					}
					return;
				}

				const nextChunk = await loadEntityChunk(currentManifest, entity);
				if (isCurrentRequest()) {
					setChunks((current) => ({ ...current, [entity]: nextChunk }));
					if (entity === "jobs") {
						setFullJobsLoaded(true);
						setFullJobsRequested(false);
						setFullJobsError(null);
					}
					setError(null);
				}
			} catch (caught) {
				if (isCurrentRequest()) {
					const nextError = formatLoadError(caught);
					if (entity === "jobs" && chunks.jobs) {
						setFullJobsError(nextError);
					} else {
						setFullJobsError(null);
					}
					setError(nextError);
				}
			} finally {
				if (isCurrentRequest()) {
					setLoadingEntity(null);
					setLoadingFullJobs(false);
				}
			}
		}

		void loadChunk();
		return () => {
			if (chunkLoadRequest.current === requestId) {
				chunkLoadRequest.current += 1;
			}
		};
	}, [chunkRetryKey, chunks, entity, manifest, shouldLoadFullJobs, showInspector]);

	const queryTerms = useMemo(
		() => terms(deferredFilters.query),
		[deferredFilters.query],
	);
	const locationTerms = useMemo(
		() => terms(deferredFilters.location),
		[deferredFilters.location],
	);
	const visibleRows = useMemo(() => {
		if (!activeChunk) {
			return [];
		}
		const rows = activeChunk.rows.filter((row) =>
			matchesRow(entity, row, deferredFilters, queryTerms, locationTerms),
		);
		return sortRows(entity, rows, sortKey, queryTerms);
	}, [activeChunk, deferredFilters, entity, locationTerms, queryTerms, sortKey]);

	const pageRows = visibleRows.slice(0, visibleLimit);
	const isLoading =
		showInspector &&
		(loadingManifest || loadingEntity === entity || shouldLoadFullJobs);
	const canLoadFullJobs =
		showInspector &&
		entity === "jobs" &&
		Boolean(activeChunk) &&
		!fullJobsLoaded &&
		!loadingFullJobs &&
		!fullJobsError;
	const indexNote =
		entity === "jobs" && activeChunk && !fullJobsLoaded
			? loadingFullJobs
				? "Loading the full static jobs index for global matches."
				: fullJobsError
					? "Showing the latest open jobs. Retry the full index for global matches."
					: "Showing the latest open jobs. Search, filter, sort, or load the full index for global matches."
			: null;
	const renderBlockingError = error && !fullJobsError;

	const clearFullJobsError = () => {
		if (fullJobsError) {
			setFullJobsError(null);
			setError(null);
		}
	};
	const retryFullJobsIndex = () => {
		setError(null);
		setFullJobsError(null);
		resetPage();
		setFullJobsRequested(true);
	};
	const retryManifest = () => {
		setError(null);
		setFullJobsError(null);
		setLoadingManifest(true);
		setManifestRetryKey((current) => current + 1);
	};
	const retryActiveEntity = () => {
		if (fullJobsError) {
			retryFullJobsIndex();
			return;
		}
		setError(null);
		setFullJobsError(null);
		resetPage();
		setChunkRetryKey((current) => current + 1);
	};
	const updateFilters = (updater: (current: ExplorerFilters) => ExplorerFilters) => {
		clearFullJobsError();
		setFilters(updater);
	};
	const selectEntity = (nextEntity: Entity) => {
		clearFullJobsError();
		setEntity(nextEntity);
		setFullJobsRequested(false);
	};
	const handleClearFilters = () => {
		clearFullJobsError();
		clearFilters();
		setFullJobsRequested(false);
	};
	const openInspector = () => {
		if (!showInspector) {
			trackTelemetry("explorer.inspector_opened", {
				entity,
				activeFilters,
			});
		}
		setShowInspector(true);
	};
	const closeInspector = () => {
		trackTelemetry("explorer.inspector_closed", {
			entity,
			activeFilters,
		});
		setShowInspector(false);
		setFullJobsRequested(false);
	};

	return (
		<section className="not-prose mx-auto w-full max-w-[96rem] px-3 py-4 sm:px-5 lg:px-6">
			<div className="opps-ledger-shell">
				<ExplorerDashboard
					manifest={manifest}
					loading={loadingManifest}
					warning={error && !manifest ? error : null}
					onInspectRows={openInspector}
					onRetry={!manifest && error ? retryManifest : undefined}
				/>

				{showInspector ? (
					<div className="mt-5 border-t border-border/70 pt-4">
						<div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
							<div>
								<p className="opps-kicker">Row inspector</p>
								<h2 className="font-heading text-lg font-semibold">
									Generated index rows
								</h2>
							</div>
							<Button
								type="button"
								variant="outline"
								size="sm"
								onClick={closeInspector}
							>
								Hide inspector
							</Button>
						</div>

						<ExplorerStatusBar manifest={manifest} />

						<ExplorerEntityTabs
							entity={entity}
							manifest={manifest}
							activeChunk={activeChunk}
							onSelect={selectEntity}
						/>

						<ExplorerToolbar
							entity={entity}
							filters={filters}
							manifest={manifest}
							sortKey={sortKey}
							matchCount={visibleRows.length}
							onFiltersChange={updateFilters}
							onSortChange={(value) => {
								clearFullJobsError();
								setSortKey(value);
							}}
							onClearFilters={handleClearFilters}
						/>

						{error ? (
							<ExplorerErrorPanel
								message={error}
								onRetry={retryActiveEntity}
								retryLabel={fullJobsError ? "Retry full jobs index" : "Retry index"}
							/>
						) : null}
						{indexNote ? (
							<p className="mt-3 text-xs text-muted-foreground">{indexNote}</p>
						) : null}
						{isLoading ? (
							<ExplorerLoadingPanel
								entity={entity}
								fullJobs={loadingFullJobs || shouldLoadFullJobs}
							/>
						) : null}
						{!isLoading && !renderBlockingError ? (
							<ExplorerResultsPanel
								entity={entity}
								rows={pageRows}
								total={visibleRows.length}
								visibleLimit={visibleLimit}
								onMore={() => setVisibleLimit(visibleLimit + PAGE_SIZE)}
								canLoadFullJobs={
									canLoadFullJobs && visibleLimit >= visibleRows.length
								}
								onLoadFullJobs={retryFullJobsIndex}
							/>
						) : null}
					</div>
				) : null}
			</div>
		</section>
	);
}

function ExplorerLoadingPanel({
	entity,
	fullJobs,
}: {
	entity: Entity;
	fullJobs: boolean;
}) {
	const label = entity === "providers" ? "board providers" : entity;
	return (
		<div className="opps-loading mt-4">
			<Loader2 className="size-4 animate-spin text-primary" />
			{fullJobs ? "Loading full jobs index." : `Loading ${label}.`}
		</div>
	);
}

function ExplorerErrorPanel({
	message,
	onRetry,
	retryLabel = "Retry index",
}: {
	message: string;
	onRetry?: () => void;
	retryLabel?: string;
}) {
	return (
		<div className="opps-error-banner mt-4">
			<span>{message}</span>
			{onRetry ? (
				<Button type="button" variant="outline" size="sm" onClick={onRetry}>
					{retryLabel}
				</Button>
			) : null}
		</div>
	);
}
